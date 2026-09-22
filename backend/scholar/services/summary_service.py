from __future__ import annotations

from ..models import Paper, PaperSummary


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
