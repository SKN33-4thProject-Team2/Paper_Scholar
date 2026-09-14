"""Evaluate completed RAG cases with RAGAS.

Run this module only in the dedicated evaluation environment documented in
``evaluation/README.md``.  RAGAS is imported lazily so the main chatbot does
not acquire an evaluation-only runtime dependency.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from evaluation.framework_cases import FrameworkCase, load_v3_framework_cases
from evaluation.v3_runtime import RESULTS_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
RAGAS_METRICS = (
    "id_based_context_precision",
    "id_based_context_recall",
    "faithfulness",
    "answer_relevancy",
)


def build_ragas_rows(cases: Iterable[FrameworkCase]) -> list[dict[str, Any]]:
    """Map successful grounded RAG cases to the RAGAS single-turn schema."""

    rows: list[dict[str, Any]] = []
    for case in cases:
        if case.suite not in {"rag", "retrieval"} or case.errors or not case.answer:
            continue
        # Refusal correctness is already measured by the deterministic suite.
        # RAGAS grounding metrics require retrieved evidence, so refusal cases
        # without contexts are deliberately excluded.
        if case.expected_refusal is True or not case.contexts:
            continue
        rows.append(
            {
                "user_input": case.question,
                "response": case.answer,
                "retrieved_contexts": list(case.contexts),
                "retrieved_context_ids": list(case.retrieved_context_ids),
                "reference_context_ids": list(case.reference_context_ids),
                "reference": case.reference_answer or None,
            }
        )
    return rows


def _averages(records: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for record in records:
        for key in RAGAS_METRICS:
            value = record.get(key)
            if isinstance(value, (int, float)):
                values[key].append(float(value))
    return {
        key: round(sum(scores) / len(scores), 4)
        for key, scores in values.items()
        if scores
    }


def run_ragas(
    cases: Iterable[FrameworkCase],
    *,
    model: str = DEFAULT_MODEL,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> dict[str, Any]:
    """Execute the four project RAGAS metrics and return JSON-safe results."""

    try:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas import EvaluationDataset, evaluate
        from ragas.metrics import (
            Faithfulness,
            IDBasedContextPrecision,
            IDBasedContextRecall,
            ResponseRelevancy,
        )
    except ImportError as error:
        raise RuntimeError(
            "RAGAS 평가 환경이 없습니다. evaluation/requirements.txt를 설치해 주세요."
        ) from error

    rows = build_ragas_rows(cases)
    if not rows:
        raise ValueError("RAGAS로 평가할 근거 포함 RAG 결과가 없습니다.")

    dataset = EvaluationDataset.from_list(rows)
    result = evaluate(
        dataset=dataset,
        metrics=[
            IDBasedContextPrecision(),
            IDBasedContextRecall(),
            Faithfulness(),
            ResponseRelevancy(),
        ],
        llm=ChatOpenAI(model=model, temperature=0),
        embeddings=OpenAIEmbeddings(model=embedding_model),
        experiment_name="academic-paper-ragas",
        raise_exceptions=False,
        show_progress=True,
    )
    records = result.to_pandas().to_dict(orient="records")
    return {
        "framework": "ragas",
        "case_count": len(records),
        "metrics": list(RAGAS_METRICS),
        "averages": _averages(records),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Academic-paper RAGAS evaluation")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    parser.add_argument("--model", default=os.getenv("EVALUATION_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--embedding-model",
        default=os.getenv("EVALUATION_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    if not os.getenv("OPENAI_API_KEY", "").strip():
        parser.error("OPENAI_API_KEY가 필요합니다.")

    cases = load_v3_framework_cases(
        "retrieval",
        results_path=args.results,
        max_cases=args.max_cases,
    )
    report = run_ragas(cases, model=args.model, embedding_model=args.embedding_model)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"RAGAS report: {output}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["RAGAS_METRICS", "build_ragas_rows", "run_ragas"]
