"""요약 SQLite DB를 번역 DB로 변환하고 Markdown으로 내보내는 도구.

실행 예시::

    python -m src.tools.translate_tool_v2
    python -m src.tools.translate_tool_v2 --paper-id 1702.01806v2
    python -m src.tools.translate_tool_v2 --export-only

번역 모델은 ``model_config.yaml``의 Gemini 설정을 사용한다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from services.translation_service import TranslateService
from dotenv import load_dotenv

from services.translation_markdown_service import (
    protect_translation_markup,
    restore_translation_markup,
    split_markdown,
)
from services.model_config_service import load_task_config
from tools import PAPER_TRANSLATE_DIR, SUMMARY_DB, TRANSLATE_DB

load_dotenv()

DEFAULT_SUMMARY_DB = SUMMARY_DB
DEFAULT_TRANSLATE_DIR = PAPER_TRANSLATE_DIR
DEFAULT_TRANSLATE_DB = TRANSLATE_DB


class ContentTranslator(Protocol):
    def translate(self, content: str) -> tuple[str, int]: ...


class _ContentTranslator:
    """DB에서 읽은 텍스트 콘텐츠를 문서 종류와 관계없이 번역한다."""

    PROMPT = """Translate the following document content from English to Korean.
Return only the complete Korean translation.
Do not summarize, omit, or copy the English source text.
Preserve the original paragraph structure and Markdown formatting.
Never modify LaTeX formulas, tables, or protected tokens.
Do not add explanations, comments, or code fences.

