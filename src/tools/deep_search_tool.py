"""로컬 논문 목록, 상세 정보, 본문 근거를 조회하는 검색 도구."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools import PROJECT_DIR


BASE_DIR = PROJECT_DIR / "data" / "paper_extract"
JSON_LIST_PATH = BASE_DIR / "extracted_papers.json"
DB_PATH = BASE_DIR / "extracted_papers.db"
REF_DB_PATH = BASE_DIR / "extracted_papers_ref.db"
PAPER_CANDIDATE_LIMIT = 5


class DeepSearchError(RuntimeError):
    """로컬 논문 검색을 완료하지 못했을 때 발생한다."""


class SearchPaperListInput(BaseModel):
    keyword: str = Field(
        default="",
        description=(
            "검색할 키워드. 특정 논문을 찾을 때 사용하며, 전체 리스트를 원할 "
            "경우 반드시 빈 문자열('')을 입력하세요."
        ),
    )


class GetPaperDetailsInput(BaseModel):
    paper_id: str = Field(..., description="상세 내용을 조회할 논문의 고유 ID")


class SearchPaperPassagesInput(BaseModel):
    question: str = Field(..., min_length=1, description="논문 본문에서 근거를 찾을 질문")
    paper_id: str = Field(
        ...,
        min_length=1,
        description="본문 검색 범위를 제한할 단일 논문 ID",
    )
    limit: int = Field(default=5, ge=1, le=10, description="반환할 근거 청크 수")


class DeepSearch:
    """로컬 논문 카탈로그와 본문 Vector DB를 조회한다.

    파일·DB 경로와 외부 의존성을 생성자에서 주입할 수 있으므로 LangGraph
    노드와 통합 테스트에서 같은 검색 계약을 재사용할 수 있다. 무거운 임베딩과
    Chroma 객체는 실제 검색 시점까지 생성하지 않는다.
    """

    def __init__(
        self,
        *,
        json_list_path: str | Path = JSON_LIST_PATH,
        db_path: str | Path = DB_PATH,
        reference_db_path: str | Path = REF_DB_PATH,
        embeddings_factory: Callable[[], Any] | None = None,
        fulltext_store_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.json_list_path = Path(json_list_path)
        self.db_path = Path(db_path)
        self.reference_db_path = Path(reference_db_path)
        self._embeddings_factory = embeddings_factory
        self._fulltext_store_factory = fulltext_store_factory

        self._cache_lock = RLock()
        self._paper_list_cache: dict[str, Any] | None = None
        self._paper_list_mtime_ns: int | None = None
        self._vector_store: Any | None = None
        self._vector_store_mtime_ns: int | None = None
        self._fulltext_store: Any | None = None

    def close(self) -> None:
        """생성된 Vector DB 리소스를 명시적으로 해제한다."""
        with self._cache_lock:
            self._close_resource(self._vector_store)
            self._close_resource(self._fulltext_store)
            self._vector_store = None
            self._vector_store_mtime_ns = None
            self._fulltext_store = None

    @staticmethod
    def _close_resource(resource: Any | None) -> None:
        close = getattr(resource, "close", None)
        if callable(close):
            close()

    def _invalidate_vector_store(self) -> None:
        self._close_resource(self._vector_store)
        self._vector_store = None
        self._vector_store_mtime_ns = None

    def _load_paper_catalog(self) -> dict[str, Any]:
        """파일이 변경된 경우에만 논문 카탈로그를 다시 읽는다."""
        try:
            mtime_ns = self.json_list_path.stat().st_mtime_ns
        except FileNotFoundError as exc:
            raise DeepSearchError(
                f"논문 리스트 파일 누락: {self.json_list_path}"
            ) from exc

        with self._cache_lock:
            if (
                self._paper_list_cache is not None
                and self._paper_list_mtime_ns == mtime_ns
            ):
                return self._paper_list_cache

            try:
                with self.json_list_path.open("r", encoding="utf-8-sig") as file:
                    payload = json.load(file)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise DeepSearchError(
                    f"논문 리스트 파일을 읽지 못했습니다: {self.json_list_path}"
                ) from exc
            if not isinstance(payload, dict):
                raise DeepSearchError(
                    "논문 리스트 JSON의 최상위 값은 객체여야 합니다."
                )

            if self._paper_list_mtime_ns != mtime_ns:
                self._invalidate_vector_store()
            self._paper_list_cache = payload
            self._paper_list_mtime_ns = mtime_ns
            return payload

    def _create_embeddings(self) -> Any:
        if self._embeddings_factory is not None:
            return self._embeddings_factory()
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings()

    def _get_vector_store(self) -> Any:
        """현재 논문 카탈로그의 제목 Vector DB를 한 번만 생성한다."""
        catalog = self._load_paper_catalog()
        with self._cache_lock:
            if (
                self._vector_store is not None
                and self._vector_store_mtime_ns == self._paper_list_mtime_ns
            ):
                return self._vector_store

            try:
                from langchain_chroma import Chroma
            except ImportError:
                from langchain_community.vectorstores import Chroma
            from langchain_core.documents import Document

            documents = [
                Document(page_content=title, metadata={"id": paper_id})
                for paper_id, info in catalog.items()
                if isinstance(info, dict)
                and (title := str(info.get("title", "")).strip())
            ]
            if not documents:
                raise DeepSearchError("벡터 검색에 사용할 논문 제목이 없습니다.")

            self._vector_store = Chroma.from_documents(
                documents, self._create_embeddings()
            )
            self._vector_store_mtime_ns = self._paper_list_mtime_ns
            return self._vector_store

    def _get_fulltext_store(self) -> Any:
        """본문 검색용 Vector DB를 요청 간 재사용한다."""
        with self._cache_lock:
            if self._fulltext_store is None:
                if self._fulltext_store_factory is None:
                    from services.fulltext_vector_store import ChromaFullTextStore

                    self._fulltext_store = ChromaFullTextStore()
                else:
                    self._fulltext_store = self._fulltext_store_factory()
            return self._fulltext_store

    @staticmethod
    def _connect_readonly(path: Path) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)

    def search_papers(self, keyword: str = "") -> dict[str, Any]:
        """전체 논문 목록 또는 제목 벡터 검색 결과를 반환한다."""
        catalog = self._load_paper_catalog()
        normalized_keyword = keyword.strip()
        if not normalized_keyword:
            results = [
                {"id": paper_id, "title": str(info.get("title", ""))}
                for paper_id, info in catalog.items()
                if isinstance(info, dict)
            ]
            return {
                "search_type": "all",
                "total_count": len(results),
                "results": results,
            }

        documents = self._get_vector_store().similarity_search(
            normalized_keyword,
            k=min(PAPER_CANDIDATE_LIMIT, len(catalog)),
        )
        return {
            "search_type": "vector_similarity",
            "keyword": normalized_keyword,
            "results": [
                {"id": document.metadata["id"], "title": document.page_content}
                for document in documents
            ],
        }

    def get_paper_details(self, paper_id: str) -> dict[str, Any]:
        """논문 ID로 초록, 본문, 참고문헌을 조회한다."""
        normalized_paper_id = paper_id.strip()
        if not normalized_paper_id:
            raise DeepSearchError("논문 ID를 입력해 주세요.")
        if not self.db_path.is_file():
            raise DeepSearchError(f"논문 원본 DB 누락: {self.db_path}")

        try:
            with self._connect_readonly(self.db_path) as connection:
                row = connection.execute(
                    "SELECT title, abstract, content FROM extracted WHERE id = ?",
                    (normalized_paper_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise DeepSearchError(f"DB 조회 오류: {exc}") from exc
        if row is None:
            raise DeepSearchError(f"ID '{normalized_paper_id}' 논문 없음.")

        details: dict[str, Any] = {
            "paper_id": normalized_paper_id,
            "title": row[0],
            "abstract": row[1],
            "content": row[2],
        }
        if not self.reference_db_path.is_file():
            details["references"] = ["레퍼런스 DB 누락됨"]
            return details

        try:
            with self._connect_readonly(self.reference_db_path) as connection:
                rows = connection.execute(
                    "SELECT ref_index, reference_text FROM extracted_ref "
                    "WHERE paper_id = ? ORDER BY ref_index",
                    (normalized_paper_id,),
                ).fetchall()
            details["references"] = [f"[{index}] {text}" for index, text in rows]
        except sqlite3.Error:
            details["references"] = ["레퍼런스 DB 파싱 오류 발생"]
        return details

    def search_passages(
        self,
        question: str,
        *,
        paper_id: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        """논문 본문 Vector DB에서 질문과 관련된 근거 청크를 검색한다."""
        normalized_question = question.strip()
        if not normalized_question:
            raise DeepSearchError("본문에서 검색할 질문을 입력해 주세요.")
        if not 1 <= limit <= 10:
            raise DeepSearchError("본문 검색 결과 수는 1개에서 10개 사이여야 합니다.")

        normalized_paper_id = paper_id.strip()
        if not normalized_paper_id:
            raise DeepSearchError("심층 검색할 논문 ID를 입력해 주세요.")
        results = self._get_fulltext_store().search(
            normalized_question,
            paper_id=normalized_paper_id,
            limit=limit,
        )
        return {"question": normalized_question, "results": results}


def _json_response(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


_DEFAULT_DEEP_SEARCH = DeepSearch()


@tool("search_local_paper_list", args_schema=SearchPaperListInput)
def search_local_paper_list(keyword: str = "") -> str:
    """저장된 논문 전체 목록 또는 제목 벡터 검색 결과를 반환합니다."""
    try:
        payload = _DEFAULT_DEEP_SEARCH.search_papers(keyword)
        if keyword.strip() and not payload["results"]:
            return f"'{keyword.strip()}'와 유사한 논문을 벡터 DB에서 찾을 수 없습니다."
        return _json_response(payload)
    except Exception as exc:
        return _json_response({"error": f"논문 검색 실패: {exc}"})


@tool("get_local_paper_details", args_schema=GetPaperDetailsInput)
def get_local_paper_details(paper_id: str) -> str:
    """논문 ID로 초록, 본문, 참고문헌을 조회합니다."""
    try:
        return _json_response(_DEFAULT_DEEP_SEARCH.get_paper_details(paper_id))
    except Exception as exc:
        return _json_response({"error": str(exc)})


@tool("search_local_paper_passages", args_schema=SearchPaperPassagesInput)
def search_local_paper_passages(
    question: str, paper_id: str, limit: int = 5
) -> str:
    """추출 논문 본문을 섹션별 청크로 검색해 답변 근거를 반환합니다."""
    try:
        payload = _DEFAULT_DEEP_SEARCH.search_passages(
            question, paper_id=paper_id, limit=limit
        )
        return _json_response(payload)
    except Exception as exc:
        return _json_response({"error": f"논문 본문 검색 실패: {exc}"})
