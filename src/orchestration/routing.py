"""Supervisor planning and routing for the paper workflow."""

from __future__ import annotations

import os
import re
from typing import Any, Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from orchestration.state import Route, WorkflowState


ExecutableRoute = Literal[
    "keyword",
    "search",
    "library",
    "download",
    "extract",
    "translate",
    "summarize",
    "deep_search",
    "deep_research",
    "human",
]


class SupervisorDecision(BaseModel):
    """A validated execution plan emitted by the supervisor."""

    steps: list[ExecutableRoute] = Field(min_length=1, max_length=8)
    reason: str
    await_selection: bool = False
    selected_paper_ids: list[str] = Field(default_factory=list)
    download_paper_ids: list[str] = Field(default_factory=list)
    deep_search_paper_id: str = ""
    human_question: str = ""


SUPERVISOR_PROMPT = """You plan work for an academic-paper assistant.
Return the shortest valid ordered list of node names.

Nodes:
- keyword: generate arXiv keywords from a research topic
- search: search arXiv; normally place keyword immediately before it
- library: list or search papers already saved locally
- download: download already selected/search-result papers
- extract: extract PDF text; required before translate
- translate: translate extracted Markdown; required before summarize
- summarize: summarize translated Markdown and store it in ChromaDB
- deep_search: retrieve relevant passages from exactly one paper saved by PaperExtractor
- deep_research: answer using only passages returned by deep_search
- human: ask the user a concise clarifying question; do not run a tool

Rules:
1. For a new external search use [keyword, search].
2. For translation use [extract, translate] unless extraction data exists.
3. For summary use [extract, translate, summarize] unless earlier artifacts exist.
4. Deep Search is retrieval only; Deep Research is answer generation only.
5. Do not invent a download step if no selected/search-result papers exist.
6. Prefer library for list/search requests about locally saved papers.
7. For any question or deep analysis about an extracted paper, use
   [deep_search]. The graph automatically passes successful evidence to
   deep_research. Never start deep_research without deep_search evidence.
8. A request that chains multiple stages (e.g. "find the latest 5 LLM papers,
   translate and summarize them, then explain them") is ONE plan, not
   separate requests — emit the full ordered chain in one call, for example
   [keyword, search, download, extract, translate, summarize, deep_search]. Only
   include the stages actually implied by the request and skip stages whose
   artifacts already exist per "Available state".
9. Treat conversational questions about which papers the assistant can explain
   as requests to list papers from data/paper_extract via deep_search. Never
   start external search or download for those local inventory questions.
10. If the request is ambiguous, lacks a needed research topic or paper target,
    or you cannot select a safe plan, use [human]. Put one concise Korean
    question in human_question. Never guess or run a tool in that case.
"""


_GENERIC_REQUESTS = {
    "이거",
    "그거",
    "해줘",
    "도와줘",
    "번역",
    "번역해줘",
    "논문 번역",
    "논문 번역해줘",
    "요약",
    "요약해줘",
    "논문 요약",
    "논문 요약해줘",
    "검색",
    "검색해줘",
    "논문 검색",
    "논문 검색해줘",
    "찾아줘",
    "다운로드",
    "다운로드해줘",
}


def _human_decision(reason: str, question: str) -> SupervisorDecision:
    return SupervisorDecision(
        steps=["human"],
        reason=reason,
        human_question=question,
    )


