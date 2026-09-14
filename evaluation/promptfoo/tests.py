"""Generate Promptfoo cases from the isolated v3 regression split."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.dataset_v3 import build_examples
from evaluation.run_v3_evaluation import select_budget_400


def _case(example: dict[str, Any]) -> dict[str, Any]:
    inputs = example["inputs"]
    expected = example["outputs"]
    variables = {
        "query": str(inputs["query"]),
        "case_id": str(inputs["case_id"]),
        "suite": str(inputs["suite"]),
        "paper_ids": list(inputs.get("paper_ids", [])),
        "required_terms": list(expected.get("required_terms", [])),
        "expected_refusal": expected.get("expected_refusal"),
        "expected_steps": list(expected.get("expected_steps", [])),
    }
    return {
        "description": str(inputs["case_id"]),
        "vars": variables,
    }


def generate_tests(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return the paper-disjoint regression split; callers may cap its size."""

    settings = config or {}
    max_cases = int(settings.get("max_cases", 400))
    examples = select_budget_400(build_examples("all"))
    examples = [
        example
        for example in examples
        if example.get("metadata", {}).get("split") == "regression"
        and example["inputs"].get("query")
    ]
    return [_case(example) for example in examples[:max_cases]]


__all__ = ["generate_tests"]
