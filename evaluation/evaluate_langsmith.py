"""Sync v3 datasets and run isolated live or cached LangSmith experiments."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from langsmith import Client
from langsmith.evaluation import evaluate

from evaluation.dataset_v3 import DATASET_VERSION, SUITES, build_examples
from evaluation.run_v3_evaluation import evaluators_for, select_budget_400
from evaluation.v3_runtime import RESULTS_PATH, V3EvaluationTarget, load_cached_results


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)


class CachedTarget:
    def __init__(self, results_path: str | Path = RESULTS_PATH) -> None:
        self.records = load_cached_results(results_path)

    def __call__(self, inputs: dict) -> dict:
        case_id = str(inputs.get("case_id") or "")
        record = self.records.get(case_id)
        if record is None:
            raise KeyError(f"캐시된 v3 실행 결과가 없습니다: {case_id}")
        return dict(record.get("outputs", {}))


def sync_dataset(
    client: Client,
    suite: str,
    *,
    split: str | None = None,
    max_cases: int | None = None,
    budget: int | None = 400,
) -> str:
    suffix = f"-{split}" if split else ""
    budget_suffix = f"-budget{budget}" if budget is not None else ""
    dataset_name = (
        f"academic-paper-quality-{DATASET_VERSION}-{suite.replace('_', '-')}"
        f"{suffix}{budget_suffix}"
    )
    if budget == 400:
        if split is not None:
            raise ValueError("400건 예산은 전체 분할에서 사용하세요.")
        examples = [
            example
            for example in select_budget_400(build_examples("all"))
            if example["inputs"]["suite"] == suite
        ]
    else:
        examples = build_examples(suite, split=split)
    if max_cases is not None:
        examples = examples[:max_cases]
    datasets = list(client.list_datasets(dataset_name=dataset_name, limit=1))
    dataset = datasets[0] if datasets else client.create_dataset(
        dataset_name,
        description=f"Academic-paper isolated {suite} evaluation {DATASET_VERSION}",
        metadata={
            "version": DATASET_VERSION,
            "suite": suite,
            "split": split or "all",
            "budget": budget,
        },
    )
    existing = {
        str(example.inputs.get("case_id")): example
        for example in client.list_examples(dataset_id=dataset.id)
        if example.inputs.get("case_id")
    }
    additions = []
    for example in examples:
        case_id = str(example["inputs"]["case_id"])
        current = existing.get(case_id)
        if current is None:
            additions.append(example)
        elif current.inputs != example["inputs"] or current.outputs != example["outputs"]:
            client.update_example(
                current.id,
                inputs=example["inputs"],
                outputs=example["outputs"],
                metadata=example.get("metadata", {}),
                dataset_id=dataset.id,
            )
    if additions:
        client.create_examples(dataset_id=dataset.id, examples=additions)
    return dataset_name


def run_suite(
    client: Client,
    suite: str,
    *,
    source: str = "cached",
    results_path: str | Path = RESULTS_PATH,
    split: str | None = None,
    max_cases: int | None = None,
    budget: int | None = 400,
    prefix: str = "academic-paper-v3",
) -> str:
    dataset_name = sync_dataset(
        client,
        suite,
        split=split,
        max_cases=max_cases,
        budget=budget,
    )
    target = CachedTarget(results_path) if source == "cached" else V3EvaluationTarget(answer_mode="openai")
    experiment = evaluate(
        target,
        data=dataset_name,
        evaluators=list(evaluators_for(suite)),
        experiment_prefix=f"{prefix}-{suite}-{uuid4().hex[:8]}",
        description=f"Isolated corpus v3 {suite} evaluation ({source})",
        max_concurrency=1,
        client=client,
    )
    return experiment.experiment_name


def main() -> int:
    parser = argparse.ArgumentParser(description="LangSmith v3 evaluation")
    parser.add_argument("--suite", choices=("all", *SUITES), default="all")
    parser.add_argument("--source", choices=("cached", "live"), default="cached")
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    parser.add_argument("--split", choices=("dev", "regression", "final"))
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--budget", type=int, choices=(400,), default=400)
    parser.add_argument("--prefix", default="academic-paper-v3")
    args = parser.parse_args()
    if not os.getenv("LANGSMITH_API_KEY", "").strip():
        parser.error("LANGSMITH_API_KEY가 필요합니다.")
    if args.budget is not None and (args.split is not None or args.max_cases is not None):
        parser.error("--budget 400은 --split/--max-cases와 함께 사용할 수 없습니다.")
    client = Client()
    selected = SUITES if args.suite == "all" else (args.suite,)
    for suite in selected:
        name = run_suite(
            client,
            suite,
            source=args.source,
            results_path=args.results,
            split=args.split,
            max_cases=args.max_cases,
            budget=args.budget,
            prefix=args.prefix,
        )
        print(f"LangSmith experiment completed: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CachedTarget", "run_suite", "sync_dataset"]
