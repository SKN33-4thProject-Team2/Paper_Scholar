"""Agent 3: 전문 번역 에이전트 (Translation Agent).

Agent 2가 파싱한 논문 마크다운을 LaTeX 수식과 전문 용어를 훼손하지 않고
한국어로 번역한다. 참고문헌 목록은 번역하지 않고 원문 그대로 보존한다.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from pathlib import Path

from log import AppLogger, LogCode
from services import PROJECT_ROOT
from services.generation_options import resolve_positive_int
from services.model_config_service import load_task_config
from services.translation_markdown_service import (
    TranslationMarkupError,
    extract_markdown_tables,
    protect_translation_markup,
    rebuild_markdown_table,
    restore_translation_markup,
    split_markdown,
    split_reference_section,
    strip_metadata_header,
)
from services.translation_service import (
    TranslateService,
    TranslateServiceError,
)
from services.translation_checkpoint_service import (
    TranslationCheckpointError,
    TranslationCheckpointStore,
)

logger = AppLogger(__name__)
TRANSLATION_CONFIG = load_task_config("translation")
DEFAULT_TRANSLATION_DIR = PROJECT_ROOT / str(
    TRANSLATION_CONFIG["output_directory"]
)
MAX_TRUNCATION_SPLIT_DEPTH = 6
TITLE_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class TranslationError(RuntimeError):
    """번역을 완료하지 못했을 때 발생한다."""

TRANSLATION_SYSTEM_PROMPT = (
    "당신은 학술 논문 전문 번역가입니다.\n"
    "입력은 하나 이상의 완전한 문단으로 구성된 논문 본문입니다.\n"
    "문단 경계와 마크다운 구조를 유지하며 한국어로 번역합니다.\n"
    "[규칙]\n"
    "1. LaTeX 수식은 절대 건드리지 않습니다. $...$, $$...$$, \\begin{...}...\\end{...} 안의 "
    "내용은 기호 하나까지 원형 그대로 출력합니다.\n"
    "2. 마크다운 구조(헤딩 #, 목록, 표, 인용구 >)를 그대로 유지합니다.\n"
    "3. 전문 용어는 한국어로 옮기되 처음 등장할 때 괄호로 원문을 병기합니다. "
    "예: 어텐션 메커니즘(attention mechanism)\n"
    "4. 고유명사, 모델명, 데이터셋명, 인용 표기([12], (Vaswani et al., 2017))는 번역하지 않습니다.\n"
    "5. 요약하거나 생략하지 않고 모든 문장을 번역합니다.\n"
    "6. __APRAG_PROTECTED_000000__ 형태의 보호 토큰은 번역, 삭제, 중복, 이동하지 않습니다.\n"
    "7. 번역문만 출력합니다. 설명, 머리말, 코드펜스를 붙이지 않습니다."
)

class TranslateTool:
    """체크포인트를 이용해 논문 마크다운을 한국어로 번역하는 도구."""

    def __init__(
        self,
        progress: Callable[[str], None] = print,
        checkpoint_store: TranslationCheckpointStore | None = None,
        output_directory: str | Path | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        chunk_chars: int | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        translate_service: TranslateService | None = None,
    ) -> None:
        self._progress = progress
        self._checkpoint_store = (
            checkpoint_store
            if checkpoint_store is not None
            else TranslationCheckpointStore()
        )
        self._output_directory = Path(output_directory or DEFAULT_TRANSLATION_DIR)
        self._translate_service = (
            translate_service
            if translate_service is not None
            else TranslateService(
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                chunk_chars=chunk_chars,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
            )
        )

    def _resolve_chunk_chars(self, chunk_chars: int | None) -> int:
        """추가 서비스 객체를 만들지 않고 청크 크기를 검증한다."""
        if chunk_chars is None:
            return self._translate_service.chunk_chars
        return resolve_positive_int("translation.chunk_chars", chunk_chars)

    @staticmethod
    def _failure_message(
        index: int, error: TranslateServiceError | TranslationMarkupError
    ) -> str:
        """오류의 재시도 가능 여부에 맞는 사용자 안내를 만든다."""
        prefix = f"{index}번째 청크 번역에 실패했습니다."
        if error.reason.startswith("output_truncated"):
            return f"{prefix} 출력 한도를 초과했고 청크를 더 나눌 수 없습니다."
        if error.retryable:
            return f"{prefix} 잠시 후 다시 시도해 주세요."
        return f"{prefix} 상세 원인은 로그 파일을 확인해 주세요."

    def translate_chunk(self, chunk: str, *, index: int, total: int) -> str:
        """청크 하나를 번역한다."""
        markdown_tables = extract_markdown_tables(chunk)
        protection = protect_translation_markup(chunk)
        prompt = (
            f"{TRANSLATION_SYSTEM_PROMPT}\n\n"
            f"다음은 논문의 {index}/{total} 번째 부분입니다. "
            f"한국어로 번역해 주세요.\n\n{protection.text}"
        )
        translated = self._translate_service.translate(prompt)
        restored = restore_translation_markup(translated, protection)
        for table_index, original_table in enumerate(markdown_tables, start=1):
            translated_table = self._translate_markdown_table(
                original_table,
                chunk_index=index,
                chunk_total=total,
                table_index=table_index,
                table_total=len(markdown_tables),
            )
            restored = restored.replace(original_table, translated_table, 1)
        return restored

    def _translate_markdown_table(
        self,
        table: str,
        *,
        chunk_index: int,
        chunk_total: int,
        table_index: int,
        table_total: int,
    ) -> str:
        """표의 셀만 번역해 원래 행·열 구조로 복원하고 실패하면 원문을 보존한다."""
        protection = protect_translation_markup(table, protect_tables=False)
        prompt = (
            "당신은 영문 학술 논문의 Markdown 표를 한국어로 번역합니다.\n"
            "헤더와 셀의 텍스트만 번역하고 행 개수, 열 개수, 파이프(|), "
            "정렬 구분 행은 유지하세요.\n"
            "__APRAG_PROTECTED_000000__ 형태의 보호 토큰은 변경하지 마세요.\n"
            "번역된 Markdown 표만 출력하고 설명이나 코드펜스를 붙이지 마세요.\n\n"
            f"{protection.text}"
        )

        max_retries = self._translate_service.max_retries
        retry_backoff = self._translate_service.retry_backoff_seconds
        for attempt in range(max_retries + 1):
            try:
                translated = self._translate_service.translate(prompt)
                restored = restore_translation_markup(translated, protection)
                return rebuild_markdown_table(table, restored)
            except (TranslateServiceError, TranslationMarkupError) as exc:
                if attempt >= max_retries:
                    logger.log(
                        LogCode.TRANSLATION_TABLE_PRESERVED,
                        chunk_index=chunk_index,
                        chunk_total=chunk_total,
                        table_index=table_index,
                        table_total=table_total,
                        table_chars=len(table),
                        reason=exc.reason,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    self._progress(
                        f"    [Ollama] {chunk_index}/{chunk_total} 청크의 표 "
                        f"{table_index}/{table_total}는 구조 보존을 위해 원문으로 유지합니다."
                    )
                    return table

                delay = retry_backoff * (2**attempt)
                logger.log(
                    LogCode.TRANSLATION_RETRYING,
                    chunk_index=chunk_index,
                    chunk_total=chunk_total,
                    table_index=table_index,
                    table_total=table_total,
                    retry_attempt=attempt + 1,
                    max_retries=max_retries,
                    delay_seconds=delay,
                    reason=exc.reason,
                    status_code=exc.status_code,
                )
                self._progress(
                    f"    [Ollama] 표 구조 검증 실패로 {delay:g}초 후 재시도합니다 "
                    f"({attempt + 1}/{max_retries})."
                )
                if delay:
                    time.sleep(delay)

        return table

    def _translate_chunk_with_retry(
        self,
        chunk: str,
        *,
        index: int,
        total: int,
        split_depth: int = 0,
    ) -> str:
        """출력 초과는 청크를 분할하고 일시적 오류만 같은 입력으로 재시도한다."""
        max_retries = self._translate_service.max_retries
        retry_backoff = self._translate_service.retry_backoff_seconds
        for attempt in range(max_retries + 1):
            try:
                return self.translate_chunk(chunk, index=index, total=total)
            except (TranslateServiceError, TranslationMarkupError) as exc:
                if exc.reason == "output_truncated":
                    if split_depth >= MAX_TRUNCATION_SPLIT_DEPTH:
                        raise TranslateServiceError(
                            "출력 한도를 초과한 청크가 반복 분할 후에도 완료되지 않았습니다.",
                            reason="output_truncated_unsplittable",
                            retryable=False,
                        ) from exc

                    split_size = max(1, len(chunk) // 2)
                    split_chunks = split_markdown(chunk, max_chars=split_size)
                    if len(split_chunks) < 2:
                        raise TranslateServiceError(
                            "출력 한도를 초과했지만 수식 또는 표 블록을 안전하게 나눌 수 없습니다.",
                            reason="output_truncated_unsplittable",
                            retryable=False,
                        ) from exc

                    logger.log(
                        LogCode.TRANSLATION_CHUNK_SPLIT,
                        chunk_index=index,
                        chunk_total=total,
                        split_depth=split_depth + 1,
                        original_chars=len(chunk),
                        split_count=len(split_chunks),
                        split_chars=[len(part) for part in split_chunks],
                        reason=exc.reason,
                    )
                    self._progress(
                        f"    [Ollama] 출력 한도 초과: {index}/{total} 청크를 "
                        f"{len(split_chunks)}개로 나눠 번역합니다."
                    )
                    return "\n\n".join(
                        self._translate_chunk_with_retry(
                            part,
                            index=index,
                            total=total,
                            split_depth=split_depth + 1,
                        )
                        for part in split_chunks
                    )

                if not exc.retryable or attempt >= max_retries:
                    raise
                delay = retry_backoff * (2**attempt)
                logger.log(
                    LogCode.TRANSLATION_RETRYING,
                    chunk_index=index,
                    chunk_total=total,
                    retry_attempt=attempt + 1,
                    max_retries=max_retries,
                    delay_seconds=delay,
                    reason=exc.reason,
                    status_code=exc.status_code,
                )
                retry_reason = (
                    "보호 마크업이 변경되어"
                    if exc.reason == "protected_markup_changed"
                    else "일시 오류로"
                )
                self._progress(
                    f"    [Ollama] {retry_reason} {delay:g}초 후 재시도합니다 "
                    f"({attempt + 1}/{max_retries})."
                )
                if delay:
                    time.sleep(delay)
        raise RuntimeError("번역 재시도 흐름이 비정상적으로 종료됐습니다.")

    def translate_markdown(
        self,
        markdown: str,
        *,
        chunk_chars: int | None = None,
        checkpoint_id: str | None = None,
    ) -> tuple[str, int]:
        """마크다운을 번역하고 실패 시 완료된 청크부터 재개한다."""
        resolved_chunk_chars = self._resolve_chunk_chars(chunk_chars)
        body, references = split_reference_section(
            strip_metadata_header(markdown)
        )
        chunks = split_markdown(body, max_chars=resolved_chunk_chars)
        if not chunks:
            logger.log(
                LogCode.TRANSLATION_REJECTED,
                reason="empty_body",
                retryable=False,
                input_chars=len(markdown),
            )
            raise TranslationError("번역할 본문이 비어 있습니다.")

        source_hash = hashlib.sha256(
            (
                f"{TRANSLATION_SYSTEM_PROMPT}\0{body}\0"
                f"{self._translate_service.temperature}\0"
                f"{self._translate_service.max_tokens}"
            ).encode("utf-8")
        ).hexdigest()
        translated: list[str] = []
        if checkpoint_id:
            try:
                translated = self._checkpoint_store.resume(
                    checkpoint_id,
                    source_hash=source_hash,
                    model=self._translate_service.model,
                    chunk_chars=resolved_chunk_chars,
                    total_chunks=len(chunks),
                )
            except TranslationCheckpointError as exc:
                raise TranslationError(
                    "번역 임시 파일을 불러오지 못했습니다. "
                    "상세 원인은 로그 파일을 확인해 주세요."
                ) from exc

            if translated:
                self._progress(
                    f"  - 임시 파일에서 {len(translated)}/{len(chunks)}개 "
                    "완료 청크를 불러왔습니다."
                )

        self._progress(
            f"  - 본문을 {len(chunks)}개 청크로 분할 "
            f"(청크당 최대 {resolved_chunk_chars:,}자)"
        )

        total_chunks = len(chunks)
        for index, chunk in enumerate(
            chunks[len(translated) :], start=len(translated) + 1
        ):
            logger.log(
                LogCode.TRANSLATION_CHUNK_STARTED,
                chunk_index=index,
                chunk_total=total_chunks,
                chunk_chars=len(chunk),
                model=self._translate_service.model,
            )
            self._progress(
                f"    [Ollama] 번역 {index}/{total_chunks} ({len(chunk):,}자)..."
            )
            try:
                translated.append(
                    self._translate_chunk_with_retry(
                        chunk, index=index, total=total_chunks
                    )
                )
            except (TranslateServiceError, TranslationMarkupError) as exc:
                logger.log(
                    LogCode.TRANSLATION_FAILED,
                    reason=exc.reason,
                    retryable=exc.retryable,
                    status_code=exc.status_code,
                    chunk_index=index,
                    chunk_total=total_chunks,
                    chunk_chars=len(chunk),
                    model=self._translate_service.model,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                raise TranslationError(self._failure_message(index, exc)) from exc
            except Exception as exc:
                logger.log(
                    LogCode.TRANSLATION_FAILED,
                    reason="unexpected_translation_error",
                    retryable=False,
                    status_code=None,
                    chunk_index=index,
                    chunk_total=len(chunks),
                    chunk_chars=len(chunk),
                    model=self._translate_service.model,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                raise TranslationError(
                    f"{index}번째 청크 번역에 예상하지 못한 오류가 발생했습니다. "
                    "상세 원인은 로그 파일을 확인해 주세요."
                ) from exc

            if checkpoint_id:
                try:
                    self._checkpoint_store.save_chunk(
                        checkpoint_id,
                        source_hash=source_hash,
                        model=self._translate_service.model,
                        chunk_chars=resolved_chunk_chars,
                        total_chunks=total_chunks,
                        chunk_index=index,
                        translated_chunk=translated[-1],
                    )
                except TranslationCheckpointError as exc:
                    raise TranslationError(
                        "번역 임시 파일을 저장하지 못했습니다. "
                        "상세 원인은 로그 파일을 확인해 주세요."
                    ) from exc

        result = "\n\n".join(translated)
        if references.strip():
            self._progress("  - 참고문헌은 원문 그대로 보존합니다.")
            result = f"{result}\n\n{references}"

        if checkpoint_id:
            try:
                self._checkpoint_store.delete(checkpoint_id)
            except TranslationCheckpointError:
                pass
        return result, total_chunks

    @staticmethod
    def _safe_name(paper_id: str) -> str:
        safe_name = re.sub(r"[^0-9A-Za-z._-]+", "_", paper_id).strip("._")
        return safe_name or hashlib.sha256(paper_id.encode("utf-8")).hexdigest()[:20]

    def _save_translation(self, *, paper_id: str, markdown: str) -> Path:
        """완료된 번역을 summary 도구가 읽을 마크다운 파일로 저장한다."""
        output_path = self._output_directory / f"{self._safe_name(paper_id)}.md"
        temporary_path = output_path.with_suffix(".md.tmp")
        try:
            self._output_directory.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(markdown, encoding="utf-8")
            temporary_path.replace(output_path)
        except (OSError, UnicodeError) as exc:
            logger.log(
                LogCode.TRANSLATION_MARKDOWN_SAVE_FAILED,
                paper_id=paper_id,
                output_path=output_path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise TranslationError(
                "번역은 생성했지만 마크다운 파일 저장에 실패했습니다. "
                "상세 원인은 로그 파일을 확인해 주세요."
            ) from exc
        logger.log(
            LogCode.TRANSLATION_MARKDOWN_SAVED,
            paper_id=paper_id,
            output_path=output_path,
            output_chars=len(markdown),
        )
        return output_path

    def translate_paper(
        self,
        markdown: str,
        *,
        paper_id: str | None = None,
        title: str | None = None,
        chunk_chars: int | None = None,
    ) -> Path:
        """추출 모듈이 반환한 마크다운 논문을 직접 번역한다."""
        if not isinstance(markdown, str) or not markdown.strip():
            logger.log(
                LogCode.TRANSLATION_REJECTED,
                paper_id=paper_id,
                reason="empty_markdown",
                retryable=False,
            )
            raise TranslationError("번역할 논문 마크다운이 비어 있습니다.")

        resolved_paper_id = (paper_id or "").strip() or (
            f"markdown-{hashlib.sha256(markdown.encode('utf-8')).hexdigest()[:16]}"
        )
        resolved_title = (title or "").strip()
        if not resolved_title:
            title_match = TITLE_PATTERN.search(markdown)
            resolved_title = title_match.group(1).strip() if title_match else "제목 없음"
        resolved_chunk_chars = self._resolve_chunk_chars(chunk_chars)
        try:
            self._translate_service.ensure_available()
        except TranslateServiceError as exc:
            raise TranslationError(str(exc)) from exc

        logger.log(
            LogCode.TRANSLATION_STARTED,
            paper_id=resolved_paper_id,
            title=resolved_title,
            model=self._translate_service.model,
            input_chars=len(markdown),
            chunk_chars=resolved_chunk_chars,
            temperature=self._translate_service.temperature,
            max_tokens=self._translate_service.max_tokens,
            timeout=self._translate_service.timeout,
            max_retries=self._translate_service.max_retries,
            retry_backoff_seconds=self._translate_service.retry_backoff_seconds,
        )
        self._progress(f"\n[Agent 3] '{resolved_title[:50]}...' 번역 시작")
        translated_markdown, n_chunks = self.translate_markdown(
            markdown,
            chunk_chars=resolved_chunk_chars,
            checkpoint_id=resolved_paper_id,
        )

        header = (
            f"# {resolved_title}\n\n"
            f"- **논문 ID**: {resolved_paper_id}\n"
            f"- **번역 모델**: {self._translate_service.model}\n\n---\n\n"
        )
        translated_markdown = header + translated_markdown
        output_path = self._save_translation(
            paper_id=resolved_paper_id,
            markdown=translated_markdown,
        )

        logger.log(
            LogCode.TRANSLATION_SUCCEEDED,
            paper_id=resolved_paper_id,
            title=resolved_title,
            model=self._translate_service.model,
            chunk_count=n_chunks,
            output_chars=len(translated_markdown),
        )
        self._progress(
            f"  [완료] 번역: {len(translated_markdown):,}자\n"
            f"  [완료] 번역 저장: {output_path}"
        )
        return output_path

    def translate_file(
        self,
        markdown_path: str | Path,
        *,
        paper_id: str | None = None,
        title: str | None = None,
        chunk_chars: int | None = None,
    ) -> Path:
        """추출된 UTF-8 마크다운 파일을 읽어 번역한다."""
        path = Path(markdown_path)
        if path.suffix.casefold() != ".md":
            logger.log(
                LogCode.TRANSLATION_REJECTED,
                paper_id=paper_id,
                reason="unsupported_file_type",
                retryable=False,
                markdown_path=path,
            )
            raise TranslationError("번역 입력 파일은 .md 형식이어야 합니다.")
        try:
            markdown = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            logger.log(
                LogCode.TRANSLATION_REJECTED,
                paper_id=paper_id,
                reason="markdown_file_read_failed",
                retryable=False,
                markdown_path=path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise TranslationError(
                f"마크다운 파일을 읽지 못했습니다: {path}"
            ) from exc

        return self.translate_paper(
            markdown,
            paper_id=paper_id or path.stem,
            title=title,
            chunk_chars=chunk_chars,
        )