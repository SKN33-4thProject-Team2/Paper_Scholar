"""DB 기반 논문 번역 에이전트."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, TypedDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tools import SUMMARY_DB, TRANSLATE_DB
from tools.translate_tool_v2 import ContentTranslator, TranslateTool


class TranslateState(TypedDict, total=False):
    db: str
    translated_paths: list[str]
    node_history: list[str]


class TranslateAgent:
    """입력 DB의 요약을 번역하고 translate.db에 저장한다."""

    def __init__(self, db: str | Path = SUMMARY_DB, *, translator: ContentTranslator | None = None,
                 translate_db: str | Path = TRANSLATE_DB) -> None:
        self.db = Path(db)
        self.translate_db = Path(translate_db)
        self.translate_db.parent.mkdir(parents=True, exist_ok=True)
        self.translator = translator

    def run(self, *, limit: int | None = None) -> dict[str, Any]:
        """전달받은 요약 DB의 모든 레코드를 번역·저장한다."""
        tool = TranslateTool(summary_db=self.db, translate_db=self.translate_db,
                             translator=self.translator)
        paper_ids = None
        if limit is not None:
            with sqlite3.connect(self.db) as db:
                rows = db.execute(
                    "SELECT paper_id FROM paper_summaries ORDER BY rowid LIMIT ?",
                    (limit,),
                ).fetchall()
            paper_ids = [str(row[0]) for row in rows]
        paths = tool.translate_database(paper_ids)
        return {"translated_paths": [str(path) for path in paths],
                "translate_db": str(self.translate_db), "node_history": ["translate"]}

    def __call__(self, state: TranslateState | str | Path | None = None) -> dict[str, Any]:
        if isinstance(state, (str, Path)):
            self.db = Path(state)
            return self.run()
        if state and state.get("db"):
            self.db = Path(state["db"])
        return self.run()


def translate_node(state: TranslateState | str | Path) -> dict[str, Any]:
    """기본 summary DB를 입력으로 사용하는 LangGraph 노드."""
    return TranslateAgent(SUMMARY_DB)(state)


__all__ = ["TranslateAgent", "TranslateState", "translate_node"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="요약 DB 전체를 번역해 translate.db에 저장")
    parser.add_argument("db", nargs="?", default=str(SUMMARY_DB),
                        help="번역할 요약 DB 경로")
    parser.add_argument("--translate-db", default=str(TRANSLATE_DB),
                        help="번역 결과 DB 경로")
    parser.add_argument("--all", action="store_true", help="전체 요약을 번역")
    args = parser.parse_args()

    limit = None if args.all else 1
    result = TranslateAgent(args.db, translate_db=args.translate_db).run(limit=limit)
    print(f"번역 DB 저장 완료: {result['translate_db']}")
    print(f"생성된 Markdown 수: {len(result['translated_paths'])}")
