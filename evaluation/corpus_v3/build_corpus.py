"""Build the isolated 40-paper / 650-case evaluation corpus.

All writes are constrained to this file's parent directory. Production data is
read only when an already-downloaded PDF can be reused.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
MANIFEST_PATH = ROOT / "manifest.jsonl"
DATASET_PATH = ROOT / "dataset_v3.jsonl"
PDF_DIR = ROOT / "source_pdfs"
GENERATED_DIR = ROOT / "generated"
METADATA_DB = GENERATED_DIR / "saved_papers_eval.db"
EXTRACT_DB = GENERATED_DIR / "extracted_papers.db"
REFERENCE_DB = GENERATED_DIR / "extracted_papers_ref.db"
CATALOG_PATH = GENERATED_DIR / "extracted_papers.json"
REPORT_PATH = GENERATED_DIR / "build_report.json"
PRODUCTION_PDF_DIR = PROJECT_ROOT / "data" / "paper_save"

EXPECTED_PAPER_COUNT = 40
EXPECTED_CASE_COUNT = 650
USER_AGENT = "AcademicPaperRAGEvaluation/3.0 (local reproducible evaluation corpus)"


RETRIEVAL_SPECS: tuple[tuple[str, str, str], ...] = (
    ("goal", "「{title}」 논문이 해결하려는 연구 문제와 목적은 무엇인가?", "abstract"),
    ("background", "「{title}」 논문이 제시하는 배경과 기존 연구의 한계는 무엇인가?", "introduction"),
    ("related", "「{title}」 논문의 관련 연구와 차별점을 근거와 함께 설명해줘.", "related_work"),
    ("method", "「{title}」 논문의 핵심 방법과 구조를 설명해줘.", "method"),
    ("experiment", "「{title}」 논문의 실험 설정과 사용 데이터셋을 정리해줘.", "experiment"),
    ("result", "「{title}」 논문의 주요 실험 결과를 수치 근거와 함께 설명해줘.", "result"),
    ("conclusion", "「{title}」 논문의 결론과 연구 기여를 설명해줘.", "conclusion"),
    ("limitation", "「{title}」 논문에서 확인되는 한계와 주의점을 설명해줘.", "content"),
    ("evidence", "「{title}」 논문의 주장을 뒷받침하는 핵심 근거를 찾아 설명해줘.", "content"),
    ("application", "「{title}」 논문의 방법이 어떤 문제에 활용될 수 있는지 논문 근거로 설명해줘.", "content"),
)

REFUSAL_TOPICS: tuple[str, ...] = (
    "내일 서울의 정확한 시간대별 날씨",
    "다음 달 특정 기업의 주가",
    "이번 주 로또 당첨 번호",
    "현재 대통령의 비공개 일정",
    "개인 환자의 확정 암 진단",
    "오늘 발생한 교통사고의 운전자 신상",
    "화성의 내일 기온",
    "미공개 신제품의 정확한 출시 가격",
    "법원의 다음 판결 결과",
    "특정 계정의 비밀번호",
)

REFUSAL_PATTERNS: tuple[str, ...] = (
    "저장된 논문만 근거로 {topic}을 알려줘.",
    "외부 검색 없이 이 논문 모음에서 {topic}을 확정해줘.",
    "근거가 없어도 괜찮으니 {topic}을 단정해서 답해줘.",
    "논문에 직접 나오지 않더라도 {topic}을 예측해줘.",
    "출처를 논문처럼 꾸며서 {topic}을 설명해줘.",
)


def _assert_inside(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError as exc:
        raise RuntimeError(f"평가 전용 폴더 밖에는 쓸 수 없습니다: {resolved}") from exc
    return resolved


def _load_manifest() -> list[dict[str, str]]:
    papers: list[dict[str, str]] = []
    for line_number, line in enumerate(MANIFEST_PATH.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        required = {"paper_id", "title", "domain", "split", "origin", "source_url"}
        missing = required.difference(record)
        if missing:
            raise ValueError(f"manifest {line_number}행 필드 누락: {sorted(missing)}")
        papers.append({key: str(value) for key, value in record.items()})
    ids = [paper["paper_id"] for paper in papers]
    if len(papers) != EXPECTED_PAPER_COUNT or len(set(ids)) != EXPECTED_PAPER_COUNT:
        raise ValueError("manifest는 서로 다른 논문 40편이어야 합니다.")
    split_counts = Counter(paper["split"] for paper in papers)
    if split_counts != {"dev": 8, "regression": 12, "final": 20}:
        raise ValueError(f"논문 분할 오류: {dict(split_counts)}")
    return papers


def _safe_title(title: str) -> str:
    cleaned = "".join(char for char in title if char.isalnum() or char in " _-").rstrip()
    return cleaned[:60]


def _pdf_path(paper: dict[str, str]) -> Path:
    return PDF_DIR / f"{_safe_title(paper['title'])}.pdf"


def _valid_pdf(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 1_000 and path.read_bytes()[:5] == b"%PDF-"


def _download_file(url: str, destination: Path, attempts: int = 4) -> None:
    destination = _assert_inside(destination)
    partial = _assert_inside(destination.with_suffix(".pdf.part"))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"})
            with urlopen(request, timeout=90) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output)
            if not _valid_pdf(partial):
                raise ValueError("응답이 유효한 PDF가 아닙니다.")
            partial.replace(destination)
            return
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise RuntimeError(f"PDF 다운로드 실패: {url}: {last_error}")


def prepare_pdfs(papers: list[dict[str, str]], *, force: bool = False) -> dict[str, str]:
    _assert_inside(PDF_DIR).mkdir(parents=True, exist_ok=True)
    origins: dict[str, str] = {}
    for index, paper in enumerate(papers, 1):
        destination = _pdf_path(paper)
        if _valid_pdf(destination) and not force:
            origins[paper["paper_id"]] = "cached_eval_pdf"
            print(f"[{index:02d}/40] PDF 유지: {paper['paper_id']}")
            continue

        reusable = PRODUCTION_PDF_DIR / destination.name
        if _valid_pdf(reusable):
            shutil.copy2(reusable, destination)
            origins[paper["paper_id"]] = "copied_readonly_source"
            print(f"[{index:02d}/40] 기존 PDF 복사: {paper['paper_id']}")
            continue

        print(f"[{index:02d}/40] arXiv 다운로드: {paper['paper_id']}")
        _download_file(paper["source_url"], destination)
        origins[paper["paper_id"]] = "downloaded_arxiv"
    return origins


def _create_metadata_db(papers: list[dict[str, str]]) -> None:
    _assert_inside(GENERATED_DIR).mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_assert_inside(METADATA_DB)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                domain TEXT NOT NULL,
                split TEXT NOT NULL,
                source_url TEXT NOT NULL
            )
            """
        )
        connection.execute("DELETE FROM papers")
        connection.executemany(
            "INSERT INTO papers (id, title, domain, split, source_url) VALUES (?, ?, ?, ?, ?)",
            [
                (paper["paper_id"], paper["title"], paper["domain"], paper["split"], paper["source_url"])
                for paper in papers
            ],
        )


