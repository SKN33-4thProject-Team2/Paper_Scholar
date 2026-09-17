from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("OPENAI_API_KEY", "test-key")

from tests import SRC_DIR  # noqa: F401 - src 경로를 등록합니다.
from feature import search_list


class LocalLibraryRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.json_file = root / "saved_papers.json"
        self.db_file = root / "saved_papers.db"
        self.pdf_dir = root / "paper_save"

        self.json_file.write_text(
            json.dumps(
                {
                    "local-1": {"title": "Local Attention Paper"},
                    "shared-1": {"title": "Shared Paper"},
                }
            ),
            encoding="utf-8",
        )
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                """
                CREATE TABLE papers (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    authors TEXT,
                    summary TEXT,
                    pdf_url TEXT
                )
                """
            )
            conn.executemany(
                "INSERT INTO papers VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        "local-1",
                        "Local Attention Paper",
                        "Local Author",
                        "Local abstract",
                        "https://example.com/local.pdf",
                    ),
                    (
                        "shared-1",
                        "Shared Paper",
                        "Legacy Author",
                        "Legacy abstract",
                        "https://example.com/shared.pdf",
                    ),
                ],
            )

        self.path_patches = (
            patch.object(search_list, "JSON_FILE", self.json_file),
            patch.object(search_list, "DB_FILE", self.db_file),
            patch.object(search_list, "PDF_SAVE_DIR", self.pdf_dir),
        )
        for path_patch in self.path_patches:
            path_patch.start()
            self.addCleanup(path_patch.stop)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def repository_module(**functions):
        module = types.ModuleType("services.django_paper_repository")
        for name, function in functions.items():
            setattr(module, name, function)
        return module

    def test_all_ids_merge_mysql_and_local_without_duplicates(self):
        repository = self.repository_module(
            list_paper_ids=lambda: ["mysql-1", "shared-1"]
        )
        with patch.dict(
            sys.modules,
            {"services.django_paper_repository": repository},
        ):
            result = search_list.LocalLibraryBot().get_all_json_ids()

        self.assertEqual(result, ["mysql-1", "shared-1", "local-1"])

    def test_search_ids_merge_mysql_and_matching_local_titles(self):
        repository = self.repository_module(
            search_paper_ids=lambda query: ["mysql-attention"]
        )
        with patch.dict(
            sys.modules,
            {"services.django_paper_repository": repository},
        ):
            result = search_list.LocalLibraryBot().search_json("attention")

        self.assertEqual(result, ["mysql-attention", "local-1"])

    def test_full_data_prefers_mysql_and_fills_missing_ids_from_sqlite(self):
        mysql_paper = {
            "id": "shared-1",
            "title": "Shared Paper",
            "authors": "MySQL Author",
            "summary": "MySQL abstract",
            "pdf_url": "https://example.com/mysql.pdf",
        }
        repository = self.repository_module(
            get_papers_by_ids=lambda paper_ids: [mysql_paper]
        )
        with patch.dict(
            sys.modules,
            {"services.django_paper_repository": repository},
        ):
            result = search_list.LocalLibraryBot().fetch_full_data_from_db(
                ["local-1", "shared-1"]
            )

        self.assertEqual([paper["id"] for paper in result], ["local-1", "shared-1"])
        self.assertEqual(result[1]["authors"], "MySQL Author")


if __name__ == "__main__":
    unittest.main()
