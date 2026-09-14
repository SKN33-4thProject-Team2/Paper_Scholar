"""LangGraph agents and shared project paths for the paper workflow."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "paper_extract" / "extracted_papers.db"
DEFAULT_SUMMARY_DB_PATH = PROJECT_ROOT / "data" / "paper_summary" / "summaries.db"

from .translate_agent import TranslateAgent, translate_node
from .summary_agent import SummaryAgent, summary_node

__all__ = [
    "DEFAULT_DB_PATH",
    "DEFAULT_SUMMARY_DB_PATH",
    "PROJECT_ROOT",
    "TranslateAgent",
    "translate_node",
    "SummaryAgent",
    "summary_node",
]
