"""Deep Search가 paper_sections 표준으로 목록·상세·근거를 읽는지 검사한다."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from tests import SRC_DIR  # noqa: F401 - 테스트 공통 import 경로 설정

from services.fulltext_vector_store import ChromaFullTextStore
from tools.deep_search_tool import DeepSearch, DeepSearchError


# feature/paper_extractor.py 의 extracted 테이블과 같은 모양이다.
EXTRACTED_SCHEMA = """
CREATE TABLE extracted (
    id TEXT PRIMARY KEY, title TEXT, source_pdf TEXT, abstract TEXT,
    introduction TEXT, related_work TEXT, method TEXT, experiment TEXT,
    result TEXT, conclusion TEXT, others TEXT, content TEXT,
    n_pages INTEGER, n_chars INTEGER, extractor TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""
# tools/extractor_tool.py 와 같은 모양이다. 추출기는 이 스키마로 저장한다는 계약이다.
PAPER_SECTIONS_SCHEMA = """
CREATE TABLE paper_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL, section_order INTEGER NOT NULL,
    section_title TEXT, section_text TEXT, section_html TEXT,
    extracted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (paper_id, section_order)
)
"""

SECTION_PAPER = "2401.00001v1"
IMRAD_ONLY_PAPER = "2401.00002v1"
SECTIONS_ONLY_PAPER = "2402.00003v1"


class FakeFullTextStore:
    """임베딩 없이 검색 결과와 본문 섹션 유무만 흉내 내는 저장소."""

    def __init__(self, results: list[dict] | None = None, known_papers: set[str] | None = None) -> None:
        self.results = list(results or [])
        self.known_papers = set(known_papers or ())

    def search(self, query: str, *, limit: int, paper_id: str) -> list[dict]:
        return [item for item in self.results if item["metadata"]["paper_id"] == paper_id][:limit]

    def has_paper(self, paper_id: str) -> bool:
        return paper_id in self.known_papers


class StoreWithoutHasPaper:
    """평가용 LexicalFullTextStore 처럼 has_paper 가 없는 저장소."""

    def search(self, query: str, *, limit: int, paper_id: str) -> list[dict]:
        return []


class DeepSearchPaperSectionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._temp.name)
        self.db_path = root / "extracted_papers.db"
        self.library_path = root / "saved_papers.db"
        self.reference_path = root / "extracted_papers_ref.db"

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(EXTRACTED_SCHEMA)
            conn.execute(PAPER_SECTIONS_SCHEMA)
            conn.executemany(
                "INSERT INTO extracted (id, title, abstract, content, created_at) VALUES (?, ?, ?, ?, ?)",
                [
                    (SECTION_PAPER, "Section Paper", "old abstract", "old content", "2026-09-10 10:00:00"),
                    (IMRAD_ONLY_PAPER, "Imrad Only Paper", "imrad abstract", "IMRaD body", "2026-09-12 10:00:00"),
                ],
            )
            conn.executemany(
                "INSERT INTO paper_sections (paper_id, section_order, section_title, section_text, section_html) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (SECTION_PAPER, 1, "Abstract", "New abstract", None),
                    (SECTION_PAPER, 2, "1 Introduction", "Intro text", None),
                    (SECTION_PAPER, 3, "References", "[1] A reference", None),
                    (SECTION_PAPER, 4, "2 Empty", "   ", None),
                    (SECTIONS_ONLY_PAPER, 1, "1 Method", "Method text", None),
                ],
            )
        with closing(sqlite3.connect(self.library_path)) as conn, conn:
            conn.execute("CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT)")
            conn.execute("INSERT INTO papers VALUES (?, ?)", (SECTIONS_ONLY_PAPER, "Library Title"))

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _search(self, **kwargs) -> DeepSearch:
        kwargs.setdefault("fulltext_store_factory", FakeFullTextStore)
        return DeepSearch(
            db_path=self.db_path,
            library_db_path=self.library_path,
            reference_db_path=self.reference_path,
            **kwargs,
        )

    def test_catalog_reads_db_without_json(self):
        result = self._search().search_papers("")

        self.assertEqual(
            [paper["id"] for paper in result["results"]],
            [IMRAD_ONLY_PAPER, SECTION_PAPER, SECTIONS_ONLY_PAPER],
        )
        self.assertEqual(result["results"][2]["title"], "Library Title")

    def test_catalog_counts_only_body_sections(self):
        catalog = self._search()._load_paper_catalog()

        self.assertEqual(catalog[SECTION_PAPER]["section_count"], 2)
        self.assertEqual(catalog[IMRAD_ONLY_PAPER]["section_count"], 0)
        self.assertEqual(catalog[SECTIONS_ONLY_PAPER]["section_count"], 1)

    def test_details_are_built_from_sections(self):
        details = self._search().get_paper_details(SECTION_PAPER)

        self.assertEqual(details["title"], "Section Paper")
        self.assertEqual(details["abstract"], "New abstract")
        self.assertIn("## 1 Introduction\n\nIntro text", details["content"])
        self.assertNotIn("A reference", details["content"])
        self.assertNotIn("old content", details["content"])
        self.assertEqual(details["section_count"], 2)

    def test_details_fall_back_to_extracted_without_sections(self):
        details = self._search().get_paper_details(IMRAD_ONLY_PAPER)

        self.assertEqual(details["content"], "IMRaD body")
        self.assertEqual(details["abstract"], "imrad abstract")
        self.assertEqual(details["section_count"], 0)

    def test_details_use_library_title_for_sections_only_paper(self):
        details = self._search().get_paper_details(SECTIONS_ONLY_PAPER)

        self.assertEqual(details["title"], "Library Title")
        self.assertEqual(details["references"], ["레퍼런스 DB 누락됨"])

    def test_unknown_paper_raises(self):
        with self.assertRaises(DeepSearchError):
            self._search().get_paper_details("9999.99999v1")

    def test_search_passages_reports_missing_sections(self):
        store = FakeFullTextStore(known_papers={SECTION_PAPER})
        searcher = self._search(fulltext_store_factory=lambda: store)

        with self.assertRaisesRegex(DeepSearchError, "paper_sections"):
            searcher.search_passages("what is it?", paper_id=IMRAD_ONLY_PAPER)

    def test_search_passages_returns_results_for_section_paper(self):
        hit = {"id": "c1", "document": "Intro text", "metadata": {"paper_id": SECTION_PAPER}, "distance": 0.1}
        store = FakeFullTextStore(results=[hit], known_papers={SECTION_PAPER})
        searcher = self._search(fulltext_store_factory=lambda: store)

        payload = searcher.search_passages("intro?", paper_id=SECTION_PAPER)

        self.assertEqual(payload["results"], [hit])

    def test_empty_results_are_allowed_when_store_cannot_check(self):
        searcher = self._search(fulltext_store_factory=StoreWithoutHasPaper)

        payload = searcher.search_passages("anything?", paper_id=IMRAD_ONLY_PAPER)

        self.assertEqual(payload["results"], [])

    def test_explicit_json_catalog_keeps_old_behavior(self):
        json_path = Path(self._temp.name) / "extracted_papers.json"
        json_path.write_text(json.dumps({"x1": {"id": "x1", "title": "Json Title"}}), encoding="utf-8")

        result = self._search(json_list_path=json_path).search_papers("")

        self.assertEqual(result["results"], [{"id": "x1", "title": "Json Title"}])

    def test_db_without_paper_sections_table_still_lists_extracted(self):
        legacy_path = Path(self._temp.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_path)) as conn, conn:
            conn.execute(EXTRACTED_SCHEMA)
            conn.execute("INSERT INTO extracted (id, title, content) VALUES (?, ?, ?)", ("old1", "Old", "body"))
        searcher = DeepSearch(db_path=legacy_path, library_db_path=self.library_path,
                              reference_db_path=self.reference_path)

        self.assertEqual([paper["id"] for paper in searcher.search_papers("")["results"]], ["old1"])
        self.assertEqual(searcher.get_paper_details("old1")["content"], "body")