class SupervisorRouter:
    """Hybrid router: structured LLM planning with a safe rule fallback."""

    def __init__(self, llm: Any | None = None, *, use_llm: bool | None = None) -> None:
        self._llm = llm
        self._use_llm = (
            os.getenv("SUPERVISOR_USE_LLM", "true").casefold() == "true"
            if use_llm is None
            else use_llm
        )

    @property
    def llm(self):
        if self._llm is None:
            model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
            self._llm = ChatOpenAI(model=model, temperature=0)
        return self._llm

    @staticmethod
    def _rule_decision(state: WorkflowState) -> SupervisorDecision | None:
        query = state["query"].casefold()
        normalized_query = re.sub(r"\s+", " ", query).strip()
        has_extraction = bool(state.get("extracted_records"))
        has_translation = bool(state.get("translated_paths"))
        has_candidates = bool(
            state.get("selected_papers")
            or state.get("search_results")
            or state.get("library_results")
        )
        active_deep_research_paper_id = str(
            state.get("deep_research_paper_id") or ""
        ).strip()
        has_active_paper = bool(state.get("paper_ids") or active_deep_research_paper_id)

        # Tool name만 말하거나 대명사만 남긴 요청은 대상·주제를 추측하면
        # 안 된다. 기존 기능을 실행하지 않고 Human-in-the-Loop으로 보낸다.
        requires_topic = normalized_query in {
            "검색",
            "검색해줘",
            "논문 검색",
            "논문 검색해줘",
            "찾아줘",
        }
        lacks_action_or_target = normalized_query in {
            "이거",
            "그거",
            "해줘",
            "도와줘",
        } or (
            normalized_query in _GENERIC_REQUESTS
            and not has_active_paper
        )
        if requires_topic or lacks_action_or_target:
            return _human_decision(
                "요청에 필요한 주제 또는 대상 논문이 없음",
                "원하는 작업과 대상 논문 또는 주제를 문장으로 알려주세요. "
                "예: 'RAG 논문 5편 검색해줘', 'paper-1을 번역해줘'.",
            )

        unresolved_pronoun = any(
            phrase in normalized_query
            for phrase in ("이 논문", "그 논문", "해당 논문", "이거", "그거")
        )
        if unresolved_pronoun and not has_active_paper:
            return _human_decision(
                "지시 대상 논문이 선택되지 않음",
                "어떤 논문을 처리할지 제목, paper_id 또는 목록 번호로 알려주세요.",
            )

        # "설명 가능한 논문이 뭐가 있어?"는 새 논문 검색 요청이 아니라
        # PaperExtractor가 저장한 로컬 논문 목록 요청으로 처리한다.
        asks_explainable_inventory = (
            "논문" in query
            and any(
                phrase in query
                for phrase in ("설명 가능한", "설명할 수 있는", "설명해줄 수 있는")
            )
            and any(term in query for term in ("뭐가", "무엇", "어떤", "있어", "있나", "보여"))
        )
        if asks_explainable_inventory:
            return SupervisorDecision(
                steps=["deep_search"],
                reason="paper_extract DB의 분석 가능한 논문 확인",
                await_selection=True,
            )

        deep_research_terms = (
            "딥리서치",
            "심층",
            "비교",
            "분석",
            "deep research",
        )
        remembered_candidates = [
            dict(source)
            for source in state.get("selection_candidates", [])
            if isinstance(source, dict)
        ]
        deep_search_candidates = [
            source
            for source in state.get("deep_search_candidates", [])
            if isinstance(source, dict)
        ]
        selection_candidates = remembered_candidates or deep_search_candidates
        selection_source = str(state.get("selection_source") or "").strip()
        number_matches = list(re.finditer(r"(\d+)\s*번", query))
        selected_numbers = list(
            dict.fromkeys(int(match.group(1)) for match in number_matches)
        )
        selected_by_number = any(
            0 < number <= len(selection_candidates)
            for number in selected_numbers
        )
        selected_by_title = any(
            str(source.get("title") or "").strip().casefold() in query
            for source in selection_candidates
            if str(source.get("title") or "").strip()
        )
        has_candidate_selection = selected_by_number or selected_by_title
        has_direct_research_target = bool(
            state.get("paper_ids")
            or active_deep_research_paper_id
            or state.get("selected_papers")
            or has_candidate_selection
        )
        asks_direct_research = any(
            term in query
            for term in (*deep_research_terms, "설명", "알려줘")
        )
        download_terms = ("다운로드", "다운받", "download")
        wants_download = any(term in query for term in download_terms)
        wants_extract = any(term in query for term in ("추출", "extract"))
        wants_translate = any(term in query for term in ("번역", "translate"))
        wants_summarize = any(
            term in query for term in ("요약", "summar", "summary")
        )

        def candidate_id(number: int) -> str:
            if not 0 < number <= len(selection_candidates):
                return ""
            return str(
                selection_candidates[number - 1].get("paper_id")
                or selection_candidates[number - 1].get("id")
                or ""
            ).strip()

        selected_candidate_ids = list(
            dict.fromkeys(
                paper_id
                for number in selected_numbers
                if (paper_id := candidate_id(number))
            )
        )
        deep_target_number = selected_numbers[-1] if selected_numbers else 0
        deep_target_id = candidate_id(deep_target_number)

        # 직전 Deep Research에서 선택한 한 편을 기준으로 하는 짧은 후속
        # 요약은 새 번역·요약 산출물 파이프라인이 아니다. 같은 논문의 근거를
        # 다시 찾아 답변하게 하며, 대상이 없으면 추출을 추측 실행하지 않는다.
        if wants_summarize and active_deep_research_paper_id and not selected_candidate_ids:
            return SupervisorDecision(
                steps=["deep_search"],
                reason="선택 논문에 대한 후속 요약 질의",
                selected_paper_ids=[active_deep_research_paper_id],
                deep_search_paper_id=active_deep_research_paper_id,
            )
        if wants_summarize and not selected_candidate_ids and not state.get("paper_ids"):
            return _human_decision(
                "요약 대상 논문이 선택되지 않음",
                "어느 논문을 요약할까요? 논문 제목, paper_id 또는 목록 번호를 알려주세요.",
            )

        # 목록에서 번호로 고른 논문은 paper_ids로 확정한 뒤 전체 처리
        # 파이프라인에 전달한다. 요약은 번역 결과를 사용하므로 번역을 포함한다.
        if selected_candidate_ids and (wants_translate or wants_summarize):
            steps: list[ExecutableRoute] = []
            should_download = wants_download or selection_source == "search"
            if should_download:
                steps.append("download")
            steps.extend(["extract", "translate"])
            if wants_summarize:
                steps.append("summarize")
            if asks_direct_research:
                steps.append("deep_search")
            return SupervisorDecision(
                steps=steps,
                reason="선택한 논문의 추출·번역·요약 파이프라인",
                selected_paper_ids=selected_candidate_ids,
                download_paper_ids=(
                    selected_candidate_ids if should_download else []
                ),
                deep_search_paper_id=(
                    deep_target_id if asks_direct_research else ""
                ),
            )

        # "3번 5번 다운로드 후 5번 설명"처럼 한 요청 안에서 작업 대상이
        # 다른 경우, 다운로드용 복수 ID와 심층 질문용 단일 ID를 분리한다.
        if (
            selection_candidates
            and selected_candidate_ids
            and wants_download
            and asks_direct_research
        ):
            return SupervisorDecision(
                steps=["download", "deep_search"],
                reason="선택 논문들을 다운로드한 뒤 지정 논문을 심층 분석",
                selected_paper_ids=selected_candidate_ids,
                download_paper_ids=selected_candidate_ids,
                deep_search_paper_id=deep_target_id or selected_candidate_ids[-1],
            )

        if has_direct_research_target and asks_direct_research:
            return SupervisorDecision(
                steps=["deep_search"],
                reason="지정된 추출 논문에서 심층 질문 근거 검색",
                selected_paper_ids=([deep_target_id] if deep_target_id else []),
                deep_search_paper_id=deep_target_id,
            )

        # 추출 요청은 LLM에게 재판단시키지 않는다. 선택 논문이 이미
        # 다운로드된 경우에는 Extract만 실행하고, PDF가 없을 수 있는
        # 새 검색 결과라면 필요한 데이터 의존 단계만 먼저 실행한다.
        if wants_extract:
            if selected_candidate_ids:
                steps = ["extract"] if state.get("downloaded_paths") else ["download", "extract"]
                return SupervisorDecision(
                    steps=steps,
                    reason="선택 논문 PDF 본문 추출 요청",
                    selected_paper_ids=selected_candidate_ids,
                    download_paper_ids=(selected_candidate_ids if "download" in steps else []),
                )
            if state.get("paper_ids"):
                return SupervisorDecision(
                    steps=["extract"],
                    reason="지정 논문 PDF 본문 추출 요청",
                )
            return _human_decision(
                "추출 대상 논문이 선택되지 않음",
                "어느 논문을 추출할까요? 논문 제목, paper_id 또는 목록 번호를 알려주세요.",
            )

        # A request can chain multiple stages in one sentence (e.g. "찾아서
        # 번역 요약해주고 설명해줘" = search + translate + summarize + explain).
        # Detect that BEFORE the single-purpose keyword checks below, which
        # would otherwise stop at whichever keyword happens to match first
        # and silently drop the rest of the request.
        wants_new_papers = any(
            term in query
            for term in ("arxiv", "외부 검색", "논문 찾아", "찾아서", "찾아줘", "검색해", *download_terms)
        )
        wants_qa = any(term in query for term in ("근거", "출처", "질문", "설명해"))
        wants_deep = any(term in query for term in deep_research_terms)
        if wants_new_papers and (wants_translate or wants_summarize or wants_qa or wants_deep):
            steps: list[ExecutableRoute] = []
            if any(
                term in query
                for term in ("arxiv", "외부 검색", "논문 찾아", "찾아서", "찾아줘", "검색해")
            ):
                steps += ["keyword", "search"]
            if wants_translate or wants_summarize:
                if not has_extraction:
                    steps.append("download")
                    steps.append("extract")
                steps.append("translate")
                if wants_summarize:
                    steps.append("summarize")
            elif wants_download:
                steps.append("download")
            if wants_qa or wants_deep:
                steps.append("deep_search")
            ordered: list[ExecutableRoute] = []
            for step in steps:
                if step not in ordered:
                    ordered.append(step)
            return SupervisorDecision(steps=ordered[:8], reason="검색부터 설명까지 이어지는 복합 요청")

        explicit_qa_signals = ("근거", "출처", "질문", "설명해")
        stored_content_signals = ("저장", "요약", "서재")
        if any(term in query for term in explicit_qa_signals) or (
            "rag" in query and any(term in query for term in stored_content_signals)
        ):
            return SupervisorDecision(
                steps=["deep_search"],
                reason="선택한 추출 논문에서 근거 검색 후 심층 답변",
            )
        if any(term in query for term in ("번역", "translate")):
            steps = [] if has_extraction else ["extract"]
            steps.append("translate")
            return SupervisorDecision(steps=steps, reason="번역 요청")
        if any(term in query for term in ("요약", "summar", "summary")):
            steps = []
            if not has_translation:
                if not has_extraction:
                    steps.append("extract")
                steps.append("translate")
            steps.append("summarize")
            return SupervisorDecision(steps=steps, reason="요약 파이프라인 요청")
        if any(term in query for term in ("arxiv", "외부 검색", "논문 찾아", "찾아서", "찾아줘", "검색해")):
            return SupervisorDecision(steps=["keyword", "search"], reason="외부 논문 검색 요청")
        if wants_download:
            if selected_candidate_ids:
                return SupervisorDecision(
                    steps=["download"],
                    reason="선택한 추출 논문 다운로드",
                    selected_paper_ids=selected_candidate_ids,
                    download_paper_ids=selected_candidate_ids,
                )
            steps = ["download"] if has_candidates else ["library", "download"]
            return SupervisorDecision(steps=steps, reason="논문 다운로드 요청")
        if any(term in query for term in deep_research_terms):
            return SupervisorDecision(
                steps=["deep_search"], reason="추출 논문 검색 후 심층 분석"
            )
        if any(term in query for term in ("서재", "저장된", "목록", "리스트", "library")):
            return SupervisorDecision(steps=["library"], reason="로컬 서재 요청")
        if any(term in query for term in ("rag", "근거", "출처", "질문", "설명해")):
            return SupervisorDecision(
                steps=["deep_search"], reason="추출 논문 근거 기반 질의응답"
            )
        return None

    @classmethod
    def _fallback(cls, state: WorkflowState) -> SupervisorDecision:
        return cls._rule_decision(state) or SupervisorDecision(
            steps=["human"],
            reason="요청 의도 또는 대상 논문을 확정할 수 없음",
            human_question=(
                "요청을 정확히 처리하려면 원하는 작업과 대상 논문 또는 주제를 "
                "문장으로 알려주세요. 예: 'RAG 논문 5편 검색해줘', "
                "'paper-1을 번역해줘', '1번 논문을 설명해줘'."
            ),
        )

    def decide(self, state: WorkflowState) -> SupervisorDecision:
        rule_decision = self._rule_decision(state)
        if rule_decision is not None:
            return rule_decision
        if not self._use_llm:
            return self._fallback(state)
        inventory = {
            "paper_ids": state.get("paper_ids", []),
            "has_search_results": bool(state.get("search_results")),
            "has_selected_papers": bool(state.get("selected_papers")),
            "has_extracted_records": bool(state.get("extracted_records")),
            "has_translated_paths": bool(state.get("translated_paths")),
        }
        try:
            structured = self.llm.with_structured_output(SupervisorDecision)
            return structured.invoke(
                f"{SUPERVISOR_PROMPT}\n\nUser request: {state['query']}\nAvailable state: {inventory}"
            )
        except Exception:
            return self._fallback(state)


def next_route(state: WorkflowState) -> Route:
    return state.get("route", "finish")
