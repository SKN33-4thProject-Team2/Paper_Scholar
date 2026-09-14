"""Compatibility entry point for the v3 retrieval LangSmith experiment."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from langsmith import Client

from evaluation.evaluate_langsmith import run_suite
from evaluation.v3_runtime import RESULTS_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="LangSmith v3 retrieval evaluation")
    parser.add_argument("--source", choices=("cached", "live"), default="cached")
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    parser.add_argument("--split", choices=("dev", "regression", "final"))
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--prefix", default="academic-paper-rag-v3")
    args = parser.parse_args()
    if not os.getenv("LANGSMITH_API_KEY", "").strip():
        parser.error("LANGSMITH_API_KEY가 필요합니다.")
    name = run_suite(
        Client(),
        "retrieval",
        source=args.source,
        results_path=args.results,
        split=args.split,
        max_cases=args.max_cases,
        prefix=args.prefix,
    )
    print(f"LangSmith experiment completed: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
