"""Natural-language planning for the web Supervisor.

The planner never performs paper work itself.  It only returns a validated
plan whose actions map to the existing search, save, extraction, summary and
translation APIs.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field


SupervisorAction = Literal["search", "save", "extract", "summarize", "translate"]


class SupervisorIntent(BaseModel):
    query: str | None = Field(
        default=None,
        description="논문 검색에 사용할 핵심 학술 주제. 동작 표현은 제외한다.",
    )
    result_count: int = Field(default=1, ge=1, le=15)
    related_count: int = Field(default=0, ge=0, le=14)
    save_to_library: bool = False
    summarize: bool = False
    translate: bool = False
    target_language: Literal["ko"] = "ko"


class SupervisorPlan(BaseModel):
    query: str = ""
    max_results: int = Field(default=1, ge=1, le=15)
    related_count: int = Field(default=0, ge=0, le=14)
    actions: list[SupervisorAction] = Field(default_factory=list)
    save_to_library: bool = False
    extract_content: bool = False
    summarize: bool = False
    translate: bool = False
    target_language: Literal["ko"] = "ko"
    needs_clarification: bool = False
    clarification_question: str = ""


_RELATED_PATTERN = re.compile(
    r"비슷한\s*(?:논문|것|걸)?\s*(\d+)\s*(?:개|편)?",
    re.IGNORECASE,
)
_COUNT_PATTERN = re.compile(r"(\d+)\s*(?:개|편|papers?)", re.IGNORECASE)
_ACTION_TEXT = re.compile(
    r"(?:비슷한\s*(?:논문|것|걸)?\s*\d+\s*(?:개|편)?(?:도)?(?:\s*같이)?|"
    r"논문|arxiv|검색|조회|찾아|찾기|해주고|해줘|해주세요|그리고|같이|"
    r"내\s*서재(?:에도)?|서재(?:에도)?|저장|본문|추출|요약|번역|한국어로|"
    r"시켜줘|돌려줘|까지|도)",
    re.IGNORECASE,
)
_AMBIGUOUS_TOPICS = {"", "무슨", "어떤", "이", "그", "해당", "관련", "비슷한"}


class SupervisorPlanner:
    """Create a safe plan that the frontend executes through existing APIs."""

    def __init__(self, *, llm=None) -> None:
        self._llm = llm

    @property
    def llm(self):
        if self._llm is None:
            from src.feature.search import OPENAI_CHAT_MODEL, create_safe_chat_model

            self._llm = create_safe_chat_model(OPENAI_CHAT_MODEL, temperature=0.0)
        return self._llm

    @staticmethod
    def _fallback_intent(message: str) -> SupervisorIntent:
        related_match = _RELATED_PATTERN.search(message)
        related_count = int(related_match.group(1)) if related_match else 0
        count_match = _COUNT_PATTERN.search(message)
        result_count = int(count_match.group(1)) if count_match else 1
        if related_count:
            result_count = related_count + 1

        topic_match = re.match(r"\s*(.+?)\s*논문(?:을|를|이|가|과|와|은|는|\s)", message)
        if topic_match:
            query = topic_match.group(1).strip()
        else:
            cleaned = _ACTION_TEXT.sub(" ", message)
            cleaned = re.sub(
                r"\d+\s*(?:개|편|papers?)?",
                " ",
                cleaned,
                flags=re.IGNORECASE,
            )
            query = re.sub(r"\s+", " ", cleaned).strip(" ,.!?를을은는이가")

        summarize = "요약" in message or "summar" in message.casefold()
        translate = "번역" in message or "translat" in message.casefold()
        save = "저장" in message or "서재" in message
        return SupervisorIntent(
            query=query or None,
            result_count=max(1, min(result_count, 15)),
            related_count=max(0, min(related_count, 14)),
            save_to_library=save,
            summarize=summarize,
            translate=translate,
        )

    def _parse_intent(self, message: str) -> SupervisorIntent:
        prompt = (
            "다음 요청을 기존 논문 기능 실행 계획으로 구조화해 주세요. "
            "query에는 검색할 학술 주제만 넣고 동작 표현은 제거하세요. "
            "'기준 논문 하나와 비슷한 논문 N개'는 result_count를 N+1로 설정하세요. "
            "요약이나 번역을 요청하면 save_to_library도 true로 설정하세요. "
            "지원 번역 언어는 한국어(ko)뿐입니다.\n\n"
            f"사용자 요청: {message}"
        )
        try:
            structured = self.llm.with_structured_output(SupervisorIntent)
            intent = structured.invoke(prompt)
        except Exception:
            intent = self._fallback_intent(message)

        related_match = _RELATED_PATTERN.search(message)
        if related_match:
            related_count = min(int(related_match.group(1)), 14)
            intent.related_count = related_count
            intent.result_count = min(related_count + 1, 15)
        return intent

    def plan(self, message: str) -> SupervisorPlan:
        clean_message = message.strip()
        if not clean_message:
            raise ValueError("요청을 입력해 주세요.")

        intent = self._parse_intent(clean_message)
        query = re.sub(r"\s+", " ", str(intent.query or "")).strip()
        ambiguity_key = re.sub(
            r"\b(?:논문|paper|papers)\b",
            "",
            query.casefold(),
            flags=re.IGNORECASE,
        ).strip()
        if ambiguity_key in _AMBIGUOUS_TOPICS:
            return SupervisorPlan(
                needs_clarification=True,
                clarification_question=(
                    "어떤 주제의 논문을 찾을까요? 예: "
                    "'RAG 논문 하나와 비슷한 논문 3편을 요약·번역해서 저장해줘'."
                ),
            )

        summarize = bool(intent.summarize)
        translate = bool(intent.translate)
        save = bool(intent.save_to_library or summarize or translate)
        extract = bool(summarize or translate)
        actions: list[SupervisorAction] = ["search"]
        if save:
            actions.append("save")
        if extract:
            actions.append("extract")
        if summarize or translate:
            actions.append("summarize")
        if translate:
            actions.append("translate")

        return SupervisorPlan(
            query=query,
            max_results=max(1, min(int(intent.result_count), 15)),
            related_count=max(0, min(int(intent.related_count), 14)),
            actions=actions,
            save_to_library=save,
            extract_content=extract,
            summarize=summarize or translate,
            translate=translate,
            target_language=intent.target_language,
        )


__all__ = ["SupervisorPlan", "SupervisorPlanner"]
