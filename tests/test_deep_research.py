"""Deep Research 목록·선택·연속 질문 기능의 단위 테스트."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

from tests import SRC_DIR  # noqa: F401 - 테스트 공통 import 경로 설정

from feature.deep_research import (
    ChromaSummaryRetriever,
    DeepResearchBot,
    PaperArtifactRepository,
    SQLitePaperRepository,
)


class FakeAnswerer:
    """API 비용 없이 챗봇 흐름만 검사하기 위한 가짜 답변 생성기."""

    def answer(self, paper: dict, question: str) -> dict:
        return {
            "answer": f"{paper['title']}에 대한 답변: {question}",
            "sources": [paper["structured_summary"]],
        }


class FakeSummaryStore:
    """실제 ChromaDB 없이 검색 인자와 결과 연결을 검사하는 저장소."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.closed = False

    def search(self, query: str, *, limit: int, paper_id: str) -> list[dict]:
        self.calls.append(
            {"query": query, "limit": limit, "paper_id": paper_id}
        )
        return [
            {
                "id": f"{paper_id}:methodology",
                "document": "선택 논문의 방법론 근거",
                "metadata": {
                    "paper_id": paper_id,
                    "section": "methodology",
                },
                "distance": 0.1,
            }
        ]

    def close(self) -> None:
        self.closed = True


class FailingSummaryStore:
    """Chroma 검색 실패 시 대체 검색을 확인하기 위한 저장소."""

    def search(self, query: str, *, limit: int, paper_id: str) -> list[dict]:
        raise RuntimeError("테스트용 Chroma 오류")


