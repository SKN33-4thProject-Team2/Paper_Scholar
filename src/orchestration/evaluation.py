"""LangSmith-compatible evaluators for routing, retrieval, and grounded answers."""

from __future__ import annotations

import re
from typing import Any

from langchain_openai import ChatOpenAI
from langsmith.evaluation import EvaluationResult
from pydantic import BaseModel, Field


def _reference(reference_outputs: dict[str, Any] | None) -> dict[str, Any]:
    return reference_outputs or {}


def route_sequence_accuracy(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    expected = list(_reference(reference_outputs).get("expected_steps", []))
    actual = list(outputs.get("steps", outputs.get("node_history", [])))
    actual = [step for step in actual if step != "finish" and not str(step).endswith(":failed")]
    if not expected:
        return EvaluationResult(
            key="route_sequence_accuracy",
            score=None,
            comment="expected_steps가 없어 평가하지 않음",
        )
    return EvaluationResult(
        key="route_sequence_accuracy",
        score=float(actual == expected),
        metadata={"expected": expected, "actual": actual},
    )


def retrieval_recall_at_k(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    expected = {str(item) for item in _reference(reference_outputs).get("relevant_source_ids", [])}
    if not expected:
        return EvaluationResult(
            key="retrieval_recall_at_k",
            score=None,
            comment="relevant_source_ids가 없어 평가하지 않음",
        )
    retrieved = [
        {
            str(source.get("id") or ""),
            str(source.get("paper_id") or ""),
        }
        for source in outputs.get("sources", [])
    ]
    matched = {source_id for source_id in expected if any(source_id in item for item in retrieved)}
    score = len(matched) / len(expected)
    return EvaluationResult(
        key="retrieval_recall_at_k",
        score=score,
        metadata={
            "expected": sorted(expected),
            "retrieved": [sorted(item - {""}) for item in retrieved],
        },
    )


def reciprocal_rank(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    expected = {str(item) for item in _reference(reference_outputs).get("relevant_source_ids", [])}
    if not expected:
        return EvaluationResult(
            key="reciprocal_rank",
            score=None,
            comment="relevant_source_ids가 없어 평가하지 않음",
        )
    for rank, source in enumerate(outputs.get("sources", []), start=1):
        source_ids = {
            str(source.get("id") or ""),
            str(source.get("paper_id") or ""),
        }
        if expected.intersection(source_ids):
            return EvaluationResult(key="reciprocal_rank", score=1.0 / rank)
    return EvaluationResult(key="reciprocal_rank", score=0.0)


def refusal_accuracy(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    expected = _reference(reference_outputs).get("expected_refusal")
    if expected is None:
        return EvaluationResult(
            key="refusal_accuracy",
            score=None,
            comment="expected_refusal이 없어 평가하지 않음",
        )
    answer = str(outputs.get("answer") or outputs.get("response") or "").casefold()
    refusal_markers = (
        "근거가 부족",
        "근거를 찾지 못",
        "확인할 수 없",
        "답할 수 없",
        "insufficient evidence",
        "cannot answer",
    )
    refused = any(marker in answer for marker in refusal_markers)
    return EvaluationResult(
        key="refusal_accuracy",
        score=float(refused == bool(expected)),
        metadata={"expected_refusal": bool(expected), "detected_refusal": refused},
    )


def citation_precision(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    answer = str(outputs.get("answer") or outputs.get("response") or "")
    citations = set(re.findall(r"\[(S\d+)\]", answer))
    valid = {str(source.get("label")) for source in outputs.get("sources", [])}
    if not valid:
        return EvaluationResult(
            key="citation_precision",
            score=None,
            comment="검색 근거가 없어 인용 정확도를 평가하지 않음",
        )
    if not citations:
        return EvaluationResult(key="citation_precision", score=0.0)
    return EvaluationResult(
        key="citation_precision",
        score=len(citations.intersection(valid)) / len(citations),
        metadata={"citations": sorted(citations), "valid_labels": sorted(valid)},
    )


class JudgeGrade(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    reason: str


class LLMJudgeEvaluators:
    """Reference correctness and source faithfulness judges.

    Missing references/evidence produce score=None instead of an artificial 1.0.
    """

    def __init__(self, llm: Any | None = None) -> None:
        self._judge = (llm or ChatOpenAI(model="gpt-4o-mini", temperature=0)).with_structured_output(
            JudgeGrade
        )

    def answer_correctness(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        reference_outputs: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        reference = str(_reference(reference_outputs).get("reference_answer", "")).strip()
        if not reference:
            return EvaluationResult(
                key="answer_correctness",
                score=None,
                comment="reference_answer가 없어 평가하지 않음",
            )
        answer = str(outputs.get("answer") or outputs.get("response") or "")
        grade = self._judge.invoke(
            "질문, 기준 답변, 실제 답변을 비교해 의미적 정확도를 0~1로 평가하세요.\n"
            f"질문: {inputs.get('query', inputs.get('question', ''))}\n"
            f"기준 답변: {reference}\n실제 답변: {answer}"
        )
        return EvaluationResult(key="answer_correctness", score=grade.score, comment=grade.reason)

    def faithfulness(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        reference_outputs: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        sources = outputs.get("sources", [])
        if not sources:
            return EvaluationResult(
                key="faithfulness",
                score=None,
                comment="검색 근거가 없어 평가하지 않음",
            )
        answer = str(outputs.get("answer") or outputs.get("response") or "")
        evidence = "\n\n".join(str(source.get("excerpt", "")) for source in sources)
        grade = self._judge.invoke(
            "실제 답변의 주장들이 제공 근거로 뒷받침되는 정도를 0~1로 평가하세요. "
            "근거 밖의 주장은 감점하세요.\n"
            f"근거:\n{evidence}\n\n실제 답변:\n{answer}"
        )
        return EvaluationResult(key="faithfulness", score=grade.score, comment=grade.reason)
