"""추출된 논문 본문을 섹션별 청크로 색인하는 검색 저장소.

HTML 마크업을 복원하여 수식($...$)과 표(Markdown Table)를 보존한 채 청킹하며,
사전 색인 구조를 채택하여 쿼리 시점의 검색 지연을 최소화한다.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------
# [프로젝트 루트 및 임베딩 설정 로드]
# ---------------------------------------------------------------------
try:
    from . import PROJECT_ROOT
    from .summary_vector_store import STORAGE_CONFIG
except (ImportError, ValueError):
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    STORAGE_CONFIG = {
        "directory": PROJECT_ROOT / "data" / "vector_store" / "chroma",
        "embedding_model": "BAAI/bge-m3",
        "device": "cpu",
        "normalize_embeddings": True,
    }

EXTRACT_DB_PATH = PROJECT_ROOT / "data" / "paper_extract" / "extracted_papers.db"
SAVED_PAPERS_DB_PATH = PROJECT_ROOT / "data" / "paper_list" / "saved_papers.db"
COLLECTION_NAME = "paper_fulltext_chunks"
SECTION_COLUMNS = (
    "abstract", "introduction", "related_work", "method", "experiment",
    "result", "conclusion", "others",
)
# 참고문헌은 본문 시맨틱 검색을 왜곡하므로 색인 대상에서 배제
EXCLUDED_SECTIONS = {"references", "bibliography"}
# 표 한 개가 이보다 길면 행 단위로 분할
TABLE_CHUNK_LIMIT = 4000


class FullTextStoreError(RuntimeError):
    """본문 색인 또는 검색에 실패했을 때 발생한다."""


def split_text(text: str, *, chunk_size: int = 1200, overlap: int = 180) -> list[str]:
    """문단을 우선 보존하며 겹치는 검색용 청크로 나눈다."""
    if chunk_size < 200 or not 0 <= overlap < chunk_size:
        raise ValueError("chunk_size와 overlap 값이 올바르지 않습니다.")
    chunks: list[str] = []
    for paragraph in (part.strip() for part in text.split("\n\n") if part.strip()):
        start = 0
        while start < len(paragraph):
            end = min(start + chunk_size, len(paragraph))
            chunks.append(paragraph[start:end])
            if end == len(paragraph):
                break
            start = end - overlap
    return chunks


def _replace_with_text(element, text: str) -> None:
    """XML/HTML 요소를 지우고 그 자리에 텍스트만 남긴다."""
    parent = element.getparent()
    if parent is None:
        return
    payload = text + (element.tail or "")
    previous = element.getprevious()
    if previous is not None:
        previous.tail = (previous.tail or "") + payload
    else:
        parent.text = (parent.text or "") + payload
    parent.remove(element)


def _table_to_markdown(table) -> str:
    """HTML <tr>, <td>를 마크다운 표로 변환한다."""
    rows: list[list[str]] = []
    for row in table.xpath(".//tr"):
        cells = [" ".join(cell.text_content().split()) for cell in row.xpath("./td|./th")]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = [
        "| " + " | ".join(rows[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n\n" + "\n".join(lines) + "\n\n"


def restore_markup(html: str) -> str:
    """section_html에서 MathML 수식($...$)과 표를 복원하여 본문 텍스트로 만든다."""
    if not html or not html.strip():
        return ""
    try:
        from lxml import html as lxml_html
    except ImportError as exc:
        raise FullTextStoreError("lxml이 설치되어 있지 않습니다.") from exc

    root = lxml_html.fromstring(f"<div>{html}</div>")

    # 1. 수식 MathML을 LaTeX 문자열($...$)로 치환
    for math in root.xpath(".//math"):
        latex = math.xpath('.//annotation[@encoding="application/x-tex"]/text()')
        body = latex[0].strip() if latex and latex[0].strip() else ""
        _replace_with_text(math, f" ${body}$ " if body else "")

    # 2. 표 HTML을 Markdown Table로 치환
    for table in root.xpath(".//table"):
        _replace_with_text(table, _table_to_markdown(table))

    for paragraph in root.xpath(".//p"):
        paragraph.tail = (paragraph.tail or "") + "\n\n"

    text = re.sub(r"[ \t]+", " ", root.text_content())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_section(text: str) -> list[str]:
    """표는 블록 단위로 온전히 보존하고, 일반 텍스트는 문단 단위로 청킹한다."""
    blocks = re.split(r"(\n\|(?:[^\n]*\|)+(?:\n\|(?:[^\n]*\|)+)*)", "\n" + text)
    chunks: list[str] = []
    for block in blocks:
        stripped = block.strip()
        if not stripped:
            continue
        if not stripped.startswith("|"):
            chunks.extend(split_text(stripped))
            continue
        if len(stripped) <= TABLE_CHUNK_LIMIT:
            chunks.append(stripped)
            continue
        # 거대 표는 헤더를 보존하며 행 단위로 분할
        lines = stripped.splitlines()
        header, current = lines[:2], list(lines[:2])
        for line in lines[2:]:
            if sum(len(item) for item in current) + len(line) > TABLE_CHUNK_LIMIT:
                chunks.append("\n".join(current))
                current = list(header)
            current.append(line)
        if len(current) > 2:
            chunks.append("\n".join(current))
    return chunks


class ChromaFullTextStore:
    """추출 SQLite DB를 Chroma에 동기화하고 관련 본문 청크를 반환한다."""

    def __init__(self, *, db_path: str | Path = EXTRACT_DB_PATH, directory: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.directory = Path(directory or STORAGE_CONFIG["directory"])
        self._client: Any | None = None
        self._model_instance: Any | None = None

    def _collection(self):
        try:
            import chromadb
        except ImportError as exc:
            raise FullTextStoreError("chromadb가 설치되어 있지 않습니다.") from exc
        self.directory.mkdir(parents=True, exist_ok=True)
        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self.directory))
        return self._client.get_or_create_collection(
            name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )

    def _model(self):
        if self._model_instance is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise FullTextStoreError("sentence-transformers가 설치되어 있지 않습니다.") from exc
            self._model_instance = SentenceTransformer(
                str(STORAGE_CONFIG["embedding_model"]),
                device=str(STORAGE_CONFIG["device"]),
            )
        return self._model_instance

    def _titles(self) -> dict[str, str]:
        """paper_sections에 제목이 없어 서재 DB(saved_papers.db)에서 가져온다."""
        if not SAVED_PAPERS_DB_PATH.exists():
            return {}
        try:
            with sqlite3.connect(SAVED_PAPERS_DB_PATH) as conn:
                return {
                    str(row[0]): str(row[1] or "")
                    for row in conn.execute("SELECT id, title FROM papers")
                }
        except sqlite3.Error:
            return {}

    def _read_papers(
        self, *, paper_id: str | None = None
    ) -> list[tuple[str, str, list[tuple[str, str]]]]:
        """선택 논문 또는 전체 paper_sections를 절 단위로 읽는다."""
        if not self.db_path.exists():
            raise FullTextStoreError(f"논문 원본 DB를 찾을 수 없습니다: {self.db_path}")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                query = (
                    "SELECT paper_id, section_order, section_title, section_text, section_html "
                    "FROM paper_sections"
                )
                params: tuple[str, ...] = ()
                if paper_id:
                    query += " WHERE paper_id = ?"
                    params = (paper_id,)
                query += " ORDER BY paper_id, section_order"
                rows = conn.execute(query, params).fetchall()
        except sqlite3.Error as exc:
            raise FullTextStoreError("논문 원본 DB를 읽지 못했습니다.") from exc

        titles = self._titles()
        grouped: dict[str, list[tuple[str, str]]] = {}
        for row in rows:
            section_title = str(row["section_title"] or "").strip()
            if section_title.casefold() in EXCLUDED_SECTIONS:
                continue
            body = restore_markup(str(row["section_html"] or ""))
            if not body:
                body = str(row["section_text"] or "").strip()
            if not body:
                continue
            order = int(row["section_order"] or 0)
            label = f"{order:02d} {section_title}".strip()
            grouped.setdefault(str(row["paper_id"]), []).append((label, body))

        return [
            (paper_id, titles.get(paper_id, paper_id), sections)
            for paper_id, sections in grouped.items()
        ]

    def ensure_index(self, *, paper_id: str | None = None) -> int:
        """선택 논문 또는 전체 논문의 본문 청크를 Chroma 컬렉션에 동기화한다."""
        collection = self._collection()
        added = 0
        for indexed_paper_id, title, sections in self._read_papers(paper_id=paper_id):
            source_hash = hashlib.sha256("\n".join(text for _, text in sections).encode()).hexdigest()
            existing = collection.get(where={"paper_id": indexed_paper_id}, include=["metadatas"])
            existing_metadata = existing.get("metadatas") or []

            # 이미 색인되어 있고 본문 해시가 일치하면 재색인 건너뜀
            if existing_metadata and all(item.get("source_hash") == source_hash for item in existing_metadata):
                continue

            if existing.get("ids"):
                collection.delete(where={"paper_id": indexed_paper_id})

            ids: list[str] = []
            documents: list[str] = []
            metadata: list[dict[str, Any]] = []
            for section, text in sections:
                for index, chunk in enumerate(split_section(text)):
                    ids.append(f"{indexed_paper_id}:{section}:{index}")
                    documents.append(f"{title}\n\n{section}\n{chunk}")
                    metadata.append({
                        "paper_id": indexed_paper_id,
                        "title": title,
                        "section": section,
                        "chunk_index": index,
                        "has_table": "| --- |" in chunk,
                        "has_math": "$" in chunk,
                        "source_hash": source_hash,
                    })
            if documents:
                embeddings = self._model().encode(
                    documents,
                    normalize_embeddings=bool(STORAGE_CONFIG["normalize_embeddings"]),
                    show_progress_bar=False
                )
                collection.upsert(ids=ids, documents=documents, embeddings=embeddings.tolist(), metadatas=metadata)
                added += len(documents)
        return added

    def search(self, query: str, *, limit: int = 5, paper_id: str | None = None) -> list[dict[str, object]]:
        """질의와 가장 유사한 본문 청크를 벡터 검색한다. (검색 지연 최적화 적용)"""
        if not query.strip():
            raise ValueError("본문 검색어가 비어 있습니다.")
        selected_paper_id = paper_id.strip() if paper_id else None

        collection = self._collection()
        where = {"paper_id": selected_paper_id} if selected_paper_id else None

        # [최적화 핵심] 매번 ensure_index()를 돌리지 않고, 기존에 색인된 데이터가 없을 때만 방어적으로 색인
        available = len(collection.get(where=where).get("ids", [])) if where else collection.count()
        if available == 0 and selected_paper_id:
            self.ensure_index(paper_id=selected_paper_id)
            available = len(collection.get(where=where).get("ids", []))

        if available == 0:
            return []

        embedding = self._model().encode(
            [query],
            normalize_embeddings=bool(STORAGE_CONFIG["normalize_embeddings"]),
            show_progress_bar=False
        ).tolist()[0]

        result = collection.query(
            query_embeddings=[embedding],
            n_results=min(limit, available),
            where=where,
            include=["documents", "metadatas", "distances"]
        )
        return [
            {"id": item_id, "document": document, "metadata": metadata, "distance": distance}
            for item_id, document, metadata, distance in zip(
                result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
            )
        ]