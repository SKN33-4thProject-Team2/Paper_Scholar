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

from tools import LIBRARY_DB, PROJECT_DIR


BASE_DIR = PROJECT_DIR / "data" / "paper_extract"
JSON_LIST_PATH = BASE_DIR / "extracted_papers.json"
DB_PATH = BASE_DIR / "extracted_papers.db"
REF_DB_PATH = BASE_DIR / "extracted_papers_ref.db"
PAPER_CANDIDATE_LIMIT = 5
# 참고문헌 절과 내용이 빈 절은 본문이 아니므로 목록·상세 어디에서도 세지 않는다.
BODY_SECTION_FILTER = (
    "LOWER(TRIM(COALESCE(section_title, ''))) NOT IN ('references', 'bibliography') "
    "AND (TRIM(COALESCE(section_text, '')) <> '' OR TRIM(COALESCE(section_html, '')) <> '')"
)


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

    본문 표준은 paper_sections 이다. 논문 목록도 기본으로 추출 DB에서 만들고,
    json_list_path 를 넘긴 경우(평가 코퍼스 등)에만 예전 JSON 카탈로그를 읽는다.
    """

    def __init__(
        self,
        *,
        json_list_path: str | Path | None = None,
        db_path: str | Path = DB_PATH,
        reference_db_path: str | Path = REF_DB_PATH,
        library_db_path: str | Path = LIBRARY_DB,
        embeddings_factory: Callable[[], Any] | None = None,
        fulltext_store_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.json_list_path = Path(json_list_path) if json_list_path else None
        self.db_path = Path(db_path)
        self.reference_db_path = Path(reference_db_path)
        self.library_db_path = Path(library_db_path)
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
        """카탈로그 원본(추출 DB 또는 JSON)이 변경된 경우에만 다시 읽는다."""
        source = self.json_list_path or self.db_path
        try:
            mtime_ns = source.stat().st_mtime_ns
        except FileNotFoundError as exc:
            raise DeepSearchError(f"논문 리스트 원본 누락: {source}") from exc

        with self._cache_lock:
            if (
                self._paper_list_cache is not None
                and self._paper_list_mtime_ns == mtime_ns
            ):
                return self._paper_list_cache

            payload = (
                self._read_json_catalog()
                if self.json_list_path
                else self._read_db_catalog()
            )

            if self._paper_list_mtime_ns != mtime_ns:
                self._invalidate_vector_store()
            self._paper_list_cache = payload
            self._paper_list_mtime_ns = mtime_ns
            return payload

    def _read_json_catalog(self) -> dict[str, Any]:
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
        return payload

    def _read_db_catalog(self) -> dict[str, Any]:
        """추출 DB에서 논문 목록을 만든다.

        extracted 에만 있고 paper_sections 에는 없는 논문도 목록에 올린다.
        그래야 선택했을 때 "근거 0건" 대신 "본문 섹션 없음"을 분명히 알려 줄 수 있다.
        순서는 예전 JSON 과 같은 extracted 최신순이고, paper_sections 에만
        있는 논문은 그 뒤에 붙인다. "1번 논문" 같은 번호 선택이 바뀌지 않게 하기 위함이다.
        """
        try:
            with self._connect_readonly(self.db_path) as connection:
                tables = self._table_names(connection)
                extracted_rows = (
                    connection.execute(
                        "SELECT id, title FROM extracted ORDER BY created_at DESC"
                    ).fetchall()
                    if "extracted" in tables
                    else []
                )
                section_rows = (
                    connection.execute(
                        "SELECT paper_id, COUNT(*) FROM paper_sections "
                        f"WHERE {BODY_SECTION_FILTER} "
                        "GROUP BY paper_id ORDER BY MAX(id) DESC"
                    ).fetchall()
                    if "paper_sections" in tables
                    else []
                )
        except sqlite3.Error as exc:
            raise DeepSearchError(f"논문 리스트 DB 조회 오류: {exc}") from exc

        section_counts = {str(paper_id): int(count) for paper_id, count in section_rows}
        library_titles = self._library_titles()
        catalog: dict[str, Any] = {}
        for paper_id, title in [
            *extracted_rows,
            *((paper_id, "") for paper_id, _ in section_rows),
        ]:
            paper_id = str(paper_id)
            if paper_id in catalog:
                continue
            catalog[paper_id] = {
                "id": paper_id,
                "title": str(title or library_titles.get(paper_id) or paper_id),
                "section_count": section_counts.get(paper_id, 0),
            }
        return catalog

    def _library_titles(self) -> dict[str, str]:
        """paper_sections 에는 제목이 없어 서재 DB 제목으로 채운다."""
        if not self.library_db_path.is_file():
            return {}
        try:
            with self._connect_readonly(self.library_db_path) as connection:
                return {
                    str(paper_id): str(title or "")
                    for paper_id, title in connection.execute(
                        "SELECT id, title FROM papers"
                    )
                }
        except sqlite3.Error:
            return {}

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

                    # 목록·상세와 본문 근거가 같은 추출 DB를 보도록 경로를 넘긴다.
                    self._fulltext_store = ChromaFullTextStore(db_path=self.db_path)
                else:
                    self._fulltext_store = self._fulltext_store_factory()
            return self._fulltext_store

    @staticmethod
    def _connect_readonly(path: Path) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)

    @staticmethod
    def _table_names(connection: sqlite3.Connection) -> set[str]:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

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
        """논문 ID로 초록, 본문, 참고문헌을 조회한다.

        본문은 paper_sections 의 절을 순서대로 이어 만든다. 절이 없는 논문은
        전환 기간 동안 extracted 의 abstract·content 로 대신한다.
        """
        normalized_paper_id = paper_id.strip()
        if not normalized_paper_id:
            raise DeepSearchError("논문 ID를 입력해 주세요.")
        if not self.db_path.is_file():
            raise DeepSearchError(f"논문 원본 DB 누락: {self.db_path}")

        try:
            with self._connect_readonly(self.db_path) as connection:
                tables = self._table_names(connection)
                sections = (
                    connection.execute(
                        "SELECT section_title, section_text FROM paper_sections "
                        f"WHERE paper_id = ? AND {BODY_SECTION_FILTER} "
                        "ORDER BY section_order",
                        (normalized_paper_id,),
                    ).fetchall()
                    if "paper_sections" in tables
                    else []
                )
                row = (
                    connection.execute(
                        "SELECT title, abstract, content FROM extracted WHERE id = ?",
                        (normalized_paper_id,),
                    ).fetchone()
                    if "extracted" in tables
                    else None
                )
        except sqlite3.Error as exc:
            raise DeepSearchError(f"DB 조회 오류: {exc}") from exc
        if not sections and row is None:
            raise DeepSearchError(f"ID '{normalized_paper_id}' 논문 없음.")

        title, abstract, content = row if row is not None else ("", "", "")
        if sections:
            content = "\n\n".join(
                f"## {str(section_title or '').strip()}\n\n{str(section_text or '').strip()}"
                for section_title, section_text in sections
            )
            abstract = next(
                (
                    str(section_text or "")
                    for section_title, section_text in sections
                    if "abstract" in str(section_title or "").casefold()
                ),
                abstract,
            )

        details: dict[str, Any] = {
            "paper_id": normalized_paper_id,
            "title": title
            or self._library_titles().get(normalized_paper_id)
            or normalized_paper_id,
            "abstract": abstract,
            "content": content,
            "section_count": len(sections),
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
        store = self._get_fulltext_store()
        results = store.search(
            normalized_question,
            paper_id=normalized_paper_id,
            limit=limit,
        )
        # 결과가 비었을 때 "관련 근거가 없다"와 "색인할 본문 자체가 없다"를 구분한다.
        # 저장소가 has_paper 를 제공할 때만 확인하므로 평가용 저장소 등은 예전과 같다.
        has_paper = getattr(store, "has_paper", None)
        if not results and callable(has_paper) and not has_paper(normalized_paper_id):
            raise DeepSearchError(
                f"'{normalized_paper_id}' 논문의 본문 섹션(paper_sections)이 없어 "
                "근거를 검색할 수 없습니다. 추출 결과가 paper_sections에 저장됐는지 확인해 주세요."
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
