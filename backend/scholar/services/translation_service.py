from __future__ import annotations

import logging
import requests
from django.conf import settings

from ..models import Paper, Translation

# 로깅 객체 초기화
logger = logging.getLogger(__name__)

# 마크다운 및 토큰 보존용 학술 프롬프트
SUMMARY_TRANSLATION_PROMPT = """Translate the following academic paper summary from English to Korean.
Return only the complete Korean translation.
Do not summarize, omit, or add information.
Preserve paragraph structure, Markdown, model names, dataset names, citations, numbers, and formulas.
Do not modify __APRAG_PROTECTED_000000__ style protected tokens.

[English summary]
"""

FULL_TEXT_TRANSLATION_PROMPT = """Translate the following academic paper text from English to Korean.
Return only the complete Korean translation.
Do not summarize, omit, or add information.
Preserve section headings, paragraph structure, Markdown, model names, dataset names, citations, numbers, and formulas.
Do not translate bibliography entries or modify __APRAG_PROTECTED_000000__ style protected tokens.

[English paper text]
"""


def _translate_without_markup_tokens(
    service,
    protection,
    token_pattern,
    translation_prompt: str,
) -> str:
    """토큰을 지키지 못하는 모델에서는 텍스트 조각만 번역해 원문 수식을 끼워 넣는다."""
    tokens = tuple(token_pattern.findall(protection.text))
    text_parts = token_pattern.split(protection.text)
    output: list[str] = []

    for index, text_part in enumerate(text_parts):
        if text_part.strip():
            output.append(
                service.translate(f"{translation_prompt}\n{text_part.strip()}").strip()
            )
        if index < len(tokens):
            output.append(protection.replacements[tokens[index]])

    return "\n\n".join(part for part in output if part)


def translate_chunk_preserving_markup(
    service,
    chunk: str,
    *,
    translation_prompt: str = SUMMARY_TRANSLATION_PROMPT,
) -> str:
    """수식·표 토큰을 보존해 번역하고, 토큰 훼손 시 결정적인 조각 번역으로 복구한다."""
    from src.services.translation_markdown_service import (
        PROTECTED_TOKEN_PATTERN,
        TranslationMarkupError,
        protect_translation_markup,
        restore_translation_markup,
    )

    protection = protect_translation_markup(chunk)
    required_tokens = " ".join(protection.token_order)
    prompt = f"{translation_prompt}\n{protection.text}"
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
                    f"{translation_prompt}\n"
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
        translation_prompt,
    )


def _translate_markdown(source_text: str, *, translation_prompt: str):
    from src.services.translation_markdown_service import split_markdown
    from src.services.translation_service import TranslateService

    service = TranslateService()
    service.ensure_available()
    chunks = split_markdown(source_text, max_chars=service.chunk_chars)
    if not chunks:
        raise ValueError("번역할 내용이 없습니다.")

    translated_chunks = [
        translate_chunk_preserving_markup(
            service,
            chunk,
            translation_prompt=translation_prompt,
        )
        for chunk in chunks
    ]
    return service, chunks, "\n\n".join(translated_chunks)


def generate_summary_translation(
    paper: Paper,
    *,
    target_language: str = "ko",
) -> Translation:
    """MySQL 요약을 기존 번역 서비스로 번역하고 결과를 MySQL에 저장합니다."""
    if target_language != "ko":
        raise ValueError("현재 지원하는 번역 대상 언어는 한국어(ko)입니다.")

    from src.services.django_paper_repository import upsert_translation
    summary = paper.summary
    service, chunks, translated_text = _translate_markdown(
        summary.summary_text,
        translation_prompt=SUMMARY_TRANSLATION_PROMPT,
    )

    translation, _created = upsert_translation(
        paper.arxiv_id,
        source_text=summary.summary_text,
        translated_text=translated_text,
        translation_type=Translation.TranslationType.SUMMARY,
        source_language="en",
        target_language=target_language,
        model_name=service.model,
        chunk_count=len(chunks),
    )
    return translation


def generate_full_text_translation(
    paper: Paper,
    *,
    target_language: str = "ko",
) -> Translation:
    """추출된 논문 본문 전체를 섹션 구조를 유지해 번역하고 저장합니다."""
    if target_language != "ko":
        raise ValueError("현재 지원하는 번역 대상 언어는 한국어(ko)입니다.")

    from src.services.django_paper_repository import upsert_translation

    sections = list(paper.sections.order_by("section_order"))
    source_parts = []
    for section in sections:
        text = section.section_text.strip()
        if not text:
            continue
        title = section.section_title.strip()
        source_parts.append(f"# {title}\n\n{text}" if title else text)

    source_text = "\n\n".join(source_parts)
    if not source_text:
        raise ValueError("번역할 본문 섹션이 없습니다.")

    service, chunks, translated_text = _translate_markdown(
        source_text,
        translation_prompt=FULL_TEXT_TRANSLATION_PROMPT,
    )
    translation, _created = upsert_translation(
        paper.arxiv_id,
        source_text=source_text,
        translated_text=translated_text,
        translation_type=Translation.TranslationType.FULL_TEXT,
        source_language="en",
        target_language=target_language,
        model_name=service.model,
        chunk_count=len(chunks),
    )
    return translation


# ==============================================================================
# RunPod Ollama Direct Inference Endpoint
# ==============================================================================
def translate_text(text: str, target_language: str = "Korean") -> str:
    """
    RunPod에서 구동 중인 Ollama(qwen2.5:3b) 인스턴스를 호출하여 텍스트를 대상 언어로 번역합니다.
    """
    # [경계값 검증] 입력 텍스트 공백 및 Null 처리
    if not text or not text.strip():
        logger.warning("번역할 입력 텍스트가 비어 있습니다.")
        return ""

    # RunPod Ollama 엔드포인트 및 모델 파라미터 로드
    base_url = settings.OLLAMA_BASE_URL
    model_name = settings.OLLAMA_MODEL
    api_url = f"{base_url}/api/generate"

    # HTTP 요청 헤더 구성 (RunPod Bearer Token 포함)
    headers = {
        "Content-Type": "application/json",
    }
    if hasattr(settings, "OLLAMA_HEADERS") and settings.OLLAMA_HEADERS:
        headers.update(settings.OLLAMA_HEADERS)

    # 학술 번역 프롬프트 구성
    prompt = (
        f"You are a professional academic paper translator. "
        f"Translate the following text into natural and accurate {target_language}. "
        f"Preserve technical terms and formatting without adding explanations:\n\n"
        f"{text}"
    )

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,  # 번역 왜곡 방지를 위한 낮은 온도로 설정
        },
    }

    try:
        # RunPod 프록시 엔드포인트로 인퍼런스 요청 전송 (네트워크 지연 대비 타임아웃 120초)
        response = requests.post(api_url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        result_json = response.json()

        # 번역 결과 텍스트 추출
        translated_text = result_json.get("response", "").strip()
        return translated_text

    except requests.exceptions.RequestException as e:
        logger.error(f"[RunPod Ollama] 번역 API 호출 실패 (URL: {api_url}): {str(e)}")
        raise RuntimeError(f"RunPod Ollama 번역 처리 중 네트워크 오류가 발생했습니다: {str(e)}") from e
