"""New evaluators for the corpus_v4 harness.

These are written fresh here rather than by editing
``src/orchestration/evaluation.py`` (which must not be touched): v4's
paper_sections are page-based, not semantically named, so page-level
Recall@K / MRR need different matching logic than the v3 evaluators. A new
"관련성" (answer relevancy) LLM judge is added here too, since no equivalent
existed in the reusable evaluator library.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from langchain_openai import ChatOpenAI
from langsmith.evaluation import EvaluationResult

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from orchestration.evaluation import JudgeGrade


def _reference(reference_outputs: dict[str, Any] | None) -> dict[str, Any]:
    return reference_outputs or {}


def page_recall_at_k(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    """검색 품질(Recall): 정답 페이지가 상위 K개 근거 안에 포함되는가."""
    expected_section = str(_reference(reference_outputs).get("expected_section") or "")
    if not expected_section:
        return EvaluationResult(
            key="page_recall_at_k", score=None, comment="expected_section이 없어 평가하지 않음"
        )
    retrieved_sections = [str(source.get("section") or "") for source in outputs.get("sources", [])]
    hit = expected_section in retrieved_sections
    return EvaluationResult(
        key="page_recall_at_k",
        score=float(hit),
        metadata={"expected_section": expected_section, "retrieved_sections": retrieved_sections},
    )


def page_reciprocal_rank(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    """검색 품질(MRR): 정답 페이지가 몇 번째 근거로 나오는가."""
    expected_section = str(_reference(reference_outputs).get("expected_section") or "")
    if not expected_section:
        return EvaluationResult(
            key="page_reciprocal_rank", score=None, comment="expected_section이 없어 평가하지 않음"
        )
    for rank, source in enumerate(outputs.get("sources", []), start=1):
        if str(source.get("section") or "") == expected_section:
            return EvaluationResult(key="page_reciprocal_rank", score=1.0 / rank)
    return EvaluationResult(key="page_reciprocal_rank", score=0.0)


class V4RelevancyJudge:
    """관련성(Answer Relevancy): 답변이 질문 자체에 얼마나 직접적으로 부합하는가.

    faithfulness(출처 근거와 답변의 정합성)와는 독립적으로, 질문-답변 간
    주제적 적합도만 평가한다. 회피성 답변이나 논점 이탈은 감점한다.
    """

    def __init__(self, llm: Any | None = None) -> None:
        self._judge = (llm or ChatOpenAI(model="gpt-4o-mini", temperature=0)).with_structured_output(
            JudgeGrade
        )

    def answer_relevancy(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        reference_outputs: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        question = str(inputs.get("query") or inputs.get("question") or "")
        answer = str(outputs.get("answer") or outputs.get("response") or "")
        if not answer.strip():
            return EvaluationResult(key="answer_relevancy", score=0.0, comment="빈 답변")
        grade = self._judge.invoke(
            "아래 질문과 답변만 보고, 답변이 질문에서 요구한 내용을 얼마나 직접적으로 "
            "다루는지 0~1로 평가하세요. 근거 자료의 사실 여부가 아니라 "
            "'질문에 대한 대답으로서의 적합성'만 평가하세요. 질문과 무관한 내용, "
            "논점 이탈, 회피성 답변은 감점하세요.\n"
            f"질문: {question}\n답변: {answer}"
        )
        return EvaluationResult(key="answer_relevancy", score=grade.score, comment=grade.reason)


__all__ = ["V4RelevancyJudge", "page_recall_at_k", "page_reciprocal_rank"]
