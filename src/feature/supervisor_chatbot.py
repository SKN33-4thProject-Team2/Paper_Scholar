"""Application-facing Supervisor chatbot service.

The CLI and a future UI should call this module instead of depending on the
LangGraph wiring directly.  UI layout and message rendering deliberately stay
outside this file.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from orchestration.graph import build_graph
from orchestration.state import initial_state


class SupervisorChatbot:
    """Run one user request through the Supervisor-managed LangGraph."""

    def __init__(self, *, graph: Any | None = None) -> None:
        # Build once so callers such as a future Streamlit session can reuse it.
        self.graph = graph or build_graph()

    def invoke(
        self,
        query: str,
        *,
        thread_id: str | None = None,
        paper_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return the complete workflow result for CLI or UI consumers."""

        run_thread_id = thread_id or f"chat-{uuid4().hex[:8]}"
        config = {
            "configurable": {"thread_id": run_thread_id},
            "run_name": "academic-paper-supervisor-chatbot",
            "tags": ["academic-paper", "langgraph", "supervisor-chatbot"],
        }
        result = self.graph.invoke(
            initial_state(
                query,
                thread_id=run_thread_id,
                paper_ids=paper_ids,
            ),
            config=config,
        )
        return dict(result)

    def chat(
        self,
        query: str,
        *,
        thread_id: str | None = None,
        paper_ids: list[str] | None = None,
    ) -> str:
        """Return only the answer text for a simple chatbot interface."""

        result = self.invoke(
            query,
            thread_id=thread_id,
            paper_ids=paper_ids,
        )
        return str(result.get("response") or "응답을 생성하지 못했습니다.")


def run_supervisor_chatbot(
    query: str,
    *,
    thread_id: str | None = None,
    paper_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Convenience entry point for one-off callers."""

    return SupervisorChatbot().invoke(
        query,
        thread_id=thread_id,
        paper_ids=paper_ids,
    )


__all__ = ["SupervisorChatbot", "run_supervisor_chatbot"]
