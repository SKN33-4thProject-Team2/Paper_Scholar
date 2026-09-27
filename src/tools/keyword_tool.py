"""Academic keyword generation tool for ArXiv search.

Generates concise, English academic domain keywords using a lightweight,
ultra-fast language model (gpt-4o-mini) to minimize latency (< 1 sec).
"""

from __future__ import annotations

import os
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool

# ---------------------------------------------------------------------
# [모듈 임포트 경로 설정: src 및 프로젝트 루트 추가]
# ---------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent          # src/tools
SRC_DIR = CURRENT_DIR.parent                          # src
PROJECT_ROOT = SRC_DIR.parent                         # Paper_Scholar

if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

load_dotenv()

# 로거 모듈 임포트
try:
    from log.app_logger import AppLogger
    from log.log_codes import LogCode
except ImportError:
    class LogCode:
        KEYWORD_GENERATION_STARTED = "KEYWORD_GENERATION_STARTED"
        KEYWORD_GENERATION_SUCCEEDED = "KEYWORD_GENERATION_SUCCEEDED"
        KEYWORD_GENERATION_FAILED = "KEYWORD_GENERATION_FAILED"

    class AppLogger:
        def __init__(self, name: str):
            self.name = name
        def log(self, code: str, **kwargs):
            pass

logger = AppLogger(__name__)


class KeywordToolError(Exception):
    """키워드 생성 중 발생하는 기본 예외 클래스"""
    pass


class ArxivKeywords(BaseModel):
    keywords: List[str] = Field(
        ...,
        description="arXiv 학술 논문 검색에 사용할 3~5개의 핵심 영문 학술 명사구 리스트",
        min_items=1,
        max_items=5
    )


class KeywordInput(BaseModel):
    user_query: str = Field(..., description="사용자가 입력한 자연어 질문 또는 검색 주제")


# ---------------------------------------------------------------------
# [초경량 고속 LLM 초기화: gpt-4o-mini 적용]
# ---------------------------------------------------------------------
# 지연 시간 0.5초대, 추론 VRAM 로딩이 없어 즉시 실행됨
FAST_KEYWORD_MODEL = os.getenv("FAST_KEYWORD_MODEL", "gpt-4o-mini")


@lru_cache(maxsize=1)
def _get_keyword_llm():
    """Create the keyword model only when keyword generation is requested.

    Importing this module is part of the paper save path, which does not need an
    OpenAI client. Delaying construction keeps Django startup and non-LLM tasks
    usable when credentials are intentionally unavailable.
    """
    return ChatOpenAI(
        model=FAST_KEYWORD_MODEL,
        temperature=0.1,
        timeout=10.0
    ).with_structured_output(ArxivKeywords)


@tool("generate_arxiv_keywords", args_schema=KeywordInput)
def generate_arxiv_keywords(user_query: str) -> dict:
    """사용자의 질의를 기반으로 arXiv 논문 탐색에 가장 적합한 핵심 학술 영문 키워드 3~5개를 초고속으로 생성합니다."""
    from src.services.search_intent import search_keywords

    start = time.monotonic()
    keywords = search_keywords(user_query)
    return {"query": user_query, "keywords": keywords,
            "duration_sec": round(time.monotonic() - start, 2)}


# ---------------------------------------------------------------------
# [단독 실행 테스트]
# ---------------------------------------------------------------------
if __name__ == "__main__":
    test_topic = "대규모 언어 모델 경량화 및 추론 최적화"
    print(f"테스트 질의: {test_topic}")
    t0 = time.time()
    res = generate_arxiv_keywords.invoke({"user_query": test_topic})
    print(f"생성 결과: {res['keywords']}")
    print(f"총 소요 시간: {time.time() - t0:.2f}초")
