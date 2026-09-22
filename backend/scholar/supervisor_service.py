"""웹에서 LangGraph Supervisor를 실행한다.

이 모듈은 계획을 직접 만들지 않는다. 계획 수립과 실행은 모두
`src/orchestration`의 LangGraph Supervisor가 담당하고, 여기서는 그 결과를
웹 응답 형태로 옮기기만 한다. 프론트가 단계를 순서대로 호출하던 방식은
더 이상 쓰지 않으며, 그래프가 필요한 Agent만 골라 비동기로 실행한다.
"""

from __future__ import annotations

import asyncio
from typing import Any

# 노드 이름을 화면에 보여줄 한국어 라벨로 바꾼다.
ROUTE_LABELS: dict[str, str] = {
    "keyword": "검색 키워드 생성",
    "search": "arXiv 논문 검색",
    "library": "내 서재 조회",
    "download": "논문 저장·다운로드",
    "extract": "본문 추출",
    "summarize": "요약 생성",
    "translate": "한국어 번역",
    "deep_search": "본문 근거 검색",
    "deep_research": "근거 기반 답변",
    "human": "추가 정보 요청",
    "finish": "완료",
}


def _initial_state(query: str, thread_id: str):
    from orchestration.state import initial_state

    return initial_state(query, thread_id=thread_id)


def build_plan(query: str, *, thread_id: str = "preview") -> dict[str, Any]:
    """실행 전에 어떤 Agent가 움직일지 미리 보여준다."""

    from orchestration.routing import SupervisorRouter

    decision = SupervisorRouter().decide(_initial_state(query, thread_id))
    needs_input = list(decision.steps) == ["human"]
    return {
        "status": "success",
        "query": query,
        "actions": list(decision.steps),
        "steps": [
            {"step": index, "action": route, "name": ROUTE_LABELS.get(route, route)}
            for index, route in enumerate(decision.steps, start=1)
        ],
        "reason": decision.reason,
        "needs_clarification": needs_input,
        "clarification_question": decision.human_question if needs_input else "",
    }


_chatbot: Any | None = None


def _get_chatbot():
    """그래프는 한 번만 만들어 재사용한다. 같은 thread_id의 이전 턴을 기억한다."""

    global _chatbot
    if _chatbot is None:
        from feature.supervisor_chatbot import SupervisorChatbot

        _chatbot = SupervisorChatbot()
    return _chatbot


def run_supervisor(query: str, *, thread_id: str) -> dict[str, Any]:
    """LangGraph의 비동기 인터페이스로 그래프 전체를 실행한다."""

    chatbot = _get_chatbot()
    return asyncio.run(chatbot.ainvoke(query, thread_id=thread_id))


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    """그래프 State에서 화면이 쓰는 값만 추린다."""

    papers = (
        result.get("selected_papers")
        or result.get("search_results")
        or result.get("library_results")
        or []
    )
    return {
        "response": str(result.get("response") or ""),
        "node_history": [
            route for route in result.get("node_history", []) if route != "finish"
        ],
        "papers": [
            {
                "arxiv_id": str(paper.get("id") or paper.get("arxiv_id") or ""),
                "title": str(paper.get("title") or ""),
            }
            for paper in papers
            if isinstance(paper, dict)
        ],
        "sources": [
            {
                "label": str(source.get("label") or ""),
                "title": str(source.get("title") or ""),
                "section": str(source.get("section") or ""),
                "excerpt": str(source.get("excerpt") or ""),
            }
            for source in result.get("sources", [])
            if isinstance(source, dict)
        ],
        "needs_input": bool(result.get("human_input_required")),
        "errors": list(result.get("errors", [])),
    }


__all__ = ["ROUTE_LABELS", "build_plan", "run_supervisor", "summarize_result"]
