"""단일 YAML에서 공통 설정과 모듈별 모델 설정을 읽는다."""

from __future__ import annotations

import yaml

from . import MODEL_CONFIG_PATH


class ModelConfigError(RuntimeError):
    """model_config.yaml 구조를 읽을 수 없을 때 발생한다."""


def _load_config() -> dict[str, object]:
    try:
        with MODEL_CONFIG_PATH.open(encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ModelConfigError("model_config.yaml을 읽을 수 없습니다.") from exc
    if not isinstance(data, dict):
        raise ModelConfigError("model_config.yaml은 YAML 객체여야 합니다.")
    return data


def load_provider_config(provider: str) -> dict[str, object]:
    """지정한 제공자의 연결 설정만 반환한다."""
    providers = _load_config().get("providers")
    data = providers.get(provider) if isinstance(providers, dict) else None
    if not isinstance(data, dict):
        raise ModelConfigError(f"providers.{provider} 섹션이 필요합니다.")
    return data


def load_task_config(task: str) -> dict[str, object]:
    """지정한 모듈의 독립된 최상위 설정 섹션을 반환한다."""
    data = _load_config().get(task)
    if not isinstance(data, dict):
        raise ModelConfigError(f"model_config.yaml에 {task} 섹션이 필요합니다.")
    return data
