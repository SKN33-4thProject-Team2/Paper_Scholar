"""Shared evaluation records for RAGAS, DeepEval, and Promptfoo.

The project already stores LangSmith-compatible examples.  This module turns
the same example plus a workflow result into one neutral record so external
evaluation frameworks do not each invent a different dataset format.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable


def _text(value: object) -> str:
    return str(value or "").strip()


def _source_context(source: dict[str, Any]) -> str:
    return _text(
        source.get("excerpt")
        or source.get("document")
        or source.get("content")
        or source.get("text")
    )


def _source_id(source: dict[str, Any]) -> str:
    return _text(
        source.get("paper_id")
        or source.get("id")
        or source.get("title")
        or source.get("label")
    )


def _steps(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(
        step
        for value in values
        if (step := _text(value))
        and step != "finish"
        and not step.endswith(":failed")
    )


@dataclass(frozen=True)
class FrameworkCase:
    """One completed workflow case consumable by multiple eval frameworks."""

    case_id: str
    suite: str
    question: str
    answer: str
    contexts: tuple[str, ...] = ()
    retrieved_context_ids: tuple[str, ...] = ()
    reference_context_ids: tuple[str, ...] = ()
    reference_answer: str = ""
    expected_steps: tuple[str, ...] = ()
    actual_steps: tuple[str, ...] = ()
    expected_refusal: bool | None = None
    errors: tuple[str, ...] = ()

    @classmethod
    def from_result(
        cls,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        reference: dict[str, Any] | None = None,
    ) -> "FrameworkCase":
        expected = reference or {}
        sources = [
            source
            for source in outputs.get("sources", [])
            if isinstance(source, dict)
        ]
        contexts = tuple(
            context for source in sources if (context := _source_context(source))
        )
        source_ids = tuple(
            source_id for source in sources if (source_id := _source_id(source))
        )
        expected_refusal = expected.get("expected_refusal")
        return cls(
            case_id=_text(inputs.get("case_id")),
            suite=_text(inputs.get("suite")),
            question=_text(inputs.get("query") or inputs.get("question")),
            answer=_text(outputs.get("answer") or outputs.get("response")),
            contexts=contexts,
            retrieved_context_ids=source_ids,
            reference_context_ids=tuple(
                _text(value)
                for value in expected.get("relevant_source_ids", [])
                if _text(value)
            ),
            reference_answer=_text(expected.get("reference_answer")),
            expected_steps=_steps(expected.get("expected_steps", [])),
            actual_steps=_steps(
                outputs.get("steps", outputs.get("node_history", []))
            ),
            expected_refusal=(
                bool(expected_refusal) if expected_refusal is not None else None
            ),
            errors=tuple(
                _text(value) for value in outputs.get("errors", []) if _text(value)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in tuple(payload.items()):
            if isinstance(value, tuple):
                payload[key] = list(value)
        return payload


def collect_framework_cases(
    suite: str,
    *,
    max_cases: int | None = None,
) -> list[FrameworkCase]:
    """Run existing examples and return their normalized results.

    This function is intentionally called only by explicit live-evaluation
    commands because RAG and workflow suites can invoke models and services.
    """

    from evaluation.dataset import build_examples
    from evaluation.run_evaluation import EvaluationTarget

    examples = build_examples(suite)
    if max_cases is not None:
        if max_cases < 1:
            raise ValueError("max_cases는 1 이상이어야 합니다.")
        examples = examples[:max_cases]

    target = EvaluationTarget()
    return [
        FrameworkCase.from_result(
            example["inputs"],
            target(example["inputs"]),
            example.get("outputs"),
        )
        for example in examples
    ]


def load_v3_framework_cases(
    suite: str,
    *,
    results_path: str | Path | None = None,
    max_cases: int | None = None,
) -> list[FrameworkCase]:
    """Load completed v3 graph results without invoking the application again."""

    from evaluation.v3_runtime import RESULTS_PATH

    path = Path(results_path or RESULTS_PATH)
    if not path.is_file():
        raise FileNotFoundError(
            f"v3 실행 결과가 없습니다: {path}. run_v3_evaluation을 먼저 실행하세요."
        )
    allowed = {"retrieval", "refusal"} if suite == "rag" else {suite}
    cases: list[FrameworkCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        inputs = record.get("inputs", {})
        if str(inputs.get("suite")) not in allowed:
            continue
        cases.append(
            FrameworkCase.from_result(
                inputs,
                record.get("outputs", {}),
                record.get("reference", {}),
            )
        )
        if max_cases is not None and len(cases) >= max_cases:
            break
    return cases


__all__ = ["FrameworkCase", "collect_framework_cases", "load_v3_framework_cases"]
