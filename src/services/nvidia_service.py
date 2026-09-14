"""NVIDIA Build API(OpenAI 호환 엔드포인트) 호출만 담당하는 서비스."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import yaml
from dotenv import load_dotenv

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_VISION_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
DEFAULT_RENDER_DPI = 150

load_dotenv()


class NvidiaServiceError(RuntimeError):
    """NVIDIA Build API 요청을 완료하지 못했을 때 발생한다."""


def _load_nvidia_config() -> dict[str, object]:
    """model_config.yaml 의 providers.nvidia 를 읽는다. 없거나 깨져도 기본값으로 돈다.

    설정 파일을 하나로 모으기 전에는 nvidia_config.yaml 을 따로 두었다. 읽는 방식은
    그대로다 — 값이 없으면 기본값을 쓰고, 파일이 깨져도 예외를 밖으로 내보내지
    않는다. 임포트 시점에 한 번 부르는 함수라 여기서 죽으면 추출이 통째로 멈춘다.
    """
    config: dict[str, object] = {
        "base_url": DEFAULT_BASE_URL,
        "vision_model": DEFAULT_VISION_MODEL,
        "render_dpi": DEFAULT_RENDER_DPI,
        "disable_thinking": True,
    }
    try:
        from .model_config_service import ModelConfigError, load_provider_config

        loaded = load_provider_config("nvidia")
    except (ImportError, ModelConfigError, OSError, yaml.YAMLError):
        return config

    if isinstance(loaded, dict):
        for key in ("base_url", "vision_model"):
            if loaded.get(key):
                config[key] = str(loaded[key]).strip()
        try:
            if loaded.get("render_dpi"):
                config["render_dpi"] = int(loaded["render_dpi"])
        except (TypeError, ValueError):
            pass
        if "disable_thinking" in loaded:
            config["disable_thinking"] = bool(loaded["disable_thinking"])
    return config


NVIDIA_CONFIG = _load_nvidia_config()


def api_key() -> str:
    """.env 또는 환경변수에서 NVIDIA Build API 키를 읽는다."""
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key:
        raise NvidiaServiceError(
            "NVIDIA_API_KEY 가 설정되지 않았습니다. "
            "프로젝트 루트의 .env 에 NVIDIA_API_KEY=nvapi-... 를 추가해 주세요."
        )
    return key


def is_available() -> bool:
    """키가 준비돼 있는지만 확인한다. 네트워크는 건드리지 않는다."""
    return bool(os.environ.get("NVIDIA_API_KEY", "").strip())


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    timeout: int = 180,
    retries: int = 2,
    response_format: dict | None = None,
) -> str:
    """chat/completions 를 호출하고 모델의 텍스트 응답만 반환한다.

    ``response_format`` 에 JSON 스키마를 주면 그 모양으로만 답하게 한다. 요약처럼
    정해진 키를 받아야 하는 곳에서 쓴다. 지시문으로만 부탁하면 모델이 키 이름을
    바꾸거나(research_goal 을 research_objective 로) 코드펜스를 둘러 온다.
    """
    base_url = str(NVIDIA_CONFIG["base_url"]).rstrip("/")
    payload = {
        "model": model or NVIDIA_CONFIG["vision_model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if NVIDIA_CONFIG.get("disable_thinking", True):
        # nemotron 계열은 추론 모델이라 기본값으로 사고 과정을 따로 생성한다.
        # 페이지를 옮겨 적는 데는 필요 없고, 켜두면 사고 토큰이 2만 자를 넘기며
        # 같은 쪽이 14초에서 82초로 느려진다.
        payload["chat_template_kwargs"] = {"thinking": False}
    if response_format:
        payload["response_format"] = response_format

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key()}",
        "Accept": "application/json",
    }

    last_error: str = "원인을 알 수 없습니다."
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            f"{base_url}/chat/completions", data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            content = parsed["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("응답 본문이 비어 있습니다. max_tokens 를 늘려보세요.")
            return content
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            # 4xx 는 다시 보내도 같은 결과라 즉시 중단한다. 429(과다요청)만 예외다.
            if 400 <= exc.code < 500 and exc.code != 429:
                raise NvidiaServiceError(f"NVIDIA API 오류 {exc.code}: {detail}") from exc
            last_error = f"NVIDIA API 오류 {exc.code}: {detail}"
        except (OSError, urllib.error.URLError, TimeoutError, KeyError, IndexError,
                TypeError, ValueError) as exc:
            last_error = f"NVIDIA API 호출 실패: {exc}"

        if attempt < retries:
            time.sleep(2 ** attempt)

    raise NvidiaServiceError(last_error)


def generate(
    prompt: str,
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    timeout: float = 180,
    response_format: dict | str | None = None,
    **_ignored,
) -> str:
    """ollama_service.generate 와 같은 모양으로 NVIDIA 를 부른다.

    요약 도구는 generate(prompt, model=, response_format=, ...) 를 그대로 부르므로,
    호출부를 고치지 않고 이 함수를 끼워 넣기만 하면 제공자가 바뀐다. Ollama 는
    format 에 스키마를 그대로 주지만 OpenAI 호환 규약은 json_schema 로 감싸야 해서
    여기서 모양을 맞춘다. stream 처럼 이쪽에 없는 인자는 조용히 흘린다.
    """
    formatted: dict | None = None
    if isinstance(response_format, dict):
        formatted = {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": response_format, "strict": True},
        }
    elif response_format:
        formatted = {"type": "json_object"}

    return chat(
        [{"role": "user", "content": prompt}],
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=int(timeout),
        response_format=formatted,
    )


def describe_image(image_base64: str, prompt: str, **kwargs) -> str:
    """이미지 한 장과 지시문을 함께 보내 텍스트 응답을 받는다."""
    return chat(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                    },
                ],
            }
        ],
        **kwargs,
    )
