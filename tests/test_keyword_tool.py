"""Ollama 키워드 생성 Tool의 단위 테스트."""

from __future__ import annotations

import os
import sys
import unittest

from tests import PROJECT_ROOT, SRC_DIR

from tools.keyword_tool import generate_arxiv_keywords


# 실제 Ollama 키워드 생성을 확인할 사용자 입력. 원하는 주제로 이 값만 바꾼다.
USER_PROMPT = "LLM을 활용한 논문들이 뭐가 있는지 찾아줘"


class KeywordToolTest(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("RUN_MODEL_INTEGRATION_TESTS") == "1",
        "RUN_MODEL_INTEGRATION_TESTS=1일 때만 실제 Ollama 통합 테스트를 실행합니다.",
    )
    def test_generates_keywords_with_user_prompt(self):
        """테스트 파일 상단의 사용자 입력으로 실제 Ollama 키워드를 생성한다."""
        result = generate_arxiv_keywords.invoke({"user_query": USER_PROMPT})

        self.assertEqual(len(result["keywords"]), 6)
        self.assertTrue(all(isinstance(keyword, str) and keyword for keyword in result["keywords"]))
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print("\nGenerated keywords:")
        for index, keyword in enumerate(result["keywords"], start=1):
            print(f"{index}. {keyword}")


if __name__ == "__main__":
    unittest.main()
