"""사람과 후속 에이전트가 읽을 수 있는 요약 마크다운을 저장한다."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol

from log import AppLogger, LogCode

from . import PROJECT_ROOT
from .model_config_service import ModelConfigError, load_task_config


logger = AppLogger(__name__)


class SummaryArtifactError(RuntimeError):
    """요약 마크다운 산출물을 저장하지 못했을 때 발생한다."""


class SummaryArtifactStore(Protocol):
    """SummaryTool이 사용하는 요약 파일 저장소 규격."""

    def save(self, *, paper_id: str, markdown: str) -> Path:
        """마크다운 산출물을 저장하고 경로를 반환한다."""


def _output_directory() -> Path:
    try:
        config = load_task_config("summary")
    except ModelConfigError as exc:
        raise RuntimeError("요약 산출물 설정을 읽지 못했습니다.") from exc
    directory = str(config.get("output_directory", "")).strip()
    if not directory:
        raise RuntimeError("model_config.yaml의 summary.output_directory가 필요합니다.")
    return PROJECT_ROOT / directory


DEFAULT_SUMMARY_DIR = _output_directory()


class MarkdownSummaryArtifactStore:
    """논문 ID별 요약 마크다운을 원자적으로 저장한다."""

    def __init__(self, directory: str | Path = DEFAULT_SUMMARY_DIR) -> None:
        self.directory = Path(directory)

    @staticmethod
    def _safe_name(paper_id: str) -> str:
        safe_name = re.sub(r"[^0-9A-Za-z._-]+", "_", paper_id).strip("._")
        if safe_name:
            return safe_name
        return hashlib.sha256(paper_id.encode("utf-8")).hexdigest()[:20]

    def path_for(self, paper_id: str) -> Path:
        return self.directory / f"{self._safe_name(paper_id)}.md"

    def save(self, *, paper_id: str, markdown: str) -> Path:
        """완성된 요약을 UTF-8 마크다운 파일로 저장한다."""
        if not markdown.strip():
            raise SummaryArtifactError("저장할 요약 마크다운이 비어 있습니다.")
        output_path = self.path_for(paper_id)
        temporary_path = output_path.with_suffix(".md.tmp")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(markdown, encoding="utf-8")
            temporary_path.replace(output_path)
        except (OSError, UnicodeError) as exc:
            logger.log(
                LogCode.SUMMARY_MARKDOWN_SAVE_FAILED,
                paper_id=paper_id,
                output_path=output_path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise SummaryArtifactError("요약 마크다운을 저장하지 못했습니다.") from exc

        logger.log(
            LogCode.SUMMARY_MARKDOWN_SAVED,
            paper_id=paper_id,
            output_path=output_path,
            output_chars=len(markdown),
        )
        return output_path
