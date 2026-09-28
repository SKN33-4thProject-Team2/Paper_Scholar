"""Run the corpus_v4 Deep Search Q&A evaluation and report the four requested metrics:

- 답변 충실성 (faithfulness)   -- orchestration.evaluation.LLMJudgeEvaluators.faithfulness (imported, unmodified)
- 관련성 (answer relevancy)    -- evaluation_v4_metrics.V4RelevancyJudge (new)
- 검색 품질 (retrieval quality) -- evaluation_v4_metrics.page_recall_at_k / page_reciprocal_rank (new, page-aware)
- 출처 적절성 (citation quality) -- orchestration.evaluation.citation_precision (imported, unmodified)

Strictly read-only against src/backend/frontend: only imports existing Agent
code and runs it against the isolated evaluation/corpus_v4 SQLite DB. All
output is written under evaluation/corpus_v4/generated/.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import statistics
import time
from typing import Any

from v4_runtime import GENERATED_ROOT, V4EvaluationTarget

QUESTIONS_PATH = GENERATED_ROOT / "questions_v4.jsonl"
RESULTS_PATH = GENERATED_ROOT / "evaluation_results_v4.jsonl"
SUMMARY_PATH = GENERATED_ROOT / "evaluation_summary_v4.json"


def _load_questions(path=QUESTIONS_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_case(target: V4EvaluationTarget, case: dict[str, Any]) -> dict[str, Any]:
    from orchestration.evaluation import LLMJudgeEvaluators, citation_precision
    from evaluation_v4_metrics import V4RelevancyJudge, page_recall_at_k, page_reciprocal_rank

    inputs = {
        "case_id": case["paper_id"],
        "query": case["question"],
        "paper_ids": [case["paper_id"]],
    }
    reference_outputs = {
        "expected_section": case["expected_section"],
        "reference_answer": case.get("reference_answer", ""),
    }
    outputs = target(inputs)

    judges = LLMJudgeEvaluators()
    relevancy_judge = V4RelevancyJudge()

    metrics = {}
    for name, fn in (
        ("faithfulness", judges.faithfulness),
        ("answer_relevancy", relevancy_judge.answer_relevancy),
        ("page_recall_at_k", page_recall_at_k),
        ("page_reciprocal_rank", page_reciprocal_rank),
        ("citation_precision", citation_precision),
    ):
        try:
            result = fn(inputs, outputs, reference_outputs)
            metrics[name] = {"score": result.score, "comment": result.comment}
        except Exception as exc:
            metrics[name] = {"score": None, "comment": f"평가 오류: {exc}"}

    return {
        "paper_id": case["paper_id"],
        "topic": case.get("topic"),
        "question": case["question"],
        "response": outputs.get("response", ""),
        "node_history": outputs.get("node_history", []),
        "errors": outputs.get("errors", []),
        "num_sources": len(outputs.get("sources", [])),
        "metrics": metrics,
    }


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = ["faithfulness", "answer_relevancy", "page_recall_at_k", "page_reciprocal_rank", "citation_precision"]
    overall: dict[str, Any] = {}
    for name in metric_names:
        scores = [
            record["metrics"][name]["score"]
            for record in records
            if record["metrics"].get(name, {}).get("score") is not None
        ]
        overall[name] = {
            "mean": round(statistics.mean(scores), 4) if scores else None,
            "n": len(scores),
        }

    by_topic: dict[str, dict[str, Any]] = defaultdict(dict)
    topics = sorted({record.get("topic") or "unknown" for record in records})
    for topic in topics:
        topic_records = [record for record in records if (record.get("topic") or "unknown") == topic]
        for name in metric_names:
            scores = [
                record["metrics"][name]["score"]
                for record in topic_records
                if record["metrics"].get(name, {}).get("score") is not None
            ]
            by_topic[topic][name] = round(statistics.mean(scores), 4) if scores else None

    execution_errors = sum(1 for record in records if record.get("errors"))
    return {
        "total_cases": len(records),
        "execution_errors": execution_errors,
        "overall": overall,
        "by_topic": dict(by_topic),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", default=str(QUESTIONS_PATH))
    parser.add_argument("--limit", type=int, default=None, help="디버그용: 실행 개수 제한")
    parser.add_argument("--no-resume", action="store_true", help="기존 결과를 무시하고 전부 재실행")
    args = parser.parse_args()

    from pathlib import Path

    cases = _load_questions(Path(args.questions))
    if args.limit:
        cases = cases[: args.limit]

    cached: dict[str, dict[str, Any]] = {}
    if not args.no_resume and RESULTS_PATH.is_file():
        for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            cached[record["paper_id"]] = record

    target = V4EvaluationTarget()
    records: list[dict[str, Any]] = []
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", encoding="utf-8") as handle:
        for index, case in enumerate(cases, start=1):
            if case["paper_id"] in cached:
                record = cached[case["paper_id"]]
            else:
                started = time.time()
                record = _run_case(target, case)
                record["elapsed_sec"] = round(time.time() - started, 2)
            records.append(record)
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"[{index}/{len(cases)}] {case['paper_id']} -> "
                  f"faithfulness={record['metrics']['faithfulness']['score']} "
                  f"relevancy={record['metrics']['answer_relevancy']['score']} "
                  f"recall={record['metrics']['page_recall_at_k']['score']} "
                  f"citation={record['metrics']['citation_precision']['score']}")

    summary = _aggregate(records)
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== 요약 ===")
    print(json.dumps(summary["overall"], ensure_ascii=False, indent=2))
    print(f"\n전체 결과: {RESULTS_PATH}")
    print(f"요약: {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
