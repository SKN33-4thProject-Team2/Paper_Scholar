from __future__ import annotations

from ..models import Paper, Translation


TRANSLATION_PROMPT = """Translate the following academic paper summary from English to Korean.
Return only the complete Korean translation.
Do not summarize, omit, or add information.
Preserve paragraph structure, Markdown, model names, dataset names, citations, numbers, and formulas.
Do not modify __APRAG_PROTECTED_000000__ style protected tokens.

[English summary]
"""


def _translate_without_markup_tokens(service, protection, token_pattern) -> str:
    """토큰을 지키지 못하는 모델에서는 텍스트 조각만 번역해 원문 수식을 끼워 넣는다."""
    tokens = tuple(token_pattern.findall(protection.text))
    text_parts = token_pattern.split(protection.text)
    output: list[str] = []

    for index, text_part in enumerate(text_parts):
        if text_part.strip():
            output.append(
                service.translate(f"{TRANSLATION_PROMPT}\n{text_part.strip()}").strip()
            )
        if index < len(tokens):
            output.append(protection.replacements[tokens[index]])

    return "\n\n".join(part for part in output if part)


def translate_chunk_preserving_markup(service, chunk: str) -> str:
    """수식·표 토큰을 보존해 번역하고, 토큰 훼손 시 결정적인 조각 번역으로 복구한다."""
    from src.services.translation_markdown_service import (
        PROTECTED_TOKEN_PATTERN,
        TranslationMarkupError,
        protect_translation_markup,
        restore_translation_markup,
    )

    protection = protect_translation_markup(chunk)
    required_tokens = " ".join(protection.token_order)
    prompt = f"{TRANSLATION_PROMPT}\n{protection.text}"
    if required_tokens:
        prompt = (
            f"{prompt}\n\nEvery protected token below must appear exactly once and in this order:\n"
            f"{required_tokens}"
        )

    markup_attempts = 2 if protection.token_order else 1
    for attempt in range(markup_attempts):
        translated = service.translate(prompt).strip()
        try:
            return restore_translation_markup(translated, protection)
        except TranslationMarkupError:
            if attempt + 1 < markup_attempts:
                prompt = (
                    f"{TRANSLATION_PROMPT}\n"
                    "Your previous response changed or omitted protected tokens. "
                    "Copy every required token verbatim, exactly once, in the original order.\n\n"
                    f"{protection.text}\n\nRequired tokens:\n{required_tokens}"
                )

    # 일부 모델은 긴 수식 토큰을 반복해서 훼손한다. 마지막에는 토큰을 모델에
    # 보내지 않고 텍스트 사이만 번역하여 수식·표를 원래 위치에 확실히 복원한다.
    return _translate_without_markup_tokens(
        service,
        protection,
        PROTECTED_TOKEN_PATTERN,
    )


def generate_summary_translation(
    paper: Paper,
    *,
    target_language: str = "ko",
) -> Translation:
    """MySQL 요약을 기존 번역 서비스로 번역하고 결과를 MySQL에 저장합니다."""
    if target_language != "ko":
        raise ValueError("현재 지원하는 번역 대상 언어는 한국어(ko)입니다.")

    from src.services.django_paper_repository import upsert_translation
    from src.services.translation_markdown_service import split_markdown
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
        translated_chunks.append(translate_chunk_preserving_markup(service, chunk))

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