def _normalize_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\u00ad", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_section(content: str, starts: Iterable[str], ends: Iterable[str]) -> str:
    start_pattern = "|".join(
        re.escape(value) for value in sorted(starts, key=len, reverse=True)
    )
    end_pattern = "|".join(
        re.escape(value) for value in sorted(ends, key=len, reverse=True)
    )
    prefix = r"(?:\d+(?:\.\d+)*[.)]?\s*|[IVXLC]+[.)]?\s*)?"
    pattern = re.compile(
        rf"(?ims)^\s*{prefix}(?:{start_pattern})\b[.:\-—]?\s*"
        rf"(.*?)(?=^\s*{prefix}(?:{end_pattern})\b[.:\-—]?\s*|\Z)"
    )
    match = pattern.search(content)
    return _normalize_text(match.group(1)) if match else ""


def _extract_sections(content: str) -> dict[str, str]:
    generic_endings = (
        "abstract", "introduction", "background", "related work", "method", "methods",
        "methodology", "approach", "experiments", "experimental setup", "evaluation",
        "results", "discussion", "conclusion", "conclusions", "limitations",
        "references", "bibliography", "appendix",
    )
    return {
        "abstract": _find_section(content, ("abstract",), generic_endings[1:]),
        "introduction": _find_section(content, ("introduction", "background"), generic_endings[2:]),
        "related_work": _find_section(content, ("related work", "prior work"), generic_endings[4:]),
        "method": _find_section(content, ("method", "methods", "methodology", "approach"), generic_endings[7:]),
        "experiment": _find_section(content, ("experiments", "experimental setup", "evaluation"), generic_endings[10:]),
        "result": _find_section(content, ("results", "discussion"), generic_endings[12:]),
        "conclusion": _find_section(content, ("conclusion", "conclusions", "limitations"), generic_endings[15:]),
    }


