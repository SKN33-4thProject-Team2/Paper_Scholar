"""구조화된 논문 요약을 임베딩하여 ChromaDB에 저장한다."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from log import AppLogger, LogCode

from . import PROJECT_ROOT
from .model_config_service import ModelConfigError, load_task_config


logger = AppLogger(__name__)


class SummaryStoreError(RuntimeError):
    """논문 요약을 벡터 DB에 저장하지 못했을 때 발생한다."""


class SummaryStore(Protocol):
    """SummaryTool이 사용하는 요약 저장소 규격."""

    def save(
        self,
        *,
        paper_id: str,
        title: str,
        source: str,
        summary_model: str,
        sections: Mapping[str, str],
    ) -> int:
        """요약 섹션을 저장하고 저장한 문서 수를 반환한다."""


def _load_storage_config() -> dict[str, object]:
    try:
        config = load_task_config("summary_store")
    except ModelConfigError as exc:
        raise RuntimeError("요약 저장소 설정을 읽지 못했습니다.") from exc

    embedding = config.get("embedding")
    vector_db = config.get("vector_db")
    if not isinstance(embedding, dict) or not isinstance(vector_db, dict):
        raise RuntimeError("embedding과 vector_db 설정이 필요합니다.")

    model = str(embedding.get("model", "")).strip()
    device = str(embedding.get("device", "cpu")).strip()
    provider = str(vector_db.get("provider", "")).strip().casefold()
    directory = str(vector_db.get("persist_directory", "")).strip()
    collection = str(vector_db.get("summary_collection", "")).strip()
    if not model or not device or provider != "chroma" or not directory or not collection:
        raise RuntimeError("임베딩 또는 ChromaDB 설정값이 올바르지 않습니다.")

    return {
        "embedding_model": model,
        "device": device,
        "normalize_embeddings": bool(
            embedding.get("normalize_embeddings", True)
        ),
        "directory": PROJECT_ROOT / directory,
        "collection": collection,
    }


STORAGE_CONFIG = _load_storage_config()


class ChromaSummaryStore:
    """요약의 네 개 섹션을 각각 하나의 Chroma 문서로 저장한다."""

    def __init__(
        self,
        *,
        directory: str | Path | None = None,
        collection: str | None = None,
    ) -> None:
        self._directory = Path(directory or STORAGE_CONFIG["directory"])
        self._collection_name = collection or str(STORAGE_CONFIG["collection"])
        self._embedding_model = None
        self._client = None

    def _collection(self):
        try:
            import chromadb
        except ImportError as exc:
            raise SummaryStoreError("chromadb가 설치되어 있지 않습니다.") from exc

        self._directory.mkdir(parents=True, exist_ok=True)
        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self._directory))
        return self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def close(self) -> None:
        """Windows에서도 DB 파일 잠금이 해제되도록 Chroma 연결을 종료한다."""
        if self._client is None:
            return
        self._client._system.stop()
        self._client = None
        from chromadb.api.client import SharedSystemClient

        SharedSystemClient.clear_system_cache()

    def initialize(self) -> int:
        """영구 ChromaDB와 요약 컬렉션을 만들고 현재 문서 수를 반환한다."""
        try:
            return self._collection().count()
        except SummaryStoreError:
            raise
        except Exception as exc:
            raise SummaryStoreError("ChromaDB를 초기화하지 못했습니다.") from exc

    def _model(self):
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise SummaryStoreError(
                    "sentence-transformers가 설치되어 있지 않습니다."
                ) from exc
            self._embedding_model = SentenceTransformer(
                str(STORAGE_CONFIG["embedding_model"]),
                device=str(STORAGE_CONFIG["device"]),
            )
        return self._embedding_model

    def save(
        self,
        *,
        paper_id: str,
        title: str,
        source: str,
        summary_model: str,
        sections: Mapping[str, str],
    ) -> int:
        """요약 섹션을 임베딩하고 같은 논문·섹션 ID로 upsert한다."""
        documents = [
            f"{title}\n\n{section_name}\n{content.strip()}"
            for section_name, content in sections.items()
            if content.strip()
        ]
        section_names = [
            section_name
            for section_name, content in sections.items()
            if content.strip()
        ]
        if not documents:
            raise SummaryStoreError("저장할 요약 내용이 비어 있습니다.")

        logger.log(
            LogCode.SUMMARY_STORAGE_STARTED,
            paper_id=paper_id,
            collection=self._collection_name,
            document_count=len(documents),
        )
        try:
            collection = self._collection()
            embeddings = self._model().encode(
                documents,
                normalize_embeddings=bool(
                    STORAGE_CONFIG["normalize_embeddings"]
                ),
                show_progress_bar=False,
            )
            if hasattr(embeddings, "tolist"):
                embeddings = embeddings.tolist()
            collection.upsert(
                ids=[f"{paper_id}:{name}" for name in section_names],
                documents=documents,
                embeddings=embeddings,
                metadatas=[
                    {
                        "paper_id": paper_id,
                        "title": title,
                        "section": name,
                        "source": source,
                        "summary_model": summary_model,
                        "embedding_model": str(STORAGE_CONFIG["embedding_model"]),
                    }
                    for name in section_names
                ],
            )
        except SummaryStoreError as exc:
            self._log_failure(paper_id, exc)
            raise
        except Exception as exc:
            self._log_failure(paper_id, exc)
            raise SummaryStoreError("ChromaDB에 요약을 저장하지 못했습니다.") from exc

        logger.log(
            LogCode.SUMMARY_STORAGE_SUCCEEDED,
            paper_id=paper_id,
            collection=self._collection_name,
            document_count=len(documents),
            embedding_model=STORAGE_CONFIG["embedding_model"],
        )
        return len(documents)

    def save_chunk(self, *, paper_id: str, chunk_index: int, title: str,
                   summary_text: str, source: str = "summary_chunks",
                   summary_model: str = "") -> int:
        """문단별 요약을 고유한 chunk_index로 임베딩 저장한다."""
        return self.save(
            paper_id=paper_id,
            title=title,
            source=source,
            summary_model=summary_model,
            sections={f"chunk_{chunk_index}": summary_text},
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        paper_id: str | None = None,
    ) -> list[dict[str, object]]:
        """요약 컬렉션만 의미 검색하여 챗봇 근거를 반환한다."""
        query = query.strip()
        if not query:
            raise ValueError("요약 검색어가 비어 있습니다.")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit은 1 이상의 정수여야 합니다.")

        collection = self._collection()
        document_count = collection.count()
        if document_count == 0:
            return []

        query_embedding = self._model().encode(
            [query],
            normalize_embeddings=bool(STORAGE_CONFIG["normalize_embeddings"]),
            show_progress_bar=False,
        )
        if hasattr(query_embedding, "tolist"):
            query_embedding = query_embedding.tolist()
        query_options: dict[str, object] = {
            "query_embeddings": [query_embedding[0]],
            "n_results": min(limit, document_count),
            "include": ["documents", "metadatas", "distances"],
        }
        if paper_id:
            query_options["where"] = {"paper_id": paper_id}
        result = collection.query(**query_options)

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return [
            {
                "id": result_id,
                "document": document,
                "metadata": metadata,
                "distance": distance,
            }
            for result_id, document, metadata, distance in zip(
                ids, documents, metadatas, distances
            )
        ]

    def _log_failure(self, paper_id: str, error: Exception) -> None:
        logger.log(
            LogCode.SUMMARY_STORAGE_FAILED,
            paper_id=paper_id,
            collection=self._collection_name,
            error_type=type(error).__name__,
            error=str(error),
        )
