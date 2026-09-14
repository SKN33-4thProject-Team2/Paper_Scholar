"""Evaluate RAG and LangGraph workflow results with DeepEval."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from evaluation.framework_cases import FrameworkCase, load_v3_framework_cases
from evaluation.v3_runtime import RESULTS_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gpt-4o-mini"
SUPPORTED_SUITES = ("rag", "retrieval", "deep_research", "pipeline")


def build_deepeval_payloads(cases: Iterable[FrameworkCase]) -> list[dict[str, Any]]:
    """Build a dependency-free representation of DeepEval test cases."""

    payloads: list[dict[str, Any]] = []
    for case in cases:
        if case.errors or not case.question or not case.answer:
            continue
        payloads.append(
            {
                "name": case.case_id,
                "input": case.question,
                "actual_output": case.answer,
                "expected_output": case.reference_answer or None,
                "retrieval_context": list(case.contexts) or None,
                "tools_called": list(case.actual_steps),
                "expected_tools": list(case.expected_steps),
                "metadata": {"suite": case.suite, "case_id": case.case_id},
            }
        )
    return payloads


def _metric_payload(metric: Any) -> dict[str, Any]:
    return {
        "name": getattr(metric, "name", type(metric).__name__),
        "score": getattr(metric, "score", None),
        "success": getattr(metric, "success", None),
        "reason": getattr(metric, "reason", None),
        "error": getattr(metric, "error", None),
    }


def run_deepeval(
    cases: Iterable[FrameworkCase],
    *,
    suite: str,
    model: str = DEFAULT_MODEL,
    threshold: float = 0.7,
) -> dict[str, Any]:
    """Run response/grounding metrics for RAG or tool metrics for workflows."""

    if suite not in SUPPORTED_SUITES:
        raise ValueError(f"지원하지 않는 DeepEval suite입니다: {suite}")
    try:
        from deepeval import evaluate
        from deepeval.metrics import (
            AnswerRelevancyMetric,
            FaithfulnessMetric,
            ToolCorrectnessMetric,
        )
        from deepeval.test_case import LLMTestCase, ToolCall
    except ImportError as error:
        raise RuntimeError(
            "DeepEval 평가 환경이 없습니다. evaluation/requirements.txt를 설치해 주세요."
        ) from error

    payloads = [
        payload
        for payload in build_deepeval_payloads(cases)
        if payload["metadata"]["suite"] == suite
    ]
    if suite in {"rag", "retrieval"}:
        payloads = [payload for payload in payloads if payload["retrieval_context"]]
    else:
        payloads = [payload for payload in payloads if payload["expected_tools"]]
    if not payloads:
        raise ValueError("DeepEval로 평가할 성공 결과가 없습니다.")

    test_cases = [
        LLMTestCase(
            name=payload["name"],
            input=payload["input"],
            actual_output=payload["actual_output"],
            expected_output=payload["expected_output"],
            retrieval_context=payload["retrieval_context"],
            tools_called=[ToolCall(name=name) for name in payload["tools_called"]],
            expected_tools=[ToolCall(name=name) for name in payload["expected_tools"]],
            additional_metadata=payload["metadata"],
        )
        for payload in payloads
    ]
    if suite in {"rag", "retrieval"}:
        metrics = [
            AnswerRelevancyMetric(threshold=threshold, model=model, async_mode=False),
            FaithfulnessMetric(threshold=threshold, model=model, async_mode=False),
        ]
    else:
        metrics = [
            AnswerRelevancyMetric(threshold=threshold, model=model, async_mode=False),
            ToolCorrectnessMetric(
                threshold=threshold,
                model=model,
                async_mode=False,
                should_consider_ordering=True,
            ),
        ]

    result = evaluate(
        test_cases=test_cases,
        metrics=metrics,
        identifier=f"academic-paper-{suite}",
    )
    records = [
        {
            "name": item.name,
            "success": item.success,
            "input": item.input,
            "actual_output": item.actual_output,
            "metadata": item.metadata,
            "metrics": [
                _metric_payload(metric) for metric in (item.metrics_data or [])
            ],
        }
        for item in result.test_results
    ]
    return {
        "framework": "deepeval",
        "suite": suite,
        "case_count": len(records),
        "passed": sum(bool(record["success"]) for record in records),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Academic-paper DeepEval evaluation")
    parser.add_argument("--suite", choices=SUPPORTED_SUITES, default="retrieval")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    parser.add_argument("--model", default=os.getenv("EVALUATION_MODEL", DEFAULT_MODEL))
    parser.add_argument("--threshold", type=float, default=0.7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    if not os.getenv("OPENAI_API_KEY", "").strip():
        parser.error("OPENAI_API_KEY가 필요합니다.")
    if not 0 <= args.threshold <= 1:
        parser.error("threshold는 0~1이어야 합니다.")

    cases = load_v3_framework_cases(
        args.suite,
        results_path=args.results,
        max_cases=args.max_cases,
    )
    report = run_deepeval(
        cases,
        suite=args.suite,
        model=args.model,
        threshold=args.threshold,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"DeepEval report: {output}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SUPPORTED_SUITES", "build_deepeval_payloads", "run_deepeval"]
