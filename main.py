"""CLI entry point for the LangGraph academic-paper assistant."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from feature.supervisor_chatbot import SupervisorChatbot


EXIT_COMMANDS = {"종료", "exit", "quit", "q"}


def run(chatbot: SupervisorChatbot, query: str, *, thread_id: str, paper_ids: list[str] | None = None) -> dict:
    return chatbot.invoke(
        query,
        thread_id=thread_id,
        paper_ids=paper_ids,
    )


def _print_result(result: dict) -> None:
    print(result["response"])
    if result.get("sources"):
        print("\n출처:")
        for source in result["sources"]:
            print(f"- [{source['label']}] {source.get('title') or source.get('paper_id')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Academic Paper LangGraph chatbot")
    parser.add_argument("query", nargs="?", help="사용자 요청")
    parser.add_argument("--paper-id", action="append", default=[])
    parser.add_argument("--thread-id", default=f"cli-{uuid4().hex[:8]}")
    args = parser.parse_args()

    chatbot = SupervisorChatbot()
    exit_code = 0

    if args.query:
        result = run(chatbot, args.query, thread_id=args.thread_id, paper_ids=args.paper_id)
        _print_result(result)
        exit_code = 1 if result.get("errors") else 0

    # 한 번의 요청으로 종료하지 않고, 같은 thread_id로 대화를 이어가며
    # 사용자가 명시적으로 종료를 요청할 때까지 에이전트들이 계속 협업한다.
    while True:
        query = input("\n요청을 입력하세요 (종료: 'q'): ").strip()
        if not query:
            continue
        if query.casefold() in EXIT_COMMANDS:
            break
        result = run(chatbot, query, thread_id=args.thread_id, paper_ids=args.paper_id)
        _print_result(result)
        if result.get("errors"):
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
