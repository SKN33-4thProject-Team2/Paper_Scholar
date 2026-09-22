from __future__ import annotations

import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


from tests import SRC_DIR  # noqa: F401 - src 경로를 등록합니다.
from tools import extractor_tool


class ExtractorMySQLSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.library_db = root / "saved_papers.db"
        self.extracted_db = root / "extracted_papers.db"

        with sqlite3.connect(self.library_db) as connection:
            connection.execute("CREATE TABLE papers (id TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO papers VALUES (?)", ("paper-1",))
            connection.execute("INSERT INTO papers VALUES (?)", ("paper-2v3",))

        self.sections = [
            (1, "Abstract", "Abstract text", "<p>Abstract text</p>"),
            (2, "Introduction", "Introduction text", "<p>Introduction text</p>"),
        ]

        self.path_patches = (
            patch.object(extractor_tool, "LIBRARY_DB", self.library_db),
            patch.object(extractor_tool, "EXTRACTED_DB", self.extracted_db),
            patch.object(
                extractor_tool.ArxivExtractor,
                "extract",
                return_value=self.sections,
            ),
        )
        for path_patch in self.path_patches:
            path_patch.start()
            self.addCleanup(path_patch.stop)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def vector_store_module():
        module = types.ModuleType("services.fulltext_vector_store")

        class ChromaFullTextStore:
            def ensure_index(self, paper_id=None):
                return 0

        module.ChromaFullTextStore = ChromaFullTextStore
        return module

    def test_extraction_synchronizes_sections_to_mysql_repository(self):
        calls = []
        repository = types.ModuleType("services.django_paper_repository")

        def replace_paper_sections(paper_id, sections):
            calls.append((paper_id, list(sections)))
            return len(calls[0][1])

        repository.replace_paper_sections = replace_paper_sections

        with patch.dict(
            sys.modules,
            {
                "services.django_paper_repository": repository,
                "services.fulltext_vector_store": self.vector_store_module(),
            },
        ):
            count = extractor_tool.extract_and_save("paper-1v2")

        self.assertEqual(count, 2)
        self.assertEqual(calls, [("paper-1", self.sections)])
        with sqlite3.connect(self.extracted_db) as connection:
            stored_count = connection.execute(
                "SELECT COUNT(*) FROM paper_sections"
            ).fetchone()[0]
        self.assertEqual(stored_count, 2)

    def test_mysql_failure_does_not_rollback_sqlite_extraction(self):
        repository = types.ModuleType("services.django_paper_repository")

        def replace_paper_sections(paper_id, sections):
            raise RuntimeError("MySQL unavailable")

        repository.replace_paper_sections = replace_paper_sections

        with patch.dict(
            sys.modules,
            {
                "services.django_paper_repository": repository,
                "services.fulltext_vector_store": self.vector_store_module(),
            },
        ):
            count = extractor_tool.extract_and_save("paper-1")

        self.assertEqual(count, 2)
        with sqlite3.connect(self.extracted_db) as connection:
            stored_count = connection.execute(
                "SELECT COUNT(*) FROM paper_sections"
            ).fetchone()[0]
        self.assertEqual(stored_count, 2)

    def test_required_django_sync_reports_mysql_failure(self):
        repository = types.ModuleType("services.django_paper_repository")

        def replace_paper_sections(paper_id, sections):
            raise RuntimeError("MySQL unavailable")

        repository.replace_paper_sections = replace_paper_sections

        with patch.dict(
            sys.modules,
            {
                "services.django_paper_repository": repository,
                "services.fulltext_vector_store": self.vector_store_module(),
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "MySQL unavailable"):
                extractor_tool.extract_and_save(
                    "paper-1",
                    require_django_sync=True,
                )

        with sqlite3.connect(self.extracted_db) as connection:
            stored_count = connection.execute(
                "SELECT COUNT(*) FROM paper_sections"
            ).fetchone()[0]
        self.assertEqual(stored_count, 2)

    def test_extraction_accepts_versioned_legacy_library_record(self):
        calls = []
        repository = types.ModuleType("services.django_paper_repository")

        def replace_paper_sections(paper_id, sections):
            calls.append((paper_id, list(sections)))
            return len(calls[0][1])

        repository.replace_paper_sections = replace_paper_sections

        with patch.dict(
            sys.modules,
            {
                "services.django_paper_repository": repository,
                "services.fulltext_vector_store": self.vector_store_module(),
            },
        ):
            count = extractor_tool.extract_and_save("paper-2")

        self.assertEqual(count, 2)
        self.assertEqual(calls, [("paper-2", self.sections)])


if __name__ == "__main__":
    unittest.main()
