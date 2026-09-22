"""Extract arXiv HTML papers and store sections in SQLite databases.

The library database keeps the user's saved papers. The extracted database
keeps one row per section, while preserving both searchable text and HTML.
Automatically synchronizes extracted sections to Chroma vector store upon extraction.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.tools import tool

# ---------------------------------------------------------------------
# [모듈 임포트 경로 설정: src 및 프로젝트 루트 추가]
# ---------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent          # src/tools
SRC_DIR = CURRENT_DIR.parent                          # src
PROJECT_ROOT = SRC_DIR.parent                         # Paper_Scholar

if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

load_dotenv()

# 로거 모듈 임포트 (기존 5000번대 공식 규격 반영)
try:
    from log.app_logger import AppLogger
    from log.log_codes import LogCode
except ImportError:
    class LogCode:
        PAPER_EXTRACTION_STARTED = 5100
        PAPER_EXTRACTION_SKIPPED = 5101
        PAPER_EXTRACTION_SUCCEEDED = 5200
        PAPER_EXTRACTION_REJECTED = 5400
        PAPER_EXTRACTION_FAILED = 5500

    class AppLogger:
        def __init__(self, name: str):
            self.name = name

        def log(self, code, **kwargs):
            pass

logger = AppLogger(__name__)

# DB 경로 설정
try:
    from tools import EXTRACTED_DB, LIBRARY_DB
except ImportError:
    DATA_DIR = PROJECT_ROOT / "data"
    LIBRARY_DB = DATA_DIR / "paper_list" / "saved_papers.db"
    EXTRACTED_DB = DATA_DIR / "paper_extract" / "extracted_papers.db"


def ensure_library_record(
    paper_id: str,
    *,
    title: str = "",
    authors: str = "",
    summary: str = "",
    pdf_url: str = "",
) -> bool:
    """서재 DB(saved_papers.db)에 논문 한 줄을 보장한다.

    extract_and_save 는 이 행이 없으면 추출을 거부한다. 웹에서 저장한 논문은
    MySQL 에만 들어가므로, 추출을 걸기 전에 여기에도 등록해 둬야 한다.
    이미 있으면 건드리지 않는다(기존 메타데이터를 덮어쓰지 않기 위해).
    """
    clean_id = re.sub(r"v\d+$", "", str(paper_id or "").strip())
    if not clean_id:
        return False

    LIBRARY_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(LIBRARY_DB) as library:
        library.execute(
            """CREATE TABLE IF NOT EXISTS papers (
                id      TEXT PRIMARY KEY,
                title   TEXT,
                authors TEXT,
                summary TEXT,
                pdf_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        existing = library.execute(
            "SELECT 1 FROM papers WHERE id = ?", (clean_id,)
        ).fetchone()
        if existing:
            return False
        library.execute(
            "INSERT INTO papers (id, title, authors, summary, pdf_url) VALUES (?, ?, ?, ?, ?)",
            (clean_id, title or "", authors or "", summary or "", pdf_url or ""),
        )
    return True


def init_schema() -> None:
    """추출된 논문 섹션을 저장할 SQLite 테이블(paper_sections)을 초기화합니다."""
    EXTRACTED_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(EXTRACTED_DB) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS paper_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id TEXT NOT NULL, section_order INTEGER NOT NULL,
            section_title TEXT, section_text TEXT, section_html TEXT,
            extracted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (paper_id, section_order)
        )""")


def fetch_html(paper_id: str, timeout: int = 30) -> str:
    """arXiv HTML 엔드포인트로부터 웹 문서를 스크래핑합니다."""
    clean_id = re.sub(r"v\d+$", "", paper_id.strip())
    response = requests.get(
        f"https://arxiv.org/html/{clean_id}",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        timeout=timeout,
    )
    if response.status_code == 404:
        raise ValueError(
            f"arXiv HTML을 찾을 수 없습니다 (404 Not Found): {clean_id}. "
            "해당 논문은 HTML 렌더링이 제공되지 않는 구형 논문일 수 있습니다."
        )
    response.raise_for_status()
    return response.text


MIN_BODY_CHARS = 200  # 정상 논문의 짧은 각주 같은 조각은 넣지 않는다


def _body_before_first_heading(root) -> tuple[str, str]:
    """첫 h2/h3 앞의 본문 문단을 모은다. 섹션 제목 없이 쓴 짧은 논문은 본문 전체가 여기에 있다."""
    nodes = []
    for node in root.find_all(["h2", "h3", "div", "p"]):
        if node.name in {"h2", "h3"}:
            break
        classes = node.get("class") or []
        if (
            "ltx_para" in classes
            and not node.find_parent(class_="ltx_abstract")
            and not node.find_parent(class_="ltx_para")
        ):
            nodes.append(node)
    fragment_soup = BeautifulSoup("".join(str(node) for node in nodes), "html.parser")
    for image in fragment_soup.select("img"):
        image.decompose()
    return fragment_soup.get_text(" ", strip=True), str(fragment_soup)


def parse_sections(html: str) -> list[tuple[int, str, str, str]]:
    """HTML 문서를 섹션 단위(Abstract, H2, H3)로 파싱하여 수식/표를 보존합니다."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("main") or soup.select_one("article") or soup
    sections = []

    # 1. Abstract 섹션 추출
    abstract = root.select_one(".ltx_abstract, #abstract, [class*='abstract']")
    if abstract:
        for image in abstract.select("img"):
            image.decompose()
        abstract_html = str(abstract)
        abstract_text = abstract.get_text(" ", strip=True)
        sections.append((1, "Abstract", abstract_text, abstract_html))

    # 1-2. 첫 h2/h3 앞의 본문 (섹션 제목 없이 쓴 Letter·에세이형 논문은 본문 전체가 여기에 있다)
    body_text, body_html = _body_before_first_heading(root)
    if len(body_text) >= MIN_BODY_CHARS:
        sections.append((len(sections) + 1, "본문", body_text, body_html))

    # 2. H2, H3 헤딩 기준 본문 분할 (수식 및 표 구조 유지)
    headings = root.select("h2, h3")
    for order, heading in enumerate(headings, len(sections) + 1):
        title = heading.get_text(" ", strip=True)
        parts = []
        node = heading.find_next_sibling()
        while node and node.name not in {"h2", "h3"}:
            if getattr(node, "name", None):
                parts.append(str(node))
            node = node.find_next_sibling()
        fragment = "".join(parts)
        fragment_soup = BeautifulSoup(fragment, "html.parser")
        for image in fragment_soup.select("img"):
            image.decompose()
        fragment = str(fragment_soup)
        text = fragment_soup.get_text(" ", strip=True)
        if text or fragment:
            sections.append((order, title, text, fragment))

    # 3. 헤딩 태그가 없는 단일 본문 대응
    if not sections:
        text = root.get_text(" ", strip=True)
        sections.append((1, "본문", text, str(root)))

    return sections


