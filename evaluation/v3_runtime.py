"""Evaluation-only LangGraph runtime backed by the isolated v3 corpus."""

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

from evaluation.dataset_v3 import CORPUS_ROOT


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
GENERATED_ROOT = CORPUS_ROOT / "generated"
EXTRACT_DB = GENERATED_ROOT / "extracted_papers.db"
REFERENCE_DB = GENERATED_ROOT / "extracted_papers_ref.db"
CATALOG_PATH = GENERATED_ROOT / "extracted_papers.json"
RESULTS_PATH = GENERATED_ROOT / "execution_results_v3.jsonl"

for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
load_dotenv(PROJECT_ROOT / ".env", override=False)


TOKEN_PATTERN = re.compile(r"[가-힣A-Za-z0-9]{2,}")
SECTION_HINTS = {
    "abstract": ("목적", "문제", "초록", "goal", "purpose"),
    "introduction": ("배경", "기존", "한계", "background", "motivation"),
    "related_work": ("관련", "차별", "related", "prior"),
    "method": ("방법", "구조", "모델", "method", "architecture"),
    "experiment": ("실험 설정", "데이터셋", "평가", "experiment", "dataset"),
    "result": ("결과", "수치", "성능", "result", "performance"),
    "conclusion": ("결론", "기여", "후속", "conclusion", "contribution"),
}


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


class LexicalFullTextStore:
    """Read-only, dependency-free passage search for the evaluation DB."""

    SECTION_COLUMNS = (
        "abstract", "introduction", "related_work", "method",
        "experiment", "result", "conclusion",
    )

    def __init__(self, db_path: str | Path = EXTRACT_DB) -> None:
        self.db_path = Path(db_path)
        self._papers: dict[str, list[dict[str, Any]]] | None = None

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if self._papers is not None:
            return self._papers
        if not self.db_path.is_file():
            raise FileNotFoundError(f"평가용 본문 DB가 없습니다: {self.db_path}")
        papers: dict[str, list[dict[str, Any]]] = {}
        with sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT id, title, abstract, introduction, related_work, method, "
                "experiment, result, conclusion, content FROM extracted"
            ).fetchall()
        for row in rows:
            chunks: list[dict[str, Any]] = []
            seen: set[str] = set()
            sections = [
                (section, str(row[section] or "").strip())
                for section in self.SECTION_COLUMNS
                if str(row[section] or "").strip()
            ]
            if not sections:
                sections = [("content", str(row["content"] or "").strip())]
            for section, section_text in sections:
                for index, chunk in enumerate(_split_text(section_text)):
                    digest = f"{section}:{hash(chunk)}"
                    if not chunk or digest in seen:
                        continue
                    seen.add(digest)
                    # Keep title, section and evidence in one paragraph. The existing
                    # KeywordPaperRetriever splits on blank lines; a blank line here
                    # would make title-only chunks outrank the actual evidence.
                    document = f"{row['title']}\n{section}\n{chunk}"
                    chunks.append(
                        {
                            "id": f"{row['id']}:{section}:{index}",
                            "document": document,
                            "metadata": {
                                "paper_id": str(row["id"]),
                                "title": str(row["title"]),
                                "section": section,
                            },
                            "tokens": _tokens(document),
                        }
                    )
            papers[str(row["id"])] = chunks
        self._papers = papers
        return papers

    @staticmethod
    def _section_boost(query: str, section: str) -> float:
        normalized = query.casefold()
        hints = SECTION_HINTS.get(section, ())
        return 3.0 if any(hint in normalized for hint in hints) else 0.0

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
            score += self._section_boost(query, str(candidate["metadata"]["section"]))
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
    """Turn the existing answerer's empty UNSUPPORTED result into a refusal."""

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


