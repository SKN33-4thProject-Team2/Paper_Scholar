"""학술 논문 본문 전체 추출, DB/인용문헌(References) DB 자동 매핑, 피규어 캡션 통합 관리 및 백그라운드 마크다운 번역/요약 모듈.

- PDF 추출 데이터를 메인 본문 DB(extracted_papers.db)와 인용문헌 DB(extracted_papers_ref.db)에 'paper_id' 기준으로 분리 저장
- 윈도우 파일 시스템 제약에 안전한 파일명 정규화 로직 적용으로 FileNotFoundError 원천 차단
- 수식을 한 줄로 정돈하고 핵심 중심의 간결한 마크다운(.md) 번역 결과물 자동 저장
"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool

# ---------------------------------------------------------------------
# [모듈 임포트 경로 설정: tests 및 프로젝트 루트 기준 절대 경로 보정]
# ---------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for _path in (SRC_DIR, PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.append(str(_path))

from log.app_logger import AppLogger
from log.log_codes import LogCode
from services.nvidia_service import (
    NVIDIA_CONFIG,
    NvidiaServiceError,
    chat,
    describe_image,
    is_available,
)

# ---------------------------------------------------------------------
# [전역 설정 및 정규식 정제 규칙]
# ---------------------------------------------------------------------
load_dotenv()
logger = AppLogger(__name__)

DEFAULT_PDF_DIR = PROJECT_ROOT / "data" / "paper_save"
DEFAULT_METADATA_DB = PROJECT_ROOT / "data" / "paper_list" / "saved_papers.db"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "paper_extract"
OPENAI_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")

TEXT_REPLACEMENTS = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st", "ﬆ": "st",
    " ": " ", " ": " ", "­": "",
    "7→": "↦",
}

CAPTION_PATTERN = re.compile(
    r"^\s*(fig(?:ure)?\.?|table|algorithm|listing)\s*\.?\s*\d+", re.IGNORECASE
)
ARXIV_STAMP_PATTERN = re.compile(r"arXiv:\s*\d{4}\.\d{4,5}v?\d*\s*\[[^\]]+\]", re.IGNORECASE)
REFERENCE_HEADING_PATTERN = re.compile(
    r"^\s*(?:\d+\.?\s*)?(references|bibliography)\s*$", re.IGNORECASE
)
NUMBERED_HEADING_PATTERN = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})*)\.?\s+([A-Z][^.]{2,60})\s*$")
UPPER_HEADING_PATTERN = re.compile(r"^\s*([A-Z][A-Z \-]{3,40})\s*$")
KNOWN_HEADINGS = {
    "abstract", "introduction", "background", "related work", "method", "methods",
    "methodology", "approach", "experiments", "experimental setup", "results",
    "evaluation", "discussion", "conclusion", "conclusions", "limitations",
    "acknowledgments", "acknowledgements", "appendix",
}

SUBSCRIPT_SIZE_RATIO = 0.85
SUBSCRIPT_OFFSET_RATIO = 0.12
SUBSCRIPT_MAX_CHARS = 12
OVERSIZED_GLYPH_SHARE = 0.05
OVERSIZED_GLYPH_RATIO = 1.4
TABLE_MIN_FILLED_RATIO = 0.4
DEFAULT_VISION_WORKERS = 8

UNK_RUN_PATTERN = re.compile(r"(?:<unk>\s*){4,}")
REPEATED_RUN_PATTERN = re.compile(r"(.{2,40}?)\1{6,}", re.DOTALL)
TABLE_ROW_PATTERN = re.compile(r"^[ \t]*\|.*$", re.MULTILINE)
VISION_LENGTH_LIMIT = 3.0

MAX_PAGES_FOR_TABLES = 8
REFERENCE_PAGE_PATTERN = re.compile(
    r"^\s*(?:\d+\.?\s*)?(?:references|bibliography)\s*$", re.IGNORECASE | re.MULTILINE
)
CITATION_ENTRY_PATTERN = re.compile(r"^\s*\[\d{1,3}\]\s", re.MULTILINE)
CITATION_ENTRIES_PER_PAGE = 5

REFERENCE_SECTION_PATTERN = re.compile(
    r"^#{1,6}\s+(?:references|bibliography)\s*$", re.IGNORECASE | re.MULTILINE
)
MIN_REFERENCE_LENGTH = 25

VISION_PROMPT = (
    "Transcribe this page of an academic paper as GitHub-flavored Markdown.\n"
    "Rules:\n"
    "1. Write every formula as LaTeX: inline math as $...$, display math as $$...$$.\n"
    "   Use \\frac, \\sqrt, \\sum, \\mathbb, ^{} and _{} exactly as the page shows.\n"
    "2. Render tables as Markdown tables with a header row. Never use LaTeX tabular.\n"
    "3. Section titles become Markdown headings (## for sections, ### for subsections).\n"
    "4. Keep figure and table captions as normal lines starting with 'Figure N:' or 'Table N:'.\n"
    "   Do not describe the figure image itself.\n"
    "5. Drop page numbers, running headers, footers and the arXiv stamp.\n"
    "6. Transcribe every word. Never summarize, translate, or add commentary.\n"
    "7. Output only the Markdown, with no preamble and no surrounding code fence."
)

VISION_PROMPT_TEXT_ONLY = (
    "Transcribe this page of an academic paper as GitHub-flavored Markdown.\n"
    "Rules:\n"
    "1. Write every formula as LaTeX: inline math as $...$, display math as $$...$$.\n"
    "   Use \\frac, \\sqrt, \\sum, \\mathbb, ^{} and _{} exactly as the page shows.\n"
    "2. Skip tables and figures entirely. Do not transcribe table contents, do not write\n"
    "   Markdown tables, and do not write figure or table captions.\n"
    "3. Section titles become Markdown headings (## for sections, ### for subsections).\n"
    "4. Drop page numbers, running headers, footers and the arXiv stamp.\n"
    "5. Transcribe every sentence of the running text. Never summarize or add commentary.\n"
    "6. Output only the Markdown, with no preamble and no surrounding code fence."
)

ARABIC_SECTION_NUMBER = re.compile(r"^\d+$")
ROMAN_SECTION_NUMBER = re.compile(r"^[IVXLCDM]+$")
AMBIGUOUS_LETTERS = set("IVXLCDM")
MAJOR_SECTION_TITLES = {
    "abstract", "introduction", "background", "related work", "method", "methods",
    "methodology", "approach", "experiments", "experimental setup", "results",
    "results and analysis", "evaluation", "discussion", "conclusion", "conclusions",
    "limitations", "acknowledgments", "acknowledgements", "appendix",
}
EXCLUDED_SECTION_TITLES = {"references", "bibliography"}

INLINE_ABSTRACT_PATTERN = re.compile(
    r"^[*_\s]*(abstract|index terms|keywords)[*_\s]*[—–\-:]{1,3}\s*", re.IGNORECASE
)
INLINE_SECTION_PATTERN = re.compile(
    r"(?:(?<=\.)|(?<=^))\s*((?:[IVXLCDM]{1,5}|\d{1,2})\.)\s+([A-Z][A-Z][A-Z \-]{2,40}?)"
    r"(?=\s+[A-Z][a-z])"
)

IMRAD_COLUMNS = (
    "abstract",
    "introduction",
    "related_work",
    "method",
    "experiment",
    "result",
    "conclusion",
)
OTHERS_COLUMN = "others"

SECTION_KEYWORDS = {
    "abstract": ("abstract",),
    "introduction": ("introduction", "motivation"),
    "related_work": ("related work", "related research", "background", "prior work"),
    "method": ("method", "approach", "model", "architecture", "framework", "algorithm",
               "proposed", "theory", "formulation", "preliminaries"),
    "experiment": ("experiment", "setup", "implementation", "dataset", "data",
                   "simulation", "training", "evaluation protocol"),
    "result": ("result", "analysis", "discussion", "evaluation", "ablation", "finding"),
    "conclusion": ("conclusion", "summary", "future work", "outlook", "concluding"),
}

SECTION_CLASSIFY_SYSTEM_PROMPT = (
    "You classify the structure of academic papers. Given the list of a paper's "
    "top-level sections, decide what role each one plays in the paper.\n"
    "[Categories]\n"
    "- abstract: the paper's abstract\n"
    "- introduction: background, motivation, the problem being solved\n"
    "- related_work: survey of prior research\n"
    "- method: the proposed technique, model, architecture, theory, or definitions\n"
    "- experiment: experimental setup, datasets, implementation details, simulation procedure\n"
    "- result: experimental results, analysis, discussion, ablations\n"
    "- conclusion: conclusions, summary, future work\n"
    "- others: none of the above\n"
    "[Rules]\n"
    "1. Judge by the role the section plays, not by its name.\n"
    "2. Reply with JSON only."
)

SECTION_LABEL_PATTERN = re.compile(
    r"^\s*(\d+(?:\.\d+)*\.?|[IVXLC]{1,5}\.|[A-Z]\.)\s+(\S.*)$"
)

# ---------------------------------------------------------------------
# [데이터 구조 및 Pydantic 의도 분류 모델]
# ---------------------------------------------------------------------
class PaperExtractionError(RuntimeError):
    """논문 본문 추출 실패 시 예외"""

@dataclass(frozen=True)
class PaperRef:
    id: str
    title: str
    pdf_path: Path
    from_metadata: bool = True

@dataclass(frozen=True)
class Section:
    no: str
    title: str
    pages: tuple[int, ...]
    text: str

    @property
    def n_chars(self) -> int:
        return len(self.text)

@dataclass(frozen=True)
class ExtractionResult:
    id: str
    title: str
    source_pdf: str
    content: str
    n_pages: int
    n_vision_pages: int = 0
    skipped: bool = False
    sections: tuple[Section, ...] = ()
    columns: dict = field(default_factory=dict)
    others: dict = field(default_factory=dict)
    references: tuple = ()

    @property
    def n_chars(self) -> int:
        return len(self.content)

    @property
    def extractor(self) -> str:
        if not self.n_vision_pages:
            return "pymupdf"
        if self.n_vision_pages == self.n_pages:
            return "vision"
        return f"mixed({self.n_vision_pages}/{self.n_pages})"

class UserIntent(BaseModel):
    intent_type: str = Field(
        description="의도 유형: 'list'(목록/리스트 요청), 'search'(키워드/주제 탐색), 'select_paper'(논문 선택), 'action'(번역/요약 요청), 'page'(페이지 이동), 'location'(저장 위치/경로 문의), 'exit'(종료), 'unknown'(기타)"
    )
    list_count: Optional[int] = Field(description="목록에서 보여줄 논문의 개수 (예: 5개, 20개). 지정되지 않으면 None", default=None)
    show_all_list: bool = Field(description="'모든 리스트 다 보여줘', '전부 보여줘' 등 목록 전체 출력을 원할 때 True", default=False)
    keyword: Optional[str] = Field(description="검색 키워드 또는 주제어", default=None)
    selected_indices: List[int] = Field(description="선택한 논문 번호 리스트 (1부터 시작하는 순번 목록)", default_factory=list)
    select_all: bool = Field(description="'모두', '전부', '다', '전체' 등으로 목록 전체 선택 시 True", default=False)
    action_type: Optional[str] = Field(
        description="원하는 작업: 'translate'(번역만), 'summarize'(요약만), 'both'(번역과 요약 모두)",
        default=None
    )
    page_direction: Optional[str] = Field(description="페이지 이동 방향: 'next'(다음), 'prev'(이전)", default=None)

# ---------------------------------------------------------------------
# [Class 1: PaperExtractor - 본문 추출 및 인용문헌 매핑 저장 엔진]
# ---------------------------------------------------------------------
class PaperExtractor:
    """PDF를 팀 정제 규칙대로 가공하여 메인 DB와 인용문헌(References) DB에 paper_id 기준으로 저장/업데이트하는 클래스."""

    def __init__(
        self,
        *,
        pdf_dir: str | Path | None = None,
        metadata_db: str | Path | None = None,
        output_dir: str | Path | None = None,
        use_vision: bool = True,
        vision_workers: int = DEFAULT_VISION_WORKERS,
    ) -> None:
        self.pdf_dir = Path(pdf_dir) if pdf_dir else DEFAULT_PDF_DIR
        self.metadata_db = Path(metadata_db) if metadata_db else DEFAULT_METADATA_DB
        self.output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR

        self.db_path = self.output_dir / "extracted_papers.db"
        self.ref_db_path = self.output_dir / "extracted_papers_ref.db"
        self.json_path = self.output_dir / "extracted_papers.json"

        self.use_vision = use_vision
        self.vision_workers = max(1, vision_workers)
        self._embedded_title = ""

    @staticmethod
    def safe_title(title: str) -> str:
        cleaned = "".join(c for c in title if c.isalnum() or c in " _-").rstrip()
        return cleaned[:60]

    def list_papers(self) -> list[PaperRef]:
        if not self.metadata_db.is_file():
            raise PaperExtractionError(f"논문 메타데이터 DB가 없습니다: {self.metadata_db}")

        with closing(sqlite3.connect(self.metadata_db)) as conn:
            rows = conn.execute("SELECT id, title FROM papers").fetchall()

        by_path: dict[Path, PaperRef] = {}
        for paper_id, title in rows:
            path = self.pdf_dir / f"{self.safe_title(title or '')}.pdf"
            if path.is_file():
                by_path[path] = PaperRef(id=paper_id, title=title, pdf_path=path, from_metadata=True)

        if self.pdf_dir.is_dir():
            for path in sorted(self.pdf_dir.glob("*.pdf")):
                by_path.setdefault(
                    path,
                    PaperRef(id=path.stem, title=path.stem, pdf_path=path, from_metadata=False),
                )

        refs = list(by_path.values())
        refs.sort(key=lambda ref: ref.title.lower())
        return refs

    def find(self, paper_id: str) -> PaperRef:
        for ref in self.list_papers():
            if ref.id == paper_id:
                return ref
        raise PaperExtractionError(f"'{paper_id}' 에 해당하는 PDF가 없습니다.")

    def is_extracted(self, paper_id: str) -> bool:
        if not self.db_path.is_file():
            return False
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute("SELECT 1 FROM extracted WHERE id = ?", (paper_id,)).fetchone()
        return row is not None

    def get(self, paper_id: str) -> dict | None:
        if not self.db_path.is_file():
            return None
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM extracted WHERE id = ?", (paper_id,)).fetchone()
        return dict(row) if row else None

    def extract(self, paper_id: str, *, force: bool = False) -> ExtractionResult:
        if self.is_extracted(paper_id) and not force:
            record = self.get(paper_id) or {}
            logger.log(LogCode.PAPER_EXTRACTION_SKIPPED, paper_id=paper_id)
            return ExtractionResult(
                id=paper_id,
                title=record.get("title", ""),
                source_pdf=record.get("source_pdf", ""),
                content=record.get("content", ""),
                n_pages=int(record.get("n_pages") or 0),
                skipped=True,
            )

        ref = self.find(paper_id)
        logger.log(LogCode.PAPER_EXTRACTION_STARTED, paper_id=paper_id, title=ref.title)

        try:
            pages, n_vision, with_tables = self._read_pdf(ref.pdf_path)
            numbered = self._refine(pages, with_tables)
            sections = self._build_sections(numbered)
            content = "\n\n".join(text for _, text in numbered)
        except Exception as exc:
            logger.log(LogCode.PAPER_EXTRACTION_FAILED, paper_id=paper_id, reason=str(exc))
            raise PaperExtractionError(f"'{paper_id}' 추출에 실패했습니다: {exc}") from exc

        title = ref.title
        if not ref.from_metadata and self._embedded_title:
            title = self._embedded_title

        extracted = ExtractionResult(
            id=ref.id,
            title=title,
            source_pdf=ref.pdf_path.name,
            content=content,
            n_pages=len(pages),
            n_vision_pages=n_vision,
            sections=sections,
            references=self._extract_references(content),
        )

        mapping = self._classify_sections(title, sections)
        columns, others = self._to_imrad(sections, mapping)
        result = replace(extracted, columns=columns, others=others)

        self._save(result)
        logger.log(
            LogCode.PAPER_EXTRACTION_SUCCEEDED,
            paper_id=paper_id,
            pages=result.n_pages,
            chars=result.n_chars,
            extractor=result.extractor,
        )
        return result

    def extract_many(self, paper_ids: list[str], *, force: bool = False) -> list[ExtractionResult]:
        results: list[ExtractionResult] = []
        for paper_id in paper_ids:
            try:
                results.append(self.extract(paper_id, force=force))
            except PaperExtractionError:
                continue
        return results

    @staticmethod
    def _import_pymupdf():
        try:
            import pymupdf
        except ImportError:
            import fitz as pymupdf
        return pymupdf

    @staticmethod
    def _table_is_useful(table) -> bool:
        try:
            rows = table.extract()
        except Exception:
            return False
        if len(rows) < 2 or table.col_count < 2:
            return False
        cells = [cell for row in rows for cell in row]
        if not cells:
            return False
        filled = sum(1 for cell in cells if cell and str(cell).strip())
        return filled / len(cells) >= TABLE_MIN_FILLED_RATIO

    def _read_pdf(self, pdf_path: Path) -> tuple[list[str], int, bool]:
        pymupdf = self._import_pymupdf()
        with pymupdf.open(pdf_path) as document:
            self._embedded_title = (document.metadata or {}).get("title", "").strip()
            local_pages = [self._read_page(page) for page in document]
            content_pages = self._content_page_count(local_pages)
            with_tables = content_pages <= MAX_PAGES_FOR_TABLES

            if not self.use_vision or not is_available():
                return [self._normalize(page) for page in local_pages], 0, with_tables

            dpi = int(NVIDIA_CONFIG.get("render_dpi", 150))
            images = [
                base64.b64encode(page.get_pixmap(dpi=dpi).tobytes("png")).decode()
                for page in document
            ]

        pages, n_vision = self._read_pages_with_vision(images, local_pages, with_tables)
        return [self._normalize(page) for page in pages], n_vision, with_tables

    @staticmethod
    def _content_page_count(local_pages: list[str]) -> int:
        for index, page in enumerate(local_pages):
            if REFERENCE_PAGE_PATTERN.search(page):
                return index
            if len(CITATION_ENTRY_PATTERN.findall(page)) >= CITATION_ENTRIES_PER_PAGE:
                return index
        return len(local_pages)

    @staticmethod
    def _degeneration_reason(text: str, local_text: str) -> str:
        if not text.strip():
            return "빈 응답"
        if UNK_RUN_PATTERN.search(text):
            return "<unk> 반복"
        if REPEATED_RUN_PATTERN.search(TABLE_ROW_PATTERN.sub("", text)):
            return "같은 조각 반복"
        local_length = len(local_text.strip())
        if local_length > 200 and len(text) > local_length * VISION_LENGTH_LIMIT:
            return f"분량 과다 ({len(text)}자 vs 로컬 {local_length}자)"
        return ""

    def _read_pages_with_vision(
        self, images: list[str], local_pages: list[str], with_tables: bool
    ) -> tuple[list[str], int]:
        prompt = VISION_PROMPT if with_tables else VISION_PROMPT_TEXT_ONLY

        def read_one(index: int) -> tuple[str, bool]:
            local = local_pages[index]
            try:
                text = describe_image(images[index], prompt, max_tokens=4096, retries=4).strip()
            except NvidiaServiceError:
                return local, False

            flaw = self._degeneration_reason(text, local)
            if flaw:
                return local, False
            return text, True

        with ThreadPoolExecutor(max_workers=self.vision_workers) as pool:
            outcomes = list(pool.map(read_one, range(len(images))))

        return [text for text, _ in outcomes], sum(1 for _, ok in outcomes if ok)

    def _read_page(self, page) -> str:
        table_areas: list[tuple[float, float, float, str]] = []
        try:
            for table in page.find_tables().tables:
                if not self._table_is_useful(table):
                    continue
                bbox = table.bbox
                rendered = table.to_markdown().strip().replace("~~", "").replace("_", "")
                if rendered:
                    table_areas.append((float(bbox[1]), float(bbox[3]), float(bbox[0]), rendered))
        except Exception:
            table_areas = []

        pieces: list[tuple[float, str]] = [(top, markdown) for top, _, _, markdown in table_areas]

        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            block_top = float(block["bbox"][1])
            block_bottom = float(block["bbox"][3])
            if any(top <= block_top and block_bottom <= bottom for top, bottom, _, _ in table_areas):
                continue

            lines = [
                rendered
                for line in block.get("lines", [])
                if (rendered := self._render_line(line.get("spans", []))).strip()
            ]
            if lines:
                pieces.append((block_top, "\n".join(lines)))

        pieces.sort(key=lambda item: item[0])
        return "\n".join(text for _, text in pieces)

    @staticmethod
    def _render_line(spans: list[dict]) -> str:
        weights: Counter[float] = Counter()
        for span in spans:
            text = span.get("text", "")
            if text.strip():
                weights[round(float(span.get("size", 0)), 1)] += len(text.strip())
        if not weights:
            return ""

        total = sum(weights.values())
        ordered = sorted(weights, reverse=True)
        body_size = ordered[0]
        for index, size in enumerate(ordered):
            smaller = ordered[index + 1] if index + 1 < len(ordered) else None
            is_outlier = (
                weights[size] / total < OVERSIZED_GLYPH_SHARE
                and smaller is not None
                and size > smaller * OVERSIZED_GLYPH_RATIO
            )
            if not is_outlier:
                body_size = size
                break
        body_spans = [
            span for span in spans
            if round(float(span.get("size", 0)), 1) == body_size and span.get("text", "").strip()
        ]
        if not body_spans:
            return "".join(span.get("text", "") for span in spans)

        centers = [(float(span["bbox"][1]) + float(span["bbox"][3])) / 2 for span in body_spans]
        body_center = sum(centers) / len(centers)
        threshold = body_size * SUBSCRIPT_OFFSET_RATIO

        marked: list[tuple[str, str]] = []
        for span in spans:
            text = span.get("text", "")
            stripped = text.strip()
            size = float(span.get("size", 0))
            if not stripped or size >= body_size * SUBSCRIPT_SIZE_RATIO:
                marked.append(("body", text))
                continue

            center = (float(span["bbox"][1]) + float(span["bbox"][3])) / 2
            if center < body_center - threshold:
                marked.append(("sup", stripped))
            elif center > body_center + threshold:
                marked.append(("sub", stripped))
            else:
                marked.append(("body", text))

        parts: list[str] = []
        index = 0
        while index < len(marked):
            kind, text = marked[index]
            if kind == "body":
                parts.append(text)
                index += 1
                continue

            run = [text]
            index += 1
            while index < len(marked) and marked[index][0] == kind:
                run.append(marked[index][1])
                index += 1

            merged = "".join(run)
            if len(merged) > SUBSCRIPT_MAX_CHARS:
                parts.append(merged)
            else:
                parts.append(f"^{{{merged}}}" if kind == "sup" else f"_{{{merged}}}")
        return "".join(parts)

    @staticmethod
    def _normalize(text: str) -> str:
        for source, target in TEXT_REPLACEMENTS.items():
            text = text.replace(source, target)
        return text

    @staticmethod
    def _running_lines(pages: list[str]) -> set[str]:
        if len(pages) < 4:
            return set()
        counter: Counter[str] = Counter()
        for page in pages:
            lines = [line.strip() for line in page.splitlines() if line.strip()]
            for line in lines[:2] + lines[-2:]:
                if 3 <= len(line) <= 90:
                    counter[line] += 1
        threshold = max(3, int(len(pages) * 0.6))
        return {line for line, count in counter.items() if count >= threshold}

    @staticmethod
    def _is_noise(line: str, running: set[str]) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if stripped in running:
            return True
        if stripped.isdigit() and len(stripped) <= 4:
            return True
        return bool(ARXIV_STAMP_PATTERN.search(stripped))

    @staticmethod
    def _as_heading(line: str) -> str | None:
        stripped = line.strip().strip("*_ ").strip()
        if not stripped or len(stripped) > 80:
            return None

        if REFERENCE_HEADING_PATTERN.match(stripped):
            return "## References"

        numbered = NUMBERED_HEADING_PATTERN.match(stripped)
        if numbered:
            depth = numbered.group(1).count(".") + 2
            return f"{'#' * min(depth, 6)} {numbered.group(1)} {numbered.group(2).strip()}"

        if stripped.lower().strip(". ") in KNOWN_HEADINGS:
            return f"## {stripped.strip('. ')}"

        upper = UPPER_HEADING_PATTERN.match(stripped)
        if upper and upper.group(1).strip().lower() in KNOWN_HEADINGS:
            return f"## {upper.group(1).strip().title()}"
        return None

    @staticmethod
    def _join_hyphenation(text: str) -> str:
        def replace_match(match: re.Match[str]) -> str:
            left, right = match.group(1), match.group(2)
            if "-" in left or not right[:1].islower():
                return f"{left}-{right}"
            return f"{left}{right}"

        return re.sub(r"([A-Za-z][A-Za-z-]*)-\s+([A-Za-z]\w*)", replace_match, text)

    def _refine_page(self, page: str, running: set[str], with_tables: bool = True) -> list[str]:
        refined: list[str] = []
        paragraph_lines: list[str] = []
        table_rows: list[str] = []

        def flush_paragraph() -> None:
            if not paragraph_lines:
                return
            paragraph = self._join_hyphenation(" ".join(paragraph_lines))
            paragraph = re.sub(r"\s{2,}", " ", paragraph).strip()
            if paragraph:
                refined.extend(self._split_inline_headings(paragraph))
            paragraph_lines.clear()

        def flush_table() -> None:
            if table_rows:
                refined.append("\n".join(table_rows))
                table_rows.clear()

        for line in page.splitlines():
            if self._is_noise(line, running):
                continue
            stripped = line.strip()

            if stripped.startswith("|"):
                flush_paragraph()
                if with_tables:
                    table_rows.append(stripped)
                continue
            flush_table()

            if not stripped:
                flush_paragraph()
                continue

            heading = self._as_heading(stripped)
            if heading:
                flush_paragraph()
                refined.append(heading)
                continue

            if CAPTION_PATTERN.match(stripped):
                flush_paragraph()
                if with_tables:
                    refined.append(f"> **{stripped}**")
                continue

            paragraph_lines.append(stripped)

        flush_paragraph()
        flush_table()
        return refined

    def _refine(self, pages: list[str], with_tables: bool = True) -> list[tuple[int, str]]:
        running = self._running_lines(pages)
        numbered: list[tuple[int, str]] = []
        for page_number, page in enumerate(pages, start=1):
            for block in self._refine_page(page, running, with_tables):
                if block.strip():
                    numbered.append((page_number, block.strip()))
        return numbered

    @staticmethod
    def _is_heading(text: str) -> bool:
        first = text.lstrip().splitlines()[0] if text.strip() else ""
        return first.startswith("#")

    @staticmethod
    def _split_section_label(heading_text: str) -> tuple[str, str]:
        title = heading_text.lstrip("#").strip()
        matched = SECTION_LABEL_PATTERN.match(title)
        if not matched:
            return "", title
        return matched.group(1).rstrip(".").strip(), matched.group(2).strip()

    @classmethod
    def _split_inline_headings(cls, paragraph: str) -> list[str]:
        pieces: list[str] = []
        matched = INLINE_ABSTRACT_PATTERN.match(paragraph)
        if matched:
            pieces.append(f"## {matched.group(1).title()}")
            paragraph = paragraph[matched.end():].strip()
            if not paragraph:
                return pieces

        parts = INLINE_SECTION_PATTERN.split(paragraph)
        if len(parts) == 1:
            pieces.append(paragraph)
            return pieces

        leading = parts[0].strip()
        if leading:
            pieces.append(leading)
        for index in range(1, len(parts), 3):
            number, heading, tail = parts[index], parts[index + 1], parts[index + 2]
            pieces.append(f"## {number} {heading.strip()}")
            if tail.strip():
                pieces.append(tail.strip())
        return pieces

    @staticmethod
    def _extract_references(content: str) -> tuple[str, ...]:
        match = REFERENCE_SECTION_PATTERN.search(content)
        ref_text = ""
        if match:
            ref_text = content[match.end():]
        else:
            match_cite = CITATION_ENTRY_PATTERN.search(content)
            if match_cite:
                ref_text = content[match_cite.start():]

        if not ref_text:
            return ()

        entries: list[str] = []
        for block in ref_text.split("\n\n"):
            block = block.strip()
            if not block or block.startswith("<sup>"):
                continue
            if block.startswith("#") and not any(k in block.lower() for k in ["ref", "bib"]):
                break
            if len(block) >= MIN_REFERENCE_LENGTH:
                entries.append(block)
        return tuple(entries)

    @staticmethod
    def _numbering_style(numbers: list[str]) -> str:
        if any(len(n) > 1 and ROMAN_SECTION_NUMBER.match(n) for n in numbers):
            return "roman"
        if any(ARABIC_SECTION_NUMBER.match(n) for n in numbers):
            return "arabic"
        return ""

    @staticmethod
    def _roman_value(number: str) -> int:
        values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        if not number or any(ch not in values for ch in number):
            return 0
        total = 0
        for index, ch in enumerate(number):
            current = values[ch]
            following = values.get(number[index + 1], 0) if index + 1 < len(number) else 0
            total += -current if current < following else current
        return total

    @classmethod
    def _is_major_section(cls, number: str, title: str, style: str = "", last_major: int = 0) -> bool:
        plain = title.strip().lower().rstrip(".")
        if plain in EXCLUDED_SECTION_TITLES:
            return False

        if number:
            if style == "arabic":
                return bool(ARABIC_SECTION_NUMBER.match(number))
            if style == "roman":
                value = cls._roman_value(number)
                return value > 0 and value == last_major + 1
            if ARABIC_SECTION_NUMBER.match(number) or ROMAN_SECTION_NUMBER.match(number):
                return True

        return plain in MAJOR_SECTION_TITLES

    def _build_sections(self, numbered: list[tuple[int, str]]) -> tuple[Section, ...]:
        style = self._numbering_style(
            [self._split_section_label(text)[0] for _, text in numbered if self._is_heading(text)]
        )

        sections: list[Section] = []
        title, number = "", ""
        pages, parts = [], []
        collecting = False
        stopped = False
        last_major = 0

        def close() -> None:
            if collecting and parts:
                sections.append(
                    Section(
                        no=number,
                        title=title,
                        pages=tuple(sorted(set(pages))),
                        text="\n\n".join(parts).strip(),
                    )
                )

        for page, text in numbered:
            if self._is_heading(text):
                heading_no, heading_title = self._split_section_label(text)
                plain = heading_title.strip().lower().rstrip(".")

                if plain in EXCLUDED_SECTION_TITLES:
                    close()
                    collecting = False
                    stopped = True
                    continue

                if not stopped and self._is_major_section(heading_no, heading_title, style, last_major):
                    close()
                    number, title = heading_no, heading_title
                    if style == "roman":
                        last_major = self._roman_value(heading_no) or last_major
                    pages, parts = [], []
                    collecting = True
                    continue

            if collecting:
                pages.append(page)
                parts.append(text)

        close()
        return tuple(sections)

    @staticmethod
    def _keyword_bucket(title: str) -> str:
        plain = title.strip().lower()
        for bucket, keywords in SECTION_KEYWORDS.items():
            if any(keyword in plain for keyword in keywords):
                return bucket
        return OTHERS_COLUMN

    def _classify_sections(self, title: str, sections: tuple[Section, ...]) -> dict[str, str]:
        fallback = {section.title: self._keyword_bucket(section.title) for section in sections}
        if not sections or not is_available():
            return fallback

        listing = "\n".join(
            f"{index}. {section.no + ' ' if section.no else ''}{section.title}\n"
            f"   opening: {' '.join(section.text.split())[:120]}"
            for index, section in enumerate(sections, start=1)
        )
        try:
            response = chat(
                [
                    {"role": "system", "content": SECTION_CLASSIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Paper title: {title}\n\n[Sections]\n{listing}"},
                ],
                max_tokens=1024,
            )
        except NvidiaServiceError:
            return fallback

        payload = self._parse_classification(response)
        if not payload:
            return fallback

        answers = {
            self._normalize_label(key): str(value).strip().lower()
            for key, value in payload.items()
        }
        allowed = set(IMRAD_COLUMNS) | {OTHERS_COLUMN}

        mapping: dict[str, str] = {}
        for section in sections:
            bucket = answers.get(self._normalize_label(section.title), "")
            mapping[section.title] = bucket if bucket in allowed else fallback[section.title]
        return mapping

    @staticmethod
    def _normalize_label(label: str) -> str:
        stripped = re.sub(r"^\s*(?:\d+(?:\.\d+)*|[IVXLC]{1,5}|[A-Z])[.)]?\s+", "", label.strip())
        return re.sub(r"[^a-z0-9 ]", "", stripped.lower()).strip()

    @staticmethod
    def _parse_classification(response: str) -> dict:
        text = response.strip()
        fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        if not text.startswith("{"):
            brace = re.search(r"\{.*\}", text, re.DOTALL)
            text = brace.group(0) if brace else text
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _to_imrad(
        self, sections: tuple[Section, ...], mapping: dict[str, str]
    ) -> tuple[dict[str, str], dict[str, str]]:
        buckets: dict[str, list[str]] = {name: [] for name in IMRAD_COLUMNS}
        others: dict[str, str] = {}

        for section in sections:
            label = f"{section.no} {section.title}".strip()
            body = f"## {label}\n\n{section.text}"
            target = mapping.get(section.title, OTHERS_COLUMN)
            if target in buckets:
                buckets[target].append(body)
            else:
                others[label] = section.text

        return {name: "\n\n".join(parts) for name, parts in buckets.items()}, others

    def _init_db(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS extracted (
                    id           TEXT PRIMARY KEY,
                    title        TEXT,
                    source_pdf   TEXT,
                    abstract     TEXT,
                    introduction TEXT,
                    related_work TEXT,
                    method       TEXT,
                    experiment   TEXT,
                    result       TEXT,
                    conclusion   TEXT,
                    others       TEXT,
                    content      TEXT,
                    n_pages      INTEGER,
                    n_chars      INTEGER,
                    extractor    TEXT,
                    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

        with closing(sqlite3.connect(self.ref_db_path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS extracted_ref (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id       TEXT,
                    ref_index      INTEGER,
                    reference_text TEXT,
                    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(paper_id) REFERENCES extracted(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_extracted_ref_paper_id ON extracted_ref(paper_id);")

    def _save(self, result: ExtractionResult) -> None:
        self._init_db()

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            existing = conn.execute("SELECT 1 FROM extracted WHERE id = ?", (result.id,)).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE extracted SET
                        title = ?,
                        source_pdf = ?,
                        abstract = ?,
                        introduction = ?,
                        related_work = ?,
                        method = ?,
                        experiment = ?,
                        result = ?,
                        conclusion = ?,
                        others = ?,
                        content = ?,
                        n_pages = ?,
                        n_chars = ?,
                        extractor = ?,
                        created_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        result.title,
                        result.source_pdf,
                        *[result.columns.get(name, "") for name in IMRAD_COLUMNS],
                        json.dumps(result.others, ensure_ascii=False),
                        result.content,
                        result.n_pages,
                        result.n_chars,
                        result.extractor,
                        result.id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO extracted 
                    (id, title, source_pdf, abstract, introduction, related_work, method, 
                     experiment, result, conclusion, others, content, 
                     n_pages, n_chars, extractor, created_at) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        result.id,
                        result.title,
                        result.source_pdf,
                        *[result.columns.get(name, "") for name in IMRAD_COLUMNS],
                        json.dumps(result.others, ensure_ascii=False),
                        result.content,
                        result.n_pages,
                        result.n_chars,
                        result.extractor,
                    ),
                )

        with closing(sqlite3.connect(self.ref_db_path)) as conn, conn:
            conn.execute("DELETE FROM extracted_ref WHERE paper_id = ?", (result.id,))
            for idx, ref_text in enumerate(result.references, start=1):
                conn.execute(
                    "INSERT INTO extracted_ref (paper_id, ref_index, reference_text) VALUES (?, ?, ?)",
                    (result.id, idx, ref_text)
                )

        self._rebuild_json()

    def _rebuild_json(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute("SELECT id, title FROM extracted ORDER BY created_at DESC").fetchall()

        refs_map: dict[str, list[str]] = {}
        if self.ref_db_path.is_file():
            with closing(sqlite3.connect(self.ref_db_path)) as conn:
                ref_rows = conn.execute(
                    "SELECT paper_id, reference_text FROM extracted_ref WHERE paper_id IS NOT NULL ORDER BY paper_id, ref_index"
                ).fetchall()
                for p_id, r_text in ref_rows:
                    refs_map.setdefault(p_id, []).append(r_text)

        payload = {
            row[0]: {
                "id": row[0],
                "title": row[1],
                "reference_pdf": refs_map.get(row[0], []),
            }
            for row in rows
        }
        self.json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")

# ---------------------------------------------------------------------
# [Class 2: PaperExtraRAGBot - 대화형 탐색 및 백그라운드 번역/요약 챗봇]
# ---------------------------------------------------------------------
class PaperExtraRAGBot:
    """내 서재 대용량 논문 조회, 키워드 검색 추천, 백그라운드 마크다운 번역 및 요약 수행 챗봇"""

    def __init__(self, data_dir: Optional[str] = None):
        root_data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "paper_list"
        self.data_dir = data_dir or str(root_data_dir)
        self.db_file = os.path.join(self.data_dir, "saved_papers.db")
        self.json_file = os.path.join(self.data_dir, "saved_papers.json")
        self.output_dir = os.path.join(self.data_dir, "processed_outputs")
        os.makedirs(self.output_dir, exist_ok=True)

        self.logger = AppLogger(__name__)
        self.llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0)

        self.candidate_papers: List[Dict[str, Any]] = []
        self.selected_papers: List[Dict[str, Any]] = []
        self.current_page: int = 1
        self.page_size: int = 10

    @staticmethod
    def _safe_filename(title: str) -> str:
        """윈도우 파일 시스템 제약(길이 제한, 특수문자)에 안전한 파일명을 생성한다."""
        cleaned = re.sub(r'[\\/*?:"<>|]', "", title)
        cleaned = "_".join(cleaned.split())
        return cleaned[:50].strip("_")

    def _get_db_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_file)

    def _ensure_paper_extracted(self, paper_id: str) -> str:
        extractor = PaperExtractor()
        if not extractor.is_extracted(paper_id):
            if not DEFAULT_PDF_DIR.is_dir() or not any(DEFAULT_PDF_DIR.glob("*.pdf")):
                print("\n[System] 현재 data/paper_save 디렉토리에 처리할 PDF 논문 파일이 존재하지 않습니다.")
                print("[System] 먼저 논문 검색 및 다운로드를 진행해 주세요.")

            print(f"\n[System] '{paper_id}' PDF 본문 전체 및 인용문헌 DB 추출을 진행합니다...")
            try:
                extractor.extract(paper_id)
                print(f"[System] DB 매핑 완료 (본문: extracted_papers.db / 인용문헌: extracted_papers_ref.db)")
            except Exception as e:
                print(f"[System] PDF 원문 추출 오류 발생: {e}")

        record = extractor.get(paper_id)
        if record and record.get("content"):
            return record["content"]

        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT title, summary FROM papers WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return f"Title: {row[0]}\n\nSummary:\n{row[1]}"
        return ""

    def fetch_papers_paginated(self, page: int = 1, page_size: int = 10) -> tuple[List[Dict[str, Any]], int]:
        if not os.path.exists(self.db_file):
            return [], 0

        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM papers")
            total_count = cursor.fetchone()[0]

            offset = (page - 1) * page_size
            cursor.execute(
                "SELECT id, title, authors, summary, pdf_url, created_at FROM papers ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (page_size, offset)
            )
            rows = cursor.fetchall()
            conn.close()

            papers = [
                {
                    "id": r[0],
                    "title": r[1],
                    "authors": r[2],
                    "summary": r[3],
                    "pdf_url": r[4],
                    "created_at": r[5]
                }
                for r in rows
            ]
            return papers, total_count
        except Exception as e:
            self.logger.log(
                LogCode.PAPER_SAVE_FAILED,
                stage="fetch_papers_paginated",
                error_type=type(e).__name__,
                error=str(e)
            )
            return [], 0

    def search_papers_by_keyword(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        if not os.path.exists(self.db_file) or not keyword:
            return []

        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            query_param = f"%{keyword}%"
            cursor.execute(
                "SELECT id, title, authors, summary, pdf_url FROM papers WHERE title LIKE ? OR summary LIKE ? ORDER BY created_at DESC LIMIT ?",
                (query_param, query_param, limit)
            )
            rows = cursor.fetchall()
            conn.close()

            return [
                {"id": r[0], "title": r[1], "authors": r[2], "summary": r[3], "pdf_url": r[4]}
                for r in rows
            ]
        except Exception as e:
            self.logger.log(
                LogCode.PAPER_SEARCH_FAILED,
                stage="search_papers_by_keyword",
                keyword=keyword,
                error=str(e)
            )
            return []

    def parse_intent(self, user_input: str) -> UserIntent:
        structured_llm = self.llm.with_structured_output(UserIntent)
        prompt = (
            f"사용자의 의도를 정밀하게 분석해주세요.\n"
            f"- 입력 문장: {user_input}\n"
            f"- 현재 후보 목록 존재 여부: {len(self.candidate_papers) > 0}개\n"
            f"- 현재 선택된 논문 존재 여부: {len(self.selected_papers) > 0}개\n\n"
            f"[의도 분류 기준]\n"
            f"1. list: '리스트', '목록', '나 뭐 갖고 있어?', '저장된 논문' 등\n"
            f"  * 주의: 사용자가 특정 개수(예: '20개 보여줘')를 원하면 'list_count'에 숫자를, '전부/모두 다 보여줘'라면 'show_all_list'를 True로 설정하세요.\n"
            f"2. search: 특정 연구 주제/키워드로 검색을 요청하는 경우\n"
            f"3. select_paper: 특정 번호(예: '3번', '1, 3번') 또는 '모두', '전부', '다' 등의 선택 표현\n"
            f"4. action: '번역', '요약', '번역하고 요약' 등 작업 요청 또는 '요약', '번역' 단독 입력\n"
            f"5. page: '다음', '이전' 등 목록 페이지 이동\n"
            f"6. location: 저장 위치/경로 문의\n"
            f"7. exit: '종료', '그만', 'q' 등"
        )
        try:
            return structured_llm.invoke(prompt)
        except Exception:
            return UserIntent(intent_type="unknown")

    def display_paper_list(self, papers: List[Dict[str, Any]], title: str, total_count: Optional[int] = None):
        if not papers:
            print("\n[System] 조건에 해당하는 논문이 없습니다.")
            return

        header = f"\n{title}"
        if total_count is not None:
            total_pages = (total_count + self.page_size - 1) // self.page_size if self.page_size > 0 else 1
            current_page_display = self.current_page
            header += f" (페이지 {current_page_display}/{total_pages} | 총 {total_count}건)"

        print(header)
        print("=" * 70)
        for idx, p in enumerate(papers, 1):
            display_idx = ((self.current_page - 1) * self.page_size) + idx
            print(f"{display_idx}. [{p['id']}] {p['title']}")
            print(f"   - 저자: {p['authors']}")
            print(f"   - 요약: {p['summary'][:120]}...")
            print("-" * 70)

    def execute_translation(self, paper: Dict[str, Any]) -> str:
        full_content = self._ensure_paper_extracted(paper["id"])

        self.logger.log(LogCode.TRANSLATION_STARTED, action="translate_full_md", paper_id=paper["id"])
        print(f"[System] '{paper['title']}' 본문 전체 마크다운 번역 실행 중...")

        prompt = ChatPromptTemplate.from_messages([
            ("system", "당신은 학술 논문 전문 번역가입니다. 제공된 논문 본문을 과도한 부연 설명 없이 핵심 논지와 구조를 살려 간결하고 자연스러운 학술 한국어로 번역하세요. 마크다운(# 헤더) 형식을 유지하되, 모든 수식은 줄바꿈 없이 한 줄($...$)로 정돈하여 출력하세요."),
            ("user", "논문 제목: {title}\n\n[본문 전체 내용]\n{content}")
        ])
        chain = prompt | self.llm
        res = chain.invoke({"title": paper["title"], "content": full_content})

        translated_text = res.content
        safe_title = self._safe_filename(paper["title"])

        os.makedirs(self.output_dir, exist_ok=True)
        out_path = os.path.join(self.output_dir, f"{safe_title}_full_translated.md")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# 원제: {paper['title']}\n\n[본문 전체 마크다운 번역 결과]\n\n{translated_text}")

        print(f"[System] 번역 완료 및 마크다운 저장 (저장 경로: {out_path})")
        return translated_text

    def execute_summary(self, paper: Dict[str, Any], translated_text: Optional[str] = None) -> str:
        full_content = translated_text if translated_text else self._ensure_paper_extracted(paper["id"])

        self.logger.log(LogCode.SUMMARY_STARTED, action="summarize", paper_id=paper["id"])
        print(f"[System] '{paper['title']}' 핵심 요약 보고서 생성 실행 중...")

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "당신은 수석 연구원입니다. 아래 논문 내용을 바탕으로 4개 항목"
             "(1. 연구 배경 및 목적, 2. 핵심 방법론 및 아키텍처, 3. 주요 실험 성과, "
             "4. 연구의 시사점 및 한계점)으로 심층 요약하세요.\n"
             "수식은 반드시 달러 기호로 감쌉니다. 문장 안에서는 $...$ 로, "
             "독립된 줄에서는 $$...$$ 로 씁니다. "
             "\\( \\) 나 \\[ \\] 표기는 절대 쓰지 않습니다."),
            ("user", "논문 제목: {title}\n\n{content}")
        ])
        chain = prompt | self.llm
        res = chain.invoke({"title": paper["title"], "content": full_content})

        summary_text = res.content
        safe_title = self._safe_filename(paper["title"])

        os.makedirs(self.output_dir, exist_ok=True)
        out_path = os.path.join(self.output_dir, f"{safe_title}_summary.md")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# {paper['title']} 요약본\n\n{summary_text}")

        print(f"[System] 요약 완료 및 마크다운 저장 (저장 경로: {out_path})")
        return summary_text

    def _process_batch_actions(self, target_papers: List[Dict[str, Any]], act: str):
        print(f"\n[System] 총 {len(target_papers)}편의 논문에 대해 일괄 변환을 시작합니다. (작업: {act})")

        for idx, paper in enumerate(target_papers, 1):
            print(f"\n-------------------- [{idx}/{len(target_papers)}] {paper['title']} --------------------")

            safe_title = self._safe_filename(paper["title"])
            trans_path = os.path.join(self.output_dir, f"{safe_title}_full_translated.md")
            summ_path = os.path.join(self.output_dir, f"{safe_title}_summary.md")

            file_exists = False
            if act == "translate" and os.path.exists(trans_path):
                file_exists = True
            elif act == "summarize" and os.path.exists(summ_path):
                file_exists = True
            elif act == "both" and (os.path.exists(trans_path) or os.path.exists(summ_path)):
                file_exists = True

            if file_exists:
                print(f"[System] 번역 요약이 완료되었습니다.")
                ans = input("기존의 파일을 삭제하고 다시 번역 요약해드릴까요? (예/아니오): ").strip().lower()

                if not any(w in ans for w in ["예", "응", "y", "yes", "네", "진행"]):
                    print("[System] 기존 파일을 유지하며, 해당 논문의 작업을 건너뜁니다.")
                    continue

            translated = None
            if act in ["translate", "both"]:
                translated = self.execute_translation(paper)
            if act in ["summarize", "both"]:
                self.execute_summary(paper, translated)

        print(f"\n요청하신 {len(target_papers)}편의 일괄 변환 작업이 모두 완료되었습니다!")

    def run(self):
        print("=" * 70)
        print("학술 서재 RAG 대화형 서비스 (파일명 정규화 및 마크다운 번역)")
        print("=" * 70)
        print("무엇을 도와드릴까요? (예: '나 무슨 논문 갖고 있어?', 'AI 관련 논문 찾아줘')\n")

        while True:
            try:
                user_input = input("[User]: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n[System] 서비스를 종료합니다.")
                break

            if not user_input:
                continue

            intent = self.parse_intent(user_input)

            if intent.intent_type == "exit":
                print("\n[System] 이용해 주셔서 감사합니다. 대화를 종료합니다.")
                break

            elif intent.intent_type == "list":
                if getattr(intent, 'show_all_list', False):
                    self.page_size = 99
                elif getattr(intent, 'list_count', None):
                    self.page_size = min(intent.list_count, 99)
                else:
                    self.page_size = 10

                self.current_page = 1
                papers, total_count = self.fetch_papers_paginated(self.current_page, self.page_size)
                self.candidate_papers = papers
                self.selected_papers = []
                self.display_paper_list(self.candidate_papers, "보유 중인 논문 목록", total_count)
                print("\n원하시는 논문의 번호를 선택하거나('모두', '3번' 등), 키워드를 입력해 주세요.")

            elif intent.intent_type == "page":
                if getattr(intent, 'list_count', None):
                    self.page_size = min(intent.list_count, 99)

                if intent.page_direction == "next":
                    self.current_page += 1
                elif intent.page_direction == "prev" and self.current_page > 1:
                    self.current_page -= 1

                papers, total_count = self.fetch_papers_paginated(self.current_page, self.page_size)
                if papers:
                    self.candidate_papers = papers
                    self.selected_papers = []
                    self.display_paper_list(self.candidate_papers, "보유 중인 논문 목록", total_count)
                else:
                    print("\n[System] 더 이상 표시할 논문이 없습니다.")
                    self.current_page = max(1, self.current_page - 1)

            elif intent.intent_type == "location" or any(w in user_input for w in ["위치", "경로", "어디"]):
                print("\n**현재 시스템 저장 위치 안내**")
                print(f" 메타데이터 DB: {self.db_file}")
                print(f" 목록 JSON: {self.json_file}")
                print(f" 번역/요약 결과 저장 폴더: {self.output_dir} (마크다운 .md 형식)")
                print(f" 추출 본문 DB: {DEFAULT_OUTPUT_DIR / 'extracted_papers.db'}")
                print(f" 인용문헌 DB: {DEFAULT_OUTPUT_DIR / 'extracted_papers_ref.db'}")
                print(f" 원본 PDF 저장 폴더: {DEFAULT_PDF_DIR}")

            elif intent.intent_type in ["search", "select_paper", "action"] or any(w in user_input for w in ["모두", "전부", "다", "전체", "번역", "요약"]):

                if intent.keyword:
                    matched = self.search_papers_by_keyword(intent.keyword)
                    if matched:
                        self.candidate_papers = matched
                        self.selected_papers = []
                        self.display_paper_list(self.candidate_papers, f"'{intent.keyword}' 관련 탐색 결과")
                    else:
                        print(f"\n서재에서 '{intent.keyword}' 관련 논문을 찾지 못했습니다.")
                        continue

                if not self.candidate_papers and not self.selected_papers:
                    papers, total_count = self.fetch_papers_paginated(self.current_page, self.page_size)
                    self.candidate_papers = papers

                if intent.select_all or any(w in user_input for w in ["모두", "전부", "다", "전체"]):
                    if self.candidate_papers:
                        self.selected_papers = self.candidate_papers
                    else:
                        print("\n[System] 현재 서재에 저장된 논문이 존재하지 않습니다. 먼저 논문 검색 및 다운로드를 진행해 주세요.")
                        continue
                elif intent.selected_indices:
                    if self.candidate_papers:
                        valid_papers = []
                        invalid_indices = []
                        for i in intent.selected_indices:
                            # 실제 배열 인덱스 매핑 보정
                            actual_index = i - ((self.current_page - 1) * self.page_size) - 1
                            if 0 <= actual_index < len(self.candidate_papers):
                                valid_papers.append(self.candidate_papers[actual_index])
                            else:
                                invalid_indices.append(i)

                        if invalid_indices:
                            print(f"\n[System] 입력하신 번호 {invalid_indices}번은 현재 목록에 존재하지 않습니다.")
                            print("[System] '리스트 보여줘'를 통해 목록을 확인하신 후 올바른 번호를 선택해 주세요.")

                        if valid_papers:
                            self.selected_papers = valid_papers
                        else:
                            continue
                    else:
                        print("\n[System] 선택 가능한 논문 목록이 없습니다. 먼저 논문 목록을 불러와 주세요.")
                        continue

                act = intent.action_type
                if not act:
                    if "번역" in user_input and "요약" in user_input:
                        act = "both"
                    elif "요약" in user_input:
                        act = "summarize"
                    elif "번역" in user_input:
                        act = "translate"

                if not self.selected_papers and self.candidate_papers:
                    digits = [int(s) for s in re.findall(r'\d+', user_input)]
                    if digits:
                        valid_papers = []
                        invalid_digits = []
                        for d in digits:
                            actual_index = d - ((self.current_page - 1) * self.page_size) - 1
                            if 0 <= actual_index < len(self.candidate_papers):
                                valid_papers.append(self.candidate_papers[actual_index])
                            else:
                                invalid_digits.append(d)

                        if invalid_digits:
                            print(f"\n[System] 입력하신 번호 {invalid_digits}번은 현재 목록에 존재하지 않습니다.")
                            print("[System] 목록에 존재하는 논문 번호를 선택해 주세요.")

                        if valid_papers:
                            self.selected_papers = valid_papers

                if self.selected_papers and act:
                    self._process_batch_actions(self.selected_papers, act)
                    self.selected_papers = []
                elif self.selected_papers and not act:
                    print(f"\n총 {len(self.selected_papers)}편의 논문이 선택되었습니다. **무엇을 변환 시켜 드릴까요?** ('번역', '요약', '번역과 요약')")
                elif not self.selected_papers and act:
                    print(f"\n먼저 유효한 논문 번호를 선택해 주세요. (예: '1번', '3번', '모두')")
                elif not self.selected_papers and not intent.keyword:
                    print("\n원하시는 논문 번호를 선택해 주세요. (예: '1번', '1, 3번', '모두')")

            else:
                print("\n죄송합니다. 잘 이해하지 못했습니다.")
                print("   '리스트 보여줘', '특정 키워드 검색', 또는 '1번 번역 및 요약', '모두 번역 요약'으로 요청해 주세요.")

# ---------------------------------------------------------------------
# [LangChain 에이전트 전용 툴 정의]
# ---------------------------------------------------------------------
@tool
def extract_paper_text(paper_ids: list[str]) -> dict:
    """사용자가 고른 논문 PDF의 본문을 가공해 DB에 직접 저장한다."""
    extractor = PaperExtractor()
    results = extractor.extract_many(paper_ids)
    return {
        "extracted": [
            {
                "id": result.id,
                "title": result.title,
                "n_pages": result.n_pages,
                "n_chars": result.n_chars,
                "skipped": result.skipped,
            }
            for result in results
        ],
        "failed": [pid for pid in paper_ids if pid not in {r.id for r in results}],
    }

# ---------------------------------------------------------------------
# [실행 메인 엔트리포인트]
# ---------------------------------------------------------------------
if __name__ == "__main__":
    bot = PaperExtraRAGBot()
    bot.run()