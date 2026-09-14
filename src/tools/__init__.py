"""공용 도구 패키지의 경로 설정."""

from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SRC_DIR.parent
PROJECT_ROOT = PROJECT_DIR
LIBRARY_DB = PROJECT_ROOT / "data" / "paper_list" / "saved_papers.db"
EXTRACTED_DB = PROJECT_ROOT / "data" / "paper_extract" / "extracted_papers.db"
SUMMARY_DB = PROJECT_ROOT / "data" / "paper_summary" / "summary.db"
PAPER_TRANSLATE_DIR = PROJECT_ROOT / "data" / "paper_translate"
TRANSLATE_DB = PAPER_TRANSLATE_DIR / "translate.db"

__all__ = [
    "SRC_DIR",
    "PROJECT_DIR",
    "PROJECT_ROOT",
    "LIBRARY_DB",
    "EXTRACTED_DB",
    "SUMMARY_DB",
    "PAPER_TRANSLATE_DIR",
    "TRANSLATE_DB",
]
