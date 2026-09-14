"""Adapters that expose existing chatbot classes as StateGraph nodes."""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from orchestration.state import WorkflowState


_COUNT_PATTERN = re.compile(r"(\d+)\s*(개|편|papers?)", re.IGNORECASE)
_LATEST_TERMS = ("최신", "최근", "latest", "recent", "newest")

# The local keyword model sometimes leaks the request's action verbs (부탁한
# "번역"/"요약"/"설명" 같은 동작) into the generated search terms instead of
# sticking to the actual topic. Strip those before they pollute the arXiv
# query with generic OR-clauses that match almost anything.
_GENERIC_KEYWORD_BLOCKLIST = {
    "recent", "recently", "latest", "newest", "new",
    "paper", "papers", "article", "articles", "study", "studies", "research",
    "analysis", "analyze", "analyses",
    "summary", "summaries", "summarization", "summarize",
    "translation", "translate", "translated",
    "search", "find", "explain", "explanation", "explained",
}


class NodeExecutionError(RuntimeError):
    """Raised when an existing team component cannot satisfy the node contract."""


class StateNode(Protocol):
    def __call__(self, state: WorkflowState) -> dict[str, Any]: ...


def _record(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    raise NodeExecutionError(f"지원하지 않는 결과 형식입니다: {type(value).__name__}")


def _default_keyword_tool():
    from tools.keyword_tool import KeywordTool

    return KeywordTool()


def _default_search_bot():
    from feature.search import ArxivSearchBot

    return ArxivSearchBot()


def _default_library_bot():
    from feature.search_list import LocalLibraryBot

    return LocalLibraryBot()


def _default_extractor():
    from feature.paper_extractor import PaperExtractor

    return PaperExtractor()


def _default_translator():
    from tools.translation_tool import TranslateTool

    return TranslateTool()


def _default_summarizer():
    from tools.summary_tool import SummaryTool

    return SummaryTool()


def _default_deep_search():
    from tools.deep_search_tool import DeepSearch

    return DeepSearch()


def _default_deep_research_answerer():
    from feature.deep_research import LangChainPaperAnswerer

    return LangChainPaperAnswerer.with_openai()


class KeywordNode:
    def __init__(self, factory: Callable[[], Any] = _default_keyword_tool) -> None:
        self._factory = factory
        self._tool: Any | None = None

    @property
    def tool(self):
        if self._tool is None:
            self._tool = self._factory()
        return self._tool

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        topic = state["query"]
        if int(state.get("retry_counts", {}).get("search", 0)) > 0:
            previous = ", ".join(state.get("keywords", []))
            topic = (
                f"{topic}\n"
                "이전 검색 결과가 없었습니다. 같은 의미를 유지하되 "
                f"다음 표현과 겹치지 않는 대체 학술 용어를 생성하세요: {previous}"
            )
        result = self.tool.generate_keywords(topic)
        keywords = [str(item) for item in result.get("keywords", []) if str(item).strip()]
        if not keywords:
            raise NodeExecutionError("검색 키워드를 생성하지 못했습니다.")
        return {"keywords": keywords, "node_history": ["keyword"]}


class ArxivSearchNode:
    def __init__(
        self,
        factory: Callable[[], Any] = _default_search_bot,
        *,
        max_results: int = 10,
    ) -> None:
        self._factory = factory
        self._bot: Any | None = None
        self._max_results = max_results

    @property
    def bot(self):
        if self._bot is None:
            self._bot = self._factory()
        return self._bot

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        terms = state.get("keywords") or [state["query"]]
        filtered_terms = [
            term for term in terms if term.strip().casefold() not in _GENERIC_KEYWORD_BLOCKLIST
        ]
        terms = filtered_terms or terms
        query = " OR ".join(f'"{term}"' for term in terms)

        raw_query = state["query"]
        count_match = _COUNT_PATTERN.search(raw_query)
        max_results = int(count_match.group(1)) if count_match else self._max_results
        max_results = max(1, min(max_results, 15))
        sort_by = "n" if any(term in raw_query for term in _LATEST_TERMS) else "r"

        papers = list(self.bot.search_papers(query, sort_by=sort_by, max_results=max_results))
        # PaperExtractor resolves paper_id -> PDF file by looking the id up in
        # saved_papers.db, so search results must be persisted immediately —
        # otherwise a later download/extract step can save the PDF but never
        # find it again by id.
        if papers and hasattr(self.bot, "save_papers"):
            try:
                self.bot.save_papers(papers)
            except Exception:
                pass
        return {
            "search_results": papers,
            "selection_candidates": [_record(paper) for paper in papers],
            "selection_source": "search",
            "node_history": ["search"],
        }


class LocalLibraryNode:
    def __init__(self, factory: Callable[[], Any] = _default_library_bot) -> None:
        self._factory = factory
        self._bot: Any | None = None

    @property
    def bot(self):
        if self._bot is None:
            self._bot = self._factory()
        return self._bot

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        paper_ids = list(state.get("paper_ids", []))
        if not paper_ids:
            paper_ids = self.bot.search_json(state["query"])
        papers = self.bot.fetch_full_data_from_db(paper_ids) if paper_ids else []
        return {
            "paper_ids": [str(paper["id"]) for paper in papers],
            "library_results": papers,
            "selection_candidates": [_record(paper) for paper in papers],
            "selection_source": "library",
            "node_history": ["library"],
        }


class DownloadNode:
    def __init__(self, factory: Callable[[], Any] = _default_library_bot) -> None:
        self._factory = factory
        self._bot: Any | None = None

    @property
    def bot(self):
        if self._bot is None:
            self._bot = self._factory()
        return self._bot

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        download_paper_ids = [
            str(paper_id).strip()
            for paper_id in state.get("download_paper_ids", [])
            if str(paper_id).strip()
        ]
        if download_paper_ids:
            papers = self.bot.fetch_full_data_from_db(download_paper_ids)
        else:
            papers = (
                state.get("selected_papers")
                or state.get("library_results")
                or state.get("search_results")
                or []
            )
        if not papers:
            raise NodeExecutionError("다운로드할 논문이 선택되지 않았습니다.")
        paths: list[str] = []
        paper_ids: list[str] = []
        for paper in papers:
            # download_pdf returns a status code ("success"/"exists"/"error"/
            # "no_url"), not a file path — only "error"/"no_url" are real
            # failures, so a paper counts as available whenever the file is
            # now on disk (either just downloaded or already present).
            status = self.bot.download_pdf(paper)
            if status in ("success", "exists"):
                paths.append(f"{paper.get('title', paper.get('id', ''))}: {status}")
                if paper.get("id"):
                    paper_ids.append(str(paper["id"]))
        deep_search_paper_id = str(
            state.get("deep_search_paper_id") or ""
        ).strip()
        selected_paper_ids = [
            str(paper_id).strip()
            for paper_id in state.get("paper_ids", [])
            if str(paper_id).strip()
        ]
        return {
            "paper_ids": (
                selected_paper_ids
                or ([deep_search_paper_id] if deep_search_paper_id else paper_ids)
            ),
            "downloaded_paths": paths,
            "node_history": ["download"],
        }


class ExtractNode:
    def __init__(self, factory: Callable[[], Any] = _default_extractor) -> None:
        self._factory = factory
        self._extractor: Any | None = None

    @property
    def extractor(self):
        if self._extractor is None:
            self._extractor = self._factory()
        return self._extractor

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        paper_ids = list(state.get("paper_ids", []))
        if not paper_ids:
            raise NodeExecutionError("추출할 paper_id가 없습니다.")
        results = self.extractor.extract_many(paper_ids)
        records = [_record(result) for result in results]
        if not records:
            raise NodeExecutionError("논문 본문을 추출하지 못했습니다.")
        return {"extracted_records": records, "node_history": ["extract"]}


class TranslateNode:
    def __init__(
        self,
        translator_factory: Callable[[], Any] = _default_translator,
        extractor_factory: Callable[[], Any] = _default_extractor,
    ) -> None:
        self._translator_factory = translator_factory
        self._extractor_factory = extractor_factory
        self._translator: Any | None = None
        self._extractor: Any | None = None

    @property
    def translator(self):
        if self._translator is None:
            self._translator = self._translator_factory()
        return self._translator

    @property
    def extractor(self):
        if self._extractor is None:
            self._extractor = self._extractor_factory()
        return self._extractor

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        records = list(state.get("extracted_records", []))
        if not records:
            records = [
                record
                for paper_id in state.get("paper_ids", [])
                if (record := self.extractor.get(paper_id))
            ]
        if not records:
            raise NodeExecutionError("번역 전에 논문 본문 추출이 필요합니다.")

        paths: list[str] = []
        failures: list[str] = []
        for record in records:
            title = str(record.get("title", "")) or str(record.get("id", ""))
            try:
                path = self.translator.translate_paper(
                    record["content"],
                    paper_id=str(record.get("id", "")),
                    title=str(record.get("title", "")),
                )
            except Exception as exc:  # a single paper's failure must not drop the rest
                failures.append(f"{title}: {exc}")
                continue
            paths.append(str(path))

        if not paths:
            raise NodeExecutionError(
                "모든 논문 번역에 실패했습니다: " + "; ".join(failures)
            )
        return {"translated_paths": paths, "node_history": ["translate"]}


class SummaryNode:
    def __init__(self, factory: Callable[[], Any] = _default_summarizer) -> None:
        self._factory = factory
        self._tool: Any | None = None

    @property
    def tool(self):
        if self._tool is None:
            self._tool = self._factory()
        return self._tool

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        paths = [Path(path) for path in state.get("translated_paths", [])]
        if not paths:
            raise NodeExecutionError("요약 전에 번역 Markdown 생성이 필요합니다.")

        summaries: list[dict[str, Any]] = []
        failures: list[str] = []
        for path in paths:
            try:
                summary = _record(self.tool.summarize_file(path))
            except Exception as exc:  # one paper's failure must not drop the rest
                failures.append(f"{path.name}: {exc}")
                continue
            if summary.get("markdown_path") is not None:
                summary["markdown_path"] = str(summary["markdown_path"])
            summaries.append(summary)

        if not summaries:
            raise NodeExecutionError(
                "모든 논문 요약에 실패했습니다: " + "; ".join(failures)
            )
        return {"summaries": summaries, "node_history": ["summarize"]}


class DeepSearchNode:
    """선택된 논문 한 편에서 질문 관련 본문 근거를 검색한다."""

    def __init__(
        self,
        factory: Callable[[], Any] = _default_deep_search,
        *,
        limit: int = 5,
    ) -> None:
        if not 1 <= limit <= 10:
            raise ValueError("Deep Search 근거 수는 1개에서 10개 사이여야 합니다.")
        self._factory = factory
        self._searcher: Any | None = None
        self._limit = limit

    @property
    def searcher(self):
        if self._searcher is None:
            self._searcher = self._factory()
        return self._searcher

    @staticmethod
    def _select_candidate(
        query: str, candidates: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        number_match = re.search(r"(\d+)\s*번", query)
        if number_match:
            index = int(number_match.group(1)) - 1
            return candidates[index] if 0 <= index < len(candidates) else None

        normalized_query = query.casefold()
        matches = [
            candidate
            for candidate in candidates
            if any(
                value and value.casefold() in normalized_query
                for value in (
                    str(candidate.get("paper_id") or "").strip(),
                    str(candidate.get("title") or "").strip(),
                )
            )
        ]
        return (
            max(matches, key=lambda item: len(str(item.get("title") or "")))
            if matches
            else None
        )

    @staticmethod
    def _selection_payload(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        lines = [
            f"{index}. {paper.get('title') or paper.get('paper_id')}"
            for index, paper in enumerate(candidates, start=1)
        ]
        response = (
            "\n".join(
                [
                    "심층 질문이 가능한 추출 논문 목록입니다.",
                    *lines,
                    "번호나 제목으로 논문 한 편을 선택해 주세요.",
                ]
            )
            if candidates
            else "PaperExtractor로 추출된 논문이 없습니다."
        )
        return {
            "paper_ids": [],
            "sources": [],
            "deep_search_references": [],
            "deep_search_candidates": candidates,
            "selection_candidates": candidates,
            "selection_source": "deep_search",
            "deep_search_selection_required": bool(candidates),
            "response": response,
            "node_history": ["deep_search"],
        }

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        requested_paper_id = str(
            state.get("deep_search_paper_id") or ""
        ).strip()
        paper_ids = list(
            dict.fromkeys(
                str(paper_id).strip()
                for paper_id in state.get("paper_ids", [])
                if str(paper_id).strip()
            )
        )
        if requested_paper_id:
            paper_ids = [requested_paper_id]
        active_paper_id = str(state.get("deep_research_paper_id") or "").strip()
        candidates = [
            dict(candidate)
            for candidate in state.get("deep_search_candidates", [])
            if isinstance(candidate, dict)
        ]
        if candidates and not requested_paper_id:
            selected = self._select_candidate(state["query"], candidates)
            if selected is not None:
                selected_id = str(selected.get("paper_id") or "").strip()
                if selected_id:
                    paper_ids = [selected_id]

        if len(paper_ids) != 1:
            catalog = self.searcher.search_papers("")
            allowed_ids = set(paper_ids)
            candidates = [
                {
                    "paper_id": str(paper.get("id") or ""),
                    "title": str(paper.get("title") or ""),
                }
                for paper in catalog.get("results", [])
                if isinstance(paper, dict)
                and str(paper.get("id") or "").strip()
                and (
                    not allowed_ids
                    or str(paper.get("id") or "").strip() in allowed_ids
                )
            ]
            selected = self._select_candidate(state["query"], candidates)
            selected_id = str((selected or {}).get("paper_id") or "").strip()
            if not selected_id and active_paper_id and any(
                candidate.get("paper_id") == active_paper_id
                for candidate in candidates
            ):
                selected_id = active_paper_id
            if not selected_id:
                return self._selection_payload(candidates)
            paper_ids = [selected_id]

        paper_id = paper_ids[0]
        # PaperExtractor가 extracted_papers.db에 저장한 동일 ID가 실제로
        # 존재하는지 먼저 확인한다. 제목 검색이나 다른 논문 후보로 대체하지 않는다.
        try:
            paper = self.searcher.get_paper_details(paper_id)
        except Exception as exc:
            return {
                "paper_ids": [],
                "sources": [],
                "deep_search_references": [],
                "deep_search_candidates": [],
                "deep_search_selection_required": False,
                "response": f"선택한 논문의 추출 본문을 찾지 못했습니다: {exc}",
                "node_history": ["deep_search"],
            }
        if str(paper.get("paper_id") or "").strip() != paper_id:
            raise NodeExecutionError(
                "선택한 논문 ID와 추출 DB의 논문 ID가 일치하지 않습니다."
            )

        references = [
            str(reference).strip()
            for reference in paper.get("references", [])
            if str(reference).strip()
            and str(reference).strip()
            not in {"레퍼런스 DB 누락됨", "레퍼런스 DB 파싱 오류 발생"}
        ]

        try:
            payload = self.searcher.search_passages(
                state["query"],
                paper_id=paper_id,
                limit=self._limit,
            )
        except Exception as exc:
            return {
                "paper_ids": [],
                "sources": [],
                "deep_search_references": [],
                "deep_search_candidates": [],
                "deep_search_selection_required": False,
                "response": f"선택한 논문의 본문 근거 검색에 실패했습니다: {exc}",
                "node_history": ["deep_search"],
            }
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise NodeExecutionError("Deep Search 결과 형식이 올바르지 않습니다.")

        sources: list[dict[str, Any]] = []
        for index, result in enumerate(raw_results, start=1):
            if not isinstance(result, dict):
                continue
            metadata = result.get("metadata")
            metadata = dict(metadata) if isinstance(metadata, dict) else {}
            document = str(result.get("document") or "")
            sources.append(
                {
                    "label": f"S{index}",
                    "id": str(result.get("id") or ""),
                    "paper_id": str(metadata.get("paper_id") or paper_id),
                    "title": str(metadata.get("title") or paper.get("title") or ""),
                    "section": str(metadata.get("section") or ""),
                    "distance": result.get("distance"),
                    "document": document,
                    "excerpt": document[:500],
                }
            )

        response = (
            f"선택한 논문에서 질문과 관련된 근거 {len(sources)}개를 찾았습니다."
            if sources
            else "선택한 논문에서 질문과 관련된 본문 근거를 찾지 못했습니다."
        )
        return {
            "paper_ids": [paper_id],
            "sources": sources,
            "deep_search_references": references,
            "deep_search_candidates": [],
            "deep_search_selection_required": False,
            "response": response,
            "node_history": ["deep_search"],
        }


class DeepResearchNode:
    """Deep Search가 찾은 단일 논문의 근거만 사용해 답변한다."""

    def __init__(
        self,
        factory: Callable[[], Any] = _default_deep_research_answerer,
    ) -> None:
        self._factory = factory
        self._answerer: Any | None = None

    @property
    def answerer(self):
        if self._answerer is None:
            self._answerer = self._factory()
        return self._answerer

    @staticmethod
    def _insufficient_evidence_response(references: list[str]) -> str:
        message = "선택한 논문에서 질문에 답할 직접적인 본문 근거를 찾지 못했습니다."
        if not references:
            return message + " 이 논문에 저장된 참고문헌도 없습니다."
        return "\n".join(
            [
                message,
                "대신 이 논문이 근거로 사용한 참고문헌을 안내합니다.",
                *references,
            ]
        )

    @staticmethod
    def _with_download_summary(state: WorkflowState, response: str) -> str:
        if "download" not in state.get("node_history", []):
            return response
        paths = [str(path) for path in state.get("downloaded_paths", []) if path]
        if not paths:
            return response
        return "\n".join(
            ["다운로드 결과:", *(f"- {path}" for path in paths), "", response]
        )

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        paper_ids = [
            str(paper_id).strip()
            for paper_id in state.get("paper_ids", [])
            if str(paper_id).strip()
        ]
        if len(set(paper_ids)) != 1:
            raise NodeExecutionError(
                "Deep Research를 실행하려면 논문을 정확히 한 편 선택해야 합니다."
            )
        paper_id = paper_ids[0]
        references = [
            str(reference).strip()
            for reference in state.get("deep_search_references", [])
            if str(reference).strip()
        ]

        sources = [
            dict(source)
            for source in state.get("sources", [])
            if isinstance(source, dict)
            and str(source.get("paper_id") or "").strip() == paper_id
            and str(source.get("document") or source.get("excerpt") or "").strip()
        ]
        if not sources:
            response = self._with_download_summary(
                state,
                self._insufficient_evidence_response(references),
            )
            return {
                "response": response,
                "deep_research_status": "insufficient_evidence",
                "deep_research_answer": response,
                "deep_research_sources": [],
                "deep_research_paper_id": paper_id,
                "node_history": ["deep_research"],
            }

        title = next(
            (
                str(source.get("title") or "").strip()
                for source in sources
                if str(source.get("title") or "").strip()
            ),
            paper_id,
        )
        evidence = "\n\n".join(
            str(source.get("document") or source.get("excerpt") or "").strip()
            for source in sources
        )
        paper = {
            "id": paper_id,
            "title": title,
            "translation_text": evidence,
            "structured_summary": "",
        }
        raw_result = self.answerer.answer(paper, state["query"])
        result = (
            raw_result
            if isinstance(raw_result, dict)
            else {"answer": str(raw_result)}
        )
        response = str(result.get("answer") or "").strip()
        if not response:
            raise NodeExecutionError("Deep Research 답변을 생성하지 못했습니다.")

        answer_sources = result.get("sources")
        if result.get("has_evidence") is False or (
            isinstance(answer_sources, list) and not answer_sources
        ):
            response = self._with_download_summary(
                state,
                self._insufficient_evidence_response(references),
            )
            return {
                "response": response,
                "deep_research_status": "insufficient_evidence",
                "deep_research_answer": response,
                "deep_research_sources": [],
                "deep_research_paper_id": paper_id,
                "node_history": ["deep_research"],
            }

        response = self._with_download_summary(state, response)

        return {
            "response": response,
            "deep_research_status": "success",
            "deep_research_answer": response,
            "deep_research_sources": sources,
            "deep_research_paper_id": paper_id,
            "node_history": ["deep_research"],
        }
