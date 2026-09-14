"""Build a small multi-paper RAG evaluation corpus without editing team files."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services.model_config_service import load_task_config
from services.summary_vector_store import ChromaSummaryStore
from tools.summary_tool import SummaryTool


DEFAULT_PAPER_IDS = ("2007.13199v2", "2107.06493v1")
EXTRACT_DB = PROJECT_ROOT / "data" / "paper_extract" / "extracted_papers.db"
# 요약은 SummaryTool 이 하고, 어떤 모델이 만들었는지는 설정에서 읽어 그대로 남긴다.
# 여기에 모델명을 적어 두면 model_config.yaml 의 summary.model 을 바꿨을 때
# 메타데이터만 옛 이름으로 남아, 나중에 어떤 모델이 만든 요약인지 알 수 없게 된다.
SUMMARY_MODEL = str(load_task_config("summary")["model"])


def load_paper(paper_id: str) -> tuple[str, str]:
    with sqlite3.connect(EXTRACT_DB) as connection:
        row = connection.execute(
            "SELECT title, content FROM extracted WHERE id = ?",
            (paper_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"추출 DB에 없는 paper_id입니다: {paper_id}")
    return str(row[0]), str(row[1])


def indexed_paper_ids(store: ChromaSummaryStore) -> set[str]:
    collection = store._collection()
    payload = collection.get(include=["metadatas"])
    return {
        str(metadata.get("paper_id"))
        for metadata in payload.get("metadatas", [])
        if metadata and metadata.get("paper_id")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the multi-paper RAG eval corpus")
    parser.add_argument("--paper-id", action="append", dest="paper_ids")
    args = parser.parse_args()

    store = ChromaSummaryStore()
    existing = indexed_paper_ids(store)
    summarizer = SummaryTool(summary_store=store)
    for paper_id in args.paper_ids or list(DEFAULT_PAPER_IDS):
        if paper_id in existing:
            print(f"[skip] already indexed: {paper_id}")
            continue
        title, content = load_paper(paper_id)
        sections = summarizer.summarize_markdown(content, title=title, paper_id=paper_id)
        stored = store.save(
            paper_id=paper_id,
            title=title,
            source="extracted_markdown_for_evaluation",
            summary_model=SUMMARY_MODEL,
            sections=sections,
        )
        print(f"[done] {paper_id}: {stored} sections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
