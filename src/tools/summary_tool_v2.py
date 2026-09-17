"""Extracted-papers DB를 문단 단위로 요약하는 독립 도구."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from tools import EXTRACTED_DB, SUMMARY_DB
from services.model_config_service import load_task_config

DEFAULT_SOURCE_DB = EXTRACTED_DB
DEFAULT_SUMMARY_DB = SUMMARY_DB.parent / "summary.db"
SUMMARY_CONFIG = load_task_config("summary")
DEFAULT_PROVIDER = str(SUMMARY_CONFIG.get("provider", "ollama")).strip().casefold()
DEFAULT_MODEL = str(SUMMARY_CONFIG.get("model", "qwen2.5:3b"))
DEFAULT_CHUNK_CHARS = int(SUMMARY_CONFIG.get("chunk_chars", 7000))
DEFAULT_CHUNK_MAX_TOKENS = int(SUMMARY_CONFIG.get("chunk_max_tokens", 2048))
DEFAULT_MAX_TOKENS = int(SUMMARY_CONFIG.get("max_tokens", 4096))
DEFAULT_TIMEOUT = float(SUMMARY_CONFIG.get("timeout", 300))
DEFAULT_MAX_RETRIES = int(SUMMARY_CONFIG.get("max_retries", 2))
DEFAULT_RETRY_BACKOFF = float(SUMMARY_CONFIG.get("retry_backoff_seconds", 2.0))
DEFAULT_TEMPERATURE = float(SUMMARY_CONFIG.get("temperature", 0.0))

load_dotenv()


def generate_with_gemini(prompt: str, *, model: str, max_tokens: int,
                         temperature: float, timeout: float) -> str:
    """Gemini GenerateContent API를 SummaryTool generator 형식으로 호출한다."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 필요합니다.")
    model_id = model.removeprefix("models/")
    query = urllib.parse.urlencode({"key": api_key})
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?{query}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    for attempt in range(DEFAULT_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code not in (429, 500, 502, 503, 504) or attempt >= DEFAULT_MAX_RETRIES:
                raise RuntimeError(
                    f"Gemini API 호출에 실패했습니다 (HTTP {exc.code}): {error_body}"
                ) from exc
            time.sleep(DEFAULT_RETRY_BACKOFF * (2 ** attempt))
        except Exception as exc:
            raise RuntimeError(f"Gemini API 호출에 실패했습니다: {exc}") from exc
    try:
        return str(body["candidates"][0]["content"]["parts"][0]["text"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Gemini 응답 형식이 올바르지 않습니다: {body}") from exc

SUMMARY_PROMPT = """당신은 학술 논문 문단을 요약하는 분석가입니다.
입력 문단에 있는 정보만 사용하고, 수치·모델명·데이터셋명·인용 번호는 보존하세요.
실험 결과를 요약할 때는 반드시 모델명, 과제/데이터셋, 실험 조건, 평가 지표와 수치를 함께 보존하세요.
방법을 요약할 때는 실제로 사용한 모델·데이터·절차를 관련 연구의 소개와 구분하세요.
저자가 명시한 한계와 결론은 보존하되, 원문에 없는 한계나 해석은 추가하지 마세요.
표와 수식 placeholder는 삭제하거나 이름을 바꾸지 말고 해당 위치에 그대로 두세요.
표/수식이 무엇을 나타내거나 어떤 결론을 뒷받침하는지 설명하는 문장이 있으면 반드시 요약에 포함하세요.
표와 수식의 의미는 원문에 명시된 설명과 직접 확인 가능한 정보만 요약하세요.
원문에 없는 수치 비교, 원인, 해석은 추론하거나 추가하지 마세요.
입력된 원문과 동일한 언어로 요약하세요. 원문에 없는 내용은 추측하지 마세요.
문단의 핵심 내용과 표·수식 설명을 빠짐없이 포함하되, 불필요하게 길게 확장하지 마세요.
"""

PAPER_PROMPT = """당신은 학술 논문 전체를 통합 요약하는 분석가입니다.
입력된 청크 요약만 사용하여 섹션의 핵심 주장, 방법, 결과를 중복 없이 통합하세요.
입력된 원문과 동일한 언어로 요약하세요. 원문에 없는 내용은 추측하지 마세요.
각 결과 수치를 해당 모델명, 과제/데이터셋, 실험 조건, 평가 지표와 함께 유지하세요.
관련 연구에서 소개한 모델이나 방법을 본 논문의 실험 결과로 바꾸어 쓰지 마세요.
표와 수식은 placeholder를 삭제·변경하지 말고 유지하세요.
표와 수식의 의미는 원문에 명시된 설명과 직접 확인 가능한 정보만 요약하세요.
원문에 없는 수치 비교, 원인, 해석은 추론하거나 추가하지 마세요.
연구 목적, 핵심 방법, 주요 결과, 한계와 결론이 드러나도록 작성하세요.
Markdown의 연구 목적, 연구 방법, 주요 결과, 한계 및 결론 항목으로 작성하세요.
한계는 원문에서 확인되는 경우에만 쓰고, 확인되지 않으면 명시되지 않았다고 표시하세요.
References, Bibliography, 참고문헌 항목은 만들지 마세요.
"""

MARKUP_REPAIR_PROMPT = """앞서 작성한 요약에서 표·수식 placeholder가 누락되거나 변경되었습니다.
요약문의 문장과 내용은 유지하고, 아래 placeholder를 원래 순서대로 정확히 포함하여 다시 출력하세요.
placeholder 외의 표·수식 원문은 직접 작성하지 마세요. 설명되지 않은 내용은 추가하지 마세요.
JSON, Markdown 코드펜스, 부연 설명 없이 요약문만 출력하세요.
"""

# 표는 전체 블록, 수식은 LaTeX 환경/display/inline 순서로 보호한다.
_TABLE = re.compile(
    r"<table\b.*?</table>|(?:^[ \t]*\|[^\n]*\|[ \t]*(?:\n|$)){2,}", re.I | re.S | re.M
)
_MATH = re.compile(
    r"\\begin\{(?:equation\*?|align\*?|gather\*?|multline\*?|cases|split|array|matrix|pmatrix|bmatrix)\}.*?"
    r"\\end\{(?:equation\*?|align\*?|gather\*?|multline\*?|cases|split|array|matrix|pmatrix|bmatrix)\}"
    r"|\$\$.*?\$\$|\\\[.*?\\\]|(?<!\$)\$(?!\$)(?:\\.|[^$\n])+?(?<!\\)\$(?!\$)", re.S)
_TOKEN = re.compile(r"__SUMMARY_(?:TABLE|FORMULA)_\d{6}__")
_WORD = re.compile(r"[A-Za-z가-힣][A-Za-z가-힣0-9_-]{1,}")
_IMPORTANT = re.compile(r"\b\d+(?:\.\d+)?\s*%?|\b(?:significant|outperform|improv|achiev|result|propos|conclu|however|limitation|accuracy|precision|recall|f1|loss|dataset)\w*\b", re.I)
_ARTIFACT_REF = re.compile(
    r"__SUMMARY_(?:TABLE|FORMULA)_\d{6}__|\b(?:table|tab\.?|equation|eq\.?)\s*\d*\b|표\s*\d*|수식\s*\d*",
    re.I,
)
_EXCLUDED_SECTION = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*|[IVX]+)[\s.)-]+)?"
    r"(?:abstract|초록|요약|references|bibliography|참고문헌)\b",
    re.I,
)


