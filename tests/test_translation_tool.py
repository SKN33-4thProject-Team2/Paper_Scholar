"""TranslateTool의 Markdown 파일 입력 테스트."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from tests import SRC_DIR  # noqa: F401 - src 경로를 sys.path에 등록한다.

from services import PROJECT_ROOT
from tools.translation_tool import TranslateTool


TEST_MARKDOWN_PATH = PROJECT_ROOT / "data" / "paper_extract" / "2312.04649v1.md"
TRANSLATION_OUTPUT_DIRECTORY = PROJECT_ROOT / "data" / "translations"


class RecordingTranslateService:
    """모델 호출 없이 번역 도구에 전달된 청크를 기록한다."""

    model = "test-model"
    temperature = 0.0
    max_tokens = 1024
    chunk_chars = 12
    max_retries = 0
    retry_backoff_seconds = 0.0

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def translate(self, prompt: str) -> str:
        chunk = prompt.rsplit("\n\n", 1)[-1]
        self.chunks.append(chunk)
        return chunk


class TranslationToolTest(unittest.TestCase):
    def test_translation_moves_formula_whole_to_next_chunk(self) -> None:
        """번역 모델에는 경계에 걸린 수식이 다음 청크에서 온전히 전달된다."""
        service = RecordingTranslateService()
        tool = TranslateTool(progress=lambda _message: None, translate_service=service)

        translated, chunk_count = tool.translate_markdown("abcdefgh$E=mc^2$tail")

        self.assertEqual(chunk_count, 2)
        self.assertEqual(service.chunks[0], "abcdefgh")
        self.assertNotIn("$E=mc^2$", service.chunks[0])
        self.assertIn("__APRAG_PROTECTED_000001__", service.chunks[1])
        self.assertEqual(translated, "abcdefgh\n\n$E=mc^2$tail")

    @unittest.skipUnless(
        os.getenv("RUN_MODEL_INTEGRATION_TESTS") == "1",
        "RUN_MODEL_INTEGRATION_TESTS=1일 때만 실제 Ollama 통합 테스트를 실행합니다.",
    )
    def test_translate_file_chunks_translates_and_saves_markdown(self) -> None:
        """실제 Ollama로 Markdown을 청킹 번역하고 결과 파일을 저장한다."""
        tool = TranslateTool(
            progress=print,
            output_directory=TRANSLATION_OUTPUT_DIRECTORY,
        )

        output_path = tool.translate_file(TEST_MARKDOWN_PATH)

        self.assertTrue(output_path.is_file())
        self.assertEqual(output_path.parent, TRANSLATION_OUTPUT_DIRECTORY)
        self.assertGreater(output_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
