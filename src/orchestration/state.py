"""Shared state contract for the academic-paper StateGraph."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.message import add_messages


_RESET = "__RESET__"


def _accumulate(current: list[str], update: list[str]) -> list[str]:
    """Append like ``operator.add``, but let a turn's initial input reset the log.

    The graph loops through many nodes within a single ``invoke`` call, so
    node returns must accumulate onto this channel. Across separate
    ``invoke`` calls that share a ``thread_id`` (a multi-turn conversation),
    the checkpointer keeps applying this same reducer to the new turn's
    input, so a plain ``operator.add`` would carry the previous turn's
    history forward forever. ``initial_state`` marks each new turn with a
    leading ``_RESET`` sentinel so the log actually starts empty per turn.
    """

    if update and update[0] == _RESET:
        return list(update[1:])
    return list(current) + list(update)


Route = Literal[
    "keyword",
    "search",
    "library",
    "download",
    "extract",
    "translate",
    "summarize",
    "deep_search",
    "deep_research",
    "finish",
]


class WorkflowState(TypedDict, total=False):
    """Data shared by the supervisor and every tool node.

    Team-owned classes keep their native interfaces. Adapters translate those
    native return values into this state contract.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    query: str
    route: Route
    route_reason: str
    remaining_steps: list[Route]
    thread_id: str
    retry_counts: dict[str, int]
    max_retries: int
    max_steps: int

    keywords: list[str]
    paper_ids: list[str]
    download_paper_ids: list[str]
    deep_search_paper_id: str
    selected_papers: list[dict[str, Any]]
    search_results: list[dict[str, Any]]
    library_results: list[dict[str, Any]]
    selection_candidates: list[dict[str, Any]]
    selection_source: str
    downloaded_paths: list[str]
    extracted_records: list[dict[str, Any]]
    translated_paths: list[str]
    summaries: list[dict[str, Any]]

    sources: list[dict[str, Any]]
    deep_search_references: list[str]
    deep_search_candidates: list[dict[str, Any]]
    deep_search_selection_required: bool
    deep_research_status: str
    deep_research_answer: str
    deep_research_sources: list[Any]
    deep_research_paper_id: str
    response: str

    node_history: Annotated[list[str], _accumulate]
    errors: Annotated[list[str], _accumulate]


def initial_state(
    query: str,
    *,
    thread_id: str = "default",
    paper_ids: list[str] | None = None,
    max_retries: int = 1,
    max_steps: int = 20,
) -> WorkflowState:
    """Create the minimal valid state accepted by the compiled graph."""

    normalized = query.strip()
    if not normalized:
        raise ValueError("질문을 입력해 주세요.")
    return {
        "messages": [HumanMessage(content=normalized)],
        "query": normalized,
        "thread_id": thread_id,
        "paper_ids": list(paper_ids or []),
        "download_paper_ids": [],
        "deep_search_paper_id": "",
        "remaining_steps": [],
        "retry_counts": {},
        "max_retries": max(0, max_retries),
        "max_steps": max(1, max_steps),
        "node_history": [_RESET],
        "errors": [_RESET],
        # Per-turn outputs: these are plain (non-reducer) fields, so a prior
        # turn's value would otherwise sit in the checkpoint untouched and
        # leak into a turn whose plan never sets it.
        "response": "",
        "sources": [],
        "deep_search_references": [],
        "deep_search_selection_required": False,
        "deep_research_status": "",
        "deep_research_answer": "",
        "deep_research_sources": [],
    }