class ChromaFullTextStoreHasPaperTest(unittest.TestCase):
    """임베딩·Chroma 없이 SQLite 만으로 동작하는 has_paper 를 검사한다."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self._temp.name) / "extracted_papers.db"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(PAPER_SECTIONS_SCHEMA)
            conn.executemany(
                "INSERT INTO paper_sections (paper_id, section_order, section_title, section_text, section_html) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    ("body", 1, "1 Introduction", "text", None),
                    ("html_only", 1, "1 Method", "", "<p>html</p>"),
                    ("refs_only", 1, "References", "[1] ref", None),
                    ("blank_only", 1, "1 Empty", "  ", None),
                ],
            )

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_has_paper(self):
        store = ChromaFullTextStore(db_path=self.db_path, directory=Path(self._temp.name) / "chroma")

        self.assertTrue(store.has_paper("body"))
        self.assertTrue(store.has_paper("html_only"))
        self.assertFalse(store.has_paper("refs_only"))
        self.assertFalse(store.has_paper("blank_only"))
        self.assertFalse(store.has_paper("missing"))

    def test_has_paper_without_table_or_db(self):
        empty_db = Path(self._temp.name) / "empty.db"
        with closing(sqlite3.connect(empty_db)):
            pass

        self.assertFalse(ChromaFullTextStore(db_path=empty_db).has_paper("body"))
        self.assertFalse(ChromaFullTextStore(db_path=Path(self._temp.name) / "nope.db").has_paper("body"))


if __name__ == "__main__":
    unittest.main()
