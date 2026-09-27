"""LangChain adapter for the shared web/graph academic keyword service."""
from __future__ import annotations

import time
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.services.search_intent import SearchIntentError as KeywordToolError
from src.services.search_intent import search_keywords


class KeywordInput(BaseModel):
    user_query: str = Field(..., description="사용자의 자연어 논문 검색 요청")


@tool("generate_arxiv_keywords", args_schema=KeywordInput)
def generate_arxiv_keywords(user_query: str) -> dict:
    """한국어·영문 논문 검색 요청을 핵심 영문 학술 용어로 변환합니다."""
    start = time.monotonic()
    keywords = search_keywords(user_query)
    return {"query": user_query, "keywords": keywords,
            "duration_sec": round(time.monotonic() - start, 2)}


__all__ = ["generate_arxiv_keywords", "KeywordToolError"]
