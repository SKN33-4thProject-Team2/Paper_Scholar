"""Run local or LangSmith quality evaluation suites.

Default execution evaluates the ten checked-in translation/summary artifacts
without making model or network calls.  RAG, Deep Research and full pipeline
suites are explicit because they can call local or hosted models.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Callable
from uuid import uuid4

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
load_dotenv(PROJECT_ROOT / ".env")

from langsmith import Client
from langsmith.evaluation import EvaluationResult, evaluate

from evaluation.dataset import DATASET_VERSION, build_examples, dataset_counts
from evaluation.quality_metrics import (
    ARTIFACT_EVALUATORS,
    DEEP_RESEARCH_EVALUATORS,
    PIPELINE_EVALUATORS,
    QualityJudgeEvaluators,
)
from orchestration.evaluation import (
    LLMJudgeEvaluators,
    citation_precision,
    reciprocal_rank,
    refusal_accuracy,
    retrieval_recall_at_k,
    route_sequence_accuracy,
)


EXTRACT_DB = PROJECT_ROOT / "data" / "paper_extract" / "extracted_papers.db"
SUITES = ("artifacts", "rag", "deep_research", "pipeline")
Evaluator = Callable[[dict[str, Any], dict[str, Any], dict[str, Any] | None], EvaluationResult]


def _read_text(path_value: str) -> str:
    path = (PROJECT_ROOT / path_value).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"프로젝트 밖의 평가 파일은 읽을 수 없습니다: {path}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"평가 파일이 없습니다: {path}")
    return path.read_text(encoding="utf-8")


def artifact_target(inputs: dict[str, Any]) -> dict[str, Any]:
    paper_id = str(inputs["paper_id"])
    with sqlite3.connect(EXTRACT_DB) as connection:
        row = connection.execute(
            "SELECT title, content FROM extracted WHERE id = ?",
            (paper_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"추출 DB에 없는 평가 논문입니다: {paper_id}")
    return {
        "paper_id": paper_id,
        "title": str(row[0]),
        "source_text": str(row[1]),
        "translation_text": _read_text(str(inputs["translation_path"])),
        "summary_text": _read_text(str(inputs["summary_path"])),
    }


class EvaluationTarget:
    """Lazily construct expensive workflow objects only for the selected suite."""

    def __init__(self) -> None:
        self._rag_chain: Any | None = None
        self._chatbot: Any | None = None

    @property
    def rag_chain(self):
        if self._rag_chain is None:
            from orchestration.rag_chain import SummaryRAGChain

            self._rag_chain = SummaryRAGChain(top_k=5)
        return self._rag_chain

    @property
    def chatbot(self):
        if self._chatbot is None:
            from feature.supervisor_chatbot import SupervisorChatbot

            self._chatbot = SupervisorChatbot()
        return self._chatbot

    def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
        suite = str(inputs["suite"])
        try:
            if suite == "artifacts":
                return artifact_target(inputs)
            if suite == "rag":
                return self.rag_chain.invoke(str(inputs["query"]))
            if suite in {"deep_research", "pipeline"}:
                return self.chatbot.invoke(
                    str(inputs["query"]),
                    thread_id=f"eval-{inputs['case_id']}-{uuid4().hex[:6]}",
                    paper_ids=list(inputs.get("paper_ids", [])),
                )
            raise ValueError(f"지원하지 않는 평가 suite입니다: {suite}")
        except Exception as exc:
            return {
                "response": "",
                "sources": [],
                "node_history": [],
                "errors": [f"{type(exc).__name__}: {exc}"],
            }


def evaluators_for(suite: str, *, llm_judge: bool = False) -> list[Evaluator]:
    if suite == "artifacts":
        evaluators: list[Evaluator] = list(ARTIFACT_EVALUATORS)
        if llm_judge:
            judges = QualityJudgeEvaluators()
            evaluators.extend([judges.translation_quality, judges.summary_quality])
        return evaluators
    if suite == "rag":
        evaluators = [
            retrieval_recall_at_k,
            reciprocal_rank,
            citation_precision,
            refusal_accuracy,
        ]
        if llm_judge:
            standard_judges = LLMJudgeEvaluators()
            quality_judges = QualityJudgeEvaluators()
            evaluators.extend([standard_judges.faithfulness, quality_judges.citation_grounding])
        return evaluators
    if suite == "deep_research":
        evaluators = [route_sequence_accuracy, *DEEP_RESEARCH_EVALUATORS]
        if llm_judge:
            evaluators.append(QualityJudgeEvaluators().deep_research_quality)
        return evaluators
    if suite == "pipeline":
        return [route_sequence_accuracy, *PIPELINE_EVALUATORS]
    raise ValueError(f"지원하지 않는 평가 suite입니다: {suite}")


def _result_payload(result: EvaluationResult) -> dict[str, Any]:
    return {
        "key": result.key,
        "score": result.score,
        "comment": result.comment,
        "metadata": result.metadata,
    }


def evaluate_local(suite: str, *, llm_judge: bool = False) -> dict[str, Any]:
    target = EvaluationTarget()
    cases: list[dict[str, Any]] = []
    totals: dict[str, list[float]] = defaultdict(list)
    for example in build_examples(suite):
        inputs = example["inputs"]
        reference = example["outputs"]
        outputs = target(inputs)
        metrics: list[dict[str, Any]] = []
        for evaluator in evaluators_for(suite, llm_judge=llm_judge):
            try:
                result = evaluator(inputs, outputs, reference)
            except Exception as exc:
                result = EvaluationResult(
                    key=getattr(evaluator, "__name__", "evaluator"),
                    score=0.0,
                    comment=f"평가 실행 오류: {type(exc).__name__}: {exc}",
                )
            metrics.append(_result_payload(result))
            if result.score is not None:
                totals[result.key].append(float(result.score))
        cases.append(
            {
                "case_id": inputs["case_id"],
                "suite": suite,
                "errors": list(outputs.get("errors", [])),
                "metrics": metrics,
            }
        )
    averages = {
        key: round(sum(values) / len(values), 4)
        for key, values in sorted(totals.items())
        if values
    }
    return {
        "dataset_version": DATASET_VERSION,
        "suite": suite,
        "dataset_counts": dataset_counts(),
        "case_count": len(cases),
        "averages": averages,
        "cases": cases,
    }


def sync_langsmith_dataset(client: Client, suite: str) -> str:
    dataset_name = f"academic-paper-quality-{DATASET_VERSION}-{suite.replace('_', '-')}"
    datasets = list(client.list_datasets(dataset_name=dataset_name, limit=1))
    dataset = datasets[0] if datasets else client.create_dataset(
        dataset_name,
        description=f"Academic paper {suite} quality evaluation {DATASET_VERSION}",
        metadata={"version": DATASET_VERSION, "suite": suite},
    )
    existing = {
        str(example.inputs.get("case_id")): example
        for example in client.list_examples(dataset_id=dataset.id)
        if example.inputs.get("case_id")
    }
    new_examples = []
    for example in build_examples(suite):
        case_id = str(example["inputs"]["case_id"])
        current = existing.get(case_id)
        if current is None:
            new_examples.append(example)
            continue
        if current.inputs != example["inputs"] or current.outputs != example["outputs"]:
            client.update_example(
                current.id,
                inputs=example["inputs"],
                outputs=example["outputs"],
                dataset_id=dataset.id,
            )
    if new_examples:
        client.create_examples(dataset_id=dataset.id, examples=new_examples)
    return dataset_name


def evaluate_langsmith(suite: str, *, llm_judge: bool = False, prefix: str) -> str:
    if not os.getenv("LANGSMITH_API_KEY", "").strip():
        raise RuntimeError("LANGSMITH_API_KEY가 없어 LangSmith 평가를 실행할 수 없습니다.")
    client = Client()
    dataset_name = sync_langsmith_dataset(client, suite)
    experiment = evaluate(
        EvaluationTarget(),
        data=dataset_name,
        evaluators=evaluators_for(suite, llm_judge=llm_judge),
        experiment_prefix=f"{prefix}-{DATASET_VERSION}-{uuid4().hex[:8]}",
        description=f"Academic paper {suite} evaluation {DATASET_VERSION}",
        max_concurrency=1,
        client=client,
    )
    return experiment.experiment_name


def main() -> int:
    parser = argparse.ArgumentParser(description="Academic paper quality evaluation")
    parser.add_argument("--suite", choices=SUITES, default="artifacts")
    parser.add_argument("--mode", choices=("local", "langsmith"), default="local")
    parser.add_argument("--llm-judge", action="store_true")
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="RAG·Deep Research·pipeline의 실제 모델 및 저장소 호출을 허용",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prefix", default="academic-paper-quality")
    args = parser.parse_args()

    if args.suite != "artifacts" and not args.allow_live:
        parser.error("artifacts 외 suite는 실제 서비스를 호출하므로 --allow-live가 필요합니다.")

    if args.mode == "langsmith":
        name = evaluate_langsmith(args.suite, llm_judge=args.llm_judge, prefix=args.prefix)
        print(f"LangSmith experiment completed: {name}")
        return 0

    report = evaluate_local(args.suite, llm_judge=args.llm_judge)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Evaluation report: {output}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
