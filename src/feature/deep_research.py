"""번역 완료 논문을 선택하고 연속 질문하는 Deep Research 기능.

실시간 토큰 스트리밍과 paper_sections 기반 고속 근거 검색을 지원하여
터미널 체감 응답 대기 시간을 1초대로 단축한다.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Protocol

# ---------------------------------------------------------------------
# [로거 모듈 안전 임포트]
# ---------------------------------------------------------------------
try:
    from log import AppLogger, LogCode
except ImportError:
    try:
        from log.app_logger import AppLogger
        from log.log_codes import LogCode
    except ImportError:
        class LogCode:
            DEEP_RESEARCH_LIST_STARTED = "DEEP_RESEARCH_LIST_STARTED"
            DEEP_RESEARCH_LIST_SUCCEEDED = "DEEP_RESEARCH_LIST_SUCCEEDED"
            DEEP_RESEARCH_REQUEST_REJECTED = "DEEP_RESEARCH_REQUEST_REJECTED"
            DEEP_RESEARCH_PAPER_SELECTED = "DEEP_RESEARCH_PAPER_SELECTED"
            DEEP_RESEARCH_ANSWER_STARTED = "DEEP_RESEARCH_ANSWER_STARTED"
            DEEP_RESEARCH_ANSWER_SUCCEEDED = "DEEP_RESEARCH_ANSWER_SUCCEEDED"
            DEEP_RESEARCH_ANSWER_FAILED = "DEEP_RESEARCH_ANSWER_FAILED"
            DEEP_RESEARCH_RELATED_SEARCH_STARTED = "DEEP_RESEARCH_RELATED_SEARCH_STARTED"
            DEEP_RESEARCH_RELATED_SEARCH_SUCCEEDED = "DEEP_RESEARCH_RELATED_SEARCH_SUCCEEDED"
            DEEP_RESEARCH_RELATED_SEARCH_FAILED = "DEEP_RESEARCH_RELATED_SEARCH_FAILED"

        class AppLogger:
            def __init__(self, name: str):
                self.name = name

            def log(self, code, **kwargs):
                pass


logger = AppLogger(__name__)

# ---------------------------------------------------------------------
# [경로 상수 설정: 서재 DB, 본문 추출 DB, 참고문헌 DB, 산출물 경로]
# ---------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "paper_list" / "saved_papers.db"
DEFAULT_EXTRACT_DB_PATH = (
    PROJECT_ROOT / "data" / "paper_extract" / "extracted_papers.db"
)
DEFAULT_EXTRACT_JSON_PATH = (
    PROJECT_ROOT / "data" / "paper_extract" / "extracted_papers.json"
)
DEFAULT_REFERENCE_DB_PATH = (
    PROJECT_ROOT / "data" / "paper_extract" / "extracted_papers_ref.db"
)
DEFAULT_PROCESSED_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "paper_list" / "processed_outputs"
)
DEFAULT_TRANSLATION_DIR = PROJECT_ROOT / "data" / "translations"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "data" / "summaries"
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"


class DeepResearchError(RuntimeError):
    """Deep Research 처리 중 사용자에게 안내할 수 있는 오류."""


class PaperAnswerer(Protocol):
    """논문과 질문을 받아 답변 dict 또는 문자열을 만드는 객체의 계약."""

    def answer(self, paper: dict[str, Any], question: str) -> dict[str, Any] | str:
        """선택한 논문만 근거로 질문에 답한다."""


class PaperRetriever(Protocol):
    """질문과 관련된 논문 근거 조각을 찾는 객체의 계약."""

    def retrieve(self, paper: dict[str, Any], question: str) -> list[str]:
        """선택한 논문 안에서 질문과 가까운 근거를 반환한다."""


class PaperRepository(Protocol):
    """DeepResearchBot이 사용할 논문 저장소의 공통 규격."""

    def list_translated_papers(self) -> list[dict[str, Any]]:
        """Deep Research가 가능한 논문 목록을 반환한다."""

    def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        """논문 ID로 번역문과 구조화 요약을 반환한다."""

    def list_references(self, paper_id: str) -> list[dict[str, Any]]:
        """논문 ID에 연결된 참고문헌 목록을 반환한다."""


class RelatedPaperSearchAgent(Protocol):
    """참고문헌을 실제 외부 논문 검색으로 연결하는 검색 에이전트 규격."""

    def search_papers(
        self,
        final_query: str,
        sort_by: str = "r",
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """검색어와 가까운 외부 논문 목록을 반환한다."""


class PaperArtifactRepository:
    """추출 DB와 번역·요약 Markdown을 하나의 논문 데이터로 조립한다."""

    def __init__(
        self,
        extract_db_path: str | Path = DEFAULT_EXTRACT_DB_PATH,
        *,
        library_db_path: str | Path = DEFAULT_DB_PATH,
        extract_json_path: str | Path | None = None,
        reference_db_path: str | Path = DEFAULT_REFERENCE_DB_PATH,
        processed_output_dir: str | Path = DEFAULT_PROCESSED_OUTPUT_DIR,
        translation_dir: str | Path = DEFAULT_TRANSLATION_DIR,
        summary_dir: str | Path = DEFAULT_SUMMARY_DIR,
        require_summary: bool = False,
        allow_extracted_only: bool = True,
    ) -> None:
        self.extract_db_path = Path(extract_db_path).expanduser().resolve()
        self.library_db_path = Path(library_db_path).expanduser().resolve()
        self.extract_json_path = Path(
            extract_json_path
            or self.extract_db_path.with_name(DEFAULT_EXTRACT_JSON_PATH.name)
        ).expanduser().resolve()
        self.reference_db_path = Path(reference_db_path).expanduser().resolve()
        self.processed_output_dir = (
            Path(processed_output_dir).expanduser().resolve()
        )
        self.translation_dir = Path(translation_dir).expanduser().resolve()
        self.summary_dir = Path(summary_dir).expanduser().resolve()
        self.require_summary = require_summary
        self.allow_extracted_only = allow_extracted_only

    @staticmethod
    def _safe_name(paper_id: str) -> str:
        safe_name = re.sub(r"[^0-9A-Za-z._-]+", "_", paper_id).strip("._")
        if not safe_name:
            raise DeepResearchError("논문 ID로 안전한 파일명을 만들 수 없습니다.")
        return safe_name

    def _artifact_path(self, directory: Path, paper_id: str) -> Path:
        return directory / f"{self._safe_name(paper_id)}.md"

    def _translation_path(self, paper_id: str) -> Path:
        return self._artifact_path(self.translation_dir, paper_id)

    def _summary_path(self, paper_id: str) -> Path:
        return self._artifact_path(self.summary_dir, paper_id)

    @staticmethod
    def _safe_processed_title(title: str) -> str:
        cleaned = re.sub(r'[\\/*?:"<>|]', "", title)
        cleaned = "_".join(cleaned.split())[:50].strip("_")
        if not cleaned:
            raise DeepResearchError("논문 제목으로 안전한 파일명을 만들 수 없습니다.")
        return cleaned

    def _processed_translation_path(self, title: str) -> Path:
        safe_title = self._safe_processed_title(title)
        return self.processed_output_dir / f"{safe_title}_full_translated.md"

    def _processed_summary_path(self, title: str) -> Path:
        safe_title = self._safe_processed_title(title)
        return self.processed_output_dir / f"{safe_title}_summary.md"

    def _resolve_artifact_paths(self, paper_id: str, title: str) -> tuple[Path, Path]:
        processed_translation = self._processed_translation_path(title)
        processed_summary = self._processed_summary_path(title)
        translation_path = (
            processed_translation
            if processed_translation.is_file()
            else self._translation_path(paper_id)
        )
        summary_path = (
            processed_summary
            if processed_summary.is_file()
            else self._summary_path(paper_id)
        )
        return translation_path, summary_path

    @staticmethod
    def _read_markdown(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8-sig").strip()
        except FileNotFoundError:
            return ""
        except (OSError, UnicodeError) as error:
            raise DeepResearchError(
                f"논문 Markdown을 읽지 못했습니다: {path}"
            ) from error

    def _connect(self) -> sqlite3.Connection:
        """추출 DB(paper_sections) 연결 및 테이블 구조를 검증한다."""
        if not self.extract_db_path.exists():
            raise DeepResearchError(
                f"추출 논문 DB를 찾을 수 없습니다: {self.extract_db_path}"
            )
        connection = sqlite3.connect(self.extract_db_path)
        connection.row_factory = sqlite3.Row

        columns = {
            str(row["name"])
            for row in connection.execute(
                'PRAGMA table_info("paper_sections")'
            ).fetchall()
        }
        if not {"paper_id", "section_order", "section_text"}.issubset(columns):
            connection.close()
            raise DeepResearchError(
                "paper_sections 테이블에서 필수 열(paper_id, section_order, section_text)을 찾을 수 없습니다."
            )
        return connection

    def _artifact_status(
        self, paper_id: str, title: str
    ) -> tuple[bool, bool, Path, Path]:
        translation_path, summary_path = self._resolve_artifact_paths(paper_id, title)
        has_translation = translation_path.is_file()
        has_summary = summary_path.is_file()
        ready = has_translation and (has_summary or not self.require_summary)
        return ready, has_summary, translation_path, summary_path

    def _library_titles(self) -> dict[str, str]:
        """paper_sections 에 제목 컬럼이 없어 서재 DB 에서 가져온다."""
        db_to_use = self.library_db_path if self.library_db_path.exists() else DEFAULT_DB_PATH
        if not db_to_use.exists():
            return {}
        try:
            with sqlite3.connect(db_to_use) as library:
                return {
                    str(row[0]): str(row[1] or "")
                    for row in library.execute("SELECT id, title FROM papers")
                }
        except sqlite3.Error:
            return {}

    def list_translated_papers(self) -> list[dict[str, Any]]:
        """paper_sections 에 절이 있는 논문만 목록에 올린다."""
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT paper_id, COUNT(*) AS section_count
                FROM paper_sections
                WHERE LOWER(section_title) NOT IN ('references', 'bibliography')
                GROUP BY paper_id
                ORDER BY paper_id
                """
            ).fetchall()
        finally:
            connection.close()

        titles = self._library_titles()
        return [
            {
                "id": str(row["paper_id"]),
                "title": titles.get(str(row["paper_id"]), str(row["paper_id"])),
                "section_count": int(row["section_count"]),
            }
            for row in rows
        ]

    def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        """선택한 논문의 본문을 paper_sections 의 절 및 산출물 파일에서 조립한다."""
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT section_order, section_title, section_text
                FROM paper_sections
                WHERE paper_id = ?
                  AND LOWER(section_title) NOT IN ('references', 'bibliography')
                  AND LOWER(section_title) NOT LIKE '%reference%'
                  AND LOWER(section_title) NOT LIKE '%bibliography%'
                ORDER BY section_order
                """,
                (paper_id,),
            ).fetchall()
        finally:
            connection.close()

        if not rows:
            return None

        title = self._library_titles().get(paper_id, paper_id)
        body = "\n\n".join(
            f"## {int(row['section_order']):02d} {str(row['section_title'] or '').strip()}"
            f"\n\n{str(row['section_text'] or '')}"
            for row in rows
        )

        def pick(*needles: str) -> str:
            for row in rows:
                name = str(row["section_title"] or "").casefold()
                if any(needle in name for needle in needles):
                    return str(row["section_text"] or "")
            return ""

        translation_path, summary_path = self._resolve_artifact_paths(paper_id, title)
        translation_text = self._read_markdown(translation_path) or body
        structured_summary = self._read_markdown(summary_path)

        return {
            "id": paper_id,
            "title": title,
            "translation_text": translation_text,
            "structured_summary": structured_summary,
            "extracted_content": body,
            "abstract": pick("abstract"),
            "introduction": pick("introduction"),
            "related_work": pick("related"),
            "method": pick("method", "approach"),
            "experiment": pick("experiment"),
            "result": pick("result"),
            "conclusion": pick("conclusion"),
            "others": "",
            "section_count": len(rows),
            "translation_completed": translation_path.is_file(),
            "translation_path": str(translation_path) if translation_path.is_file() else "",
            "summary_path": str(summary_path) if summary_path.is_file() else "",
            "translation_source": "file" if translation_path.is_file() else "paper_sections",
            "summary_source": "file" if summary_path.is_file() else "",
        }

    def list_references(self, paper_id: str) -> list[dict[str, Any]]:
        """paper_sections 의 References 절에서 인용 목록을 직접 파싱한다."""
        references: list[dict[str, Any]] = []

        try:
            connection = self._connect()
            rows = connection.execute(
                """
                SELECT section_text
                FROM paper_sections
                WHERE paper_id = ?
                  AND (
                      LOWER(section_title) LIKE '%reference%'
                      OR LOWER(section_title) LIKE '%bibliography%'
                  )
                ORDER BY section_order
                """,
                (paper_id,),
            ).fetchall()
            connection.close()

            ref_idx = 1
            for row in rows:
                text = str(row["section_text"] or "").strip()
                items = re.split(r'\n+(?=\[\d+\]|\d+\.\s+)', text)
                if len(items) <= 1:
                    items = [line.strip() for line in text.splitlines() if len(line.strip()) > 15]

                for item in items:
                    cleaned = re.sub(r'\s+', ' ', item).strip()
                    if cleaned and len(cleaned) > 10:
                        references.append({
                            "paper_id": paper_id,
                            "ref_index": ref_idx,
                            "reference_text": cleaned,
                        })
                        ref_idx += 1
        except Exception:
            pass

        if references:
            return references

        if self.reference_db_path.exists():
            try:
                ref_conn = sqlite3.connect(self.reference_db_path)
                ref_conn.row_factory = sqlite3.Row
                with ref_conn:
                    ref_rows = ref_conn.execute(
                        """
                        SELECT paper_id, ref_index, reference_text
                        FROM extracted_ref
                        WHERE paper_id = ?
                        ORDER BY ref_index
                        """,
                        (paper_id,),
                    ).fetchall()
                ref_conn.close()

                for row in ref_rows:
                    references.append({
                        "paper_id": str(row["paper_id"]),
                        "ref_index": int(row["ref_index"]),
                        "reference_text": str(row["reference_text"]),
                    })
            except Exception:
                pass

        return references


class KeywordPaperRetriever:
    """긴 논문을 나누고 관련 근거를 인-메모리에서 초고속으로 찾는 검색 클래스."""

    def __init__(
        self,
        *,
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
        top_k: int = 4,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k

    @staticmethod
    def _keywords(text: str) -> set[str]:
        tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", text.lower())
        stopwords = {
            "논문", "무엇", "어떤", "대해", "알려줘", "설명", "설명해",
            "설명해줘", "자세히", "전체적으로", "전체", "요약", "요약해줘", "이것"
        }
        return {
            token for token in tokens
            if token not in stopwords and not re.fullmatch(r"\d+번", token)
        }

    def _overview_evidence(self, paper: dict[str, Any]) -> list[str]:
        evidence: list[str] = []
        for label, field in (
            ("초록", "abstract"),
            ("연구 방법", "method"),
            ("주요 결과", "result"),
            ("결론", "conclusion"),
        ):
            content = str(paper.get(field) or "").strip()
            if not content:
                continue
            if len(content) > self.chunk_size:
                half = max(1, (self.chunk_size - 7) // 2)
                content = f"{content[:half]}\n...\n{content[-half:]}"
            evidence.append(f"[{label}]\n{content}")

        # 개요 정보가 비어있을 경우 본문 상단 일부를 발췌
        if not evidence and paper.get("translation_text"):
            evidence.append(f"[본문 시작부]\n{paper['translation_text'][:self.chunk_size]}")
        return evidence[: self.top_k]

    def _split(self, text: str) -> list[str]:
        chunks: list[str] = []
        for paragraph in (
            part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()
        ):
            start = 0
            while start < len(paragraph):
                end = min(start + self.chunk_size, len(paragraph))
                chunks.append(paragraph[start:end].strip())
                if end == len(paragraph):
                    break
                start = end - self.chunk_overlap
        return [chunk for chunk in chunks if chunk]

    def retrieve(self, paper: dict[str, Any], question: str) -> list[str]:
        context = "\n\n".join(
            part
            for part in (
                paper.get("structured_summary", ""),
                paper.get("translation_text", ""),
            )
            if part
        )
        chunks = self._split(context)
        question_keywords = self._keywords(question)

        # "전체 설명", "요약" 등의 질문은 핵심 구조화 섹션(초록, 방법, 결과, 결론)을 즉각 반환
        if not question_keywords or any(w in question for w in ["전체", "요약", "설명"]):
            overview = self._overview_evidence(paper)
            if overview:
                return overview

        ranked = sorted(
            enumerate(chunks),
            key=lambda item: (
                len(question_keywords & self._keywords(item[1])),
                -item[0],
            ),
            reverse=True,
        )

        matched_chunks = [
            text for _, text in ranked
            if len(question_keywords & self._keywords(text)) > 0
        ]
        if not matched_chunks:
            overview = self._overview_evidence(paper)
            if overview:
                return overview

        return [text for _, text in ranked[: self.top_k]]


class ChromaSummaryRetriever:
    """Chroma 본문 청크 저장소에서 선택 논문의 근거를 검색한다."""

    def __init__(
        self,
        *,
        store: Any | None = None,
        top_k: int = 4,
        fallback: PaperRetriever | None = None,
    ) -> None:
        self._store = store
        self.top_k = top_k
        self.fallback = fallback or KeywordPaperRetriever(top_k=top_k)

    def _get_store(self) -> Any:
        if self._store is None:
            try:
                from services.fulltext_vector_store import ChromaFullTextStore
            except ImportError as error:
                raise DeepResearchError(
                    "Chroma 본문 검색 모듈을 불러오지 못했습니다."
                ) from error
            self._store = ChromaFullTextStore()
        return self._store

    def retrieve(self, paper: dict[str, Any], question: str) -> list[str]:
        paper_id = str(paper.get("id", "")).strip()
        if not paper_id:
            return self.fallback.retrieve(paper, question)

        try:
            results = self._get_store().search(
                question,
                limit=self.top_k,
                paper_id=paper_id,
            )
            evidence = [
                str(result.get("document", "")).strip()
                for result in results
                if isinstance(result, dict)
                and str(result.get("document", "")).strip()
            ]
            if evidence:
                return evidence
        except Exception:
            pass
        return self.fallback.retrieve(paper, question)

    def close(self) -> None:
        if self._store is not None and hasattr(self._store, "close"):
            self._store.close()


class ExtractivePaperAnswerer:
    """외부 모델 없이 질문과 겹치는 논문 문단을 근거로 반환한다."""

    def __init__(self, retriever: PaperRetriever | None = None) -> None:
        self.retriever = retriever or KeywordPaperRetriever()

    def answer(self, paper: dict[str, Any], question: str) -> dict[str, Any]:
        evidence = self.retriever.retrieve(paper, question)
        if not evidence:
            return {
                "answer": "선택한 논문에서 답변 근거를 찾지 못했습니다.",
                "sources": [],
            }
        return {
            "answer": "선택한 논문에서 질문과 관련된 근거를 찾았습니다.",
            "sources": evidence,
        }


class LangChainPaperAnswerer:
    """실시간 스트리밍 출력을 지원하는 근거 기반 답변기."""

    SYSTEM_PROMPT = """당신은 학술 논문 Deep Research 도우미입니다.