class FakeSearchAgent:
    """외부 네트워크 없이 참조 논문 검색 연결을 검사하는 가짜 에이전트."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def search_papers(
        self, final_query: str, sort_by: str = "r", max_results: int = 10
    ) -> list[dict]:
        self.calls.append(
            {
                "query": final_query,
                "sort_by": sort_by,
                "max_results": max_results,
            }
        )
        return [
            {
                "id": "searched-paper",
                "title": "검색된 참조 논문",
                "summary": "검색 에이전트가 반환한 결과",
            }
        ]


class DeepResearchBotTest(unittest.TestCase):
    def setUp(self) -> None:
        # 각 테스트마다 운영 DB와 완전히 분리된 임시 폴더·DB를 만든다.
        # 따라서 테스트가 실제 saved_papers.db를 변경할 수 없다.
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "papers.db"
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE papers (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    translated_text TEXT,
                    structured_summary TEXT,
                    translation_status TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO papers
                    (id, title, translated_text, structured_summary, translation_status)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    # 완료 논문 두 개와 번역 중인 논문 한 개를 준비한다.
                    (
                        "1702.01806v2",
                        "첫 번째 번역 논문",
                        "이 논문은 새로운 학습 방법을 제안한다.",
                        "연구 목표와 실험 결과 요약",
                        "completed",
                    ),
                    (
                        "2401.00001v1",
                        "두 번째 번역 논문",
                        "이 논문은 검색 증강 생성을 분석한다.",
                        "RAG 분석 요약",
                        "번역완료",
                    ),
                    (
                        "2401.00002v1",
                        "번역 중인 논문",
                        "아직 번역 중인 내용",
                        "",
                        "processing",
                    ),
                ],
            )

        # 실제 저장소 클래스에는 임시 DB를, 챗봇에는 가짜 Answerer를 주입한다.
        repository = SQLitePaperRepository(self.db_path)
        self.bot = DeepResearchBot(repository, FakeAnswerer())

    def tearDown(self) -> None:
        # 테스트가 끝나면 임시 DB와 폴더를 자동 삭제한다.
        self.temp_dir.cleanup()

    def test_lists_only_completed_papers(self):
        """완료 논문만 화면 목록에 포함되는지 확인한다."""
        result = self.bot.list_papers()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["count"], 2)
        self.assertEqual([paper["number"] for paper in result["papers"]], [1, 2])
        self.assertNotIn("번역 중인 논문", [paper["title"] for paper in result["papers"]])

    def test_selects_paper_by_natural_number_expression(self):
        """'2번 논문'이라는 자연어 선택을 이해하는지 확인한다."""
        result = self.bot.handle_message("2번 논문으로 선택해줘")

        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["paper"]["id"], "2401.00001v1")

    def test_selects_paper_by_title(self):
        """번호뿐 아니라 정확한 제목으로도 선택되는지 확인한다."""
        result = self.bot.select_paper("첫 번째 번역 논문")

        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["paper"]["id"], "1702.01806v2")

    def test_keeps_selected_paper_for_follow_up_question(self):
        """후속 질문에서도 처음 선택한 논문을 기억하는지 확인한다."""
        self.bot.select_paper(1)

        first = self.bot.handle_message("이 논문의 연구 목표가 뭐야?")
        follow_up = self.bot.handle_message("그럼 실험 결과는 어때?")

        self.assertEqual(first["status"], "success")
        self.assertEqual(follow_up["status"], "success")
        self.assertEqual(first["paper"], follow_up["paper"])

    def test_number_in_follow_up_does_not_change_selected_paper(self):
        """'표 2번'을 두 번째 논문 선택으로 오해하지 않는지 확인한다."""
        self.bot.select_paper(1)

        result = self.bot.handle_message("표 2번의 결과를 설명해줘")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["paper"]["id"], "1702.01806v2")

    def test_returns_to_list_when_user_says_back(self):
        """다른 논문 요청 시 선택을 해제하고 목록으로 돌아가는지 확인한다."""
        self.bot.select_paper(1)

        result = self.bot.handle_message("다른 논문 볼래")

        self.assertEqual(result["status"], "reset")
        self.assertIsNone(self.bot.selected_paper)
        self.assertEqual(len(result["papers"]), 2)

    def test_requires_selection_before_question(self):
        """선택 전 질문에 논문 목록과 선택 안내를 주는지 확인한다."""
        result = self.bot.handle_message("이 논문의 한계가 뭐야?")

        self.assertEqual(result["status"], "selection_required")
        self.assertEqual(len(result["papers"]), 2)

    def test_direct_question_requires_selection(self):
        """ask()를 직접 호출해도 선택 여부를 검사하는지 확인한다."""
        result = self.bot.ask("연구 목표가 뭐야?")

        self.assertEqual(result["status"], "selection_required")
        self.assertEqual(result["count"], 2)

    def test_rejects_out_of_range_number(self):
        """목록 범위를 벗어난 번호를 안전하게 거부하는지 확인한다."""
        result = self.bot.select_paper("9번")

        self.assertEqual(result["status"], "invalid_selection")

    @unittest.skipUnless(find_spec("langchain_core"), "langchain-core가 설치된 환경에서 검사")
    def test_creates_importable_langchain_tools(self):
        """통합 Agent에 전달할 Tool 여섯 개가 생성되는지 확인한다."""
        tools = self.bot.as_tools()

        self.assertEqual(
            [tool.name for tool in tools],
            [
                "list_translated_papers",
                "select_research_paper",
                "ask_selected_paper",
                "list_reference_papers",
                "search_reference_papers",
                "reset_selected_paper",
            ],
        )

    @unittest.skipUnless(
        find_spec("langchain_openai") and find_spec("dotenv"),
        "OpenAI 연동 패키지가 설치된 환경에서 검사",
    )
    def test_creates_bot_with_gpt_5_6_luna_without_api_call(self):
        """기본 OpenAI 모델이 gpt-5.6-luna로 설정되는지 확인한다."""
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "test-key", "OPENAI_CHAT_MODEL": ""},
        ):
            bot = DeepResearchBot.with_openai(
                SQLitePaperRepository(self.db_path)
            )

        self.assertEqual(bot.answerer.model_name, "gpt-5.6-luna")


class PaperArtifactRepositoryTest(unittest.TestCase):
    """추출 DB와 번역·요약 Markdown 연결을 검사한다."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "paper_extract" / "extracted_papers.db"
        self.reference_db_path = root / "paper_extract" / "extracted_papers_ref.db"
        self.processed_output_dir = root / "paper_list" / "processed_outputs"
        self.translation_dir = root / "translations"
        self.summary_dir = root / "summaries"
        self.db_path.parent.mkdir(parents=True)
        self.processed_output_dir.mkdir(parents=True)
        self.translation_dir.mkdir()
        self.summary_dir.mkdir()

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE extracted (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_pdf TEXT,
                    abstract TEXT,
                    introduction TEXT,
                    related_work TEXT,
                    method TEXT,
                    experiment TEXT,
                    result TEXT,
                    conclusion TEXT,
                    others TEXT,
                    content TEXT,
                    n_pages INTEGER,
                    n_chars INTEGER,
                    extractor TEXT
                )
                """
            )
            connection.executemany(
                "INSERT INTO extracted (id, title, content) VALUES (?, ?, ?)",
                [
                    ("2312.04649v1", "번역과 요약 완료 논문", "영문 추출 전문"),
                    ("2401.00001v1", "번역만 완료된 논문", "영문 추출 전문"),
                    ("2401.00002v1", "추출만 완료된 논문", "영문 추출 전문"),
                ],
            )
        with sqlite3.connect(self.reference_db_path) as connection:
            connection.execute(
                """
                CREATE TABLE extracted_ref (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id TEXT,
                    ref_index INTEGER,
                    reference_text TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO extracted_ref (paper_id, ref_index, reference_text)
                VALUES (?, ?, ?)
                """,
                [
                    ("2312.04649v1", 1, "[1] Attention Is All You Need."),
                    ("2312.04649v1", 2, "[2] Retrieval-Augmented Generation."),
                ],
            )

        (self.translation_dir / "2312.04649v1.md").write_text(
            "# 번역과 요약 완료 논문\n\n한국어 전문 번역",
            encoding="utf-8",
        )
        (self.summary_dir / "2312.04649v1.md").write_text(
            "# 구조화 요약\n\n## 연구 목표\n연구 목표 내용",
            encoding="utf-8",
        )
        (self.translation_dir / "2401.00001v1.md").write_text(
            "# 번역만 완료된 논문\n\n한국어 전문 번역",
            encoding="utf-8",
        )

        self.repository = PaperArtifactRepository(
            self.db_path,
            reference_db_path=self.reference_db_path,
            processed_output_dir=self.processed_output_dir,
            translation_dir=self.translation_dir,
            summary_dir=self.summary_dir,
            allow_extracted_only=False,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_lists_only_papers_with_translation_and_summary(self):
        """번역과 요약이 모두 끝난 논문만 목록에 표시한다."""
        papers = self.repository.list_translated_papers()

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["id"], "2312.04649v1")
        self.assertTrue(papers[0]["has_translation"])
        self.assertTrue(papers[0]["has_summary"])

    def test_lists_from_extract_json_but_reads_selected_content_from_db(self):
        json_path = self.db_path.with_name("catalog.json")
        json_path.write_text(
            '{"2401.00002v1": {"id": "2401.00002v1", '
            '"title": "JSON 목록 논문"}}',
            encoding="utf-8",
        )
        repository = PaperArtifactRepository(
            self.db_path,
            extract_json_path=json_path,
            reference_db_path=self.reference_db_path,
            processed_output_dir=self.processed_output_dir,
            translation_dir=self.translation_dir,
            summary_dir=self.summary_dir,
            allow_extracted_only=True,
        )

        papers = repository.list_translated_papers()
        selected = repository.get_paper("2401.00002v1")

        self.assertEqual(papers, [{"id": "2401.00002v1", "title": "JSON 목록 논문"}])
        self.assertIsNotNone(selected)
        self.assertEqual(selected["translation_text"], "영문 추출 전문")

    def test_combines_database_and_markdown_artifacts(self):
        """DB 제목과 두 Markdown 본문을 공통 논문 dict로 합친다."""
        paper = self.repository.get_paper("2312.04649v1")

        self.assertIsNotNone(paper)
        self.assertEqual(paper["title"], "번역과 요약 완료 논문")
        self.assertIn("한국어 전문 번역", paper["translation_text"])
        self.assertIn("연구 목표 내용", paper["structured_summary"])
        self.assertTrue(paper["translation_completed"])
        self.assertEqual(paper["translation_source"], "legacy_artifact")
        self.assertEqual(paper["summary_source"], "legacy_artifact")

    def test_returns_none_until_summary_is_ready(self):
        """번역만 있고 요약이 없는 논문은 아직 선택하지 못하게 한다."""
        paper = self.repository.get_paper("2401.00001v1")

        self.assertIsNone(paper)

    def test_reads_extracted_database_without_translation_files(self):
        """번역 파일이 없어도 extracted DB 본문을 질문 근거로 제공한다."""
        repository = PaperArtifactRepository(
            self.db_path,
            reference_db_path=self.reference_db_path,
            processed_output_dir=self.processed_output_dir,
            translation_dir=self.translation_dir,
            summary_dir=self.summary_dir,
            allow_extracted_only=True,
        )

        paper = repository.get_paper("2401.00002v1")

        self.assertIsNotNone(paper)
        self.assertEqual(paper["translation_text"], "영문 추출 전문")
        self.assertEqual(paper["extracted_content"], "영문 추출 전문")
        self.assertFalse(paper["translation_completed"])
        self.assertEqual(paper["translation_source"], "extracted_database")

    def test_reads_processed_outputs_by_database_title(self):
        """제목 기반 팀원 번역·요약 파일을 논문 ID 데이터와 연결한다."""
        (self.processed_output_dir / "추출만_완료된_논문_full_translated.md").write_text(
            "# 원제: 추출만 완료된 논문\n\n팀원 한국어 전문 번역",
            encoding="utf-8",
        )
        (self.processed_output_dir / "추출만_완료된_논문_summary.md").write_text(
            "# 추출만 완료된 논문 요약본\n\n팀원 구조화 요약",
            encoding="utf-8",
        )

        paper = self.repository.get_paper("2401.00002v1")

        self.assertIsNotNone(paper)
        self.assertIn("팀원 한국어 전문 번역", paper["translation_text"])
        self.assertIn("팀원 구조화 요약", paper["structured_summary"])
        self.assertEqual(paper["translation_source"], "processed_outputs")
        self.assertEqual(paper["summary_source"], "processed_outputs")
        self.assertTrue(paper["translation_path"].endswith("_full_translated.md"))
        self.assertTrue(paper["summary_path"].endswith("_summary.md"))

    def test_reads_references_from_separate_database(self):
        """paper_id로 분리된 참고문헌 DB를 순서대로 조회한다."""
        references = self.repository.list_references("2312.04649v1")

        self.assertEqual([item["ref_index"] for item in references], [1, 2])
        self.assertIn("Attention Is All You Need", references[0]["reference_text"])

    def test_asks_before_search_and_reports_missing_agent(self):
        """관련 논문을 보여준 뒤 검색 동의를 받고 미연결 상태를 안내한다."""
        bot = DeepResearchBot(self.repository, FakeAnswerer())
        bot.select_paper(1)

        confirmation = bot.handle_message("이 논문과 관련된 다른 논문이 있어?")
        unavailable = bot.handle_message("응, 검색해줘")

        self.assertEqual(confirmation["status"], "search_confirmation")
        self.assertEqual(confirmation["count"], 2)
        self.assertIn("검색해드릴까요", confirmation["message"])
        self.assertEqual(unavailable["status"], "search_agent_unavailable")
        self.assertIn("검색 에이전트가 존재하지 않아", unavailable["message"])

    def test_searches_references_when_search_agent_is_connected(self):
        """검색 에이전트가 연결되면 사용자 동의 후 참조 논문을 검색한다."""
        search_agent = FakeSearchAgent()
        bot = DeepResearchBot(
            self.repository,
            FakeAnswerer(),
            search_agent=search_agent,
        )
        bot.select_paper(1)

        bot.handle_message("비슷한 논문도 있어?")
        result = bot.handle_message("네, 찾아줘")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["results"][0]["id"], "searched-paper")
        self.assertEqual(len(search_agent.calls), 2)
        self.assertNotIn("[1]", search_agent.calls[0]["query"])


class ChromaSummaryRetrieverTest(unittest.TestCase):
    """선택 논문 ID 제한과 키워드 대체 검색을 검사한다."""

    def setUp(self) -> None:
        self.paper = {
            "id": "2312.04649v1",
            "title": "테스트 논문",
            "structured_summary": "연구 방법은 신경망을 사용한다.",
            "translation_text": "논문의 전체 한국어 번역문이다.",
        }

    def test_searches_chroma_with_selected_paper_id(self):
        """다른 논문이 섞이지 않도록 선택 ID를 검색 조건으로 전달한다."""
        store = FakeSummaryStore()
        retriever = ChromaSummaryRetriever(store=store, top_k=3)

        evidence = retriever.retrieve(self.paper, "연구 방법이 뭐야?")

        self.assertEqual(evidence, ["선택 논문의 방법론 근거"])
        self.assertEqual(
            store.calls,
            [
                {
                    "query": "연구 방법이 뭐야?",
                    "limit": 3,
                    "paper_id": "2312.04649v1",
                }
            ],
        )
        retriever.close()
        self.assertTrue(store.closed)

    def test_falls_back_to_keyword_search_when_chroma_fails(self):
        """Chroma 오류가 나도 전문 번역문 검색으로 질문을 이어간다."""
        retriever = ChromaSummaryRetriever(store=FailingSummaryStore())

        evidence = retriever.retrieve(self.paper, "연구 방법이 뭐야?")

        self.assertTrue(evidence)
        self.assertTrue(any("연구 방법" in text for text in evidence))


if __name__ == "__main__":
    unittest.main()
