"""YAML에서 선택한 모델의 번역 설정, 연결 확인, 요청을 담당한다."""

from __future__ import annotations

from log import AppLogger, LogCode

from .generation_options import (
    resolve_float,
    resolve_nonnegative_int,
    resolve_positive_int,
)
from .model_config_service import ModelConfigError, load_task_config
from .nvidia_service import NvidiaServiceError
from .nvidia_service import chat as nvidia_chat
from .nvidia_service import is_available as nvidia_is_available
from .ollama_service import (
    OllamaServiceError,
    check_connection,
    generate,
)


logger = AppLogger(__name__)


def _load_translation_config() -> dict[str, object]:
    """번역에 필요한 YAML 항목만 읽고 검증한다."""
    try:
        data = load_task_config("translation")

        model = str(data.get("model", "")).strip()
        if not model:
            raise TranslateServiceError(
                "model_config.yaml의 translation.model이 필요합니다.",
                reason="translation_model_missing",
            )
        stream = data.get("stream")
        if not isinstance(stream, bool):
            raise ValueError("translation.stream은 true 또는 false여야 합니다.")

        # provider 로 어디에 물어볼지 고른다. 기본값은 지금까지 쓰던 ollama 다.
        provider = str(data.get("provider", "ollama")).strip().casefold() or "ollama"
        if provider not in ("ollama", "nvidia"):
            raise ValueError("translation.provider는 ollama 또는 nvidia여야 합니다.")

        return {
            "provider": provider,
            "model": model,
            "stream": stream,
            "temperature": resolve_float(
                "translation.temperature",
                data.get("temperature"),
                minimum=0.0,
                maximum=2.0,
            ),
            "max_tokens": resolve_positive_int(
                "translation.max_tokens", data.get("max_tokens")
            ),
            "timeout": resolve_float(
                "translation.timeout", data.get("timeout"), minimum=0.1
            ),
            "chunk_chars": resolve_positive_int(
                "translation.chunk_chars", data.get("chunk_chars")
            ),
            "max_retries": resolve_nonnegative_int(
                "translation.max_retries", data.get("max_retries")
            ),
            "retry_backoff_seconds": resolve_float(
                "translation.retry_backoff_seconds",
                data.get("retry_backoff_seconds"),
                minimum=0.0,
            ),
        }
    except TranslateServiceError as exc:
        logger.log(
            LogCode.OLLAMA_CONFIG_LOAD_FAILED,
            reason=exc.reason,
            error=str(exc),
        )
        raise
    except (ModelConfigError, ValueError) as exc:
        logger.log(
            LogCode.OLLAMA_CONFIG_LOAD_FAILED,
            reason="translation_config_invalid",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise TranslateServiceError(
            f"번역 모델 설정을 읽을 수 없습니다: {exc}",
            reason="translation_config_invalid",
        ) from exc


class TranslateServiceError(RuntimeError):
    """YAML에서 선택한 번역 모델을 사용할 수 없을 때 발생한다."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable
        self.status_code = status_code


class TranslateService:
    """YAML의 번역 설정과 선택된 모델로 Ollama를 호출한다."""

    def __init__(
        self,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        chunk_chars: int | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
    ) -> None:
        config = _load_translation_config()
        self.provider = str(config["provider"])
        self.model = str(config["model"])
        self.stream = bool(config["stream"])
        self.temperature = resolve_float(
            "translation.temperature",
            config["temperature"] if temperature is None else temperature,
            minimum=0.0,
            maximum=2.0,
        )
        self.max_tokens = resolve_positive_int(
            "translation.max_tokens",
            config["max_tokens"] if max_tokens is None else max_tokens,
        )
        self.timeout = resolve_float(
            "translation.timeout",
            config["timeout"] if timeout is None else timeout,
            minimum=0.1,
        )
        self.chunk_chars = resolve_positive_int(
            "translation.chunk_chars",
            config["chunk_chars"] if chunk_chars is None else chunk_chars,
        )
        self.max_retries = resolve_nonnegative_int(
            "translation.max_retries",
            config["max_retries"] if max_retries is None else max_retries,
        )
        self.retry_backoff_seconds = resolve_float(
            "translation.retry_backoff_seconds",
            config["retry_backoff_seconds"]
            if retry_backoff_seconds is None
            else retry_backoff_seconds,
            minimum=0.0,
        )

    def ensure_available(self) -> None:
        """YAML에서 선택한 모델의 연결 실패를 로그로 남기고 중단한다."""
        if self.provider == "nvidia":
            if nvidia_is_available():
                return
            logger.log(
                LogCode.TRANSLATION_REJECTED,
                reason="nvidia_key_missing",
                retryable=False,
                model=self.model,
            )
            raise TranslateServiceError(
                "NVIDIA API 키가 없어 번역 모델을 쓸 수 없습니다. "
                ".env 의 NVIDIA_API_KEY 를 확인해 주세요.",
                reason="nvidia_key_missing",
            )

        if check_connection(model=self.model):
            return
        logger.log(
            LogCode.TRANSLATION_REJECTED,
            reason="ollama_model_unavailable",
            retryable=False,
            model=self.model,
        )
        raise TranslateServiceError(
            f"Ollama 서버에서 번역 모델 '{self.model}'을 사용할 수 없습니다. "
            "Ollama 실행 상태와 모델 설치 여부를 확인해 주세요.",
            reason="ollama_model_unavailable",
        )

    def translate(self, prompt: str) -> str:
        """번역 모델을 호출하고 통신 실패를 번역 서비스 오류로 변환한다."""
        if self.provider == "nvidia":
            return self._translate_with_nvidia(prompt)

        try:
            return generate(
                prompt,
                model=self.model,
                stream=self.stream,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=self.timeout,
            ).strip()
        except OllamaServiceError as exc:
            raise TranslateServiceError(
                str(exc),
                reason=exc.reason,
                retryable=exc.retryable,
                status_code=exc.status_code,
            ) from exc

    def _translate_with_nvidia(self, prompt: str) -> str:
        """NVIDIA Build API 로 번역한다.

        같은 4,000자 조각을 로컬 CPU 는 331.9초, 이쪽은 21.8초에 옮겼다. 번역은
        입력만큼 긴 출력을 만들어야 해서 CPU 추론으로는 논문 한 편에 20~50분이
        걸린다. 재시도와 타임아웃은 nvidia_service 가 이미 처리한다.
        """
        try:
            return nvidia_chat(
                [{"role": "user", "content": prompt}],
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=int(self.timeout),
            ).strip()
        except NvidiaServiceError as exc:
            raise TranslateServiceError(
                str(exc),
                reason="nvidia_request_failed",
                retryable=True,
            ) from exc
