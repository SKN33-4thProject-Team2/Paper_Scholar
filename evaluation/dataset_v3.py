"""Read the isolated v3 JSONL dataset without importing application code."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any


DATASET_VERSION = "v3"
CORPUS_ROOT = Path(__file__).resolve().parent / "corpus_v3"
DATASET_PATH = CORPUS_ROOT / "dataset_v3.jsonl"
MANIFEST_PATH = CORPUS_ROOT / "manifest.jsonl"
SUITES = ("artifacts", "retrieval", "deep_research", "pipeline", "refusal")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"v3 평가 파일이 없습니다: {path}")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name} {line_number}행은 JSON 객체여야 합니다.")
        records.append(value)
    return records


def papers() -> list[dict[str, Any]]:
    return _read_jsonl(MANIFEST_PATH)


def build_examples(suite: str = "all", *, split: str | None = None) -> list[dict[str, Any]]:
    """Return v3 examples, optionally restricted by suite and paper split."""

    if suite == "rag":
        selected_suites = {"retrieval", "refusal"}
    elif suite == "all":
        selected_suites = set(SUITES)
    elif suite in SUITES:
        selected_suites = {suite}
    else:
        raise ValueError(f"지원하지 않는 v3 평가 suite입니다: {suite}")
    if split is not None and split not in {"dev", "regression", "final"}:
        raise ValueError(f"지원하지 않는 평가 split입니다: {split}")

    return [
        record
        for record in _read_jsonl(DATASET_PATH)
        if str(record.get("inputs", {}).get("suite")) in selected_suites
        and (split is None or str(record.get("metadata", {}).get("split")) == split)
    ]


def dataset_counts() -> dict[str, int]:
    records = build_examples()
    counts = Counter(str(record["inputs"]["suite"]) for record in records)
    result = {suite: int(counts[suite]) for suite in SUITES}
    result["rag"] = result["retrieval"] + result["refusal"]
    result["papers"] = len(papers())
    result["total"] = len(records)
    return result


__all__ = [
    "CORPUS_ROOT",
    "DATASET_PATH",
    "DATASET_VERSION",
    "MANIFEST_PATH",
    "SUITES",
    "build_examples",
    "dataset_counts",
    "papers",
]
