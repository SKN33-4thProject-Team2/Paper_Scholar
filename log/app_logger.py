"""프로젝트에서 공통으로 사용하는 애플리케이션 로거."""

from __future__ import annotations

import json
import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .log_codes import LogCode
from .log_messages import LOG_MESSAGES


DEFAULT_LOG_DIR = Path(__file__).resolve().parent


class AppLogger:
    """콘솔과 ``Log/app.log``에 구조화된 이벤트를 기록한다.

    같은 이름으로 여러 번 생성해도 핸들러가 중복 등록되지 않으므로 각 모듈에서
    ``AppLogger(__name__)`` 형태로 안전하게 사용할 수 있다.
    """

    _configured_loggers: set[str] = set()
    _lock = threading.Lock()

    def __init__(
        self,
        name: str,
        *,
        log_dir: str | Path | None = None,
        level: str | int | None = None,
        console: bool = True,
        max_bytes: int = 5 * 1024 * 1024,
        backup_count: int = 5,
    ) -> None:
        configured_level = level or os.getenv("APP_LOG_LEVEL", "INFO")
        resolved_level = self._resolve_level(configured_level)
        configured_dir = log_dir or os.getenv("APP_LOG_DIR") or DEFAULT_LOG_DIR
        self.log_path = Path(configured_dir).expanduser().resolve() / "app.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        logger_name = f"academic_paper_rag.{name}"
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(resolved_level)
        self._logger.propagate = False

        with self._lock:
            if logger_name not in self._configured_loggers:
                formatter = logging.Formatter(
                    "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
                file_handler = RotatingFileHandler(
                    self.log_path,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                )
                file_handler.setFormatter(formatter)
                self._logger.addHandler(file_handler)

                if console:
                    console_handler = logging.StreamHandler()
                    console_handler.setFormatter(formatter)
                    self._logger.addHandler(console_handler)

                self._configured_loggers.add(logger_name)

    @staticmethod
    def _resolve_level(level: str | int) -> int:
        if isinstance(level, int):
            return level
        resolved = getattr(logging, level.upper(), None)
        if not isinstance(resolved, int):
            raise ValueError(f"지원하지 않는 로그 레벨입니다: {level}")
        return resolved

    @staticmethod
    def _message(code: LogCode, details: dict[str, Any]) -> str:
        definition = LOG_MESSAGES[code]
        payload = {
            "code": int(code),
            "code_name": code.name,
            "event": definition["event"],
            "message": definition["message"],
            "details": details,
        }
        return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)

    def log(self, code: LogCode | int, **details: Any) -> None:
        """등록된 코드에 해당하는 레벨·메시지와 상세 내용을 함께 기록한다."""
        try:
            resolved_code = LogCode(code)
            definition = LOG_MESSAGES[resolved_code]
        except (ValueError, KeyError) as exc:
            raise ValueError(f"등록되지 않은 로그 코드입니다: {code}") from exc

        level = self._resolve_level(definition["level"])
        self._logger.log(level, self._message(resolved_code, details))

    def close(self) -> None:
        """현재 로거의 핸들러를 닫는다. 주로 테스트나 앱 종료 시 사용한다."""
        with self._lock:
            for handler in self._logger.handlers[:]:
                handler.close()
                self._logger.removeHandler(handler)
            self._configured_loggers.discard(self._logger.name)
