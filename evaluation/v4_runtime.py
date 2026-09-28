"""Evaluation-only LangGraph runtime backed by the isolated v4 corpus (200 papers).

Mirrors ``evaluation/v3_runtime.py`` but points at ``evaluation/corpus_v4``'s own
extraction DB (page-based ``paper_sections``, not v3's named-section columns).
Nothing here writes to the production MySQL/Chroma store, and nothing under
``src/`` or ``backend/`` is modified — this file only imports the existing
Agent code and injects isolated data sources, exactly like v3_runtime does.
"""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
CORPUS_ROOT = PROJECT_ROOT / "evaluation" / "corpus_v4"
GENERATED_ROOT = CORPUS_ROOT / "generated"
EXTRACT_DB = GENERATED_ROOT / "extracted_papers_v4.db"
MANIFEST_PATH = CORPUS_ROOT / "manifest_200.jsonl"
RESULTS_PATH = GENERATED_ROOT / "execution_results_v4.jsonl"

for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
load_dotenv(PROJECT_ROOT / ".env", override=False)


TOKEN_PATTERN = re.compile(r"[가-힣A-Za-z0-9]{2,}")


def _tokens(text: str) -> Counter[str]:
    return Counter(token.casefold() for token in TOKEN_PATTERN.findall(text))


def _split_text(text: str, *, chunk_size: int = 1_200, overlap: int = 180) -> list[str]:
    chunks: list[str] = []
    for paragraph in (part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()):
        start = 0
        while start < len(paragraph):
            end = min(start + chunk_size, len(paragraph))
            chunks.append(paragraph[start:end])
            if end == len(paragraph):
                break
            start = end - overlap
    return chunks


class V4LexicalFullTextStore:
    """Read-only passage search over corpus_v4's page-based paper_sections table."""

    def __init__(self, db_path: str | Path = EXTRACT_DB) -> None:
        self.db_path = Path(db_path)
        self._papers: dict[str, list[dict[str, Any]]] | None = None

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if self._papers is not None:
            return self._papers
        if not self.db_path.is_file():
            raise FileNotFoundError(f"corpus_v4 추출 DB가 없습니다: {self.db_path}")
        papers: dict[str, list[dict[str, Any]]] = {}
        with sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            titles = {
                row["paper_id"]: row["title"]
                for row in connection.execute("SELECT paper_id, title FROM papers")
            }
            rows = connection.execute(
                "SELECT paper_id, section_order, section_title, section_text "
                "FROM paper_sections ORDER BY paper_id, section_order"
            ).fetchall()
        for row in rows:
            paper_id = str(row["paper_id"])
            title = str(titles.get(paper_id, ""))
            section_label = f"page_{row['section_order']}"
            for index, chunk in enumerate(_split_text(str(row["section_text"] or ""))):
                if not chunk.strip():
                    continue
                document = f"{title}\n{section_label}\n{chunk}"
                papers.setdefault(paper_id, []).append(
                    {
                        "id": f"{paper_id}:{section_label}:{index}",
                        "document": document,
                        "metadata": {
                            "paper_id": paper_id,
                            "title": title,
                            "section": section_label,
                            "section_order": int(row["section_order"]),
                        },
                        "tokens": _tokens(document),
                    }
                )
        self._papers = papers
        return papers

    def search(self, query: str, *, limit: int = 5, paper_id: str | None = None) -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        candidates = self._load().get(str(paper_id or ""), [])
        ranked: list[tuple[float, dict[str, Any]]] = []
        for candidate in candidates:
            document_tokens: Counter[str] = candidate["tokens"]
            overlap = sum(
                min(query_count, document_tokens.get(token, 0))
                for token, query_count in query_tokens.items()
            )
            title_tokens = _tokens(str(candidate["metadata"]["title"]))
            title_overlap = sum(
                min(query_count, title_tokens.get(token, 0))
                for token, query_count in query_tokens.items()
            )
            score = float(overlap) + 2.0 * float(title_overlap)
            if score > 0:
                ranked.append((score, candidate))
        ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
        return [
            {
                "id": candidate["id"],
                "document": candidate["document"],
                "metadata": candidate["metadata"],
                "distance": round(1.0 / (1.0 + score), 6),
            }
            for score, candidate in ranked[:limit]
        ]

    def close(self) -> None:
        self._papers = None


