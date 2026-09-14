"""번역 재개용 청크를 각각 저장하는 임시 체크포인트 저장소."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from log import AppLogger, LogCode


DEFAULT_CHECKPOINT_DIR = Path(__file__).resolve().parents[2] / "data" / "temp_translation"
logger = AppLogger(__name__)


class TranslationCheckpointError(RuntimeError):
    """체크포인트 파일 처리에 실패했을 때 발생한다."""


class TranslationCheckpointInvalidError(TranslationCheckpointError):
    """체크포인트가 현재 번역 요청과 맞지 않을 때 발생한다."""


class TranslationCheckpointStore:
    """메타데이터와 완료 청크를 별도 파일로 원자적 저장한다."""

    def __init__(self, directory: str | Path = DEFAULT_CHECKPOINT_DIR) -> None:
        self.directory = Path(directory)

    def path_for(self, paper_id: str) -> Path:
        digest = hashlib.sha256(paper_id.encode("utf-8")).hexdigest()[:20]
        return self.directory / digest

    @staticmethod
    def _metadata(
        paper_id: str,
        *,
        source_hash: str,
        model: str,
        chunk_chars: int,
        total_chunks: int,
    ) -> dict[str, object]:
        return {
            "version": 2,
            "paper_id": paper_id,
            "source_hash": source_hash,
            "model": model,
            "chunk_chars": chunk_chars,
            "total_chunks": total_chunks,
        }

    @staticmethod
    def _chunk_path(checkpoint_path: Path, chunk_index: int) -> Path:
        return checkpoint_path / f"{chunk_index:06d}.txt"

    def load(
        self,
        paper_id: str,
        *,
        source_hash: str,
        model: str,
        chunk_chars: int,
        total_chunks: int,
    ) -> list[str]:
        """현재 요청과 일치하는 연속된 완료 청크를 불러온다."""
        checkpoint_path = self.path_for(paper_id)
        if not checkpoint_path.exists():
            return []
        if not checkpoint_path.is_dir():
            raise TranslationCheckpointInvalidError(
                "임시 체크포인트 경로가 디렉토리가 아닙니다."
            )

        expected = self._metadata(
            paper_id,
            source_hash=source_hash,
            model=model,
            chunk_chars=chunk_chars,
            total_chunks=total_chunks,
        )
        try:
            payload = json.loads(
                (checkpoint_path / "metadata.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TranslationCheckpointInvalidError(
                "임시 체크포인트 메타데이터를 읽지 못했습니다."
            ) from exc
        if payload != expected:
            raise TranslationCheckpointInvalidError(
                "임시 체크포인트가 현재 본문·모델·청크 설정과 맞지 않습니다."
            )

        completed: list[str] = []
        try:
            for index in range(1, total_chunks + 1):
                chunk_path = self._chunk_path(checkpoint_path, index)
                if not chunk_path.is_file():
                    break
                content = chunk_path.read_text(encoding="utf-8")
                if not content:
                    raise TranslationCheckpointInvalidError(
                        f"{index}번째 임시 번역 청크가 비어 있습니다."
                    )
                completed.append(content)
        except (OSError, UnicodeError) as exc:
            raise TranslationCheckpointInvalidError(
                "임시 번역 청크를 읽지 못했습니다."
            ) from exc

        chunk_files = list(checkpoint_path.glob("[0-9][0-9][0-9][0-9][0-9][0-9].txt"))
        if len(chunk_files) != len(completed):
            raise TranslationCheckpointInvalidError(
                "임시 번역 청크가 연속적으로 저장되지 않았습니다."
            )
        return completed

    def resume(
        self,
        paper_id: str,
        *,
        source_hash: str,
        model: str,
        chunk_chars: int,
        total_chunks: int,
    ) -> list[str]:
        """유효한 청크를 재개하고 오래된 체크포인트는 초기화한다."""
        try:
            completed = self.load(
                paper_id,
                source_hash=source_hash,
                model=model,
                chunk_chars=chunk_chars,
                total_chunks=total_chunks,
            )
        except TranslationCheckpointInvalidError as exc:
            logger.log(
                LogCode.TRANSLATION_CHECKPOINT_INVALID,
                paper_id=paper_id,
                reason="checkpoint_invalid_or_stale",
                checkpoint_path=self.path_for(paper_id),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            self.delete(paper_id)
            return []

        if completed:
            logger.log(
                LogCode.TRANSLATION_RESUMED,
                paper_id=paper_id,
                completed_chunks=len(completed),
                total_chunks=total_chunks,
                next_chunk=len(completed) + 1,
            )
        return completed

    def save_chunk(
        self,
        paper_id: str,
        *,
        source_hash: str,
        model: str,
        chunk_chars: int,
        total_chunks: int,
        chunk_index: int,
        translated_chunk: str,
    ) -> Path:
        """새로 완료된 청크 하나만 원자적으로 저장한다."""
        if not 1 <= chunk_index <= total_chunks or not translated_chunk:
            raise TranslationCheckpointError("저장할 번역 청크가 올바르지 않습니다.")

        checkpoint_path = self.path_for(paper_id)
        metadata_path = checkpoint_path / "metadata.json"
        chunk_path = self._chunk_path(checkpoint_path, chunk_index)
        try:
            checkpoint_path.mkdir(parents=True, exist_ok=True)
            if not metadata_path.exists():
                temporary_metadata = metadata_path.with_suffix(".tmp")
                temporary_metadata.write_text(
                    json.dumps(
                        self._metadata(
                            paper_id,
                            source_hash=source_hash,
                            model=model,
                            chunk_chars=chunk_chars,
                            total_chunks=total_chunks,
                        ),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                temporary_metadata.replace(metadata_path)

            temporary_chunk = chunk_path.with_suffix(".tmp")
            temporary_chunk.write_text(translated_chunk, encoding="utf-8")
            temporary_chunk.replace(chunk_path)
        except (OSError, UnicodeError) as exc:
            logger.log(
                LogCode.TRANSLATION_CHECKPOINT_FAILED,
                paper_id=paper_id,
                reason="checkpoint_save_failed",
                chunk_index=chunk_index,
                total_chunks=total_chunks,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise TranslationCheckpointError(
                "임시 번역 청크를 저장하지 못했습니다."
            ) from exc
        logger.log(
            LogCode.TRANSLATION_CHECKPOINT_SAVED,
            paper_id=paper_id,
            completed_chunks=chunk_index,
            total_chunks=total_chunks,
            checkpoint_path=chunk_path,
        )
        return chunk_path

    def delete(self, paper_id: str) -> Path:
        """번역이 완료된 논문의 임시 체크포인트를 삭제한다."""
        root = self.directory.resolve()
        checkpoint_path = self.path_for(paper_id).resolve()
        if checkpoint_path.parent != root:
            raise TranslationCheckpointError("안전하지 않은 체크포인트 경로입니다.")
        existed = checkpoint_path.exists()
        try:
            if checkpoint_path.is_dir():
                shutil.rmtree(checkpoint_path)
            elif checkpoint_path.exists():
                checkpoint_path.unlink()
        except OSError as exc:
            logger.log(
                LogCode.TRANSLATION_CHECKPOINT_FAILED,
                paper_id=paper_id,
                reason="checkpoint_delete_failed",
                checkpoint_path=checkpoint_path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise TranslationCheckpointError(
                "임시 체크포인트를 삭제하지 못했습니다."
            ) from exc
        if existed:
            logger.log(
                LogCode.TRANSLATION_CHECKPOINT_DELETED,
                paper_id=paper_id,
                checkpoint_path=checkpoint_path,
            )
        return checkpoint_path