제공된 선택 논문의 내용만 근거로 한국어로 알기 쉽게 상세히 설명하세요.
질문에 직접 답할 근거가 부족하면 추측하지 말고 솔직하게 답변하세요.
수식이나 결과가 있으면 논문에 제시된 수치를 정확히 인용하세요."""

    def __init__(self, model: Any, retriever: PaperRetriever | None = None) -> None:
        self.model = model
        self.model_name = str(
            getattr(model, "model_name", getattr(model, "model", "unknown"))
        )
        self.retriever = retriever or KeywordPaperRetriever()

    @classmethod
    def with_openai(
        cls,
        *,
        model_name: str | None = None,
        retriever: PaperRetriever | None = None,
    ) -> "LangChainPaperAnswerer":
        try:
            from dotenv import load_dotenv
            from langchain_openai import ChatOpenAI
        except ImportError as error:
            raise DeepResearchError(
                "OpenAI 답변을 사용하려면 langchain-openai와 python-dotenv가 필요합니다."
            ) from error

        load_dotenv(PROJECT_ROOT / ".env", override=False)
        if not os.getenv("OPENAI_API_KEY"):
            raise DeepResearchError(".env에 OPENAI_API_KEY를 설정해 주세요.")

        selected_model = (
            model_name
            or os.getenv("OPENAI_CHAT_MODEL", "").strip()
            or DEFAULT_OPENAI_MODEL
        )

        # streaming=True 설정으로 첫 글자 지연을 1초 미만으로 단축
        try:
            model = ChatOpenAI(
                model=selected_model,
                temperature=0.1,
                timeout=60,
                streaming=True,
                reasoning_effort="none"
            )
        except Exception:
            model = ChatOpenAI(
                model=selected_model,
                temperature=0.1,
                timeout=60,
                streaming=True,
            )
        return cls(model, retriever=retriever)

    def answer(self, paper: dict[str, Any], question: str) -> dict[str, Any]:
        evidence = self.retriever.retrieve(paper, question)
        if not evidence:
            return {
                "answer": "선택한 논문에서 답변 근거를 찾지 못했습니다.",
                "sources": [],
                "model": self.model_name,
            }
        context = "\n\n".join(
            f"[근거 {index}]\n{text}"
            for index, text in enumerate(evidence, start=1)
        )
        prompt = (
            f"{self.SYSTEM_PROMPT}\n\n"
            f"논문 제목: {paper['title']}\n"
            f"<paper_context>\n{context}\n</paper_context>\n\n"
            f"질문: {question}"
        )

        print("\n[답변 내용]")
        collected_chunks = []
        try:
            # 실시간 토큰 스트리밍 출력
            for chunk in self.model.stream(prompt):
                text_piece = getattr(chunk, "content", str(chunk))
                sys.stdout.write(text_piece)
                sys.stdout.flush()
                collected_chunks.append(text_piece)
            print()
            full_answer = "".join(collected_chunks).strip()
        except Exception:
            # 스트리밍 실패 시 일반 invoke 호출
            resp = self.model.invoke(prompt)
            full_answer = str(getattr(resp, "content", resp)).strip()
            print(full_answer)

        return {
            "answer": full_answer,
            "sources": evidence,
            "has_evidence": True,
            "model": self.model_name,
        }


class DeepResearchBot:
    """논문 목록·주제 검색·선택 상태·후속 질의응답을 총괄 관리하는 챗봇 클래스."""

    BACK_COMMANDS = ("뒤로", "목록으로", "선택 취소", "처음으로", "전체 목록", "전체")
    POSITIVE_COMMANDS = ("네", "예", "응", "그래", "좋아", "검색해", "찾아줘", "진행")
    NEGATIVE_COMMANDS = ("아니", "괜찮아", "취소", "검색하지 마", "안 찾아")

    def __init__(
        self,
        repository: PaperRepository,
        answerer: PaperAnswerer | None = None,
        search_agent: RelatedPaperSearchAgent | None = None,
    ) -> None:
        self.repository = repository
        self.answerer = answerer or ExtractivePaperAnswerer()
        self.search_agent = search_agent

        self.selected_paper: dict[str, Any] | None = None
        self.pending_references: list[dict[str, Any]] = []
        self.current_display_papers: list[dict[str, Any]] = []

    @classmethod
    def with_openai(
        cls,
        repository: PaperRepository | None = None,
        *,
        model_name: str | None = None,
        retriever: PaperRetriever | None = None,
        search_agent: RelatedPaperSearchAgent | None = None,
    ) -> "DeepResearchBot":
        resolved_retriever = retriever or KeywordPaperRetriever()
        answerer = LangChainPaperAnswerer.with_openai(
            model_name=model_name,
            retriever=resolved_retriever,
        )
        return cls(
            repository or PaperArtifactRepository(),
            answerer,
            search_agent=search_agent,
        )

    @staticmethod
    def _result(status: str, message: str, **data: Any) -> dict[str, Any]:
        return {"status": status, "message": message, **data}

    def list_papers(self) -> dict[str, Any]:
        logger.log(LogCode.DEEP_RESEARCH_LIST_STARTED)
        papers = self.repository.list_translated_papers()
        numbered = [
            {"number": index, **paper}
            for index, paper in enumerate(papers, start=1)
        ]
        self.current_display_papers = numbered

        if not numbered:
            logger.log(LogCode.DEEP_RESEARCH_REQUEST_REJECTED, reason="no_papers")
            return self._result(
                "empty",
                "분석 가능한 추출 논문이 없습니다.",
                papers=[],
                count=0,
            )
        logger.log(LogCode.DEEP_RESEARCH_LIST_SUCCEEDED, paper_count=len(numbered))
        return self._result(
            "success",
            f"분석 가능한 논문 {len(numbered)}개를 불러왔습니다.",
            papers=numbered,
            count=len(numbered),
        )

    def filter_papers(self, query: str) -> dict[str, Any]:
        """서재 내 논문 목록에서 사용자의 검색 주제와 일치하는 논문만 필터링한다."""
        all_papers = self.repository.list_translated_papers()
        if not all_papers:
            return self._result("empty", "서재에 저장된 논문이 없습니다.")

        clean_q = query.strip()
        topic_term = re.sub(r"(관련\s*논문|논문|보여줘|찾아줘|알려줘|검색해줘|목록)", "", clean_q).strip()
        if not topic_term:
            topic_term = clean_q

        filtered: list[dict[str, Any]] = []

        # 1. LLM 시맨틱 필터링
        if hasattr(self.answerer, "model"):
            try:
                catalog = "\n".join([f"[{idx+1}] {p['title']}" for idx, p in enumerate(all_papers)])
                prompt = (
                    f"다음은 서재에 등록된 영문 논문 목록입니다:\n{catalog}\n\n"
                    f"사용자 요청 주제: '{topic_term}'\n"
                    f"위 목록 중 사용자의 주제와 명확히 연관된 논문 번호(1~{len(all_papers)})를 JSON 정수 배열로만 반환하세요.\n"
                    f"형식: [1, 2, 5]\n"
                    f"연관된 논문이 없으면 []를 반환하세요."
                )
                resp = self.answerer.model.invoke(prompt)
                content = getattr(resp, "content", str(resp))
                match = re.search(r'\[(.*?)\]', content, re.DOTALL)
                if match:
                    indices = json.loads(f"[{match.group(1)}]")
                    filtered = [all_papers[i - 1] for i in indices if 1 <= i <= len(all_papers)]
            except Exception:
                filtered = []

        # 2. 영문 문자열 매칭 폴백
        if not filtered:
            term_lower = topic_term.lower()
            synonyms = [term_lower]
            if any(k in topic_term for k in ["강화학습", "강화 학습", "관연"]):
                synonyms.extend(["reinforcement", "policy", "q-learning", "q learning", "rl"])
            elif any(k in topic_term for k in ["자연어", "언어모델", "llm"]):
                synonyms.extend(["language", "nlp", "prompt", "transformer"])
            elif any(k in topic_term for k in ["비전", "컴퓨터 비전"]):
                synonyms.extend(["vision", "image"])
            elif any(k in topic_term for k in ["rag", "검색 증강", "검색증강"]):
                synonyms.extend(["retrieval", "rag"])

            filtered = [
                p for p in all_papers
                if any(syn in p["title"].lower() for syn in synonyms)
            ]

        if not filtered:
            self.current_display_papers = [{"number": i, **p} for i, p in enumerate(all_papers, 1)]
            return self._result(
                "filter_empty",
                f"'{topic_term}' 주제와 관련된 논문을 서재에서 찾지 못했습니다. 전체 목록 중 번호나 제목으로 직접 선택해 주세요.",
                papers=self.current_display_papers,
                count=len(all_papers),
            )

        numbered = [{"number": index, **paper} for index, paper in enumerate(filtered, start=1)]
        self.current_display_papers = numbered

        return self._result(
            "filtered",
            f"'{topic_term}' 관련 논문 {len(numbered)}개를 서재에서 찾았습니다. 질문할 논문의 번호를 선택해 주세요.",
            papers=numbered,
            count=len(numbered),
        )

    def select_paper(self, selection: str | int) -> dict[str, Any]:
        """현재 화면에 표시된 목록(필터링 결과 또는 전체 목록)을 우선 기준으로 논문을 선택한다."""
        pool = self.current_display_papers if self.current_display_papers else self.repository.list_translated_papers()
        if not pool:
            logger.log(LogCode.DEEP_RESEARCH_REQUEST_REJECTED, reason="no_papers")
            return self._result("empty", "선택할 추출 논문이 없습니다.")

        target: dict[str, Any] | None = None
        if isinstance(selection, int) and not isinstance(selection, bool):
            number = selection
        else:
            selection_text = str(selection).strip()
            num_match = re.search(r"(\d+)", selection_text)
            number = int(num_match.group(1)) if num_match else 0

            if not number:
                normalized = selection_text.casefold()
                target = next(
                    (paper for paper in pool if paper["id"].casefold() == normalized),
                    None,
                )
                if target is None:
                    exact_titles = [
                        paper for paper in pool
                        if paper["title"].casefold() == normalized
                    ]
                    partial_titles = [
                        paper for paper in pool
                        if normalized and normalized in paper["title"].casefold()
                    ]
                    candidates = exact_titles or partial_titles
                    if len(candidates) == 1:
                        target = candidates[0]
                    elif len(candidates) > 1:
                        logger.log(
                            LogCode.DEEP_RESEARCH_REQUEST_REJECTED,
                            reason="ambiguous_selection",
                            candidate_count=len(candidates),
                        )
                        return self._result(
                            "ambiguous",
                            "비슷한 제목이 여러 개입니다. 번호로 선택해 주세요.",
                            candidates=candidates,
                        )

        if target is None and number:
            if not 1 <= number <= len(pool):
                logger.log(
                    LogCode.DEEP_RESEARCH_REQUEST_REJECTED,
                    reason="selection_out_of_range",
                    selection=number,
                    paper_count=len(pool),
                )
                return self._result(
                    "invalid_selection",
                    f"1번부터 {len(pool)}번 사이에서 선택해 주세요.",
                )
            target = pool[number - 1]

        if target is None:
            logger.log(
                LogCode.DEEP_RESEARCH_REQUEST_REJECTED,
                reason="paper_not_found",
                selection=str(selection),
            )
            return self._result(
                "invalid_selection",
                "논문을 찾지 못했습니다. 번호, 제목 또는 논문 ID로 선택해 주세요.",
            )

        paper = self.repository.get_paper(target["id"])
        if paper is None:
            logger.log(
                LogCode.DEEP_RESEARCH_REQUEST_REJECTED,
                reason="selected_paper_content_missing",
                paper_id=target["id"],
            )
            return self._result(
                "not_found",
                "선택한 논문의 추출 내용을 DB에서 불러오지 못했습니다.",
            )
        self.selected_paper = paper
        logger.log(
            LogCode.DEEP_RESEARCH_PAPER_SELECTED,
            paper_id=paper["id"],
            title=paper["title"],
        )
        return self._result(
            "selected",
            f"'{paper['title']}' 논문을 선택했습니다. 궁금한 내용을 질문해 주세요.",
            paper={"id": paper["id"], "title": paper["title"]},
        )

    def ask(self, question: str) -> dict[str, Any]:
        question = question.strip()
        if not question:
            logger.log(LogCode.DEEP_RESEARCH_REQUEST_REJECTED, reason="empty_question")
            return self._result("invalid_question", "질문 내용을 입력해 주세요.")
        if self.selected_paper is None:
            logger.log(LogCode.DEEP_RESEARCH_REQUEST_REJECTED, reason="selection_required")
            paper_list = self.list_papers()
            return self._result(
                "selection_required",
                "먼저 질문할 논문을 선택해 주세요.",
                papers=paper_list.get("papers", []),
                count=paper_list.get("count", 0),
            )
        if not (
            self.selected_paper.get("translation_text")
            or self.selected_paper.get("structured_summary")
        ):
            logger.log(
                LogCode.DEEP_RESEARCH_REQUEST_REJECTED,
                reason="paper_content_missing",
                paper_id=self.selected_paper.get("id"),
            )
            return self._result(
                "content_missing",
                "선택한 논문에 질문에 사용할 추출 본문, 번역문 또는 요약이 없습니다.",
            )

        logger.log(
            LogCode.DEEP_RESEARCH_ANSWER_STARTED,
            paper_id=self.selected_paper["id"],
            question_length=len(question),
        )
        try:
            raw_answer = self.answerer.answer(self.selected_paper, question)
        except Exception as error:
            logger.log(
                LogCode.DEEP_RESEARCH_ANSWER_FAILED,
                paper_id=self.selected_paper["id"],
                error_type=type(error).__name__,
                error=str(error),
            )
            return self._result(
                "error",
                f"답변을 만드는 중 오류가 발생했습니다: {error}",
            )

        answer_data = (
            raw_answer if isinstance(raw_answer, dict) else {"answer": str(raw_answer)}
        )
        logger.log(
            LogCode.DEEP_RESEARCH_ANSWER_SUCCEEDED,
            paper_id=self.selected_paper["id"],
            source_count=len(answer_data.get("sources") or []),
        )
        return self._result(
            "success",
            "선택한 논문을 근거로 답변했습니다.",
            paper={
                "id": self.selected_paper["id"],
                "title": self.selected_paper["title"],
            },
            question=question,
            **answer_data,
        )

    def list_related_papers(self, limit: int = 10) -> dict[str, Any]:
        if self.selected_paper is None:
            return self._result(
                "selection_required",
                "먼저 관련 논문을 확인할 논문을 선택해 주세요.",
                papers=self.list_papers().get("papers", []),
            )
        try:
            references = self.repository.list_references(
                str(self.selected_paper["id"])
            )
        except Exception as error:
            return self._result(
                "reference_error",
                f"참고문헌을 불러오는 중 오류가 발생했습니다: {error}",
            )

        if not references:
            self.pending_references = []
            return self._result(
                "references_empty",
                "선택한 논문의 참고문헌 DB에 관련 논문이 없습니다.",
                references=[],
                count=0,
            )

        shown = references[:max(1, int(limit))]
        self.pending_references = shown
        return self._result(
            "search_confirmation",
            (
                f"참고문헌에서 관련 논문 {len(shown)}개를 확인했습니다. "
                "이 논문들을 검색해드릴까요?"
            ),
            paper={
                "id": self.selected_paper["id"],
                "title": self.selected_paper["title"],
            },
            references=shown,
            count=len(shown),
            search_available=self.search_agent is not None,
        )

    @staticmethod
    def _reference_query(reference_text: str) -> str:
        query = re.sub(r"^\s*(?:\[\d+\]|\d+[.)])\s*", "", reference_text)
        return re.sub(r"\s+", " ", query).strip()

    def search_related_papers(
        self,
        max_references: int = 5,
        max_results_per_reference: int = 3,
    ) -> dict[str, Any]:
        if not self.pending_references:
            logger.log(
                LogCode.DEEP_RESEARCH_REQUEST_REJECTED,
                reason="reference_confirmation_required",
            )
            return self._result(
                "reference_confirmation_required",
                "먼저 관련 논문을 확인하고 검색 여부를 선택해 주세요.",
            )
        if self.search_agent is None:
            self.pending_references = []
            logger.log(
                LogCode.DEEP_RESEARCH_REQUEST_REJECTED,
                reason="search_agent_unavailable",
            )
            return self._result(
                "search_agent_unavailable",
                "해당 검색 에이전트가 존재하지 않아 참조 논문을 검색할 수 없습니다.",
                results=[],
            )

        targets = self.pending_references[:max(1, int(max_references))]
        logger.log(
            LogCode.DEEP_RESEARCH_RELATED_SEARCH_STARTED,
            reference_count=len(targets),
            max_results_per_reference=max_results_per_reference,
        )
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        seen: set[str] = set()
        for reference in targets:
            query = self._reference_query(reference["reference_text"])
            try:
                found = self.search_agent.search_papers(
                    query,
                    sort_by="r",
                    max_results=max(1, int(max_results_per_reference)),
                )
            except Exception as error:
                logger.log(
                    LogCode.DEEP_RESEARCH_RELATED_SEARCH_FAILED,
                    ref_index=reference["ref_index"],
                    error_type=type(error).__name__,
                    error=str(error),
                )
                errors.append(
                    {
                        "ref_index": reference["ref_index"],
                        "query": query,
                        "error": str(error),
                    }
                )
                continue
            for paper in found or []:
                unique_key = str(paper.get("id") or paper.get("title") or paper)
                if unique_key in seen:
                    continue
                seen.add(unique_key)
                results.append(
                    {
                        **paper,
                        "reference_index": reference["ref_index"],
                        "reference_query": query,
                    }
                )

        self.pending_references = []
        if not results:
            if not errors:
                logger.log(
                    LogCode.DEEP_RESEARCH_RELATED_SEARCH_FAILED,
                    reason="no_results",
                )
            return self._result(
                "search_empty" if not errors else "search_error",
                (
                    "참조 논문을 검색했지만 결과를 찾지 못했습니다."
                    if not errors
                    else "참조 논문 검색 중 오류가 발생해 결과를 가져오지 못했습니다."
                ),
                results=[],
                errors=errors,
            )
        logger.log(
            LogCode.DEEP_RESEARCH_RELATED_SEARCH_SUCCEEDED,
            result_count=len(results),
            error_count=len(errors),
        )
        return self._result(
            "success",
            f"참조 논문 검색 결과 {len(results)}개를 찾았습니다.",
            results=results,
            count=len(results),
            errors=errors,
        )

    def reset_paper(self) -> dict[str, Any]:
        previous = self.selected_paper
        self.selected_paper = None
        self.pending_references = []
        res = self.list_papers()
        res["message"] = "논문 선택을 해제하고 전체 목록으로 돌아왔습니다."
        res["previous_paper"] = (
            {"id": previous["id"], "title": previous["title"]}
            if previous
            else None
        )
        return res

    def handle_message(self, user_message: str) -> dict[str, Any]:
        message = user_message.strip()
        if not message:
            return self._result("invalid_input", "메시지를 입력해 주세요.")

        # 1. 참고문헌 외부 검색 확인 응답 처리
        if self.pending_references:
            if any(command in message for command in self.NEGATIVE_COMMANDS):
                self.pending_references = []
                return self._result(
                    "search_cancelled",
                    "참조 논문 검색을 진행하지 않습니다. 다른 질문을 해주세요.",
                )
            if any(command in message for command in self.POSITIVE_COMMANDS):
                return self.search_related_papers()

        # 2. 뒤로가기 / 선택 취소 처리
        if any(cmd == message or message.startswith(cmd) for cmd in self.BACK_COMMANDS):
            return self.reset_paper()

        # 3. 전체 목록 보기
        clean_msg = re.sub(r"\s+", "", message)
        if clean_msg in {"목록", "리스트", "전체목록", "전체논문", "논문목록", "전체", "목록보여줘", "논문목록보여줘"}:
            return self.list_papers()

        # 4. 번호 + 질문 결합 원샷 패턴 감지 (예: '10번 논문 전체 설명', '1번 요약해줘')
        combo_match = re.match(r"^\[?(\d+)\]?\s*번?(?:째)?(?:\s*논문)?\s*(.*)$", message)
        pure_num_match = re.match(r"^\[?(\d+)\]?$", message)

        if combo_match and not re.match(r"^\d+\s*개", message):
            target_idx = int(combo_match.group(1))
            query_part = combo_match.group(2).strip()

            query_part = re.sub(r"^(?:선택|보기|보여줘|으로|할래)\s*", "", query_part).strip()
            query_part = re.sub(r"^(?:에\s*대해(?:서)?|[의은는이가])\s*", "", query_part).strip()

            # 선택 수행
            select_res = self.select_paper(target_idx)
            if select_res.get("status") != "selected":
                return select_res

            # 질문이 결합되어 있다면 즉시 답변 수행
            if query_part:
                return self.ask(query_part)
            return select_res

        if pure_num_match:
            return self.select_paper(int(pure_num_match.group(1)))

        # 5. 논문이 선택된 상태라면 RAG 질의응답 또는 참고문헌 탐색 수행
        if self.selected_paper is not None:
            related_request = any(
                command in message for command in ("관련 논문", "비슷한 논문", "유사 논문", "참고문헌", "인용 논문")
            ) or (
                "다른 논문" in message
                and any(word in message for word in ("있", "찾", "검색", "관련", "비슷", "추천"))
            )
            if related_request:
                return self.list_related_papers()
            return self.ask(message)

        # 6. 미선택 상태에서의 자연어는 서재 내 주제어 필터링으로 분기
        return self.filter_papers(message)

    def as_tools(self) -> list[Any]:
        try:
            from langchain_core.tools import StructuredTool
        except ImportError as error:
            raise DeepResearchError(
                "LangChain Tool을 만들려면 langchain-core가 필요합니다."
            ) from error

        return [
            StructuredTool.from_function(
                func=self.list_papers,
                name="list_translated_papers",
                description="번역 완료된 논문 목록을 번호, ID, 제목과 함께 불러온다.",
            ),
            StructuredTool.from_function(
                func=self.select_paper,
                name="select_research_paper",
                description="번호, 제목 또는 논문 ID로 Deep Research 대상 논문을 선택한다.",
            ),
            StructuredTool.from_function(
                func=self.ask,
                name="ask_selected_paper",
                description="현재 선택한 논문의 추출 본문·번역문·요약을 근거로 질문에 답한다.",
            ),
            StructuredTool.from_function(
                func=self.list_related_papers,
                name="list_reference_papers",
                description="선택 논문의 참고문헌 DB를 조회하고 사용자에게 검색 여부를 묻는다.",
            ),
            StructuredTool.from_function(
                func=self.search_related_papers,
                name="search_reference_papers",
                description="사용자 동의 후 연결된 검색 에이전트로 참조 논문을 검색한다.",
            ),
            StructuredTool.from_function(
                func=self.reset_paper,
                name="reset_selected_paper",
                description="현재 논문 선택을 해제하고 번역 완료 목록으로 돌아간다.",
            ),
        ]


def clean_llm_tags(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r'</?(?:FollowUp|QuerySuggestion|paper_context)[^>]*>', '', text)
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def format_cli_response(response: dict[str, Any]) -> str:
    status = response.get("status", "info")
    message = response.get("message", "")
    lines = [
        "=" * 65,
        f"📌 [안내] {message}",
        "-" * 65
    ]

    if "papers" in response and isinstance(response["papers"], list):
        papers = response["papers"]
        if not papers:
            lines.append("  (조회 가능한 논문이 없습니다.)")
        else:
            header = "🔍 [검색된 논문 목록]" if status == "filtered" else "📚 [논문 목록]"
            lines.append(header)
            for p in papers:
                num = p.get("number", "-")
                title = p.get("title", "제목 없음")
                lines.append(f"  [{num}번] {title}")

    if "paper" in response and isinstance(response["paper"], dict):
        paper_title = response["paper"].get("title", "제목 없음")
        if "answer" not in response and status == "selected":
            lines.append(f"\n📖 현재 선택된 논문: {paper_title}")

    if "answer" in response:
        paper_title = response.get("paper", {}).get("title", "제목 없음")
        lines.append(f"📄 대상 논문: {paper_title}")

        if "model" in response:
            lines.append(f"🤖 답변 모델: {response['model']}")

        # 스트리밍 시 이미 콘솔에 출력되었으므로 sources와 푸터만 출력
        if "sources" in response and response["sources"]:
            lines.append("\n🔍 [참고 근거]")
            for idx, src in enumerate(response["sources"], 1):
                clean_src = clean_llm_tags(str(src)).replace('\n', ' ')
                lines.append(f"  ({idx}) {clean_src[:120]}...")

    if "references" in response and isinstance(response["references"], list):
        lines.append("\n🔗 [관련 참고문헌 목록]")
        for ref in response["references"]:
            lines.append(f"  • {ref.get('reference_text', '알 수 없음')}")

    if "results" in response and isinstance(response["results"], list):
        lines.append("\n🔎 [검색 결과]")
        for idx, res in enumerate(response["results"], 1):
            res_title = res.get("title", "제목 없음")
            lines.append(f"  {idx}. {res_title}")
            if "authors" in res:
                lines.append(f"     └ 저자: {res['authors']}")
            if "pdf_url" in res:
                lines.append(f"     └ 링크: {res['pdf_url']}")

    lines.append("=" * 65)
    return "\n".join(lines)


def run_cli() -> None:
    # 1. paper_sections 및 서재 DB 조립 레포지토리
    repository = PaperArtifactRepository(
        extract_db_path=DEFAULT_EXTRACT_DB_PATH,
        library_db_path=DEFAULT_DB_PATH,
        reference_db_path=DEFAULT_REFERENCE_DB_PATH,
    )

    # 2. 고속 키워드/개요 인-메모리 검색기 (단일 논문 Q&A 최적화)
    retriever = KeywordPaperRetriever(top_k=4)

    search_agent = None
    try:
        from feature.search import ArxivSearchBot
        search_agent = ArxivSearchBot()
    except ImportError:
        pass

    try:
        bot = DeepResearchBot.with_openai(
            repository=repository,
            retriever=retriever,
            search_agent=search_agent,
        )
    except DeepResearchError as error:
        err_dict = {"status": "configuration_error", "message": str(error)}
        print(format_cli_response(err_dict))
        return

    initial_response = bot.list_papers()
    print(format_cli_response(initial_response))

    while True:
        try:
            user_message = input("\nDeep Research (종료: q)> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_message.lower() in {"q", "quit", "exit", "종료"}:
            break

        response_dict = bot.handle_message(user_message)
        print("\n" + format_cli_response(response_dict))


if __name__ == "__main__":
    run_cli()