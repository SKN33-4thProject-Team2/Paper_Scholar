"""추출된 논문 본문을 섹션별 청크로 색인하는 검색 저장소."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any

from . import PROJECT_ROOT
from .summary_vector_store import STORAGE_CONFIG


EXTRACT_DB_PATH = PROJECT_ROOT / "data" / "paper_extract" / "extracted_papers.db"
SAVED_PAPERS_DB_PATH = PROJECT_ROOT / "data" / "paper_list" / "saved_papers.db"
COLLECTION_NAME = "paper_fulltext_chunks"
SECTION_COLUMNS = (
    "abstract", "introduction", "related_work", "method", "experiment",
    "result", "conclusion", "others",
)
# 참고문헌은 본문과 성격이 달라 색인하지 않는다. 섞이면 본문 검색 결과를
# 인용 문장이 밀어낸다.
EXCLUDED_SECTIONS = {"references", "bibliography"}
# 표 한 개가 이보다 길면 그 표만 행 단위로 나눈다.
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
    """요소를 지우고 그 자리에 텍스트만 남긴다."""
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
    """<tr><td> 를 마크다운 표로 바꾼다. 청크가 잘려도 행 단위로 읽힌다."""
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
    """section_html 에서 표와 수식을 되살려 본문 텍스트로 만든다.

    section_text 는 표와 수식이 아예 지워진 채 저장돼 있다. 마스킹 토큰조차
    남지 않아 되돌릴 수 없으므로, 원형이 남아 있는 section_html 에서 다시
    만든다. 72개 절에 표 37개, 수식 828개가 들어 있다.
    """
    if not html or not html.strip():
        return ""
    try:
        from lxml import html as lxml_html
    except ImportError as exc:
        raise FullTextStoreError("lxml 이 설치되어 있지 않습니다.") from exc

    root = lxml_html.fromstring(f"<div>{html}</div>")

    # 수식을 먼저 바꾼다. 표 안에도 수식이 있어서, 표를 먼저 처리하면 셀에
    # MathML 찌꺼기가 그대로 딸려 들어간다.
    for math in root.xpath(".//math"):
        latex = math.xpath('.//annotation[@encoding="application/x-tex"]/text()')
        body = latex[0].strip() if latex and latex[0].strip() else ""
        _replace_with_text(math, f" ${body}$ " if body else "")

    for table in root.xpath(".//table"):
        _replace_with_text(table, _table_to_markdown(table))

    # text_content() 는 문단을 붙여 버린다. 청킹이 문단 경계를 쓰므로 살려 둔다.
    for paragraph in root.xpath(".//p"):
        paragraph.tail = (paragraph.tail or "") + "\n\n"

    text = re.sub(r"[ \t]+", " ", root.text_content())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_section(text: str) -> list[str]:
    """표는 통째로, 나머지는 기존 규칙대로 나눈다.

    표가 청크 중간에서 잘리면 머리글과 값이 떨어져 검색에도 답변에도 쓸 수
    없다. 표 블록만 먼저 떼어 내고 그 사이 글만 split_text 에 넘긴다.
    """
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
        # 긴 표는 머리글을 매 조각에 다시 붙여 행 단위로만 자른다.
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
        """paper_sections 에는 제목 컬럼이 없어 서재 DB 에서 가져온다."""
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

    def _read_papers(self) -> list[tuple[str, str, list[tuple[str, str]]]]:
        """paper_sections 를 절 단위로 읽어 표·수식을 되살린 본문을 돌려준다."""
        if not self.db_path.exists():
            raise FullTextStoreError(f"논문 원본 DB를 찾을 수 없습니다: {self.db_path}")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT paper_id, section_order, section_title, section_text, section_html "
                    "FROM paper_sections ORDER BY paper_id, section_order"
                ).fetchall()
        except sqlite3.Error as exc:
            raise FullTextStoreError("논문 원본 DB를 읽지 못했습니다.") from exc

        titles = self._titles()
        grouped: dict[str, list[tuple[str, str]]] = {}
        for row in rows:
            section_title = str(row["section_title"] or "").strip()
            if section_title.casefold() in EXCLUDED_SECTIONS:
                continue
            # HTML 이 비었거나 복원에 실패하면 기존 텍스트로 떨어진다.
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

    def ensure_index(self) -> int:
        collection = self._collection()
        added = 0
        for paper_id, title, sections in self._read_papers():
            source_hash = hashlib.sha256("\n".join(text for _, text in sections).encode()).hexdigest()
            existing = collection.get(where={"paper_id": paper_id}, include=["metadatas"])
            existing_metadata = existing.get("metadatas") or []
            if existing_metadata and all(item.get("source_hash") == source_hash for item in existing_metadata):
                continue
            if existing.get("ids"):
                collection.delete(where={"paper_id": paper_id})
            ids: list[str] = []
            documents: list[str] = []
            metadata: list[dict[str, Any]] = []
            for section, text in sections:
                for index, chunk in enumerate(split_section(text)):
                    ids.append(f"{paper_id}:{section}:{index}")
                    documents.append(f"{title}\n\n{section}\n{chunk}")
                    metadata.append({
                        "paper_id": paper_id,
                        "title": title,
                        "section": section,
                        "chunk_index": index,
                        "has_table": "| --- |" in chunk,
                        "has_math": "$" in chunk,
                        "source_hash": source_hash,
                    })
            if documents:
                embeddings = self._model().encode(documents, normalize_embeddings=bool(STORAGE_CONFIG["normalize_embeddings"]), show_progress_bar=False)
                collection.upsert(ids=ids, documents=documents, embeddings=embeddings.tolist(), metadatas=metadata)
                added += len(documents)
        return added

    def search(self, query: str, *, limit: int = 5, paper_id: str | None = None) -> list[dict[str, object]]:
        if not query.strip():
            raise ValueError("본문 검색어가 비어 있습니다.")
        self.ensure_index()
        collection = self._collection()
        where = {"paper_id": paper_id} if paper_id else None
        available = len(collection.get(where=where).get("ids", [])) if where else collection.count()
        if available == 0:
            return []
        embedding = self._model().encode([query], normalize_embeddings=bool(STORAGE_CONFIG["normalize_embeddings"]), show_progress_bar=False).tolist()[0]
        result = collection.query(query_embeddings=[embedding], n_results=min(limit, available), where=where, include=["documents", "metadatas", "distances"])
        return [
            {"id": item_id, "document": document, "metadata": metadata, "distance": distance}
            for item_id, document, metadata, distance in zip(result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0])
        ]