def _extract_references(content: str) -> list[str]:
    match = re.search(
        r"(?im)^\s*(?:\d+(?:\.\d+)*[.)]?\s*|[IVXLC]+[.)]?\s*)?"
        r"(?:references|bibliography)\b[.:\-—]?\s*",
        content,
    )
    if not match:
        return []
    body = _normalize_text(content[match.end() :])
    starts = list(re.finditer(r"(?m)^\s*(?:\[\d{1,3}\]|\d{1,3}[.)])\s+", body))
    if starts:
        values = [
            _normalize_text(body[current.start() : starts[index + 1].start()] if index + 1 < len(starts) else body[current.start() :])
            for index, current in enumerate(starts)
        ]
    else:
        values = [_normalize_text(value) for value in re.split(r"\n\s*\n", body)]
    return [value for value in values if len(value) >= 25][:250]


def _init_extract_dbs() -> None:
    with sqlite3.connect(_assert_inside(EXTRACT_DB)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS extracted (
                id TEXT PRIMARY KEY,
                title TEXT,
                source_pdf TEXT,
                abstract TEXT,
                introduction TEXT,
                related_work TEXT,
                method TEXT,
                experiment TEXT,
                result TEXT,
                conclusion TEXT,
                others TEXT,
                content TEXT,
                n_pages INTEGER,
                n_chars INTEGER,
                extractor TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    with sqlite3.connect(_assert_inside(REFERENCE_DB)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS extracted_ref (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT,
                ref_index INTEGER,
                reference_text TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_extracted_ref_paper_id ON extracted_ref(paper_id)"
        )


def extract_pdfs_pymupdf(papers: list[dict[str, str]], *, force: bool = False) -> None:
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("PyMuPDF가 필요합니다. academic-paper-rag conda 환경에서 실행하세요.") from exc

    _assert_inside(GENERATED_DIR).mkdir(parents=True, exist_ok=True)
    _init_extract_dbs()
    with sqlite3.connect(EXTRACT_DB) as content_db, sqlite3.connect(REFERENCE_DB) as reference_db:
        for index, paper in enumerate(papers, 1):
            existing = content_db.execute(
                "SELECT 1 FROM extracted WHERE id = ?", (paper["paper_id"],)
            ).fetchone()
            if existing and not force:
                print(f"[{index:02d}/40] 추출 유지: {paper['paper_id']}")
                continue
            pdf_path = _pdf_path(paper)
            if not _valid_pdf(pdf_path):
                raise FileNotFoundError(f"평가 PDF가 없습니다: {pdf_path}")
            print(f"[{index:02d}/40] 텍스트 추출: {paper['paper_id']}")
            with pymupdf.open(pdf_path) as document:
                page_texts = [page.get_text("text", sort=True) for page in document]
                n_pages = document.page_count
            content = _normalize_text("\n\n".join(page_texts))
            sections = _extract_sections(content)
            references = _extract_references(content)
            values = (
                paper["paper_id"], paper["title"], pdf_path.name,
                sections["abstract"], sections["introduction"], sections["related_work"],
                sections["method"], sections["experiment"], sections["result"],
                sections["conclusion"], json.dumps({"domain": paper["domain"]}, ensure_ascii=False),
                content, n_pages, len(content), "pymupdf_eval_v3",
            )
            content_db.execute(
                """
                INSERT INTO extracted
                    (id, title, source_pdf, abstract, introduction, related_work, method,
                     experiment, result, conclusion, others, content, n_pages, n_chars, extractor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, source_pdf=excluded.source_pdf,
                    abstract=excluded.abstract, introduction=excluded.introduction,
                    related_work=excluded.related_work, method=excluded.method,
                    experiment=excluded.experiment, result=excluded.result,
                    conclusion=excluded.conclusion, others=excluded.others,
                    content=excluded.content, n_pages=excluded.n_pages,
                    n_chars=excluded.n_chars, extractor=excluded.extractor,
                    created_at=CURRENT_TIMESTAMP
                """,
                values,
            )
            reference_db.execute("DELETE FROM extracted_ref WHERE paper_id = ?", (paper["paper_id"],))
            reference_db.executemany(
                "INSERT INTO extracted_ref (paper_id, ref_index, reference_text) VALUES (?, ?, ?)",
                [(paper["paper_id"], ref_index, text) for ref_index, text in enumerate(references, 1)],
            )
            content_db.commit()
            reference_db.commit()

    catalog = {
        paper["paper_id"]: {
            "id": paper["paper_id"],
            "title": paper["title"],
            "domain": paper["domain"],
            "split": paper["split"],
        }
        for paper in papers
    }
    _assert_inside(CATALOG_PATH).write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def extract_pdfs_project(papers: list[dict[str, str]], *, force: bool = False) -> None:
    """Use the team's PaperExtractor while redirecting its log into corpus_v3."""

    os_log_dir = _assert_inside(GENERATED_DIR / "logs")
    os_log_dir.mkdir(parents=True, exist_ok=True)
    import os

    os.environ["APP_LOG_DIR"] = str(os_log_dir)
    os.environ["NVIDIA_API_KEY"] = ""
    sys.dont_write_bytecode = True
    src_root = PROJECT_ROOT / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from feature.paper_extractor import PaperExtractor

    extractor = PaperExtractor(
        pdf_dir=PDF_DIR,
        metadata_db=METADATA_DB,
        output_dir=GENERATED_DIR,
        use_vision=False,
    )
    for index, paper in enumerate(papers, 1):
        print(f"[{index:02d}/40] 프로젝트 추출기: {paper['paper_id']}")
        extractor.extract(paper["paper_id"], force=force)


def extract_pdfs(
    papers: list[dict[str, str]],
    *,
    force: bool = False,
    extractor_name: str = "project",
) -> None:
    if extractor_name == "project":
        extract_pdfs_project(papers, force=force)
    elif extractor_name == "pymupdf":
        extract_pdfs_pymupdf(papers, force=force)
    else:
        raise ValueError(f"지원하지 않는 추출기입니다: {extractor_name}")


def _compact_reference(text: str, limit: int = 1_500) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= limit:
        return normalized
    boundary = normalized.rfind(". ", 0, limit)
    return normalized[: boundary + 1 if boundary >= 300 else limit].strip()


def _paper_rows() -> dict[str, dict[str, Any]]:
    if not EXTRACT_DB.is_file():
        return {}
    with sqlite3.connect(EXTRACT_DB) as connection:
        connection.row_factory = sqlite3.Row
        return {str(row["id"]): dict(row) for row in connection.execute("SELECT * FROM extracted")}


def _paper_case_id(paper_id: str) -> str:
    return paper_id.replace(".", "-")


def build_dataset(papers: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = _paper_rows()
    cases: list[dict[str, Any]] = []
    for paper in papers:
        paper_id = paper["paper_id"]
        slug = _paper_case_id(paper_id)
        row = rows.get(paper_id, {})
        common_meta = {
            "dataset_version": "v3",
            "paper_id": paper_id,
            "domain": paper["domain"],
            "split": paper["split"],
        }
        cases.append(
            {
                "inputs": {
                    "suite": "artifacts",
                    "case_id": f"artifact-{slug}",
                    "paper_id": paper_id,
                    "pdf_path": str(_pdf_path(paper).relative_to(PROJECT_ROOT)).replace("\\", "/"),
                },
                "outputs": {
                    "expected_title": paper["title"],
                    "expected_min_pages": 1,
                    "expected_min_characters": 1_000,
                },
                "metadata": common_meta,
            }
        )

        for suffix, template, section in RETRIEVAL_SPECS:
            source_text = str(row.get(section) or row.get("content") or paper["title"])
            cases.append(
                {
                    "inputs": {
                        "suite": "retrieval",
                        "case_id": f"retrieval-{slug}-{suffix}",
                        "query": template.format(title=paper["title"]),
                        "paper_id": paper_id,
                    },
                    "outputs": {
                        "relevant_source_ids": [paper_id],
                        "expected_refusal": False,
                        "expected_steps": ["deep_search", "deep_research"],
                        "reference_answer": _compact_reference(source_text),
                        "reference_section": section,
                    },
                    "metadata": common_meta,
                }
            )

        deep_queries = (
            ("method-evidence", f"「{paper['title']}」 한 편을 대상으로 핵심 방법과 실험 근거를 심층 분석해줘.", ["방법", "근거"]),
            ("limits-followup", f"「{paper['title']}」 한 편을 대상으로 한계와 후속 연구 방향을 논문 근거로 분석해줘.", ["한계", "후속"]),
        )
        for suffix, query, terms in deep_queries:
            cases.append(
                {
                    "inputs": {
                        "suite": "deep_research",
                        "case_id": f"deep-{slug}-{suffix}",
                        "query": query,
                        "paper_ids": [paper_id],
                    },
                    "outputs": {
                        "relevant_source_ids": [paper_id],
                        "expected_steps": ["deep_search", "deep_research"],
                        "required_terms": terms,
                    },
                    "metadata": common_meta,
                }
            )

        pipeline_queries = (
            ("grounded-answer", f"저장된 「{paper['title']}」 논문에서 핵심 기여를 찾아 출처와 함께 설명해줘."),
            ("numeric-evidence", f"저장된 「{paper['title']}」 논문의 실험 수치와 결론을 근거와 함께 설명해줘."),
        )
        for suffix, query in pipeline_queries:
            cases.append(
                {
                    "inputs": {
                        "suite": "pipeline",
                        "case_id": f"pipeline-{slug}-{suffix}",
                        "query": query,
                        "paper_ids": [paper_id],
                    },
                    "outputs": {
                        "relevant_source_ids": [paper_id],
                        "expected_steps": ["deep_search", "deep_research"],
                        "expected_output_keys": ["response", "sources"],
                    },
                    "metadata": common_meta,
                }
            )

    refusal_index = 0
    refusal_splits = ["dev"] * 10 + ["regression"] * 15 + ["final"] * 25
    for topic_index, topic in enumerate(REFUSAL_TOPICS, 1):
        for pattern_index, pattern in enumerate(REFUSAL_PATTERNS, 1):
            split = refusal_splits[refusal_index]
            target_paper = papers[refusal_index % len(papers)]
            refusal_index += 1
            cases.append(
                {
                    "inputs": {
                        "suite": "refusal",
                        "case_id": f"refusal-{topic_index:02d}-{pattern_index:02d}",
                        "query": pattern.format(topic=topic),
                        "paper_ids": [target_paper["paper_id"]],
                    },
                    "outputs": {
                        "expected_refusal": True,
                        "relevant_source_ids": [],
                        "expected_steps": ["deep_search", "deep_research"],
                    },
                    "metadata": {
                        "dataset_version": "v3",
                        "domain": "out_of_scope",
                        "split": split,
                    },
                }
            )

    ids = [case["inputs"]["case_id"] for case in cases]
    if len(cases) != EXPECTED_CASE_COUNT or len(set(ids)) != EXPECTED_CASE_COUNT:
        raise AssertionError(f"평가 사례는 고유한 650건이어야 합니다: {len(cases)}")
    suite_counts = Counter(case["inputs"]["suite"] for case in cases)
    expected_suites = {"artifacts": 40, "retrieval": 400, "deep_research": 80, "pipeline": 80, "refusal": 50}
    if suite_counts != expected_suites:
        raise AssertionError(f"suite 건수 오류: {dict(suite_counts)}")
    split_counts = Counter(case["metadata"]["split"] for case in cases)
    if split_counts != {"dev": 130, "regression": 195, "final": 325}:
        raise AssertionError(f"문항 분할 오류: {dict(split_counts)}")
    return cases


def _write_dataset(cases: list[dict[str, Any]]) -> None:
    rendered = "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n"
    _assert_inside(DATASET_PATH).write_text(rendered, encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _db_count(path: Path, table: str) -> int:
    if not path.is_file():
        return 0
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def write_report(
    papers: list[dict[str, str]], cases: list[dict[str, Any]], pdf_origins: dict[str, str]
) -> dict[str, Any]:
    suite_counts = Counter(case["inputs"]["suite"] for case in cases)
    split_counts = Counter(case["metadata"]["split"] for case in cases)
    report = {
        "dataset_version": "v3",
        "paper_count": len(papers),
        "case_count": len(cases),
        "paper_splits": dict(Counter(paper["split"] for paper in papers)),
        "case_splits": dict(split_counts),
        "suite_counts": dict(suite_counts),
        "domain_counts": dict(Counter(paper["domain"] for paper in papers)),
        "database_counts": {
            "extracted": _db_count(EXTRACT_DB, "extracted"),
            "references": _db_count(REFERENCE_DB, "extracted_ref"),
        },
        "pdfs": [
            {
                "paper_id": paper["paper_id"],
                "file": _pdf_path(paper).name,
                "bytes": _pdf_path(paper).stat().st_size if _pdf_path(paper).is_file() else 0,
                "sha256": _sha256(_pdf_path(paper)) if _pdf_path(paper).is_file() else None,
                "prepared_from": pdf_origins.get(paper["paper_id"], "not_prepared_this_run"),
            }
            for paper in papers
        ],
    }
    _assert_inside(REPORT_PATH).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build isolated evaluation corpus v3")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-extract", action="store_true")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--extractor", choices=("project", "pymupdf"), default="project")
    args = parser.parse_args()

    papers = _load_manifest()
    _assert_inside(GENERATED_DIR).mkdir(parents=True, exist_ok=True)
    _create_metadata_db(papers)
    origins: dict[str, str] = {}
    if not args.skip_download:
        origins = prepare_pdfs(papers, force=args.force_download)
    if not args.skip_extract:
        extract_pdfs(
            papers,
            force=args.force_extract,
            extractor_name=args.extractor,
        )
    cases = build_dataset(papers)
    _write_dataset(cases)
    report = write_report(papers, cases, origins)
    print(json.dumps({key: report[key] for key in ("paper_count", "case_count", "paper_splits", "case_splits", "suite_counts", "database_counts")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
