"""DB 기반 논문 요약 에이전트."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, TypedDict

import sys
_SRC_ROOT = Path(__file__).resolve().parents[1]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))
from agent import DEFAULT_DB_PATH, DEFAULT_MARKDOWN_DIR, DEFAULT_SUMMARY_DB_PATH, PROJECT_ROOT

from tools.summary_tool_v2 import SummaryResult, SummaryTool


class SummaryState(TypedDict, total=False):
    paper_ids: list[str]
    selected_papers: list[dict[str, Any]]
    summaries: list[dict[str, Any]]
    node_history: list[str]


def get_selected_paper_ids(state: SummaryState) -> list[str]:
    """상태에서 선택된 논문 ID를 중복 없이 가져온다."""
    values = state.get("paper_ids", [])
    if not values:
        values = [item.get("id", item.get("paper_id", ""))
                  for item in state.get("selected_papers", [])]
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def summarize_from_db(source_db: str | Path, paper_id: str,
                      summary_db: str | Path = DEFAULT_SUMMARY_DB_PATH) -> SummaryResult:
    """원문 DB의 논문 한 편을 요약하고 summary DB에 저장한다."""
    tool = SummaryTool(source_db=source_db, summary_db=summary_db)
    return tool.summarize(paper_id)


def save_summary_to_db(result: SummaryResult, summary_db: str | Path = DEFAULT_SUMMARY_DB_PATH) -> Path:
    """요약 결과가 저장된 DB를 확인하고 경로를 반환한다.

    실제 SQLite 기록은 ``SummaryTool.summarize``가 원자적으로 수행하며,
    이 함수는 에이전트 외부에서도 저장 결과를 명시적으로 확인할 수 있게 한다.
    """
    path = Path(summary_db)
    if not path.is_file():
        raise FileNotFoundError(f"요약 DB가 생성되지 않았습니다: {path}")
    with sqlite3.connect(path) as db:
        exists = db.execute(
            "SELECT 1 FROM paper_summaries WHERE paper_id = ?", (result.paper_id,)
        ).fetchone()
    if exists is None:
        raise RuntimeError(f"요약 DB 저장 결과를 찾을 수 없습니다: {result.paper_id}")
    return path


def save_summary_as_markdown(summary_db: str | Path, paper_id: str,
                            output_dir: str | Path = DEFAULT_MARKDOWN_DIR) -> Path:
    """summary DB에서 요약을 읽어 Markdown 파일로 저장한다."""
    tool = SummaryTool(summary_db=summary_db)
    safe_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in paper_id)
    output_path = Path(output_dir) / f"{safe_id or 'summary'}.md"
    return tool.export_markdown_view(paper_id, output_path)


class SummaryAgent:
    """DB를 받아 요약·DB 저장·Markdown 추출 후 결과 정보를 전달하는 agent."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH,
                 summary_db_path: str | Path = DEFAULT_SUMMARY_DB_PATH,
                 markdown_dir: str | Path = DEFAULT_MARKDOWN_DIR,
                 provider: str | None = None) -> None:
        self.db_path = Path(db_path)
        self.summary_db_path = Path(summary_db_path)
        self.markdown_dir = Path(markdown_dir)
        self.provider = provider

    def _list_paper_ids(self, tool: SummaryTool) -> list[str]:
        """extracted 또는 paper_sections 구조에서 논문 ID를 가져온다."""
        try:
            return [paper_id for paper_id, _ in tool.list_papers()]
        except sqlite3.OperationalError as exc:
            if "no such table: extracted" not in str(exc):
                raise
            with sqlite3.connect(self.db_path) as db:
                rows = db.execute(
                    "SELECT paper_id FROM paper_sections "
                    "GROUP BY paper_id ORDER BY MIN(section_order), MIN(id)"
                ).fetchall()
            return [str(row[0]) for row in rows if str(row[0]).strip()]

    def run(self, paper_ids: list[str] | None = None) -> dict[str, Any]:
        """지정 논문(없으면 전체)을 처리하고 결과 정보를 반환한다."""
        started_at = time.perf_counter()
        tool = SummaryTool(
            source_db=self.db_path,
            summary_db=self.summary_db_path,
            provider=self.provider,
            # 섹션 원문 전체를 문단 청크로 요약한 뒤 최종 통합한다.
            single_call=False,
        )
        ids = paper_ids or self._list_paper_ids(tool)
        summaries = []
        for paper_id in ids:
            paper_started_at = time.perf_counter()
            calls_before = tool.generation_calls
            result = tool.summarize(str(paper_id))
            save_summary_to_db(result, self.summary_db_path)
            markdown_path = save_summary_as_markdown(
                self.summary_db_path, result.paper_id, self.markdown_dir
            )
            summaries.append({
                "id": result.paper_id, "paper_id": result.paper_id,
                "title": result.title, "summary_markdown": result.summary_markdown,
                "summary_db": str(self.summary_db_path),
                "markdown_path": str(markdown_path), "model": result.model,
                "source": str(self.db_path),
                "generation_calls": tool.generation_calls - calls_before,
                "elapsed_seconds": round(time.perf_counter() - paper_started_at, 2),
            })
        if not summaries:
            raise ValueError("요약할 논문이 없습니다.")
        return {
            "summaries": summaries,
            "summary_db": str(self.summary_db_path),
            "elapsed_seconds": round(time.perf_counter() - started_at, 2),
            "generation_calls": tool.generation_calls,
            "node_history": ["summarize"],
        }

    def __call__(self, state: SummaryState | str | Path) -> dict[str, Any]:
        """LangGraph 상태 또는 DB 경로를 받아 처리한다."""
        if isinstance(state, (str, Path)):
            self.db_path = Path(state)
            return self.run()
        return self.run(get_selected_paper_ids(state))


summary_node = SummaryAgent()


if __name__ == "__main__":
    # data/paper_extract/extracted_papers.db 전체 논문을 처리하는 간단한 테스트 실행부
    print("[요약] SummaryAgent 실행을 시작합니다.", flush=True)
    print("[요약] 모델: qwen3:4b-instruct-2507-q4_K_M", flush=True)

    paper_id = "2410.22997v2"
    print("[요약] 대상 논문: ",paper_id, flush=True)
    agent = SummaryAgent(
        PROJECT_ROOT / "data" / "paper_extract" / "extracted_papers.db",
        provider="ollama",
    )
    print("[요약] dense 핵심 문장 선별 및 전체 4단계 요약 중...", flush=True)
    result = agent.run(paper_ids=[paper_id])
    print(f"요약 DB 저장 완료: {agent.summary_db_path}")
    print(f"전체 처리 시간: {result['elapsed_seconds']:.2f}초")
    print(f"전체 모델 호출 횟수: {result['generation_calls']}회")
    for summary in result["summaries"]:
        print(
            f"Markdown 저장 완료: {summary['markdown_path']} "
            f"({summary['elapsed_seconds']:.2f}초, "
            f"모델 호출 {summary['generation_calls']}회)"
        )
