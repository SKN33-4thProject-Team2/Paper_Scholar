"""Deterministic Promptfoo assertions shared by all regression cases."""

from __future__ import annotations

from typing import Any


ERROR_MARKERS = (
    "traceback",
    "작업을 완료하지 못했습니다",
    "modulenotfounderror",
    "importerror",
)
REFUSAL_MARKERS = (
    "근거가 부족",
    "근거를 찾지 못",
    "확인할 수 없",
    "답할 수 없",
    "insufficient evidence",
    "cannot answer",
)


def response_quality(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Score non-empty output, required terms, and expected refusal behavior."""

    answer = str(output or "").strip()
    lowered = answer.casefold()
    variables = context.get("vars", {}) if isinstance(context, dict) else {}
    required_terms = [
        str(value).strip()
        for value in variables.get("required_terms", [])
        if str(value).strip()
    ]
    expected_refusal = variables.get("expected_refusal")

    non_empty = min(len(answer) / 80, 1.0) if answer else 0.0
    no_error = float(not any(marker in lowered for marker in ERROR_MARKERS))
    if required_terms:
        matched = sum(term.casefold() in lowered for term in required_terms)
        term_score = matched / len(required_terms)
    else:
        term_score = 1.0
    refusal_detected = any(marker in lowered for marker in REFUSAL_MARKERS)
    refusal_score = (
        1.0
        if expected_refusal is None
        else float(refusal_detected == bool(expected_refusal))
    )
    score = round(
        0.25 * non_empty + 0.25 * no_error + 0.3 * term_score + 0.2 * refusal_score,
        4,
    )
    return {
        "pass": score >= 0.6,
        "score": score,
        "reason": (
            f"응답길이={non_empty:.2f}, 오류없음={no_error:.2f}, "
            f"필수어={term_score:.2f}, 거절정확도={refusal_score:.2f}"
        ),
        "namedScores": {
            "non_empty": non_empty,
            "no_error": no_error,
            "required_terms": term_score,
            "refusal_accuracy": refusal_score,
        },
    }


__all__ = ["response_quality"]
