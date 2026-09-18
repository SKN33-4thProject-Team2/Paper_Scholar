from __future__ import annotations

from ..models import Paper, Translation


TRANSLATION_PROMPT = """Translate the following academic paper summary from English to Korean.
Return only the complete Korean translation.
Do not summarize, omit, or add information.
Preserve paragraph structure, Markdown, model names, dataset names, citations, numbers, and formulas.
Do not modify __APRAG_PROTECTED_000000__ style protected tokens.

[English summary]
"""


def generate_summary_translation(
    paper: Paper,
    *,
    target_language: str = "ko",
) -> Translation:
    """MySQL 요약을 기존 번역 서비스로 번역하고 결과를 MySQL에 저장합니다."""
    if target_language != "ko":
        raise ValueError("현재 지원하는 번역 대상 언어는 한국어(ko)입니다.")

    from src.services.django_paper_repository import upsert_translation
    from src.services.translation_markdown_service import (
        protect_translation_markup,
        restore_translation_markup,
        split_markdown,
    )
    from src.services.translation_service import TranslateService

    summary = paper.summary
    service = TranslateService()
    service.ensure_available()
    chunks = split_markdown(
        summary.summary_text,
        max_chars=service.chunk_chars,
    )
    if not chunks:
        raise ValueError("번역할 요약 내용이 없습니다.")

    translated_chunks = []
    for chunk in chunks:
        protection = protect_translation_markup(chunk)
        translated = service.translate(
            f"{TRANSLATION_PROMPT}\n{protection.text}"
        )
        translated_chunks.append(
            restore_translation_markup(translated.strip(), protection)
        )

    translation, _created = upsert_translation(
        paper.arxiv_id,
        source_text=summary.summary_text,
        translated_text="\n\n".join(translated_chunks),
        translation_type=Translation.TranslationType.SUMMARY,
        source_language="en",
        target_language=target_language,
        model_name=service.model,
        chunk_count=len(chunks),
    )
    return translation
