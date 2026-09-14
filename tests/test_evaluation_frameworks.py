"""Offline tests for RAGAS, DeepEval, and Promptfoo adapters."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from tests import PROJECT_ROOT  # noqa: F401 - register project import paths

from evaluation.deepeval_evaluation import build_deepeval_payloads
from evaluation.framework_cases import FrameworkCase
from evaluation.ragas_evaluation import RAGAS_METRICS, build_ragas_rows


PROMPTFOO_DIR = PROJECT_ROOT / "evaluation" / "promptfoo"


def _load_promptfoo_module(name: str):
    path = PROMPTFOO_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"promptfoo_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Promptfoo 테스트 모듈을 읽을 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrameworkCaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.case = FrameworkCase.from_result(
            {"suite": "rag", "case_id": "rag-1", "query": "방법은?"},
            {
                "response": "제안 방법은 어텐션을 사용한다 [S1].",
                "sources": [
                    {
                        "label": "S1",
                        "paper_id": "2401.00001v1",
                        "excerpt": "제안 모델은 다중 헤드 어텐션을 사용한다.",
                    }
                ],
                "node_history": ["rag", "finish"],
                "errors": [],
            },
            {
                "relevant_source_ids": ["2401.00001v1"],
                "expected_steps": ["rag"],
                "expected_refusal": False,
            },
        )

    def test_normalizes_sources_steps_and_references(self) -> None:
        self.assertEqual(self.case.contexts, ("제안 모델은 다중 헤드 어텐션을 사용한다.",))
        self.assertEqual(self.case.retrieved_context_ids, ("2401.00001v1",))
        self.assertEqual(self.case.reference_context_ids, ("2401.00001v1",))
        self.assertEqual(self.case.actual_steps, ("rag",))

    def test_builds_ragas_rows_with_four_declared_metrics(self) -> None:
        rows = build_ragas_rows([self.case])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user_input"], "방법은?")
        self.assertEqual(rows[0]["retrieved_context_ids"], ["2401.00001v1"])
        self.assertEqual(
            RAGAS_METRICS,
            (
                "id_based_context_precision",
                "id_based_context_recall",
                "faithfulness",
                "answer_relevancy",
            ),
        )

    def test_ragas_skips_refusal_and_failed_cases(self) -> None:
        refusal = FrameworkCase(
            case_id="refusal",
            suite="rag",
            question="근거 없는 질문",
            answer="확인할 수 없습니다.",
            expected_refusal=True,
        )
        failed = FrameworkCase(
            case_id="failed",
            suite="rag",
            question="질문",
            answer="",
            errors=("실패",),
        )
        self.assertEqual(build_ragas_rows([refusal, failed]), [])

    def test_builds_deepeval_rag_and_tool_payloads(self) -> None:
        workflow = FrameworkCase(
            case_id="pipeline-1",
            suite="pipeline",
            question="논문을 요약해줘",
            answer="요약 완료",
            expected_steps=("extract", "translate", "summarize"),
            actual_steps=("extract", "translate", "summarize"),
        )
        payloads = build_deepeval_payloads([self.case, workflow])
        self.assertEqual(payloads[0]["retrieval_context"], list(self.case.contexts))
        self.assertEqual(
            payloads[1]["expected_tools"],
            ["extract", "translate", "summarize"],
        )


class PromptfooAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assertions = _load_promptfoo_module("assertions")
        cls.generator = _load_promptfoo_module("tests")

    def test_response_quality_scores_terms_and_refusal(self) -> None:
        result = self.assertions.response_quality(
            "저장된 근거가 부족하여 답할 수 없습니다.",
            {
                "vars": {
                    "required_terms": [],
                    "expected_refusal": True,
                }
            },
        )
        self.assertTrue(result["pass"])
        self.assertEqual(result["namedScores"]["refusal_accuracy"], 1.0)

    def test_generates_bounded_promptfoo_regression_cases(self) -> None:
        cases = self.generator.generate_tests({"max_cases": 4})
        self.assertEqual(len(cases), 4)
        self.assertTrue(all(case["vars"]["query"] for case in cases))
        self.assertTrue(all("suite" in case["vars"] for case in cases))


if __name__ == "__main__":
    unittest.main()
