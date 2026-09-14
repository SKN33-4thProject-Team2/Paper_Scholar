"""Agent 4: 청크 근거 추출과 최종 통합을 수행하는 논문 요약 에이전트."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from log import AppLogger, LogCode
from services.generation_options import resolve_float, resolve_nonnegative_int, resolve_positive_int
from services.model_config_service import load_task_config
from services.nvidia_service import generate as nvidia_generate
from services.nvidia_service import is_available as nvidia_is_available
from services.ollama_service import OllamaServiceError, check_connection, generate
from services.summary_markdown_store import MarkdownSummaryArtifactStore, SummaryArtifactError, SummaryArtifactStore
from services.summary_checkpoint_service import SummaryCheckpointError, SummaryCheckpointStore
from services.summary_vector_store import ChromaSummaryStore, SummaryStore, SummaryStoreError
from services.translation_markdown_service import split_markdown_by_section, split_reference_section, strip_metadata_header


logger = AppLogger(__name__)
SUMMARY_CONFIG = load_task_config("summary")

SUMMARY_SECTIONS = (
    ("research_goal", "연구 목적 (Research Goal)"),
    ("methodology", "방법론 (Methodology)"),
    ("results", "실험 결과 (Experimental Results)"),
    ("limitations", "한계점 (Limitations)"),
)
CHUNK_EVIDENCE_FIELDS = (
    "key_points",
    "research_goal_evidence",
    "methodology_evidence",
    "results_evidence",
    "limitations_evidence",
)
CHUNK_SUMMARY_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "section": {"type": "string"},
        **{
            field: {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
            }
            for field in CHUNK_EVIDENCE_FIELDS
        },
    },
    "required": ["section", *CHUNK_EVIDENCE_FIELDS],
    "additionalProperties": False,
}
FINAL_SUMMARY_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        key: {"type": "string"} for key, _label in SUMMARY_SECTIONS
    },
    "required": [key for key, _label in SUMMARY_SECTIONS],
    "additionalProperties": False,
}

CHUNK_SYSTEM_PROMPT = """당신은 학술 논문의 부분 원문에서 검증 가능한 근거만 추출하는 분석가입니다.
입력은 논문 전체가 아닌 한 청크입니다. 청크에 없는 정보를 추론하거나 빈 항목을 억지로 채우지 마세요.

[추출 규칙]
- section: 청크에서 확인되는 대표 섹션명. 알 수 없으면 빈 문자열
- key_points: 이 청크의 핵심 주장 또는 사실
- research_goal_evidence: 연구 문제, 목적, 동기를 직접 보여주는 내용
- methodology_evidence: 데이터, 모델, 알고리즘, 실험 설계 등 방법론 근거
- results_evidence: 실험 결과와 정량 수치. 수치와 조건을 함께 보존
- limitations_evidence: 저자가 직접 밝힌 한계, 실패 사례, 향후 과제
- 근거가 없는 배열은 반드시 []로 반환
- 각 배열은 최대 5개, 각 항목은 최대 2문장으로 작성
- 원문을 재구성하지 말고 요약에 필요한 핵심 근거만 추출
- 모든 내용은 한국어로 간결하게 작성하되 모델명, 데이터셋명, 수치, 수식은 보존
- JSON 외의 설명이나 코드펜스를 출력하지 않음

{"section":"", "key_points":[], "research_goal_evidence":[], "methodology_evidence":[], "results_evidence":[], "limitations_evidence":[]}"""

FINAL_SUMMARY_SYSTEM_PROMPT = """당신은 학술 논문 분석 전문가입니다.
입력은 원문 청크별로 추출한 근거 목록입니다. 근거를 중복 없이 통합하여 논문 전체의 최종 4단 요약을 작성하세요.

[항목]
1. research_goal: 논문이 해결하려는 문제와 연구 동기
2. methodology: 제안한 아키텍처, 핵심 기법, 데이터 및 실험 설계
3. results: 벤치마크 성능과 주요 실험 성과
4. limitations: 저자가 직접 언급한 제약 사항과 향후 과제