class UnsupportedAnswerNormalizer:
    """Turn the existing answerer's empty UNSUPPORTED result into a refusal.

    Mirrors ``evaluation/v3_runtime.py``'s class of the same name exactly.
    """

    def __init__(self, answerer: Any) -> None:
        self.answerer = answerer

    def answer(self, paper: dict[str, Any], question: str) -> dict[str, Any] | str:
        result = self.answerer.answer(paper, question)
        if not isinstance(result, dict):
            return result
        if result.get("has_evidence") is False and not str(result.get("answer") or "").strip():
            normalized = dict(result)
            normalized["answer"] = "선택한 논문의 근거만으로는 질문에 답할 수 없습니다."
            normalized["sources"] = []
            return normalized
        return result


def build_v4_evaluation_graph():
    """Build a graph whose data dependencies point only at evaluation/corpus_v4."""

    from feature.deep_research import LangChainPaperAnswerer
    from orchestration.adapters import DeepResearchNode, DeepSearchNode
    from orchestration.graph import build_graph
    from orchestration.routing import SupervisorDecision, SupervisorRouter
    from tools.deep_search_tool import DeepSearch

    # EVALUATION_MODEL이 명시되지 않으면 LangChainPaperAnswerer.with_openai()가
    # 운영과 동일하게 .env의 OPENAI_CHAT_MODEL을 그대로 사용하도록 None을 넘긴다.
    # (gpt-4o-mini처럼 reasoning_effort를 지원하지 않는 모델을 강제하면
    # src/feature/deep_research.py의 reasoning_effort="none" 호출이 실패한다.)
    model_name = os.getenv("EVALUATION_MODEL", "").strip() or None
    answer_factory = lambda: UnsupportedAnswerNormalizer(
        LangChainPaperAnswerer.with_openai(model_name=model_name)
    )

    search_factory = lambda: DeepSearch(
        db_path=EXTRACT_DB,
        reference_db_path=EXTRACT_DB,
        fulltext_store_factory=lambda: V4LexicalFullTextStore(EXTRACT_DB),
    )

    class V4EvaluationRouter(SupervisorRouter):
        """Keep paper-scoped evaluation inside the two approved RAG nodes."""

        def decide(self, state: dict[str, Any]) -> SupervisorDecision:
            if state.get("paper_ids"):
                return SupervisorDecision(
                    steps=["deep_search"],
                    reason="평가 입력에 선택 논문이 있으므로 격리된 RAG 경로를 실행합니다.",
                )
            return super().decide(state)

    return build_graph(
        router=V4EvaluationRouter(use_llm=False),
        nodes={
            "deep_search": DeepSearchNode(factory=search_factory, limit=5),
            "deep_research": DeepResearchNode(factory=answer_factory),
        },
    )


class V4EvaluationTarget:
    """Callable target: run one Deep Search + Deep Research turn against corpus_v4."""

    def __init__(self) -> None:
        self._graph: Any | None = None

    @property
    def graph(self):
        if self._graph is None:
            self._graph = build_v4_evaluation_graph()
        return self._graph

    def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
        try:
            from orchestration.state import initial_state

            run_id = f"eval-v4-{inputs.get('case_id', 'case')}-{uuid4().hex[:8]}"
            result = self.graph.invoke(
                initial_state(
                    str(inputs.get("query") or ""),
                    thread_id=run_id,
                    paper_ids=list(inputs.get("paper_ids", [])),
                ),
                config={
                    "configurable": {"thread_id": run_id},
                    "run_name": "academic-paper-evaluation-v4",
                    "tags": ["evaluation", "v4"],
                    "metadata": {"case_id": inputs.get("case_id")},
                },
            )
            return dict(result)
        except Exception as exc:
            return {
                "response": "",
                "sources": [],
                "node_history": [],
                "errors": [f"{type(exc).__name__}: {exc}"],
            }


def load_manifest() -> list[dict[str, Any]]:
    return [json.loads(line) for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_paper_sections(paper_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(f"file:{EXTRACT_DB.as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT section_order, section_title, section_text FROM paper_sections "
            "WHERE paper_id = ? ORDER BY section_order",
            (paper_id,),
        ).fetchall()
    return [dict(row) for row in rows]


__all__ = [
    "CORPUS_ROOT",
    "EXTRACT_DB",
    "GENERATED_ROOT",
    "MANIFEST_PATH",
    "RESULTS_PATH",
    "V4EvaluationTarget",
    "V4LexicalFullTextStore",
    "build_v4_evaluation_graph",
    "load_manifest",
    "load_paper_sections",
]
