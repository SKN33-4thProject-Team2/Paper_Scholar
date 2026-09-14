"""LangSmith-compatible quality metrics for paper artifacts and workflows."""

from __future__ import annotations

from collections import Counter
import json
import os
import re
from typing import Any, Iterable

from langchain_openai import ChatOpenAI
from langsmith.evaluation import EvaluationResult
from pydantic import BaseModel, Field


_MATH_PATTERN = re.compile(
    r"\$\$.*?\$\$|"
    r"(?<!\$)\$(?!\$).*?(?<!\$)\$(?!\$)|"
    r"\\\[.*?\\\]|\\\(.*?\\\)|"
    r"\\begin\{([^}]+)\}.*?\\end\{\1\}",
    re.DOTALL,
)
_TABLE_SEPARATOR = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_CITATION_PATTERN = re.compile(r"\[(S\d+)\]")


def _reference(reference_outputs: dict[str, Any] | None) -> dict[str, Any]:
    return reference_outputs or {}


def _answer(outputs: dict[str, Any]) -> str:
    return str(outputs.get("answer") or outputs.get("response") or "")


def _normalized_lookup(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _term_recall(text: str, expected: Iterable[object]) -> tuple[float | None, list[str]]:
    terms = [str(item).strip() for item in expected if str(item).strip()]
    if not terms:
        return None, []
    haystack = _normalized_lookup(text)
    matched = [term for term in terms if _normalized_lookup(term) in haystack]
    return len(matched) / len(terms), matched


def _extract_latex(text: str) -> list[str]:
    return [
        re.sub(r"\s+", "", match.group(0))
        for match in _MATH_PATTERN.finditer(text)
        if match.group(0).strip()
    ]


def _table_cells(row: str) -> list[str]:
    stripped = row.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _extract_table_signatures(text: str) -> list[tuple[int, tuple[int, ...]]]:
    lines = text.splitlines()
    signatures: list[tuple[int, tuple[int, ...]]] = []
    index = 0
    while index < len(lines) - 1:
        if "|" not in lines[index] or not _TABLE_SEPARATOR.match(lines[index + 1]):
            index += 1
            continue
        rows = [lines[index], lines[index + 1]]
        index += 2
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            rows.append(lines[index])
            index += 1
        signatures.append((len(rows), tuple(len(_table_cells(row)) for row in rows)))
    return signatures


def _multiset_recall(expected: list[Any], actual: list[Any]) -> float | None:
    if not expected:
        return None
    expected_counts = Counter(expected)
    actual_counts = Counter(actual)
    matched = sum(min(count, actual_counts[item]) for item, count in expected_counts.items())
    return matched / sum(expected_counts.values())


def latex_preservation(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    source_items = _extract_latex(str(outputs.get("source_text") or ""))
    translated_items = _extract_latex(str(outputs.get("translation_text") or ""))
    score = _multiset_recall(source_items, translated_items)
    return EvaluationResult(
        key="translation_latex_preservation",
        score=score,
        comment="원문에 LaTeX 수식이 없어 평가하지 않음" if score is None else None,
        metadata={"source_count": len(source_items), "translated_count": len(translated_items)},
    )


def markdown_table_preservation(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    source_tables = _extract_table_signatures(str(outputs.get("source_text") or ""))
    translated_tables = _extract_table_signatures(str(outputs.get("translation_text") or ""))
    score = _multiset_recall(source_tables, translated_tables)
    return EvaluationResult(
        key="translation_table_structure_preservation",
        score=score,
        comment="원문에 Markdown 표가 없어 평가하지 않음" if score is None else None,
        metadata={"source_tables": len(source_tables), "translated_tables": len(translated_tables)},
    )


def translation_term_recall(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    expected = _reference(reference_outputs).get("expected_translation_terms", [])
    score, matched = _term_recall(str(outputs.get("translation_text") or ""), expected)
    return EvaluationResult(
        key="translation_term_recall",
        score=score,
        comment="expected_translation_terms가 없어 평가하지 않음" if score is None else None,
        metadata={"expected": list(expected), "matched": matched},
    )


def extraction_title_accuracy(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    """Check that the isolated extraction DB preserved the selected title."""

    expected = str(_reference(reference_outputs).get("expected_title") or "").strip()
    actual = str(outputs.get("title") or "").strip()
    if not expected:
        return EvaluationResult(
            key="extraction_title_accuracy",
            score=None,
            comment="expected_title이 없어 평가하지 않음",
        )
    return EvaluationResult(
        key="extraction_title_accuracy",
        score=float(_normalized_lookup(expected) == _normalized_lookup(actual)),
        metadata={"expected_title": expected, "actual_title": actual},
    )


def extraction_content_completeness(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    """Score minimum page and character requirements without an LLM judge."""

    reference = _reference(reference_outputs)
    expected_pages = max(1, int(reference.get("expected_min_pages") or 1))
    expected_chars = max(1, int(reference.get("expected_min_characters") or 1))
    actual_pages = max(0, int(outputs.get("n_pages") or 0))
    actual_chars = max(0, int(outputs.get("n_chars") or 0))
    score = (
        min(actual_pages / expected_pages, 1.0)
        + min(actual_chars / expected_chars, 1.0)
    ) / 2
    return EvaluationResult(
        key="extraction_content_completeness",
        score=score,
        metadata={
            "expected_min_pages": expected_pages,
            "actual_pages": actual_pages,
            "expected_min_characters": expected_chars,
            "actual_characters": actual_chars,
        },
    )


def summary_title_preservation(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    title = str(_reference(reference_outputs).get("title") or outputs.get("title") or "").strip()
    if not title:
        return EvaluationResult(
            key="summary_title_preservation",
            score=None,
            comment="논문 제목이 없어 평가하지 않음",
        )
    summary = _normalized_lookup(str(outputs.get("summary_text") or ""))
    return EvaluationResult(
        key="summary_title_preservation",
        score=float(_normalized_lookup(title) in summary),
        metadata={"title": title},
    )


def summary_acronym_recall(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    expected = _reference(reference_outputs).get("expected_acronyms", [])
    score, matched = _term_recall(str(outputs.get("summary_text") or ""), expected)
    return EvaluationResult(
        key="summary_acronym_recall",
        score=score,
        comment="expected_acronyms가 없어 평가하지 않음" if score is None else None,
        metadata={"expected": list(expected), "matched": matched},
    )


def summary_numeric_recall(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    expected = _reference(reference_outputs).get("expected_numbers", [])
    score, matched = _term_recall(str(outputs.get("summary_text") or ""), expected)
    return EvaluationResult(
        key="summary_numeric_recall",
        score=score,
        comment="expected_numbers가 없어 평가하지 않음" if score is None else None,
        metadata={"expected": list(expected), "matched": matched},
    )


def required_term_recall(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    expected = _reference(reference_outputs).get("required_terms", [])
    score, matched = _term_recall(_answer(outputs), expected)
    return EvaluationResult(
        key="required_term_recall",
        score=score,
        comment="required_terms가 없어 평가하지 않음" if score is None else None,
        metadata={"expected": list(expected), "matched": matched},
    )


def passage_section_recall_at_5(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    """Check whether the expected evidence section appears in the top five passages."""

    expected = str(_reference(reference_outputs).get("reference_section") or "").strip()
    if not expected:
        return EvaluationResult(
            key="passage_section_recall_at_5",
            score=None,
            comment="reference_section이 없어 평가하지 않음",
        )
    retrieved = [
        str(source.get("section") or "").strip()
        for source in list(outputs.get("sources") or [])[:5]
        if isinstance(source, dict)
    ]
    return EvaluationResult(
        key="passage_section_recall_at_5",
        score=float(expected in retrieved),
        metadata={"expected_section": expected, "retrieved_sections": retrieved},
    )


def passage_section_reciprocal_rank(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    """Measure the rank of the first passage from the expected evidence section."""

    expected = str(_reference(reference_outputs).get("reference_section") or "").strip()
    if not expected:
        return EvaluationResult(
            key="passage_section_mrr",
            score=None,
            comment="reference_section이 없어 평가하지 않음",
        )
    retrieved = [
        str(source.get("section") or "").strip()
        for source in list(outputs.get("sources") or [])[:5]
        if isinstance(source, dict)
    ]
    rank = next((index for index, section in enumerate(retrieved, 1) if section == expected), None)
    return EvaluationResult(
        key="passage_section_mrr",
        score=0.0 if rank is None else 1.0 / rank,
        metadata={"expected_section": expected, "first_relevant_rank": rank},
    )


def deep_research_completion(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    history = [str(item) for item in outputs.get("node_history", [])]
    errors = [str(item) for item in outputs.get("errors", []) if str(item).strip()]
    completed = bool(_answer(outputs).strip()) and "deep_research" in history and not errors
    return EvaluationResult(
        key="deep_research_completion",
        score=float(completed),
        metadata={"node_history": history, "errors": errors},
    )


def pipeline_completion(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any] | None = None,
) -> EvaluationResult:
    reference = _reference(reference_outputs)
    required_keys = [str(item) for item in reference.get("expected_output_keys", [])]
    missing = [key for key in required_keys if not outputs.get(key)]
    errors = [str(item) for item in outputs.get("errors", []) if str(item).strip()]
    history = [str(item) for item in outputs.get("node_history", [])]
    completed = bool(_answer(outputs).strip()) and not missing and not errors and "finish" in history
    return EvaluationResult(
        key="pipeline_completion",
        score=float(completed),
        metadata={"required_keys": required_keys, "missing_keys": missing, "errors": errors},
    )


class QualityGrade(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    reason: str


class QualityJudgeEvaluators:
    """LLM judges for semantics that deterministic preservation checks cannot prove."""

    def __init__(self, llm: Any | None = None) -> None:
        base_llm = llm or ChatOpenAI(
            model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
            temperature=0,
        )
        self._judge = base_llm.with_structured_output(QualityGrade)

    def translation_quality(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        reference_outputs: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        source = str(outputs.get("source_text") or "")
        translation = str(outputs.get("translation_text") or "")
        if not source or not translation:
            return EvaluationResult(
                key="translation_quality",
                score=0.0,
                comment="원문 또는 번역문이 없음",
            )
        grade = self._judge.invoke(
            "영문 학술 원문과 한국어 번역을 비교해 의미 보존, 누락 여부, 전문용어 정확성, "
            "한국어 유창성을 종합하여 0~1로 평가하세요. 번역문에 없는 사실이 추가되면 감점하세요.\n\n"
            f"[원문 발췌]\n{source[:8000]}\n\n[번역문 발췌]\n{translation[:8000]}"
        )
        return EvaluationResult(key="translation_quality", score=grade.score, comment=grade.reason)

    def summary_quality(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        reference_outputs: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        translation = str(outputs.get("translation_text") or "")
        summary = str(outputs.get("summary_text") or "")
        if not translation or not summary:
            return EvaluationResult(key="summary_quality", score=0.0, comment="번역문 또는 요약문이 없음")
        grade = self._judge.invoke(
            "논문 번역문과 요약문을 비교해 연구 목적, 방법, 핵심 결과, 한계의 정확성과 "
            "중요 정보 보존 정도를 0~1로 평가하세요. 근거 없는 내용은 감점하세요.\n\n"
            f"[번역문 발췌]\n{translation[:10000]}\n\n[요약문]\n{summary[:10000]}"
        )
        return EvaluationResult(key="summary_quality", score=grade.score, comment=grade.reason)

    def citation_grounding(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        reference_outputs: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        answer = _answer(outputs)
        sources = {
            str(source.get("label")): str(source.get("excerpt") or "")
            for source in outputs.get("sources", [])
            if source.get("label")
        }
        cited_claims = []
        for sentence in re.split(r"(?<=[.!?。])\s+|\n+", answer):
            labels = _CITATION_PATTERN.findall(sentence)
            if labels:
                cited_claims.append(
                    {
                        "claim": sentence,
                        "evidence": {label: sources.get(label, "") for label in labels},
                    }
                )
        if not cited_claims:
            return EvaluationResult(
                key="citation_grounding",
                score=0.0,
                comment="근거 일치를 평가할 인용 문장이 없음",
            )
        grade = self._judge.invoke(
            "각 주장과 그 문장이 인용한 근거를 대조하세요. 근거가 주장을 직접 뒷받침하는 비율을 "
            "0~1로 평가하고, 존재하지 않는 인용 번호나 근거 밖의 수치·사실은 감점하세요.\n\n"
            + json.dumps(cited_claims, ensure_ascii=False)
        )
        return EvaluationResult(
            key="citation_grounding",
            score=grade.score,
            comment=grade.reason,
            metadata={"cited_claim_count": len(cited_claims)},
        )

    def deep_research_quality(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        reference_outputs: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        answer = _answer(outputs)
        if not answer:
            return EvaluationResult(key="deep_research_quality", score=0.0, comment="답변이 없음")
        sources = outputs.get("sources", [])
        grade = self._judge.invoke(
            "Deep Research 답변의 비교·종합 수준, 질문 충족도, 출처 기반성, 한계 명시를 "
            "0~1로 평가하세요. 출처가 없거나 근거 없이 확장한 내용은 감점하세요.\n\n"
            f"질문: {inputs.get('query', '')}\n답변: {answer}\n"
            f"출처: {json.dumps(sources, ensure_ascii=False)}"
        )
        return EvaluationResult(key="deep_research_quality", score=grade.score, comment=grade.reason)


ARTIFACT_EVALUATORS = (
    latex_preservation,
    markdown_table_preservation,
    translation_term_recall,
    summary_title_preservation,
    summary_acronym_recall,
    summary_numeric_recall,
)

EXTRACTION_EVALUATORS = (
    extraction_title_accuracy,
    extraction_content_completeness,
)

DEEP_RESEARCH_EVALUATORS = (deep_research_completion, required_term_recall)
PIPELINE_EVALUATORS = (pipeline_completion,)


__all__ = [
    "ARTIFACT_EVALUATORS",
    "DEEP_RESEARCH_EVALUATORS",
    "EXTRACTION_EVALUATORS",
    "PIPELINE_EVALUATORS",
    "QualityGrade",
    "QualityJudgeEvaluators",
    "deep_research_completion",
    "extraction_content_completeness",
    "extraction_title_accuracy",
    "latex_preservation",
    "markdown_table_preservation",
    "passage_section_recall_at_5",
    "passage_section_reciprocal_rank",
    "pipeline_completion",
    "required_term_recall",
    "summary_acronym_recall",
    "summary_numeric_recall",
    "summary_title_preservation",
    "translation_term_recall",
]
