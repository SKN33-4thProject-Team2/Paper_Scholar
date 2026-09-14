"""번역 Markdown을 요약하고 결과 저장까지 확인하는 통합 테스트."""

from __future__ import annotations

import os
import unittest

from tests import PROJECT_ROOT, SRC_DIR  # noqa: F401 - src 경로를 sys.path에 등록한다.

from services.summary_markdown_store import MarkdownSummaryArtifactStore
from services.summary_vector_store import ChromaSummaryStore
from tools.summary_tool import SUMMARY_SECTIONS, SummaryTool


# 실제 요약 테스트에 사용할 번역 Markdown 파일입니다.
# 다른 논문을 테스트하려면 이 경로만 변경하세요.
TEST_MARKDOWN_PATH = (
    PROJECT_ROOT / "data" / "translations" / "2312.04649v1.md"
)

SUMMARY_OUTPUT_DIRECTORY = PROJECT_ROOT / "data" / "summaries"
VECTOR_DB_DIRECTORY = PROJECT_ROOT / "data" / "vector_db"


class SummaryToolTest(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("RUN_MODEL_INTEGRATION_TESTS") == "1",
        "RUN_MODEL_INTEGRATION_TESTS=1일 때만 실제 Ollama 통합 테스트를 실행합니다.",
    )
    def test_summarize_file_saves_markdown_and_vector_db(self) -> None:
        """실제 Ollama로 번역 Markdown을 요약하고 두 저장 결과를 확인한다."""
        self.assertTrue(
            TEST_MARKDOWN_PATH.is_file(),
            "테스트할 번역 Markdown 파일이 없습니다. "
            f"TEST_MARKDOWN_PATH를 실제 .md 파일로 변경하세요: {TEST_MARKDOWN_PATH}",
        )
        self.assertEqual(TEST_MARKDOWN_PATH.suffix.casefold(), ".md")

        paper_id = TEST_MARKDOWN_PATH.stem
        vector_store = ChromaSummaryStore(directory=VECTOR_DB_DIRECTORY)
        markdown_store = MarkdownSummaryArtifactStore(SUMMARY_OUTPUT_DIRECTORY)
        tool = SummaryTool(
            progress=print,
            summary_store=vector_store,
            artifact_store=markdown_store,
        )

        try:
            summary = tool.summarize_file(TEST_MARKDOWN_PATH)

            self.assertEqual(summary.id, paper_id)
            self.assertEqual(
                set(summary.sections),
                {section_name for section_name, _heading in SUMMARY_SECTIONS},
            )
            self.assertTrue(all(text.strip() for text in summary.sections.values()))

            expected_markdown_path = markdown_store.path_for(paper_id)
            self.assertEqual(summary.markdown_path, expected_markdown_path)
            self.assertTrue(expected_markdown_path.is_file())
            self.assertGreater(expected_markdown_path.stat().st_size, 0)

            stored = vector_store.search(
                "연구 목적 방법론 실험 결과 한계",
                limit=len(SUMMARY_SECTIONS),
                paper_id=paper_id,
            )
            self.assertEqual(len(stored), len(SUMMARY_SECTIONS))
            self.assertEqual(
                {result["metadata"]["section"] for result in stored},
                {section_name for section_name, _heading in SUMMARY_SECTIONS},
            )
            self.assertTrue(all(result["document"].strip() for result in stored))
        finally:
            vector_store.close()


if __name__ == "__main__":
    unittest.main()
