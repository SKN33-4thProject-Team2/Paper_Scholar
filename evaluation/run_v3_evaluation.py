"""Run and resume the isolated 650-case v3 evaluation."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import time
from typing import Any, Callable

from langsmith.evaluation import EvaluationResult

from evaluation.dataset_v3 import DATASET_VERSION, SUITES, build_examples, dataset_counts
from evaluation.quality_metrics import (
    DEEP_RESEARCH_EVALUATORS,
    EXTRACTION_EVALUATORS,
    PIPELINE_EVALUATORS,
    passage_section_recall_at_5,
    passage_section_reciprocal_rank,
)
from evaluation.v3_runtime import GENERATED_ROOT, RESULTS_PATH, V3EvaluationTarget
from orchestration.evaluation import (
    citation_precision,
    reciprocal_rank,
    refusal_accuracy,
    retrieval_recall_at_k,
    route_sequence_accuracy,
)


SUMMARY_PATH = GENERATED_ROOT / "evaluation_summary_v3.json"
Evaluator = Callable[[dict[str, Any], dict[str, Any], dict[str, Any] | None], EvaluationResult]


def select_budget_400(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select a paper-balanced 400-case execution plan from the 650-case bank."""

    by_suite = {
        suite: [example for example in examples if example["inputs"]["suite"] == suite]
        for suite in SUITES
    }
    retrieval_suffixes = ("-goal", "-method", "-experiment", "-result", "-limitation", "-evidence")
    selected = [
        *by_suite["artifacts"],
        *[
            example
            for example in by_suite["retrieval"]
            if str(example["inputs"]["case_id"]).endswith(retrieval_suffixes)
        ],
        *by_suite["deep_research"][::2],
        *by_suite["pipeline"][::2],
        *[
            example
            for example in by_suite["refusal"]
            if not str(example["inputs"]["case_id"]).endswith("-05")
        ],
    ]
    counts = Counter(example["inputs"]["suite"] for example in selected)
    expected = {"artifacts": 40, "retrieval": 240, "deep_research": 40, "pipeline": 40, "refusal": 40}
    if len(selected) != 400 or counts != expected:
        raise AssertionError(f"400건 평가 계획 오류: total={len(selected)}, suites={dict(counts)}")
    return selected


def evaluators_for(suite: str) -> tuple[Evaluator, ...]:
    if suite == "artifacts":
        return tuple(EXTRACTION_EVALUATORS)
    if suite == "retrieval":
        return (
            retrieval_recall_at_k,
            reciprocal_rank,
            passage_section_recall_at_5,
            passage_section_reciprocal_rank,
            citation_precision,
            refusal_accuracy,
            route_sequence_accuracy,
        )
    if suite == "refusal":
        return (refusal_accuracy, route_sequence_accuracy)
    if suite == "deep_research":
        return (route_sequence_accuracy, *DEEP_RESEARCH_EVALUATORS)
    if suite == "pipeline":
        return (route_sequence_accuracy, *PIPELINE_EVALUATORS)
    raise ValueError(f"지원하지 않는 suite입니다: {suite}")


def _metric_payload(result: EvaluationResult) -> dict[str, Any]:
    return {
        "key": result.key,
        "score": result.score,
        "comment": result.comment,
        "metadata": result.metadata,
    }


def _evaluate_case(example: dict[str, Any], target: V3EvaluationTarget) -> dict[str, Any]:
    started = time.perf_counter()
    inputs = example["inputs"]
    reference = example["outputs"]
    outputs = target(inputs)
    metrics: list[dict[str, Any]] = []
    for evaluator in evaluators_for(str(inputs["suite"])):
        try:
            result = evaluator(inputs, outputs, reference)
        except Exception as exc:
            result = EvaluationResult(
                key=getattr(evaluator, "__name__", "evaluator"),
                score=0.0,
                comment=f"평가 실행 오류: {type(exc).__name__}: {exc}",
            )
        metrics.append(_metric_payload(result))
    return {
        "dataset_version": DATASET_VERSION,
        "answer_mode": target.answer_mode,
        "inputs": inputs,
        "reference": reference,
        "metadata": example.get("metadata", {}),
        "outputs": outputs,
        "metrics": metrics,
        "latency_seconds": round(time.perf_counter() - started, 4),
    }


