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
    search_result_limit: int = Field(default=0, ge=0, le=15)
    save_paper_count: int = Field(default=0, ge=0, le=15)
    explain_paper_rank: int = Field(default=0, ge=0, le=15)
    prioritize_primary_keyword: bool = False
    research_question: str = ""
    related_paper_title: str = ""
    pending_intent: str = ""
    pending_save_count: int = Field(default=0, ge=0, le=15)
    human_question: str = ""


SUPERVISOR_PROMPT = """You plan work for an academic-paper assistant.
Return the shortest valid ordered list of node names.

Nodes:
- keyword: generate arXiv keywords from a research topic
- search: search arXiv; normally place keyword immediately before it
- library: list or search papers already saved locally
- download: download already selected/search-result papers
- extract: extract PDF text into the shared paper store
- summarize: create a structured summary from extracted sections
- translate: translate an existing structured summary
- deep_search: retrieve relevant passages from exactly one paper saved by PaperExtractor
- deep_research: answer using only passages returned by deep_search
- human: ask the user a concise clarifying question; do not run a tool

Rules:
1. For a new external search use [keyword, search].
2. For translation use [translate]. The graph injects only missing extract and
   summary artifacts when they are actually absent.
3. For summary use [summarize]. The graph injects extraction only when it is
   actually absent.
4. Deep Search is retrieval only; Deep Research is answer generation only.
5. Do not invent a download step if no selected/search-result papers exist.
6. Prefer library for list/search requests about locally saved papers.
7. For any question or deep analysis about an extracted paper, use
   [deep_search]. The graph automatically passes successful evidence to
   deep_research. Never start deep_research without deep_search evidence.
8. A request that chains multiple stages (e.g. "find the latest 5 LLM papers,
   translate and summarize them, then explain them") is ONE plan, not
   separate requests — emit the full ordered chain in one call, for example
   [keyword, search, download, summarize, translate, deep_search]. Only
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


def _human_decision(
    reason: str,
    question: str,
    *,
    pending_intent: str = "",
    pending_save_count: int = 0,
) -> SupervisorDecision:
    return SupervisorDecision(
        steps=["human"],
        reason=reason,
        human_question=question,
        pending_intent=pending_intent,
        pending_save_count=pending_save_count,
    )


def _normalize_selected_research_question(query: str) -> str:
    """Remove a list-number target before sending the question to the LLM."""

    normalized = re.sub(
        r"^\s*\d+\s*번\s*(?:논문\s*(?:을|의)?\s*)?",
        "선택한 논문 ",
        query.strip(),
        count=1,
    )
    return re.sub(r"\s+", " ", normalized).strip()


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
        has_candidates = bool(
            state.get("selected_papers")
            or state.get("search_results")
            or state.get("library_results")
        )
        active_deep_research_paper_id = str(
            state.get("deep_research_paper_id") or ""
        ).strip()
        has_active_paper = bool(state.get("paper_ids") or active_deep_research_paper_id)

        # 짧은 인사는 도구를 호출하지 않고 챗봇 소개로 응답한다.
        greeting_only = normalized_query in {
            "안녕",
            "안녕하세요",
            "하이",
            "hello",
            "hi",
            "반가워",
            "반갑습니다",
        }
        if greeting_only:
            return _human_decision(
                "논문 챗봇 인사 응답",
                "안녕하세요! 저는 학술 논문 검색·추출·번역·요약을 도와드리는 논문 챗봇입니다.",
            )

        # 논문 작업과 무관한 일상 질문은 외부 검색이나 Agent 실행으로
        # 넘기지 않고, 지원 범위를 짧게 안내한다.
        out_of_scope_terms = (
            "날씨",
            "뭐 먹",
            "뭘 먹",
            "먹었어",
            "맛집",
            "주가",
            "주식",
        )
        paper_context_terms = (
            "논문",
            "arxiv",
            "학술",
            "검색",
            "번역",
            "요약",
            "추출",
            "저장",
            "설명",
        )
        if any(term in normalized_query for term in out_of_scope_terms) and not any(
            term in normalized_query for term in paper_context_terms
        ):
            return _human_decision(
                "논문 도메인과 무관한 질문",
                "저희는 학술 논문 검색·분석 챗봇이라 관련 정보를 드릴 수 없습니다. 논문 관련 질문을 입력해 주세요.",
            )

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
        wants_save = any(term in query for term in ("저장", "보관"))
        # 아래 단일 목적 분기들보다 먼저 "새 논문을 찾는 요청"인지 판단해야
        # "찾아서 요약해줘" 같은 복합 요청이 되묻기로 새지 않는다.
        wants_new_papers = any(
            term in query
            for term in ("arxiv", "외부 검색", "논문 찾아", "찾아서", "찾아줘", "검색해", *download_terms)
        )
        wants_qa = any(term in query for term in ("근거", "출처", "질문", "설명해"))
        wants_deep = any(term in query for term in deep_research_terms)

        # 주제가 빠진 관련 논문 저장 요청은 먼저 되묻되, 원래 작업과
        # 저장 개수를 State에 보관해 다음 사용자 입력에서 이어서 실행한다.
        pending_intent = str(state.get("pending_intent") or "").strip()
        if pending_intent == "related_search_save":
            save_count = int(state.get("pending_save_count") or 0)
            if not 1 <= save_count <= 15:
                return _human_decision(
                    "관련 논문 저장 개수가 유효하지 않음",
                    "저장할 관련 논문 수를 1~15편 사이로 알려주세요.",
                    pending_intent=pending_intent,
                    pending_save_count=save_count,
                )
            return SupervisorDecision(
                steps=["keyword", "search", "download"],
                reason="추가로 받은 주제로 관련 논문 검색·저장 재개",
                search_result_limit=save_count,
                save_paper_count=save_count,
                prioritize_primary_keyword=True,
            )

        # "위에 관련 논문 5개 찾아서 저장해줘"는 직전 심층 설명 논문을
        # 주제로 이어받는다. 직전 대상이 없으면 주제를 추측하지 않는다.
        related_followup = wants_save and (
            any(
                phrase in normalized_query
                for phrase in ("위에 관련", "위의 관련", "방금 관련", "앞의 관련")
            )
            or re.search(
                r"(?:위에|위의|방금|앞에서|앞에)\s*"
                r"(?:설명한\s*)?논문\s*(?:과|의)?\s*(?:관련|연관)",
                normalized_query,
            )
            is not None
        )
        if related_followup:
            # Deep Search knows the selected paper before answer generation.
            # Prefer that title so a follow-up still works if Deep Research
            # returns insufficient evidence; retain the older value for
            # conversations created before this context field existed.
            related_title = str(
                state.get("last_context_paper_title")
                or state.get("last_research_paper_title")
                or ""
            ).strip()
            count_match = re.search(r"(\d+)\s*(?:개|편)", normalized_query)
            save_count = int(count_match.group(1)) if count_match else 0
            if not related_title:
                return _human_decision(
                    "관련 논문의 기준 대상이 없음",
                    "어떤 논문과 관련된 논문을 찾을까요? 먼저 논문을 한 편 선택하거나 제목을 알려주세요.",
                )
            if not 1 <= save_count <= 15:
                return _human_decision(
                    "관련 논문 저장 개수가 유효하지 않음",
                    "저장할 관련 논문 수를 1~15편 사이로 알려주세요.",
                )
            return SupervisorDecision(
                steps=["keyword", "search", "download"],
                reason="직전 설명 논문과 관련된 논문 검색·저장 요청",
                search_result_limit=save_count,
                save_paper_count=save_count,
                prioritize_primary_keyword=True,
                related_paper_title=related_title,
            )

        related_topic_missing = wants_save and re.match(
            r"^\s*(?:관련|연관)\s*(?:된\s*)?논문", normalized_query
        ) is not None
        if related_topic_missing:
            count_match = re.search(r"(\d+)\s*(?:개|편)", normalized_query)
            save_count = int(count_match.group(1)) if count_match else 0
            return _human_decision(
                "관련 논문의 검색 주제가 없음",
                "어떤 주제와 관련된 논문을 저장할까요? 예: '딥러닝 모델과 관련된 논문'.",
                pending_intent="related_search_save",
                pending_save_count=save_count,
            )

        # "LLM 논문 10개 찾고 그중 5개 저장한 뒤 최상위 1개 설명"처럼
        # 검색 결과의 순위별 후속 작업이 한 문장에 포함된 요청은 별도 계획으로
        # 처리한다. 일반 검색에는 적용하지 않는다.
        search_count_match = re.search(
            r"(\d+)\s*(?:개|편)\s*(?:찾|검색)", normalized_query
        )
        save_count_match = re.search(
            r"(\d+)\s*(?:개|편)\s*(?:저장|보관)", normalized_query
        )
        ranked_explanation = (
            wants_save
            and asks_direct_research
            and search_count_match is not None
            and save_count_match is not None
            and any(term in query for term in ("최상위", "상위", "1위", "첫 번째", "첫번째"))
        )
        if ranked_explanation:
            search_limit = int(search_count_match.group(1))
            save_count = int(save_count_match.group(1))
            if not 1 <= save_count <= search_limit <= 15:
                return _human_decision(
                    "복합 요청의 검색·저장 개수가 유효하지 않음",
                    "검색 개수는 1~15편이고, 저장 개수는 검색 개수 이하여야 합니다.",
                )
            return SupervisorDecision(
                steps=["keyword", "search", "download", "extract", "deep_search"],
                reason="상위 논문 저장 후 최상위 논문 심층 설명 요청",
                search_result_limit=search_limit,
                save_paper_count=save_count,
                explain_paper_rank=1,
                prioritize_primary_keyword=True,
                research_question=(
                    "선택된 최상위 논문의 연구 목적, 방법론, "
                    "핵심 결과를 본문 근거로 설명해줘."
                ),
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
        selected_research_question = _normalize_selected_research_question(
            state["query"]
        )

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
        if (
            wants_summarize
            and not selected_candidate_ids
            and not state.get("paper_ids")
            and not wants_new_papers
        ):
            return _human_decision(
                "요약 대상 논문이 선택되지 않음",
                "어느 논문을 요약할까요? 논문 제목, paper_id 또는 목록 번호를 알려주세요.",
            )

        # 목록에서 번호로 고른 논문은 paper_ids로 확정한 뒤 필요한 Agent만
        # 계획에 넣는다. Summary/Translate의 실제 산출물 의존성은 graph가
        # 현재 State를 보고 필요한 경우에만 보충한다.
        if selected_candidate_ids and (wants_translate or wants_summarize):
            steps: list[ExecutableRoute] = []
            should_download = wants_download or selection_source == "search"
            if should_download:
                steps.append("download")
            if wants_summarize:
                steps.append("summarize")
            if wants_translate:
                steps.append("translate")
            if asks_direct_research:
                steps.append("deep_search")
            return SupervisorDecision(
                steps=steps,
                reason="선택한 논문의 요약·번역 요청",
                selected_paper_ids=selected_candidate_ids,
                download_paper_ids=(
                    selected_candidate_ids if should_download else []
                ),
                deep_search_paper_id=(
                    deep_target_id if asks_direct_research else ""
                ),
                research_question=(
                    selected_research_question if asks_direct_research else ""
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
                research_question=selected_research_question,
            )

        if has_direct_research_target and asks_direct_research:
            return SupervisorDecision(
                steps=["deep_search"],
                reason="지정된 추출 논문에서 심층 질문 근거 검색",
                selected_paper_ids=([deep_target_id] if deep_target_id else []),
                deep_search_paper_id=deep_target_id,
                research_question=selected_research_question,
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
        # 요약 번역해주고 설명해줘" = search + summarize + translate + explain).
        # Detect that BEFORE the single-purpose keyword checks below, which
        # would otherwise stop at whichever keyword happens to match first
        # and silently drop the rest of the request.
        if wants_new_papers and (
            wants_translate or wants_summarize or wants_qa or wants_deep or wants_save
        ):
            steps: list[ExecutableRoute] = []
            if any(
                term in query
                for term in ("arxiv", "외부 검색", "논문 찾아", "찾아서", "찾아줘", "검색해")
            ):
                steps += ["keyword", "search"]
            if wants_translate or wants_summarize:
                if not has_extraction:
                    steps.append("download")
                if wants_summarize:
                    steps.append("summarize")
                if wants_translate:
                    steps.append("translate")
            elif wants_download or wants_save:
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
            return SupervisorDecision(steps=["translate"], reason="요약문 번역 요청")
        if any(term in query for term in ("요약", "summar", "summary")):
            return SupervisorDecision(steps=["summarize"], reason="논문 요약 요청")
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