[통합 규칙]
- 모든 항목은 한국어로 작성
- 각 항목은 3~6문장 또는 '- '로 시작하는 불릿 3~6개
- 입력 근거에 없는 내용을 지어내거나 일반화하지 않음
- 상충하는 수치는 조건을 함께 적고 임의로 하나를 선택하지 않음
- results의 수치, 데이터셋명, 비교 기준을 가능한 한 보존
- limitations 근거가 하나도 없으면 정확히 "논문에 명시되어 있지 않습니다."만 작성
- 전문 용어는 처음 등장할 때 한국어(영어)로 병기
- JSON 외의 설명이나 코드펜스를 출력하지 않음
- 각 JSON 값은 배열이 아닌 하나의 문자열

{"research_goal":"", "methodology":"", "results":"", "limitations":""}"""


class SummaryError(RuntimeError):
    """요약을 완료하지 못했을 때 발생한다."""


@dataclass
class PaperSummary:
    """논문 한 편의 최종 4단 구조 요약."""

    id: str
    title: str
    source: str
    model: str
    sections: dict[str, str]
    markdown_path: Path | None = None

    def to_markdown(self) -> str:
        parts = [
            "---",
            "schema_version: 1",
            "artifact_type: paper_summary",
            f"paper_id: {json.dumps(self.id, ensure_ascii=False)}",
            f"title: {json.dumps(self.title, ensure_ascii=False)}",
            f"source: {json.dumps(self.source, ensure_ascii=False)}",
            f"summary_model: {json.dumps(self.model, ensure_ascii=False)}",
            "language: ko",
            "---\n",
            f"# {self.title}\n",
        ]
        for key, label in SUMMARY_SECTIONS:
            parts.extend((f"## {label}\n", f"{self.sections.get(key, '').strip()}\n"))
        return "\n".join(parts)


class SummaryTool:
    """논문을 청크별로 분석한 뒤 근거를 최종 4단 구조로 통합한다."""

    def __init__(
        self,
        progress: Callable[[str], None] = print,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        chunk_chars: int | None = None,
        chunk_max_tokens: int | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        summary_store: SummaryStore | None = None,
        artifact_store: SummaryArtifactStore | None = None,
        checkpoint_store: SummaryCheckpointStore | None = None,
        generator: Callable[..., str] | None = None,
    ) -> None:
        self._progress = progress
        # provider 로 어디에 물어볼지 고른다. 기본값은 지금까지 쓰던 ollama 다.
        # nvidia_service.generate 는 ollama 쪽과 같은 모양이라 그대로 갈아 끼운다.
        self._provider = str(SUMMARY_CONFIG.get("provider", "ollama")).strip().casefold()
        default_generator = nvidia_generate if self._provider == "nvidia" else generate
        self._generator = generator or default_generator
        self._model = str(SUMMARY_CONFIG["model"])
        self._temperature = resolve_float(
            "summary.temperature",
            SUMMARY_CONFIG["temperature"] if temperature is None else temperature,
            minimum=0.0,
            maximum=2.0,
        )
        self._max_tokens = resolve_positive_int(
            "summary.max_tokens",
            SUMMARY_CONFIG["max_tokens"] if max_tokens is None else max_tokens,
        )
        self._timeout = resolve_float(
            "summary.timeout",
            SUMMARY_CONFIG["timeout"] if timeout is None else timeout,
            minimum=0.1,
        )
        self._chunk_chars = resolve_positive_int(
            "summary.chunk_chars",
            SUMMARY_CONFIG["chunk_chars"] if chunk_chars is None else chunk_chars,
        )
        self._chunk_max_tokens = resolve_positive_int(
            "summary.chunk_max_tokens",
            SUMMARY_CONFIG["chunk_max_tokens"]
            if chunk_max_tokens is None
            else chunk_max_tokens,
        )
        self._max_retries = resolve_nonnegative_int(
            "summary.max_retries",
            SUMMARY_CONFIG["max_retries"] if max_retries is None else max_retries,
        )
        self._retry_backoff_seconds = resolve_float(
            "summary.retry_backoff_seconds",
            SUMMARY_CONFIG["retry_backoff_seconds"]
            if retry_backoff_seconds is None
            else retry_backoff_seconds,
            minimum=0.0,
        )
        # Vector DB 초기화는 실제 저장이 필요한 시점까지 미룬다.
        self._summary_store = summary_store
        self._artifact_store = artifact_store or MarkdownSummaryArtifactStore()
        self._checkpoint_store = checkpoint_store or SummaryCheckpointStore()

    @staticmethod
    def _json_object(response: str) -> dict[str, object]:
        text = response.strip()
        fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        if not text.startswith("{"):
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                text = match.group(0)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SummaryError(f"모델 응답에서 JSON을 추출하지 못했습니다: {response[:200]}") from exc
        if not isinstance(payload, dict):
            raise SummaryError("모델 요약 응답은 JSON 객체여야 합니다.")
        return payload

    @classmethod
    def _parse_chunk_response(cls, response: str) -> dict[str, object]:
        """청크 응답을 체크포인트에 저장 가능한 근거 객체로 정규화한다."""
        payload = cls._json_object(response)
        evidence: dict[str, object] = {"section": str(payload.get("section", "")).strip()}
        for field in CHUNK_EVIDENCE_FIELDS:
            value = payload.get(field, [])
            if not isinstance(value, list):
                raise SummaryError(f"청크 요약의 {field}는 배열이어야 합니다.")
            evidence[field] = [
                " ".join(item.split())
                for item in value
                if isinstance(item, str) and item.strip()
            ]
        if not any(evidence[field] for field in CHUNK_EVIDENCE_FIELDS):
            raise SummaryError("청크 요약에 유효한 근거가 없습니다.")
        return evidence

    @classmethod
    def _parse_response(cls, response: str) -> dict[str, str]:
        """최종 통합 응답에서 네 항목을 추출한다."""
        payload = cls._json_object(response)
        sections: dict[str, str] = {}
        for key, _label in SUMMARY_SECTIONS:
            value = payload.get(key, "")
            if isinstance(value, list):
                items = []
                for item in value:
                    text = str(item).strip()
                    if text:
                        items.append(text.removeprefix("- ").strip())
                sections[key] = "\n".join(f"- {item}" for item in items)
            elif isinstance(value, str):
                sections[key] = value.strip()
            else:
                sections[key] = ""
        if not all(sections.values()):
            missing = [key for key, value in sections.items() if not value]
            raise SummaryError(f"최종 요약에 비어 있는 항목이 있습니다: {', '.join(missing)}")
        return sections

    def _generate_with_retry(
        self,
        prompt: str,
        *,
        phase: str,
        max_tokens: int,
        response_schema: dict[str, object],
        chunk_index: int | None = None,
        total_chunks: int | None = None,
    ) -> str:
        attempt_max_tokens = max_tokens
        for attempt in range(self._max_retries + 1):
            try:
                return self._generator(
                    prompt,
                    model=self._model,
                    response_format=response_schema,
                    temperature=self._temperature,
                    max_tokens=attempt_max_tokens,
                    timeout=self._timeout,
                )
            except OllamaServiceError as exc:
                if not exc.retryable or attempt >= self._max_retries:
                    raise SummaryError(f"요약 생성 실패: {exc}") from exc
                if exc.reason == "output_truncated":
                    attempt_max_tokens *= 2
                delay = self._retry_backoff_seconds * (2**attempt)
                logger.log(
                    LogCode.SUMMARY_RETRYING,
                    phase=phase,
                    chunk_index=chunk_index,
                    total_chunks=total_chunks,
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    delay_seconds=delay,
                    reason=exc.reason,
                    next_max_tokens=attempt_max_tokens,
                )
                self._progress(
                    f"    [재시도] {delay:g}초 후 요약 요청을 다시 보냅니다 "
                    f"({attempt + 1}/{self._max_retries})."
                )
                if delay:
                    time.sleep(delay)
        raise AssertionError("unreachable")

    def _summarize_chunk(self, chunk: str, *, title: str, index: int, total: int) -> dict[str, object]:
        response = self._generate_with_retry(
            f"{CHUNK_SYSTEM_PROMPT}\n\n논문 제목: {title}\n청크: {index}/{total}\n\n[청크 원문]\n{chunk}",
            phase="chunk", max_tokens=self._chunk_max_tokens,
            response_schema=CHUNK_SUMMARY_SCHEMA,
            chunk_index=index, total_chunks=total,
        )
        return self._parse_chunk_response(response)

    def _reduce_summaries(self, chunk_summaries: list[dict[str, object]], *, title: str) -> dict[str, str]:
        # 들여쓰기를 제거해 reduce 단계의 입력 토큰과 직렬화 비용을 줄인다.
        evidence_json = json.dumps(chunk_summaries, ensure_ascii=False, separators=(",", ":"))
        response = self._generate_with_retry(
            f"{FINAL_SUMMARY_SYSTEM_PROMPT}\n\n논문 제목: {title}\n\n[청크별 근거]\n{evidence_json}",
            phase="reduce", max_tokens=self._max_tokens,
            response_schema=FINAL_SUMMARY_SCHEMA,
        )
        return self._parse_response(response)

    def summarize_markdown(self, markdown: str, *, title: str, paper_id: str | None = None) -> dict[str, str]:
        """본문 전체를 청크별로 분석하고 최종 4단 구조로 통합한다."""
        body, _references = split_reference_section(strip_metadata_header(markdown))
        body = body.strip()
        if not body:
            raise SummaryError("요약할 본문이 비어 있습니다.")
        chunks = split_markdown_by_section(body, max_chars=self._chunk_chars)
        total_chunks = len(chunks)
        source_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        serialized_summaries: list[str] = []
        if paper_id:
            try:
                serialized_summaries = self._checkpoint_store.resume(
                    paper_id, source_hash=source_hash, model=self._model,
                    chunk_chars=self._chunk_chars, total_chunks=total_chunks,
                )
            except SummaryCheckpointError as exc:
                raise SummaryError("요약 체크포인트를 불러오지 못했습니다.") from exc
        chunk_summaries = [
            self._parse_chunk_response(serialized) for serialized in serialized_summaries
        ]
        if serialized_summaries:
            self._progress(
                f"  - 체크포인트에서 {len(serialized_summaries)}/{total_chunks}개 "
                "청크 요약을 복구했습니다."
            )

        for index in range(len(chunk_summaries) + 1, total_chunks + 1):
            chunk = chunks[index - 1]
            logger.log(LogCode.SUMMARY_CHUNK_STARTED, paper_id=paper_id, chunk_index=index, total_chunks=total_chunks, input_chars=len(chunk), model=self._model)
            self._progress(f"    [Ollama] {index}/{total_chunks} 청크 근거 추출 중 ({len(chunk):,}자)")
            evidence = self._summarize_chunk(chunk, title=title, index=index, total=total_chunks)
            chunk_summaries.append(evidence)
            if paper_id:
                try:
                    self._checkpoint_store.save_chunk(
                        paper_id, source_hash=source_hash, model=self._model,
                        chunk_chars=self._chunk_chars, total_chunks=total_chunks,
                        chunk_index=index,
                        chunk_summary=json.dumps(
                            evidence, ensure_ascii=False, separators=(",", ":")
                        ),
                    )
                except SummaryCheckpointError as exc:
                    raise SummaryError("요약 청크는 생성했지만 체크포인트 저장에 실패했습니다.") from exc

        logger.log(LogCode.SUMMARY_REDUCE_STARTED, paper_id=paper_id, model=self._model, chunk_count=total_chunks)
        self._progress("    [Ollama] 청크별 근거를 최종 4단 요약으로 통합 중")
        return self._reduce_summaries(chunk_summaries, title=title)

    def summarize_file(self, markdown_path: str | Path) -> PaperSummary:
        """저장된 번역 Markdown 파일을 읽어 요약한다."""
        path = Path(markdown_path)
        if path.suffix.casefold() != ".md":
            raise SummaryError("요약 입력 파일은 .md 형식이어야 합니다.")
        try:
            markdown = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise SummaryError(f"번역 마크다운 파일을 읽지 못했습니다: {path}") from exc
        content = strip_metadata_header(markdown)
        title_match = re.search(r"^#\s+(.+?)\s*$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else path.stem
        return self._summarize(paper_id=path.stem, title=title, markdown=markdown, source="translated_markdown")

    def _summarize(self, *, paper_id: str, title: str, markdown: str, source: str) -> PaperSummary:
        """읽어 온 번역 Markdown을 요약하고 산출물과 Vector DB에 저장한다."""
        if self._provider == "nvidia":
            if not nvidia_is_available():
                logger.log(LogCode.SUMMARY_REJECTED, paper_id=paper_id, reason="nvidia_key_missing", retryable=False, model=self._model)
                raise SummaryError("NVIDIA API 키가 없어 요약 모델을 쓸 수 없습니다. .env 의 NVIDIA_API_KEY 를 확인해 주세요.")
        elif not check_connection(model=self._model):
            logger.log(LogCode.SUMMARY_REJECTED, paper_id=paper_id, reason="ollama_model_unavailable", retryable=False, model=self._model)
            raise SummaryError(f"Ollama 서버에서 요약 모델 '{self._model}'을 사용할 수 없습니다. Ollama 실행 상태와 모델 설치 여부를 확인해 주세요.")
        logger.log(
            LogCode.SUMMARY_STARTED, paper_id=paper_id, title=title, model=self._model,
            input_chars=len(markdown), temperature=self._temperature, max_tokens=self._max_tokens,
            timeout=self._timeout, chunk_chars=self._chunk_chars,
            chunk_max_tokens=self._chunk_max_tokens, max_retries=self._max_retries,
        )
        self._progress(f"\n[Agent 4] '{title[:50]}...' 청크 요약 시작 (입력: 번역 Markdown 파일)")
        try:
            sections = self.summarize_markdown(markdown, title=title, paper_id=paper_id)
        except SummaryError as exc:
            cause = exc.__cause__
            logger.log(LogCode.SUMMARY_FAILED, paper_id=paper_id, model=self._model, reason=getattr(cause, "reason", "summary_generation_failed"), retryable=getattr(cause, "retryable", False), status_code=getattr(cause, "status_code", None), error_type=type(exc).__name__, error=str(exc))
            raise

        summary = PaperSummary(
            id=paper_id,
            title=title,
            source=source,
            model=self._model,
            sections=sections,
        )
        summary_markdown = summary.to_markdown()
        logger.log(
            LogCode.SUMMARY_SUCCEEDED,
            paper_id=summary.id,
            title=summary.title,
            model=summary.model,
            section_count=len(summary.sections),
            output_chars=len(summary_markdown),
        )
        try:
            summary.markdown_path = self._artifact_store.save(
                paper_id=summary.id, markdown=summary_markdown
            )
        except SummaryArtifactError as exc:
            raise SummaryError("요약은 생성했지만 마크다운 파일 저장에 실패했습니다. 상세 원인은 로그 파일을 확인해 주세요.") from exc
        try:
            summary_store = self._summary_store
            if summary_store is None:
                summary_store = self._summary_store = ChromaSummaryStore()
            stored_count = summary_store.save(
                paper_id=summary.id,
                title=summary.title,
                source=summary.source,
                summary_model=summary.model,
                sections=summary.sections,
            )
        except SummaryStoreError as exc:
            raise SummaryError(f"요약은 {summary.markdown_path}에 저장했지만 벡터 DB 저장에 실패했습니다. 상세 원인은 로그 파일을 확인해 주세요.") from exc
        try:
            self._checkpoint_store.delete(paper_id)
        except SummaryCheckpointError:
            pass
        self._progress(f"  [완료] 요약 저장: {summary.markdown_path}\n  [완료] Vector DB 저장: {stored_count}개 섹션")
        return summary
