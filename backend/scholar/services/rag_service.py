from __future__ import annotations

from typing import Any

from ..models import Paper, Translation


def _section_text(sections: list[Any], *keywords: str) -> str:
    return "\n\n".join(
        section.section_text
        for section in sections
        if any(keyword in section.section_title.casefold() for keyword in keywords)
    )


def build_rag_paper(paper: Paper) -> dict[str, Any]:
    """기존 RAG 답변기가 이해하는 논문 구조를 MySQL 데이터로 구성합니다."""
    sections = list(paper.sections.all())
    summary = getattr(paper, "summary", None)
    translation = paper.translations.filter(
        translation_type=Translation.TranslationType.SUMMARY,
        target_language="ko",
    ).first()
    abstract = paper.abstract or _section_text(sections, "abstract", "초록")
    return {
        "id": paper.arxiv_id,
        "title": paper.title,
        "abstract": abstract,
        "method": _section_text(
            sections,
            "method",
            "approach",
            "model",
            "방법",
        ),
        "result": _section_text(
            sections,
            "result",
            "experiment",
            "evaluation",
            "결과",
            "실험",
        ),
        "conclusion": _section_text(sections, "conclusion", "결론"),
        "structured_summary": summary.summary_text if summary else "",
        "translation_text": translation.translated_text if translation else "",
    }


def create_rag_answerer():
    from src.feature.deep_research import (
        ChromaSummaryRetriever,
        KeywordPaperRetriever,
        LangChainPaperAnswerer,
    )

    retriever = ChromaSummaryRetriever(
        top_k=4,
        fallback=KeywordPaperRetriever(top_k=4),
    )
    return LangChainPaperAnswerer.with_openai(retriever=retriever)


def answer_paper_question(
    paper: Paper,
    question: str,
    *,
    answerer=None,
) -> dict[str, Any]:
    """선택한 논문만 근거로 답하고 출처를 API 형식으로 정규화합니다."""
    resolved_answerer = answerer or create_rag_answerer()
    result = resolved_answerer.answer(build_rag_paper(paper), question)
    if isinstance(result, str):
        result = {"answer": result, "sources": []}
    sources = [
        {"index": index, "text": str(source)}
        for index, source in enumerate(result.get("sources") or [], start=1)
    ]
    return {
        "arxiv_id": paper.arxiv_id,
        "question": question,
        "answer": str(result.get("answer") or "").strip(),
        "sources": sources,
        "model": str(result.get("model") or ""),
    }
