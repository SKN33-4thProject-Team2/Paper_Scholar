"""Promptfoo Python provider for the project Supervisor chatbot."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
load_dotenv(PROJECT_ROOT / ".env", override=False)

from evaluation.v3_runtime import load_cached_results


_RESULTS = load_cached_results()


def _prompt_text(prompt: object) -> str:
    if not isinstance(prompt, str):
        return str(prompt)
    try:
        payload = json.loads(prompt)
    except json.JSONDecodeError:
        return prompt
    if isinstance(payload, list):
        messages = [
            str(item.get("content") or "")
            for item in payload
            if isinstance(item, dict) and item.get("role") == "user"
        ]
        if messages:
            return messages[-1]
    return prompt


def call_api(prompt: str, options: dict, context: dict) -> dict[str, Any]:
    """Run one isolated Promptfoo case through the real LangGraph chatbot."""

    query = _prompt_text(prompt).strip()
    variables = context.get("vars", {}) if isinstance(context, dict) else {}
    case_id = str(variables.get("case_id") or "")
    record = _RESULTS.get(case_id)
    if record is None:
        return {"error": f"400건 캐시에 없는 평가 케이스입니다: {case_id}"}
    result = dict(record.get("outputs", {}))

    errors = [str(value) for value in result.get("errors", []) if str(value).strip()]
    if errors:
        return {"error": " | ".join(errors)}
    return {
        "output": str(result.get("response") or ""),
        "metadata": {
            "steps": list(result.get("node_history", [])),
            "source_count": len(result.get("sources", [])),
            "case_id": case_id,
            "query": query,
        },
    }


__all__ = ["call_api"]
