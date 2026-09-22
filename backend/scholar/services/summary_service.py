from __future__ import annotations

from ..models import Paper, PaperSummary


def generate_paper_summary(paper: Paper) -> PaperSummary:
    """기존 v2 요약 도구를 실행하고 MySQL에 저장된 최종 요약을 반환합니다."""
    from src.tools.summary_tool_v2 import SummaryTool

    result = SummaryTool().summarize(
        paper.arxiv_id,
        title=paper.title,
    )
    summary = PaperSummary.objects.get(paper=paper)
    if not summary.model_name and result.model:
        summary.model_name = result.model
        summary.save(update_fields=("model_name", "updated_at"))
    return summary