def _refresh_cached_metrics(
    example: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    """Recompute deterministic metrics without repeating a model invocation."""

    refreshed = dict(record)
    refreshed["inputs"] = example["inputs"]
    refreshed["reference"] = example["outputs"]
    refreshed["metadata"] = example.get("metadata", {})
    metrics: list[dict[str, Any]] = []
    for evaluator in evaluators_for(str(example["inputs"]["suite"])):
        try:
            result = evaluator(example["inputs"], refreshed["outputs"], example["outputs"])
        except Exception as exc:
            result = EvaluationResult(
                key=getattr(evaluator, "__name__", "evaluator"),
                score=0.0,
                comment=f"평가 실행 오류: {type(exc).__name__}: {exc}",
            )
        metrics.append(_metric_payload(result))
    refreshed["metrics"] = metrics
    return refreshed


def _load_records(path: Path, answer_mode: str) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("answer_mode") != answer_mode:
            continue
        if record.get("outputs", {}).get("errors"):
            continue
        case_id = str(record.get("inputs", {}).get("case_id") or "")
        if case_id:
            records[case_id] = record
    return records


def _write_records(path: Path, records: list[dict[str, Any]]) -> None:
    rendered = "\n".join(json.dumps(record, ensure_ascii=False, default=str) for record in records)
    path.write_text(rendered + ("\n" if rendered else ""), encoding="utf-8")


def build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    metric_values: dict[str, list[float]] = defaultdict(list)
    suite_metric_values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    paper_metric_values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    errors = 0
    for record in records:
        suite = str(record["inputs"]["suite"])
        paper_id = str(record.get("metadata", {}).get("paper_id") or "")
        if record.get("outputs", {}).get("errors"):
            errors += 1
        for metric in record.get("metrics", []):
            score = metric.get("score")
            if not isinstance(score, (int, float)):
                continue
            key = str(metric["key"])
            metric_values[key].append(float(score))
            suite_metric_values[suite][key].append(float(score))
            if paper_id:
                paper_metric_values[paper_id][key].append(float(score))

    macro_by_paper: dict[str, float] = {}
    metric_names = sorted(metric_values)
    for metric_name in metric_names:
        paper_means = [
            sum(values[metric_name]) / len(values[metric_name])
            for values in paper_metric_values.values()
            if values.get(metric_name)
        ]
        if paper_means:
            macro_by_paper[metric_name] = round(sum(paper_means) / len(paper_means), 4)
    return {
        "dataset_version": DATASET_VERSION,
        "question_bank_counts": dataset_counts(),
        "execution_budget": len(records),
        "evaluated_cases": len(records),
        "suite_counts": dict(Counter(record["inputs"]["suite"] for record in records)),
        "error_cases": errors,
        "micro_averages": {
            key: round(sum(values) / len(values), 4)
            for key, values in sorted(metric_values.items()) if values
        },
        "macro_averages_by_paper": macro_by_paper,
        "averages_by_suite": {
            suite: {
                key: round(sum(values) / len(values), 4)
                for key, values in sorted(metrics.items()) if values
            }
            for suite, metrics in sorted(suite_metric_values.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated v3 evaluation")
    parser.add_argument("--suite", choices=("all", "rag", *SUITES), default="all")
    parser.add_argument("--split", choices=("dev", "regression", "final"))
    parser.add_argument("--answer-mode", choices=("openai", "extractive"), default="openai")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--budget", type=int, choices=(400,))
    parser.add_argument("--output", type=Path, default=RESULTS_PATH)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    if args.max_cases is not None and args.max_cases < 1:
        parser.error("max-cases는 1 이상이어야 합니다.")

    output = args.output.expanduser().resolve()
    try:
        output.relative_to(GENERATED_ROOT.resolve())
    except ValueError:
        parser.error(f"결과 파일은 평가 전용 폴더 안에 있어야 합니다: {GENERATED_ROOT}")

    examples = build_examples(args.suite, split=args.split)
    if args.budget is not None:
        if args.suite != "all" or args.split is not None or args.max_cases is not None:
            parser.error("--budget 400은 --suite all 전체 분할에서 단독으로 사용하세요.")
        examples = select_budget_400(examples)
    if args.max_cases is not None:
        examples = examples[: args.max_cases]
    cached = {} if args.no_resume else _load_records(output, args.answer_mode)
    target = V3EvaluationTarget(answer_mode=args.answer_mode)
    ordered: list[dict[str, Any]] = []
    for index, example in enumerate(examples, 1):
        case_id = str(example["inputs"]["case_id"])
        if case_id in cached:
            record = _refresh_cached_metrics(example, cached[case_id])
            print(f"[{index:03d}/{len(examples):03d}] cache {case_id}", flush=True)
        else:
            record = _evaluate_case(example, target)
            cached[case_id] = record
            print(
                f"[{index:03d}/{len(examples):03d}] run {case_id} "
                f"({record['latency_seconds']:.2f}s)",
                flush=True,
            )
        ordered.append(record)
        if index % 10 == 0 or index == len(examples):
            _write_records(output, ordered)

    summary = build_summary(ordered)
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_summary", "evaluators_for", "select_budget_400"]
