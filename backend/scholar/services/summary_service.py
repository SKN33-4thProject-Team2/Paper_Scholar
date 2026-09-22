from __future__ import annotations
from ..models import Paper, PaperSummary
import logging
import requests
from django.conf import settings

# 로깅 객체 초기화
logger = logging.getLogger(__name__)

# 재시도 가능한 외부 NVIDIA API 에러 코드 정의
_RETRYABLE_NVIDIA_ERRORS = (" 429", " 500", " 502", " 503", " 504", "overloaded")


def generate_paper_summary(paper: Paper) -> PaperSummary:
    """기존 v2 요약 도구를 실행하고 MySQL에 저장된 최종 요약을 반환합니다."""
    from src.tools.summary_tool_v2 import SummaryTool

    # 웹 요청에서는 여러 청크를 순차 호출하는 방식보다 TF-IDF로 핵심 문장을
    # 선별한 단일 호출 모드를 사용한다. 외부 모델 과부하 가능성과 대기 시간을
    # 줄이면서도 최종 결과 저장 형식은 동일하게 유지된다.
    try:
        result = SummaryTool(single_call=True).summarize(
            paper.arxiv_id,
            title=paper.title,
        )
    except RuntimeError as exc:
        message = str(exc)
        if "NVIDIA API" not in message or not any(
            marker in message for marker in _RETRYABLE_NVIDIA_ERRORS
        ):
            raise

        # NVIDIA Build가 일시적으로 과부하이면 이미 설치된 로컬 모델로 한 번
        # 대체한다. 인증 오류나 잘못된 요청은 숨기지 않고 그대로 실패시킨다.
        result = SummaryTool(
            provider="ollama",
            model="qwen2.5:3b",
            single_call=True,
        ).summarize(
            paper.arxiv_id,
            title=paper.title,
        )
    summary = PaperSummary.objects.get(paper=paper)
    if not summary.model_name and result.model:
        summary.model_name = result.model
        summary.save(update_fields=("model_name", "updated_at"))
    return summary


def generate_summary(text: str, max_tokens: int = 512) -> str:
    """
    RunPod에서 구동 중인 Ollama(qwen2.5:3b) 인스턴스를 호출하여 텍스트 요약을 생성합니다.
    """
    # [경계값 검증] 입력 텍스트 공백 및 Null 체크
    if not text or not text.strip():
        logger.warning("요약할 입력 텍스트가 비어 있습니다.")
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

    # 요약 프롬프트 및 인퍼런스 파라미터 구성
    prompt = (
        "You are an expert academic research assistant. "
        "Please summarize the following text concisely while preserving core technical findings:\n\n"
        f"{text}"
    )

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.3,  # 사실 기반 요약을 위한 낮은 온도로 설정
        },
    }

    try:
        # RunPod 프록시 엔드포인트로 인퍼런스 요청 전송 (타임아웃 120초)
        response = requests.post(api_url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        result_json = response.json()

        # Ollama 반환 텍스트 파싱
        summary_result = result_json.get("response", "").strip()
        return summary_result

    except requests.exceptions.RequestException as e:
        logger.error(f"[RunPod Ollama] 요약 API 호출 실패 (URL: {api_url}): {str(e)}")
        raise RuntimeError(f"RunPod Ollama 요약 생성 중 네트워크 오류가 발생했습니다: {str(e)}") from e