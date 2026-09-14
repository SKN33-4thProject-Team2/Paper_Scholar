"""Extract arXiv HTML papers and store sections in SQLite databases.

The library database keeps the user's saved papers.  The extracted database
keeps one row per section, while preserving both searchable text and HTML.
"""

from __future__ import annotations

import argparse
import re
import sqlite3

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from tools import EXTRACTED_DB, LIBRARY_DB, PROJECT_ROOT

load_dotenv()


def init_schema() -> None:
    """Create the SQLite extracted-paper database and its section table."""
    EXTRACTED_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(EXTRACTED_DB) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS paper_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id TEXT NOT NULL, section_order INTEGER NOT NULL,
            section_title TEXT, section_text TEXT, section_html TEXT,
            extracted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (paper_id, section_order)
        )""")


def fetch_html(paper_id: str) -> str:
    clean_id = re.sub(r"v\d+$", "", paper_id.strip())
    response = requests.get(f"https://arxiv.org/html/{clean_id}", timeout=30)
    if response.status_code == 404:
        raise ValueError(f"arXiv HTML을 찾을 수 없습니다: {paper_id}")
    response.raise_for_status()
    return response.text


def parse_sections(html: str) -> list[tuple[int, str, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("main") or soup.select_one("article") or soup
    sections = []
    abstract = root.select_one(".ltx_abstract, #abstract, [class*='abstract']")
    if abstract:
        for image in abstract.select("img"):
            image.decompose()
        abstract_html = str(abstract)
        abstract_text = abstract.get_text(" ", strip=True)
        sections.append((1, "Abstract", abstract_text, abstract_html))

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
    if not sections:
        text = root.get_text(" ", strip=True)
        sections.append((1, "本文", text, str(root)))
    return sections


class ArxivExtractor:
    """arXiv HTML 다운로드 및 섹션 단위 본문 추출기."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def fetch_html(self, paper_id: str) -> str:
        clean_id = re.sub(r"v\d+$", "", paper_id.strip())
        response = requests.get(
            f"https://arxiv.org/html/{clean_id}", timeout=self.timeout
        )
        if response.status_code == 404:
            raise ValueError(f"arXiv HTML을 찾을 수 없습니다: {paper_id}")
        response.raise_for_status()
        return response.text

    def extract_sections(self, html: str) -> list[tuple[int, str, str, str]]:
        return parse_sections(html)

    def extract(self, paper_id: str) -> list[tuple[int, str, str, str]]:
        return self.extract_sections(self.fetch_html(paper_id))


def extract_and_save(paper_id: str) -> int:
    """Read a saved paper from paper_library and replace its extracted sections."""
    init_schema()
    if not LIBRARY_DB.exists():
        raise ValueError(f"서재 DB를 찾을 수 없습니다: {LIBRARY_DB}")
    with sqlite3.connect(LIBRARY_DB) as library:
        paper = library.execute("SELECT id FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if not paper:
        raise ValueError(f"paper_library.papers에 없는 paper_id입니다: {paper_id}")

    sections = ArxivExtractor().extract(paper_id)
    with sqlite3.connect(EXTRACTED_DB) as extracted:
        extracted.execute("DELETE FROM paper_sections WHERE paper_id = ?", (paper_id,))
        extracted.executemany(
            "INSERT INTO paper_sections "
            "(paper_id, section_order, section_title, section_text, section_html) "
            "VALUES (?, ?, ?, ?, ?)",
            [(paper_id, order, title, text, fragment) for order, title, text, fragment in sections],
        )
    return len(sections)


def export_markdown(paper_id: str, output_path: str | Path | None = None) -> Path:
    """Load extracted sections and export one paper as Markdown."""
    if not EXTRACTED_DB.exists():
        raise ValueError(f"추출 DB를 찾을 수 없습니다: {EXTRACTED_DB}")

    with sqlite3.connect(EXTRACTED_DB) as db:
        rows = db.execute(
            """SELECT section_order, section_title, section_text, section_html
               FROM paper_sections WHERE paper_id = ? ORDER BY section_order""",
            (paper_id,),
        ).fetchall()

    if not rows:
        raise ValueError(f"추출 DB에 없는 paper_id입니다: {paper_id}")

    destination = Path(output_path) if output_path else (
        PROJECT_ROOT / "data" / "paper_extract" / f"{paper_id}.md"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# arXiv Paper: {paper_id}", ""]
    for order, title, text, html in rows:
        lines.extend([f"## {title or f'Section {order}'}", ""])
        # Remove image binaries/references while preserving tables, formulas and captions.
        fragment = BeautifulSoup(html or "", "html.parser")
        for image in fragment.select("img"):
            image.decompose()
        lines.extend([str(fragment) if html else (text or ""), ""])
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("paper_id", help="예: 2402.08954 또는 2402.08954v1")
    parser.add_argument("--export-md", action="store_true", help="추출 결과를 Markdown으로 저장")
    args = parser.parse_args()
    if args.export_md:
        print(f"Markdown 저장: {export_markdown(args.paper_id)}")
    else:
        print(f"저장된 섹션 수: {extract_and_save(args.paper_id)}")