@dataclass(frozen=True)
class ProtectedText:
    text: str
    replacements: dict[str, str]
    order: tuple[str, ...]


def protect_markup(text: str) -> ProtectedText:
    """표와 수식을 placeholder로 분리한다."""
    replacements: dict[str, str] = {}
    protected = text
    # 한 번의 combined scan으로 원문 순서를 그대로 유지한다.
    pattern = re.compile(f"({_TABLE.pattern})|({_MATH.pattern})", re.I | re.S | re.M)

    def replace(match: re.Match[str]) -> str:
        original = match.group(0)
        kind = "TABLE" if match.group(1) else "FORMULA"
        token = f"__SUMMARY_{kind}_{len(replacements) + 1:06d}__"
        replacements[token] = original
        return token

    protected = pattern.sub(replace, protected)
    return ProtectedText(protected, replacements, tuple(_TOKEN.findall(protected)))


def restore_markup(text: str, protection: ProtectedText) -> str:
    """placeholder의 누락·중복·순서 변경을 거부하고 원문을 복원한다."""
    if tuple(_TOKEN.findall(text)) != protection.order:
        raise ValueError("요약 모델이 표/수식 placeholder를 변경했습니다.")
    restored = text
    for token, original in protection.replacements.items():
        restored = restored.replace(token, original)
    if _TOKEN.search(restored):
        raise ValueError("표/수식 placeholder를 모두 복원하지 못했습니다.")
    return restored