def build_evaluation_graph(*, answer_mode: str = "openai"):
    """Build a graph whose data dependencies point only at corpus_v3."""

    from feature.deep_research import ExtractivePaperAnswerer, LangChainPaperAnswerer
    from orchestration.adapters import DeepResearchNode, DeepSearchNode
    from orchestration.graph import build_graph
    from orchestration.routing import SupervisorDecision, SupervisorRouter
    from tools.deep_search_tool import DeepSearch

    if answer_mode == "openai":
        model_name = os.getenv("EVALUATION_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        answer_factory = lambda: UnsupportedAnswerNormalizer(
            LangChainPaperAnswerer.with_openai(model_name=model_name)
        )
    elif answer_mode == "extractive":
        answer_factory = ExtractivePaperAnswerer
    else:
        raise ValueError("answer_mode는 openai 또는 extractive여야 합니다.")

    search_factory = lambda: DeepSearch(
        json_list_path=CATALOG_PATH,
        db_path=EXTRACT_DB,
        reference_db_path=REFERENCE_DB,
        fulltext_store_factory=lambda: LexicalFullTextStore(EXTRACT_DB),
    )

    class EvaluationRouter(SupervisorRouter):
        """Keep paper-scoped evaluation inside the two approved RAG nodes."""

        def decide(self, state: dict[str, Any]) -> SupervisorDecision:
            if state.get("paper_ids"):
                return SupervisorDecision(
                    steps=["deep_search"],
                    reason="평가 입력에 선택 논문이 있으므로 격리된 RAG 경로를 실행합니다.",
                )
            return super().decide(state)

    return build_graph(
        router=EvaluationRouter(use_llm=False),
        nodes={
            "deep_search": DeepSearchNode(factory=search_factory, limit=5),
            "deep_research": DeepResearchNode(factory=answer_factory),
        },
    )


def artifact_target(inputs: dict[str, Any]) -> dict[str, Any]:
    paper_id = str(inputs["paper_id"])
    with sqlite3.connect(f"file:{EXTRACT_DB.as_posix()}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT title, content, n_pages, n_chars FROM extracted WHERE id = ?",
            (paper_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"평가 DB에 없는 논문입니다: {paper_id}")
    return {
        "paper_id": paper_id,
        "title": str(row[0]),
        "source_text": str(row[1]),
        "n_pages": int(row[2] or 0),
        "n_chars": int(row[3] or 0),
    }


class V3EvaluationTarget:
    """Callable LangSmith target with lazy graph construction."""

    def __init__(self, *, answer_mode: str = "openai") -> None:
        self.answer_mode = answer_mode
        self._graph: Any | None = None

    @property
    def graph(self):
        if self._graph is None:
            self._graph = build_evaluation_graph(answer_mode=self.answer_mode)
        return self._graph

    def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
        suite = str(inputs.get("suite") or "")
        try:
            if suite == "artifacts":
                return artifact_target(inputs)
            from orchestration.state import initial_state

            run_id = f"eval-v3-{inputs.get('case_id', 'case')}-{uuid4().hex[:8]}"
            result = self.graph.invoke(
                initial_state(
                    str(inputs.get("query") or ""),
                    thread_id=run_id,
                    paper_ids=list(inputs.get("paper_ids", [])),
                ),
                config={
                    "configurable": {"thread_id": run_id},
                    "run_name": "academic-paper-evaluation-v3",
                    "tags": ["evaluation", "v3", suite],
                    "metadata": {"case_id": inputs.get("case_id"), "suite": suite},
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


def load_cached_results(path: str | Path = RESULTS_PATH) -> dict[str, dict[str, Any]]:
    result_path = Path(path)
    if not result_path.is_file():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line in result_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        case_id = str(record.get("inputs", {}).get("case_id") or "")
        if case_id:
            records[case_id] = record
    return records


__all__ = [
    "CATALOG_PATH",
    "EXTRACT_DB",
    "GENERATED_ROOT",
    "LexicalFullTextStore",
    "REFERENCE_DB",
    "RESULTS_PATH",
    "UnsupportedAnswerNormalizer",
    "V3EvaluationTarget",
    "artifact_target",
    "build_evaluation_graph",
    "load_cached_results",
]
