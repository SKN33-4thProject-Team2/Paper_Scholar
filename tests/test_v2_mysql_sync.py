from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from tests import SRC_DIR  # noqa: F401 - src 경로를 sys.path에 등록한다.

from tools.summary_tool_v2 import SummaryTool
from tools.translate_tool_v2 import TranslateTool


class RecordingTranslator:
    model = "translation-test-model"

    def translate(self, content: str) -> tuple[str, int]:
        return f"번역: {content}", 2


class V2MySQLSyncTest(unittest.TestCase):
    def test_summary_single_call_syncs_final_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_db = root / "extracted.db"
            summary_db = root / "summary.db"
            with sqlite3.connect(source_db) as db:
                db.execute("CREATE TABLE extracted (id TEXT PRIMARY KEY, title TEXT, content TEXT)")
                db.execute(
                    "INSERT INTO extracted VALUES (?, ?, ?)",
                    ("2401.00001v2", "테스트 논문", "테스트 본문"),
                )
                db.execute(
                    """CREATE TABLE paper_sections (
                    id INTEGER PRIMARY KEY, paper_id TEXT, section_order INTEGER,
                    section_title TEXT, section_text TEXT
                    )"""
                )
                db.execute(
                    "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?)",
                    (1, "2401.00001v2", 1, "Introduction", "테스트 본문"),
                )

            tool = SummaryTool(
                source_db=source_db,
                summary_db=summary_db,
                generator=lambda _prompt, **_kwargs: "최종 요약",
                model="summary-test-model",
                single_call=True,
            )
            tool._read_mysql_sections = Mock(return_value=("", []))
            tool._sync_summary_to_mysql = Mock()

            result = tool.summarize("2401.00001v2")

            self.assertEqual(result.summary_markdown, "# 테스트 논문\n\n최종 요약\n")
            tool._sync_summary_to_mysql.assert_called_once_with(
                "2401.00001v2",
                "최종 요약",
                section_count=1,
                chunk_count=1,
            )

    def test_summary_translation_syncs_as_summary_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary_db = root / "summary.db"
            translate_db = root / "translate.db"
            markdown_dir = root / "markdown"
            with sqlite3.connect(summary_db) as db:
                db.execute(
                    """CREATE TABLE paper_summaries (
                    paper_id TEXT PRIMARY KEY, title TEXT, summary_text TEXT
                    )"""
                )
                db.execute(
                    "INSERT INTO paper_summaries VALUES (?, ?, ?)",
                    ("2401.00001v2", "테스트 논문", "English summary"),
                )
                db.execute(
                    """CREATE TABLE paper_summary_chunks (
                    paper_id TEXT, section_order INTEGER, chunk_index INTEGER,
                    summary_text TEXT
                    )"""
                )

            tool = TranslateTool(
                summary_db=summary_db,
                translate_db=translate_db,
                markdown_dir=markdown_dir,
                translator=RecordingTranslator(),
            )
            tool._read_mysql_summaries = Mock(return_value=[])
            tool._sync_translation_to_mysql = Mock()

            outputs = tool.translate_database()

            self.assertEqual(outputs, [markdown_dir / "2401.00001v2.md"])
            tool._sync_translation_to_mysql.assert_called_once_with(
                "2401.00001v2",
                "English summary",
                "번역: English summary",
                2,
            )

    def test_summary_reads_mysql_sections_without_local_db(self) -> None:
        tool = SummaryTool(
            source_db="missing.db",
            summary_db="unused.db",
            generator=lambda _prompt, **_kwargs: "unused",
        )
        tool._read_mysql_sections = Mock(
            return_value=(
                "MySQL 논문",
                [(1, "Introduction", "본문"), (2, "References", "제외")],
            )
        )

        title, sections = tool._read_sections("2401.00001v2")

        self.assertEqual(title, "MySQL 논문")
        self.assertEqual(sections, [(1, "Introduction", "본문")])

    def test_translation_reads_mysql_summary_without_local_db(self) -> None:
        tool = TranslateTool(
            summary_db="missing.db",
            translate_db="unused.db",
            markdown_dir="unused",
            translator=RecordingTranslator(),
        )
        mysql_rows = [
            {
                "paper_id": "2401.00001",
                "title": "MySQL 논문",
                "summary_text": "MySQL summary",
            }
        ]
        tool._read_mysql_summaries = Mock(return_value=mysql_rows)

        rows = tool._read_summaries(["2401.00001v2"])

        self.assertEqual(rows, mysql_rows)


if __name__ == "__main__":
    unittest.main()
