"""로컬 Ollama API 호출만 담당하는 서비스."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from log import AppLogger, LogCode
from .generation_options import resolve_float, resolve_positive_int
from .model_config_service import ModelConfigError, load_provider_config

logger = AppLogger(__name__)


def _load_ollama_config() -> dict[str, object]:
    """Ollama 제공자의 연결 설정만 읽는다."""
    try:
        ollama_data = load_provider_config("ollama")
    except ModelConfigError as exc:
        logger.log(
            LogCode.OLLAMA_CONFIG_LOAD_FAILED,
            reason="ollama_provider_config_invalid",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise RuntimeError("Ollama 제공자 설정을 읽을 수 없습니다.") from exc

    host = str(ollama_data.get("host", "")).strip().rstrip("/")
    if not host:
        logger.log(
            LogCode.OLLAMA_CONFIG_LOAD_FAILED,
            reason="ollama_host_missing",
            required_fields=["providers.ollama.host"],
        )
        raise RuntimeError("providers.ollama.host 설정이 필요합니다.")

    try:
        connection_timeout = resolve_float(
            "providers.ollama.connection_timeout",
            ollama_data.get("connection_timeout"),
            minimum=0.1,
        )
    except ValueError as exc:
        logger.log(
            LogCode.OLLAMA_CONFIG_LOAD_FAILED,
            reason="invalid_generation_options",
            error=str(exc),
        )
        raise RuntimeError(f"Ollama 설정값이 올바르지 않습니다: {exc}") from exc

    return {
        "host": host,
        "connection_timeout": connection_timeout,
    }


OLLAMA_CONFIG = _load_ollama_config()


class OllamaServiceError(RuntimeError):
    """Ollama 서버 요청을 완료하지 못했을 때 발생한다."""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "ollama_error",
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable
        self.status_code = status_code


def check_connection(
    timeout: float | None = None, *, model: str | None = None
) -> bool:
    """Ollama 서버와 설정된 모델의 사용 가능 여부를 확인하고 로그로 남긴다."""
    host = str(OLLAMA_CONFIG["host"])
    resolved_model = str(model or "").strip()
    if not resolved_model:
        raise ValueError("연결 확인할 모델 이름이 필요합니다.")
    resolved_timeout = resolve_float(
        "timeout",
        OLLAMA_CONFIG["connection_timeout"] if timeout is None else timeout,
        minimum=0.1,
    )
    started_at = time.perf_counter()

    try:
        with urllib.request.urlopen(
            f"{host}/api/tags", timeout=resolved_timeout
        ) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not isinstance(body, dict):
            raise TypeError("Ollama 모델 목록 응답이 JSON 객체가 아닙니다.")
        models = body.get("models")
        if not isinstance(models, list):
            raise TypeError("Ollama 모델 목록 응답에 models 배열이 없습니다.")
        available_models = {
            item.get("name")
            for item in models
            if isinstance(item, dict)
        }
        connected = resolved_model in available_models
        logger.log(
            LogCode.OLLAMA_CONNECTION_CHECKED,
            connected=connected,
            host=host,
            model=resolved_model,
            model_available=connected,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return connected
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, TypeError) as exc:
        logger.log(
            LogCode.OLLAMA_CONNECTION_FAILED,
            host=host,
            model=resolved_model,
            reason="connection_or_response_failed",
            error_type=type(exc).__name__,
            error=str(exc),
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return False


def generate(
    prompt: str,
    *,
    model: str | None = None,
    stream: bool = False,
    response_format: str | dict[str, object] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> str:
    """지정한 방식으로 Ollama generate API를 호출하고 텍스트만 반환한다."""
    resolved_model = str(model or "").strip()
    if not resolved_model:
        raise ValueError("생성에 사용할 모델 이름이 필요합니다.")
    resolved_temperature = resolve_float(
        "temperature",
        temperature,
        minimum=0.0,
        maximum=2.0,
    )
    resolved_max_tokens = resolve_positive_int(
        "max_tokens",
        max_tokens,
    )
    resolved_timeout = resolve_float(
        "timeout",
        timeout,
        minimum=0.1,
    )
    if not isinstance(stream, bool):
        raise ValueError("stream은(는) true 또는 false여야 합니다.")
    host = str(OLLAMA_CONFIG["host"])
    started_at = time.perf_counter()
    payload: dict[str, object] = {
        "model": resolved_model,
        "prompt": prompt,
        "stream": stream,
        "options": {
            "temperature": resolved_temperature,
            "num_predict": resolved_max_tokens,
        },
    }
    if response_format:
        payload["format"] = response_format

    request = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=resolved_timeout) as response:
            response_lines = [line for line in response if line.strip()]
    except urllib.error.HTTPError as exc:
        retryable = exc.code in {408, 429} or 500 <= exc.code < 600
        logger.log(
            LogCode.OLLAMA_GENERATION_FAILED,
            connected=True,
            host=host,
            model=resolved_model,
            reason="http_error",
            status_code=exc.code,
            error_type=type(exc).__name__,
            error=str(exc),
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        raise OllamaServiceError(
            f"Ollama 요청에 실패했습니다(HTTP {exc.code}).",
            reason="http_error",
            retryable=retryable,
            status_code=exc.code,
        ) from exc
    except TimeoutError as exc:
        logger.log(
            LogCode.OLLAMA_GENERATION_FAILED,
            host=host,
            model=resolved_model,
            reason="request_timeout",
            timeout=resolved_timeout,
            error_type=type(exc).__name__,
            error=str(exc),
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        raise OllamaServiceError(
            "Ollama 응답이 제한 시간 동안 도착하지 않았습니다.",
            reason="request_timeout",
            retryable=True,
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        logger.log(
            LogCode.OLLAMA_GENERATION_FAILED,
            connected=False,
            host=host,
            model=resolved_model,
            reason="request_failed",
            error_type=type(exc).__name__,
            error=str(exc),
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        raise OllamaServiceError(
            "Ollama에 연결하지 못했습니다. Ollama 실행 상태와 모델 설치 상태를 확인해 주세요.",
            reason="connection_failed",
            retryable=True,
        ) from exc

    try:
        result_parts: list[str] = []
        completed = False
        done_reason = ""
        for response_line in response_lines:
            body = json.loads(response_line.decode("utf-8"))
            if not isinstance(body, dict):
                raise TypeError("Ollama 스트리밍 응답이 JSON 객체가 아닙니다.")
            if body.get("error"):
                raise TypeError(f"Ollama 생성 오류: {body['error']}")
            text = body.get("response")
            if not isinstance(text, str):
                raise TypeError("Ollama 스트리밍 응답에 텍스트가 없습니다.")
            result_parts.append(text)
            if body.get("done") is True:
                completed = True
                done_reason = str(body.get("done_reason", ""))

        if not completed:
            raise TypeError("Ollama 스트리밍 완료 응답이 없습니다.")
        result = "".join(result_parts)
        if done_reason == "length":
            logger.log(
                LogCode.OLLAMA_GENERATION_FAILED,
                connected=True,
                host=host,
                model=resolved_model,
                reason="output_truncated",
                done_reason=done_reason,
                max_tokens=resolved_max_tokens,
                output_chars=len(result),
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            )
            raise OllamaServiceError(
                "Ollama 응답이 출력 토큰 제한으로 중단되었습니다.",
                reason="output_truncated",
                retryable=True,
            )
        logger.log(
            LogCode.OLLAMA_GENERATION_SUCCEEDED,
            connected=True,
            host=host,
            model=resolved_model,
            response_format=(
                "json_schema" if isinstance(response_format, dict) else response_format
            ),
            done_reason=done_reason,
            temperature=resolved_temperature,
            max_tokens=resolved_max_tokens,
            timeout=resolved_timeout,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return result
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.log(
            LogCode.OLLAMA_GENERATION_FAILED,
            connected=True,
            host=host,
            model=resolved_model,
            reason="invalid_response",
            error_type=type(exc).__name__,
            error=str(exc),
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        raise OllamaServiceError(
            "Ollama 응답 형식이 올바르지 않습니다.",
            reason="invalid_response",
            retryable=True,
        ) from exc