def restore_markup_safely(text: str, protection: ProtectedText) -> str:
    """모델이 placeholder를 훼손해도 표·수식 원문을 보존하며 복원한다."""
    try:
        return restore_markup(text, protection)
    except ValueError:
        if not protection.order:
            return text
        cleaned = _TOKEN.sub("", text).strip()
        return restore_markup(
            cleaned + "\n\n" + "\n\n".join(protection.order), protection
        )


def paragraph_chunks(text: str, max_chars: int = 5000) -> list[str]:
    """빈 줄 기준 문단을 유지하면서 청크를 만든다."""
    if max_chars < 1:
        raise ValueError("max_chars는 1 이상이어야 합니다.")
    blocks = [x.strip() for x in re.split(r"\n\s*\n", text.strip()) if x.strip()]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if len(block) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(block[i : i + max_chars] for i in range(0, len(block), max_chars))
        elif current and len(current) + 2 + len(block) > max_chars:
            chunks.append(current)
            current = block
        else:
            current = block if not current else f"{current}\n\n{block}"
    if current:
        chunks.append(current)
    return chunks


def _sentences(text: str) -> list[str]:
    """보호된 Markdown에서 표/수식 token을 훼손하지 않고 문장을 나눈다."""
    return [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+|\n+", text) if s.strip()]


def language_instruction(text: str) -> str:
    """추출 원문의 언어를 간단히 판별해 모델의 출력 언어를 고정한다."""
    letters = re.findall(r"[A-Za-z가-힣]", text)
    english = sum(ch.isascii() and ch.isalpha() for ch in letters)
    korean = sum("가" <= ch <= "힣" for ch in letters)
    if english >= korean * 2:
        return "OUTPUT LANGUAGE: English only. Do not translate into Korean."
    if korean >= english:
        return "출력 언어: 한국어만 사용하세요. 영어로 번역하지 마세요."
    return "Output in the same language as the source text."


def extractive_section_summary(text: str, title: str = "", *, max_sentences: int = 5) -> str:
    """AI 호출 없이 TF-IDF와 위치/결과 가중치로 핵심 문장을 추출한다."""
    sentences = _sentences(text)
    if len(sentences) <= max_sentences:
        return text.strip()
    docs = [set(_WORD.findall(s.casefold())) for s in sentences]
    df: dict[str, int] = {}
    for words in docs:
        for word in words:
            df[word] = df.get(word, 0) + 1
    n = len(sentences)
    title_words = set(_WORD.findall(title.casefold()))
    scored: list[tuple[float, int, str]] = []
    for i, (sentence, words) in enumerate(zip(sentences, docs)):
        if not words:
            continue
        tfidf = sum((1 + math.log(len(words))) * math.log((n + 1) / (df[w] + 1)) for w in words) / math.sqrt(len(words))
        position = 1.0 if i < 2 or i >= n - 2 else 0.0
        title_match = len(words & title_words) / max(1, len(title_words))
        importance = min(3.0, len(_IMPORTANT.findall(sentence)))
        artifact_ref = bool(_ARTIFACT_REF.search(sentence))
        scored.append((tfidf + 0.8 * position + 0.6 * title_match + 0.9 * importance + (4.0 if artifact_ref else 0.0), i, sentence))
    # 표·수식 자체 또는 참조 문장은 의미 설명일 가능성이 높으므로 우선 보존하고,
    # 바로 앞뒤 문장도 함께 후보에 넣어 설명 문맥이 끊기지 않게 한다.
    priority_indexes = {i for _score, i, sentence in scored if _ARTIFACT_REF.search(sentence)}
    priority_indexes |= {neighbor for i in priority_indexes for neighbor in (i - 1, i + 1) if 0 <= neighbor < n}
    priority = [item for item in scored if item[1] in priority_indexes]
    selected = priority[:max_sentences]
    if len(selected) < max_sentences:
        selected_indexes = {i for _score, i, _sentence in selected}
        remaining = [item for item in sorted(scored, reverse=True) if item[1] not in selected_indexes]
        selected.extend(remaining[: max_sentences - len(selected)])
    return " ".join(sentence for _score, _i, sentence in sorted(selected, key=lambda x: x[1]))


@dataclass
class SummaryResult:
    paper_id: str
    title: str
    summary_markdown: str
    chunk_count: int
    model: str


class SummaryTool:
    """본문 DB에서 읽고, 요약 DB에 저장하며, 저장 결과를 다시 렌더링한다."""

    def __init__(self, source_db: str | Path = DEFAULT_SOURCE_DB,
                 summary_db: str | Path = DEFAULT_SUMMARY_DB,
                 generator: Callable[..., str] | None = None, *, model: str | None = None,
                 max_chars: int | None = None, provider: str | None = None,
                 single_call: bool = False) -> None:
        self.source_db = Path(source_db)
        self.summary_db = Path(summary_db)
        self.provider = (provider or DEFAULT_PROVIDER).strip().casefold()
        self.model = model or (
            DEFAULT_MODEL if self.provider == DEFAULT_PROVIDER else "qwen2.5:3b"
        )
        self.single_call = single_call
        self.generation_calls = 0
        self.max_chars = max_chars or DEFAULT_CHUNK_CHARS
        if self.max_chars < 1:
            raise ValueError("summary.chunk_chars는 1 이상이어야 합니다.")
        if generator is None:
            if self.provider == "ollama":
                from services.ollama_service import generate
                generator = generate
            elif self.provider == "nvidia":
                from services.nvidia_service import generate
                generator = generate
            elif self.provider == "gemini":
                generator = generate_with_gemini
            else:
                raise ValueError(
                    f"지원하지 않는 summary.provider입니다: {self.provider}. "
                    "ollama, nvidia 또는 gemini를 사용하세요."
                )
        self.generator = generator

    def _generate(self, prompt: str, **kwargs: object) -> str:
        """모델을 호출하고 호출 횟수를 기록한다."""
        self.generation_calls += 1
        return str(self.generator(prompt, **kwargs))

    def _read_paper(self, paper_id: str) -> tuple[str, str]:
        if not self.source_db.exists():
            raise FileNotFoundError(f"원문 DB를 찾을 수 없습니다: {self.source_db}")
        with sqlite3.connect(self.source_db) as db:
            row = db.execute("SELECT title, content FROM extracted WHERE id = ?", (paper_id,)).fetchone()
            if row is None:
                raise KeyError(f"논문을 찾을 수 없습니다: {paper_id}")
            try:
                sections = db.execute(
                    """SELECT section_title, section_text
                       FROM paper_sections
                       WHERE paper_id = ?
                       ORDER BY section_order""",
                    (paper_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                sections = []
        if sections:
            ordered_sections = []
            for section_title, section_text in sections:
                title = str(section_title or "").strip()
                if _EXCLUDED_SECTION.search(title):
                    continue
                text = str(section_text or "").strip()
                if text:
                    ordered_sections.append(f"## {title}\n\n{text}" if title else text)
            content = "\n\n".join(ordered_sections)
        else:
            # 구버전 DB에는 paper_sections가 없거나 비어 있을 수 있다.
            content = str(row[1] or "")
        return str(row[0] or paper_id), content

    def _read_sections(self, paper_id: str) -> tuple[str, list[tuple[int, str, str]]]:
        """섹션 순서를 보존한 ``(order, title, text)`` 목록을 반환한다."""
        if not self.source_db.exists():
            raise FileNotFoundError(f"원문 DB를 찾을 수 없습니다: {self.source_db}")
        with sqlite3.connect(self.source_db) as db:
            try:
                paper = db.execute("SELECT title FROM extracted WHERE id = ?", (paper_id,)).fetchone()
            except sqlite3.OperationalError:
                paper = None
            try:
                rows = db.execute(
                    """SELECT section_order, section_title, section_text
                       FROM paper_sections WHERE paper_id = ? ORDER BY section_order""",
                    (paper_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if paper is None:
                # paper_sections만 있는 DB에서는 별도 논문 목록에서 실제 제목을 찾는다.
                metadata_path = self.source_db.parent.parent / "paper_list" / "saved_papers.json"
                metadata_title = ""
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    entry = metadata.get(paper_id, {})
                    metadata_title = str(entry.get("title", "")).strip()
                except (OSError, json.JSONDecodeError, AttributeError):
                    pass
                paper = (metadata_title or paper_id,)
            if paper is None:
                raise KeyError(f"논문을 찾을 수 없습니다: {paper_id}")
        sections = []
        for order, section_title, section_text in rows:
            title = str(section_title or "").strip()
            if _EXCLUDED_SECTION.search(title):
                continue
            text = str(section_text or "").strip()
            if text:
                sections.append((int(order), title, text))
        if not sections:
            _title, content = self._read_paper(paper_id)
            sections = [(1, "본문", content)] if content.strip() else []
        return str(paper[0] or paper_id), sections

    def list_papers(self) -> list[tuple[str, str]]:
        """원문 DB에 있는 논문 ID와 제목을 순서대로 반환한다."""
        with sqlite3.connect(self.source_db) as db:
            try:
                return [(str(row[0]), str(row[1] or row[0]))
                        for row in db.execute("SELECT id, title FROM extracted ORDER BY rowid")]
            except sqlite3.OperationalError as exc:
                if "no such table: extracted" not in str(exc):
                    raise
                # 일부 추출 DB는 논문 메타데이터 없이 paper_sections만 저장한다.
                # 이 경우 paper_id를 논문 목록으로 사용하고 제목은 ID로 대체한다.
                return [(str(row[0]), str(row[0])) for row in db.execute(
                    """SELECT paper_id
                       FROM paper_sections
                       GROUP BY paper_id
                       ORDER BY MIN(section_order), MIN(id)"""
                )]

    def _init_db(self, db: sqlite3.Connection) -> None:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS paper_summary_chunk_temp (
          paper_id TEXT NOT NULL, section_order INTEGER NOT NULL, chunk_index INTEGER NOT NULL,
          section_title TEXT NOT NULL, source_text TEXT NOT NULL,
          summary_text TEXT NOT NULL, protected_items TEXT NOT NULL DEFAULT '[]',
          model TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY (paper_id, section_order, chunk_index)
        );
        CREATE TABLE IF NOT EXISTS paper_summary_chunks (
          paper_id TEXT NOT NULL, section_order INTEGER NOT NULL, chunk_index INTEGER NOT NULL,
          section_title TEXT NOT NULL, source_text TEXT NOT NULL,
          summary_text TEXT NOT NULL, protected_items TEXT NOT NULL DEFAULT '[]',
          model TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY (paper_id, section_order, chunk_index)
        );
        CREATE TABLE IF NOT EXISTS paper_summary_sections (
          paper_id TEXT NOT NULL, section_order INTEGER NOT NULL, section_title TEXT NOT NULL,
          summary_text TEXT NOT NULL, chunk_count INTEGER NOT NULL, model TEXT NOT NULL,
          created_at TEXT NOT NULL, PRIMARY KEY (paper_id, section_order)
        );
        CREATE TABLE IF NOT EXISTS paper_summaries (
          paper_id TEXT PRIMARY KEY, title TEXT NOT NULL, summary_text TEXT NOT NULL DEFAULT '', model TEXT NOT NULL,
          section_count INTEGER NOT NULL, chunk_count INTEGER NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(paper_summaries)")}
        if "summary_text" not in columns:
            db.execute("ALTER TABLE paper_summaries ADD COLUMN summary_text TEXT NOT NULL DEFAULT ''")

    def _restore_or_repair(self, text: str, protection: ProtectedText) -> str:
        """placeholder가 누락된 모델 응답을 한 번 보정한 뒤 복원한다."""
        try:
            return restore_markup(text, protection)
        except ValueError:
            if not protection.order:
                raise
            tokens = ", ".join(protection.order)
            repair_prompt = (
                f"{MARKUP_REPAIR_PROMPT}\n필수 placeholder 순서: {tokens}\n"
                f"[요약문]\n{text}"
            )
            repaired = self._generate(
                repair_prompt,
                model=self.model,
                max_tokens=DEFAULT_CHUNK_MAX_TOKENS,
                temperature=DEFAULT_TEMPERATURE,
                timeout=DEFAULT_TIMEOUT,
            )
            try:
                return restore_markup(str(repaired).strip(), protection)
            except ValueError:
                return restore_markup_safely(str(repaired).strip(), protection)

    def summarize(self, paper_id: str, *, title: str | None = None) -> SummaryResult:
        db_title, sections = self._read_sections(paper_id)
        title = title or db_title
        if not sections:
            raise ValueError("요약할 본문이 비어 있습니다.")
        if self.single_call:
            return self._summarize_single_call(paper_id, title, sections)
        now = datetime.now(timezone.utc).isoformat()
        final_chunks: list[tuple[int, int, str, str, str, str]] = []
        chunk_inputs: list[str] = []
        self.summary_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.summary_db) as db:
            self._init_db(db)
            for section_order, section_title, section_text in sections:
                protected = protect_markup(section_text)
                # 긴 섹션은 문단 경계를 유지해 나눈 뒤, 각 청크에서 핵심 문장만 선별한다.
                chunks = paragraph_chunks(protected.text, self.max_chars)
                for index, chunk in enumerate(chunks, 1):
                    protection = protected_for_chunk(chunk, protected)
                    original_chunk = restore_markup(chunk, protection)
                    items = [protected.replacements[t] for t in _TOKEN.findall(chunk) if t in protected.replacements]
                    section_prompt = (
                        f"{language_instruction(chunk)}\n{SUMMARY_PROMPT}\n"
                        f"논문 제목: {title}\n섹션: {section_title}\n"
                        f"청크 {index}/{len(chunks)}:\n{chunk}"
                    )
                    result = self._generate(
                        section_prompt, model=self.model,
                        max_tokens=DEFAULT_CHUNK_MAX_TOKENS,
                        temperature=DEFAULT_TEMPERATURE, timeout=DEFAULT_TIMEOUT,
                    )
                    chunk_summary = self._restore_or_repair(
                        str(result).strip(), protection
                    )
                    final_chunks.append((section_order, index, section_title, original_chunk, chunk_summary, json.dumps(items, ensure_ascii=False)))
                    chunk_inputs.append(f"[{section_title} · 섹션 요약]\n{chunk_summary}")

            combined = "\n\n".join(chunk_inputs)
            combined_protection = protect_markup(combined)
            prompt = f"{language_instruction(combined)}\n{PAPER_PROMPT}\n논문 제목: {title}\n[섹션별 요약]\n{combined_protection.text}"
            artifacts = [f"{token}: {combined_protection.replacements[token]}" for token in combined_protection.order]
            if artifacts:
                prompt += "\n\n[표·수식 참고]\n" + "\n".join(artifacts)
            # 최종 4단계 요약은 불필요하게 긴 생성을 막고 설정값을 따른다.
            result = self._generate(
                prompt, model=self.model, max_tokens=max(DEFAULT_MAX_TOKENS, 1536),
                temperature=DEFAULT_TEMPERATURE, timeout=DEFAULT_TIMEOUT,
            )
            paper_summary = self._restore_or_repair(str(result).strip(), combined_protection)

            # 모든 청크와 논문 통합 요약이 성공한 뒤 최종 테이블에 반영한다.
            db.execute("DELETE FROM paper_summary_chunks WHERE paper_id = ?", (paper_id,))
            db.executemany("INSERT INTO paper_summary_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [(paper_id, *row, self.model, now) for row in final_chunks])
            db.execute("INSERT INTO paper_summaries (paper_id,title,summary_text,model,section_count,chunk_count,created_at,updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(paper_id) DO UPDATE SET title=excluded.title, summary_text=excluded.summary_text, model=excluded.model, section_count=excluded.section_count, chunk_count=excluded.chunk_count, updated_at=excluded.updated_at",
                       (paper_id, title, paper_summary, self.model, len(sections), len(final_chunks), now, now))
            db.execute("DELETE FROM paper_summary_chunk_temp WHERE paper_id = ?", (paper_id,))
            db.commit()
        markdown = self._build_markdown(title, paper_summary)
        result = SummaryResult(paper_id, title, markdown, len(final_chunks), self.model)
        return result

    def _summarize_single_call(
        self, paper_id: str, title: str, sections: list[tuple[int, str, str]]
    ) -> SummaryResult:
        """TF-IDF로 줄인 모든 섹션을 한 번에 요약한다."""
        selected = []
        for _order, section_title, section_text in sections:
            core = extractive_section_summary(section_text, section_title, max_sentences=5)
            selected.append(f"## {section_title}\n\n{core}" if section_title else core)
        combined = "\n\n".join(selected)
        protection = protect_markup(combined)
        prompt = (
            f"{language_instruction(protection.text)}\n{PAPER_PROMPT}\n"
            f"논문 제목: {title}\n[TF-IDF로 선별한 논문 내용]\n{protection.text}"
        )
        result = self._generate(
            prompt, model=self.model, max_tokens=DEFAULT_MAX_TOKENS,
            temperature=DEFAULT_TEMPERATURE, timeout=DEFAULT_TIMEOUT,
        )
        paper_summary = self._restore_or_repair(str(result).strip(), protection)
        now = datetime.now(timezone.utc).isoformat()
        self.summary_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.summary_db) as db:
            self._init_db(db)
            db.execute(
                """INSERT INTO paper_summaries
                (paper_id, title, summary_text, model, section_count, chunk_count,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET title=excluded.title,
                summary_text=excluded.summary_text, model=excluded.model,
                section_count=excluded.section_count, chunk_count=excluded.chunk_count,
                updated_at=excluded.updated_at""",
                (paper_id, title, paper_summary, self.model, len(sections), 1, now, now),
            )
            db.commit()
        result = SummaryResult(
            paper_id, title, self._build_markdown(title, paper_summary), 1, self.model
        )
        return result

    @staticmethod
    def _build_markdown(title: str, summary: str) -> str:
        return f"# {title}\n\n{summary}\n"

    def summarize_all(self, paper_ids: list[str] | None = None) -> list[SummaryResult]:
        """지정한 논문들을 DB 순서대로 요약한다. ``None``이면 전체를 처리한다."""
        ids = paper_ids or [paper_id for paper_id, _title in self.list_papers()]
        return [self.summarize(paper_id) for paper_id in ids]

    def load_markdown(self, paper_id: str) -> str:
        """Markdown 파일을 읽지 않고 요약 DB에서 표시용 Markdown을 반환한다."""
        with sqlite3.connect(self.summary_db) as db:
            row = db.execute("SELECT title, summary_text FROM paper_summaries WHERE paper_id = ?", (paper_id,)).fetchone()
        if row is None:
            raise KeyError(f"저장된 요약을 찾을 수 없습니다: {paper_id}")
        return self._build_markdown(str(row[0]), str(row[1]))

    def export_markdown_view(self, paper_id: str, output_path: str | Path) -> Path:
        """DB에 저장된 요약을 Markdown 표시 파일로 내보낸다.

        요약 생성은 수행하지 않으며, 항상 저장 DB의 문자열만 사용한다.
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.load_markdown(paper_id), encoding="utf-8")
        return path


def protected_for_chunk(chunk: str, document: ProtectedText) -> ProtectedText:
    """전체 문서 보호 정보에서 현재 청크에 필요한 토큰만 구성한다."""
    tokens = tuple(_TOKEN.findall(chunk))
    return ProtectedText(chunk, {t: document.replacements[t] for t in tokens}, tokens)


def render_summary_markdown(summary_db: str | Path, paper_id: str) -> str:
    """저장된 요약을 DB에서 읽어 Markdown 표시 문자열로 반환한다."""
    return SummaryTool(summary_db=summary_db).load_markdown(paper_id)