class ArxivExtractor:
    """arXiv HTML 다운로드 및 섹션 단위 본문 추출기."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def fetch_html(self, paper_id: str) -> str:
        return fetch_html(paper_id, timeout=self.timeout)

    def extract_sections(self, html: str) -> list[tuple[int, str, str, str]]:
        return parse_sections(html)

    def extract(self, paper_id: str) -> list[tuple[int, str, str, str]]:
        return self.extract_sections(self.fetch_html(paper_id))


def extract_and_save(paper_id: str, *, require_django_sync: bool = False) -> int:
    """서재 DB 등록을 검증하고, 추출 DB에 섹션을 적재한 뒤 Chroma 벡터 색인을 즉시 동기화한다.

    Django 비동기 작업에서는 ``require_django_sync``를 켜서 MySQL 저장까지
    성공한 경우에만 작업을 완료 처리합니다. 기존 CLI 흐름은 SQLite 우선의
    최선형 동작을 그대로 유지합니다.
    """
    clean_id = re.sub(r"v\d+$", "", paper_id.strip())
    init_schema()

    # 정식 로그 코드 사용 (5100: PAPER_EXTRACTION_STARTED)
    logger.log(LogCode.PAPER_EXTRACTION_STARTED, paper_id=clean_id, status="extracting")
    start_time = time.time()

    if not LIBRARY_DB.exists():
        err_msg = f"서재 DB를 찾을 수 없습니다: {LIBRARY_DB}"
        logger.log(LogCode.PAPER_EXTRACTION_FAILED, paper_id=clean_id, error=err_msg, error_type="FileNotFoundError")
        raise ValueError(err_msg)

    with sqlite3.connect(LIBRARY_DB) as library:
        paper = library.execute(
            "SELECT id FROM papers "
            "WHERE id = ? OR id GLOB ? "
            "ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END "
            "LIMIT 1",
            (clean_id, f"{clean_id}v[0-9]*", clean_id),
        ).fetchone()
    if not paper:
        err_msg = f"paper_library.papers에 존재하지 않는 paper_id입니다: {clean_id}. 서재 선행 등록 필요"
        logger.log(LogCode.PAPER_EXTRACTION_FAILED, paper_id=clean_id, error=err_msg, error_type="MissingLibraryRecord")
        raise ValueError(err_msg)

    try:
        # 1. HTML 본문 섹션 추출 및 SQLite 적재
        sections = ArxivExtractor().extract(clean_id)
        with sqlite3.connect(EXTRACTED_DB) as extracted:
            extracted.execute("DELETE FROM paper_sections WHERE paper_id = ?", (clean_id,))
            extracted.executemany(
                "INSERT INTO paper_sections "
                "(paper_id, section_order, section_title, section_text, section_html) "
                "VALUES (?, ?, ?, ?, ?)",
                [(clean_id, order, title, text, fragment) for order, title, text, fragment in sections],
            )

        # 2. Django/MySQL PaperSection 테이블 동기화
        try:
            from services.django_paper_repository import replace_paper_sections

            mysql_section_count = replace_paper_sections(clean_id, sections)
            print(
                f"  [System] MySQL 본문 섹션 동기화 완료 "
                f"({mysql_section_count}개)"
            )
        except Exception as mysql_err:
            print(
                f"  [Notice] MySQL 본문 섹션 동기화 경고 "
                f"({clean_id}): {mysql_err}"
            )
            if require_django_sync:
                raise

        # 3. SQLite 적재 완료 직후 Chroma 본문 벡터 스토어 즉시 색인 동기화
        try:
            from services.fulltext_vector_store import ChromaFullTextStore
            ChromaFullTextStore().ensure_index(paper_id=clean_id)
        except Exception as embed_err:
            print(f"  [Notice] Chroma 벡터 색인 보조 작업 경고 ({clean_id}): {embed_err}")

        elapsed = round(time.time() - start_time, 2)
        # 정식 로그 코드 사용 (5200: PAPER_EXTRACTION_SUCCEEDED)
        logger.log(
            LogCode.PAPER_EXTRACTION_SUCCEEDED,
            paper_id=clean_id,
            section_count=len(sections),
            duration_sec=elapsed,
            db_path=str(EXTRACTED_DB)
        )
        return len(sections)

    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        # 정식 로그 코드 사용 (5500: PAPER_EXTRACTION_FAILED)
        logger.log(
            LogCode.PAPER_EXTRACTION_FAILED,
            paper_id=clean_id,
            error=str(e),
            error_type=type(e).__name__,
            duration_sec=elapsed
        )
        raise e


def export_markdown(paper_id: str, output_path: str | Path | None = None) -> Path:
    """추출 DB의 섹션을 모아 마크다운 파일로 내보냅니다."""
    clean_id = re.sub(r"v\d+$", "", paper_id.strip())
    if not EXTRACTED_DB.exists():
        raise ValueError(f"추출 DB를 찾을 수 없습니다: {EXTRACTED_DB}")

    with sqlite3.connect(EXTRACTED_DB) as db:
        rows = db.execute(
            """SELECT section_order, section_title, section_text, section_html
               FROM paper_sections WHERE paper_id = ? ORDER BY section_order""",
            (clean_id,),
        ).fetchall()

    if not rows:
        raise ValueError(f"추출 DB에 없는 paper_id입니다: {clean_id}")

    destination = Path(output_path) if output_path else (
        PROJECT_ROOT / "data" / "paper_extract" / f"{clean_id}.md"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# arXiv Paper: {clean_id}", ""]
    for order, title, text, html in rows:
        lines.extend([f"## {title or f'Section {order}'}", ""])
        fragment = BeautifulSoup(html or "", "html.parser")
        for image in fragment.select("img"):
            image.decompose()
        lines.extend([str(fragment) if html else (text or ""), ""])
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


class ExtractToolInput(BaseModel):
    paper_id: str = Field(..., description="본문 섹션을 추출할 arXiv 논문 ID (예: '2402.08954')")
    export_md: bool = Field(default=False, description="추출 결과를 Markdown 파일로도 로컬에 내보낼지 여부")


@tool("extract_paper_content", args_schema=ExtractToolInput)
def extract_paper_content_tool(paper_id: str, export_md: bool = False) -> str:
    """서재 DB(papers 테이블)에 등록된 arXiv 논문의 HTML 본문을 파싱하여
    수식과 표가 보존된 섹션별 데이터를 추출 DB에 적재하고 벡터 색인을 동기화합니다.
    """
    clean_id = re.sub(r"v\d+$", "", paper_id.strip())
    try:
        num_sections = extract_and_save(clean_id)
        result_msg = f"[추출 및 색인 성공] 논문 [{clean_id}]의 본문 {num_sections}개 섹션이 DB 적재 및 Chroma 색인 완료되었습니다."
        if export_md:
            md_path = export_markdown(clean_id)
            result_msg += f" (Markdown 파일 저장 경로: {md_path})"
        return result_msg
    except ValueError as ve:
        return f"[추출 불가] {str(ve)}"
    except requests.RequestException as re_err:
        return f"[네트워크 오류] arXiv 서버 응답 실패 ({clean_id}): {str(re_err)}"
    except Exception as e:
        return f"[시스템 예외] 논문 추출 중 알 수 없는 오류 발생 ({clean_id}): {str(e)}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="arXiv HTML 본문 섹션 추출 및 벡터 색인 도구")
    parser.add_argument("paper_id", help="예: 2402.08954 또는 2402.08954v1")
    parser.add_argument("--export-md", action="store_true", help="추출 결과를 Markdown으로 저장")
    args = parser.parse_args()
    if args.export_md:
        print(f"Markdown 저장: {export_markdown(args.paper_id)}")
    else:
        print(f"저장된 섹션 수: {extract_and_save(args.paper_id)}")