[English source content]
"""

    def __init__(self) -> None:
        config = load_task_config("translation")
        self.model = str(config.get("model", "gemini-2.5-flash"))
        self.chunk_chars = int(config.get("chunk_chars", 700))
        self.service = TranslateService()

    def translate(self, content: str) -> tuple[str, int]:
        # 긴 요약은 모델 입력 한도와 응답 안정성을 위해 나누어 번역한다.
        chunk_chars = min(self.chunk_chars, 1500)
        chunks = split_markdown(content, max_chars=chunk_chars)
        translated_chunks: list[str] = []
        for chunk in chunks:
            protection = protect_translation_markup(chunk)
            translated = self.service.translate(f"{self.PROMPT}\n{protection.text}")
            result = restore_translation_markup(translated.strip(), protection)
            korean_chars = sum("가" <= char <= "힣" for char in result)
            if korean_chars == 0 and any("A" <= char <= "z" for char in chunk):
                raise RuntimeError("번역 결과가 한국어가 아닙니다.")
            translated_chunks.append(result)
        return "\n\n".join(translated_chunks), len(chunks)



class TranslateTool:
    """요약 DB를 읽어 번역 DB를 만들고, 번역 결과를 Markdown으로 저장한다."""

    def __init__(
        self,
        summary_db: str | Path = DEFAULT_SUMMARY_DB,
        translate_db: str | Path = DEFAULT_TRANSLATE_DB,
        markdown_dir: str | Path = DEFAULT_TRANSLATE_DIR,
        translator: ContentTranslator | None = None,
    ) -> None:
        self.summary_db = Path(summary_db)
        self.translate_db = Path(translate_db)
        self.markdown_dir = Path(markdown_dir)
        self.translator = translator or _ContentTranslator()

    def _init_db(self, db: sqlite3.Connection) -> None:
        db.execute("""CREATE TABLE IF NOT EXISTS translations (
            paper_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source_summary TEXT NOT NULL,
            translated_summary TEXT NOT NULL,
            chunk_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")

    def _sync_translation_to_mysql(
        self,
        paper_id: str,
        source_text: str,
        translated_text: str,
        chunk_count: int,
    ) -> None:
        """SQLite 번역 저장을 유지하면서 요약 번역을 MySQL에도 동기화한다."""
        try:
            from services.django_paper_repository import upsert_translation

            upsert_translation(
                paper_id,
                source_text=source_text,
                translated_text=translated_text,
                translation_type="summary",
                model_name=str(getattr(self.translator, "model", "")),
                chunk_count=chunk_count,
            )
        except Exception as exc:
            print(f"[Warning] MySQL 요약 번역 동기화 실패: {exc}")

    def _read_summaries(self, paper_ids: list[str] | None = None) -> list[sqlite3.Row]:
        if not self.summary_db.is_file():
            raise FileNotFoundError(f"요약 DB를 찾을 수 없습니다: {self.summary_db}")
        with sqlite3.connect(self.summary_db) as db:
            db.row_factory = sqlite3.Row
            query = "SELECT paper_id, title, summary_text FROM paper_summaries"
            params: tuple[str, ...] = ()
            ids = [x.strip() for x in (paper_ids or []) if x.strip()]
            if ids:
                query += " WHERE paper_id IN (" + ",".join("?" for _ in ids) + ")"
                params = tuple(ids)
            query += " ORDER BY rowid"
            paper_rows = db.execute(query, params).fetchall()

            # 최종 요약(summary_text)이 축약되어 있을 수 있으므로,
            # 실제 요약 청크 전체를 순서대로 합쳐 번역 입력으로 사용한다.
            result: list[sqlite3.Row] = []
            for paper in paper_rows:
                chunks = db.execute(
                    """SELECT summary_text FROM paper_summary_chunks
                       WHERE paper_id = ? ORDER BY section_order, chunk_index""",
                    (paper["paper_id"],),
                ).fetchall()
                content = "\n\n".join(
                    str(chunk["summary_text"] or "").strip()
                    for chunk in chunks
                    if str(chunk["summary_text"] or "").strip()
                )
                if not content:
                    content = str(paper["summary_text"] or "").strip()
                result.append(
                    {"paper_id": paper["paper_id"], "title": paper["title"], "summary_text": content}
                )
            return result

    @staticmethod
    def _safe_name(value: str) -> str:
        name = re.sub(r"[^A-Za-z0-9가-힣._-]+", "_", value).strip("._")
        return name or "translation"

    def translate_database(self, paper_ids: list[str] | None = None) -> list[Path]:
        """원본 DB를 읽어 번역 DB에 저장하고 Markdown 파일을 만든다."""
        rows = self._read_summaries(paper_ids)
        if not rows:
            raise ValueError("번역할 요약 결과가 없습니다.")
        self.translate_db.parent.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        outputs: list[Path] = []
        mysql_sync_rows: list[tuple[str, str, str, int]] = []
        with sqlite3.connect(self.translate_db) as db:
            self._init_db(db)
            for row in rows:
                source = str(row["summary_text"] or "").strip()
                if not source:
                    continue
                translated, chunk_count = self.translator.translate(source)
                db.execute("""INSERT INTO translations
                    (paper_id, title, source_summary, translated_summary, chunk_count, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(paper_id) DO UPDATE SET
                    title=excluded.title, source_summary=excluded.source_summary,
                    translated_summary=excluded.translated_summary, chunk_count=excluded.chunk_count,
                    updated_at=excluded.updated_at""",
                    (row["paper_id"], row["title"] or row["paper_id"], source,
                     translated, chunk_count, now, now))
                mysql_sync_rows.append(
                    (str(row["paper_id"]), source, translated, chunk_count)
                )
                outputs.append(self.export_markdown(str(row["paper_id"]), db=db,
                                                    title=str(row["title"] or row["paper_id"]),
                                                    translated=str(translated)))
            db.commit()
        for paper_id, source, translated, chunk_count in mysql_sync_rows:
            self._sync_translation_to_mysql(
                paper_id,
                source,
                translated,
                chunk_count,
            )
        return outputs

    # 기존 호출부와의 호환용 별칭
    translate_and_save = translate_database

    def export_markdown(self, paper_id: str, *, db: sqlite3.Connection | None = None,
                        title: str | None = None, translated: str | None = None) -> Path:
        close = db is None
        connection = db or sqlite3.connect(self.translate_db)
        try:
            if translated is None or title is None:
                row = connection.execute(
                    "SELECT title, translated_summary FROM translations WHERE paper_id = ?",
                    (paper_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"번역 결과를 찾을 수 없습니다: {paper_id}")
                title, translated = str(row[0]), str(row[1])
            path = self.markdown_dir / f"{self._safe_name(paper_id)}.md"
            path.write_text(f"# {title}\n\n{translated.rstrip()}\n", encoding="utf-8")
            return path
        finally:
            if close:
                connection.close()

    def export_all(self) -> list[Path]:
        if not self.translate_db.is_file():
            raise FileNotFoundError(f"번역 DB를 찾을 수 없습니다: {self.translate_db}")
        with sqlite3.connect(self.translate_db) as db:
            rows = db.execute("SELECT paper_id FROM translations ORDER BY rowid").fetchall()
        return [self.export_markdown(str(row[0])) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="summary.db 요약 번역 및 Markdown 내보내기")
    parser.add_argument("--paper-id", action="append", dest="paper_ids")
    parser.add_argument("--export-only", action="store_true", help="기존 translate.db를 Markdown으로만 내보냄")
    args = parser.parse_args()
    tool = TranslateTool()
    paths = tool.export_all() if args.export_only else tool.translate_database(args.paper_ids)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
