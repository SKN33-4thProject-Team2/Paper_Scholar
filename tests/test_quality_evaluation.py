"""Expanded artifact, citation, Deep Research and E2E evaluation tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from tests import PROJECT_ROOT, SRC_DIR  # noqa: F401 - register project import paths

from evaluation.dataset import PAPERS, build_examples, dataset_counts
from evaluation.quality_metrics import (
    QualityGrade,
    QualityJudgeEvaluators,
    deep_research_completion,
    latex_preservation,
    markdown_table_preservation,
    pipeline_completion,
    summary_acronym_recall,
    summary_numeric_recall,
    summary_title_preservation,
    translation_term_recall,
)
from evaluation.run_evaluation import evaluate_local, sync_langsmith_dataset


class FakeJudgeLLM:
    def __init__(self, score: float = 0.8) -> None:
        self.score = score
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt: str) -> QualityGrade:
        self.prompts.append(prompt)
        return QualityGrade(score=self.score, reason="테스트 판정")


class EvaluationDatasetTest(unittest.TestCase):
    def test_expanded_dataset_counts(self) -> None:
        self.assertEqual(
            dataset_counts(),
            {
                "artifacts": 10,
                "rag": 23,
                "deep_research": 5,
                "pipeline": 8,
                "papers": 10,
                "total": 46,
            },
        )

    def test_every_paper_has_two_rag_questions_and_artifacts(self) -> None:
        rag_examples = build_examples("rag")
        artifact_examples = build_examples("artifacts")
        for paper in PAPERS:
            paper_id = paper["paper_id"]
            self.assertEqual(
                sum(paper_id in example["inputs"]["case_id"] for example in rag_examples),
                2,
            )
            artifact = next(
                example
                for example in artifact_examples
                if example["inputs"]["paper_id"] == paper_id
            )
            self.assertTrue((PROJECT_ROOT / artifact["inputs"]["translation_path"]).is_file())
            self.assertTrue((PROJECT_ROOT / artifact["inputs"]["summary_path"]).is_file())

    def test_langsmith_sync_adds_new_cases_and_updates_changed_cases(self) -> None:
        rag_examples = build_examples("rag")
        first = rag_examples[0]

        class FakeClient:
            def __init__(self) -> None:
                self.dataset = SimpleNamespace(id="dataset-1")
                self.existing = SimpleNamespace(
                    id="example-1",
                    inputs=first["inputs"],
                    outputs={"outdated": True},
                )
                self.updated: list[dict] = []
                self.created: list[dict] = []

            def list_datasets(self, **kwargs):
                return iter([self.dataset])

            def list_examples(self, **kwargs):
                return iter([self.existing])

            def update_example(self, example_id, **kwargs):
                self.updated.append({"example_id": example_id, **kwargs})

            def create_examples(self, **kwargs):
                self.created.extend(kwargs["examples"])

        client = FakeClient()
        name = sync_langsmith_dataset(client, "rag")
        self.assertEqual(name, "academic-paper-quality-v2-rag")
        self.assertEqual(len(client.updated), 1)
        self.assertEqual(client.updated[0]["outputs"], first["outputs"])
        self.assertEqual(len(client.created), len(rag_examples) - 1)


class ArtifactMetricTest(unittest.TestCase):
    def test_latex_and_table_structure_preservation(self) -> None:
        source = """Equation $E = mc^2$.

| Model | Score |
| --- | ---: |
| Base | 0.8 |
"""
        translation = """수식 $E = mc^2$.

| 모델 | 점수 |
| --- | ---: |
| 기준 | 0.8 |
"""
        outputs = {"source_text": source, "translation_text": translation}
        self.assertEqual(latex_preservation({}, outputs, {}).score, 1.0)
        self.assertEqual(markdown_table_preservation({}, outputs, {}).score, 1.0)

    def test_translation_and_summary_required_values(self) -> None:
        outputs = {
            "translation_text": "PACS와 SMA 모델을 비교한다.",
            "summary_text": "# PACS Study\nPACS와 SMA는 정확도 0.981을 기록했다.",
        }
        reference = {
            "title": "PACS Study",
            "expected_translation_terms": ["PACS", "SMA"],
            "expected_acronyms": ["PACS", "SMA"],
            "expected_numbers": ["0.981"],
        }
        self.assertEqual(translation_term_recall({}, outputs, reference).score, 1.0)
        self.assertEqual(summary_title_preservation({}, outputs, reference).score, 1.0)
        self.assertEqual(summary_acronym_recall({}, outputs, reference).score, 1.0)
        self.assertEqual(summary_numeric_recall({}, outputs, reference).score, 1.0)

    def test_checked_in_artifacts_generate_a_local_report(self) -> None:
        report = evaluate_local("artifacts")
        self.assertEqual(report["case_count"], 10)
        self.assertEqual(report["dataset_counts"]["rag"], 23)
        self.assertEqual(report["averages"]["summary_title_preservation"], 1.0)
        self.assertFalse(any(case["errors"] for case in report["cases"]))


class GroundingAndWorkflowMetricTest(unittest.TestCase):
    def test_citation_grounding_judges_claim_against_cited_excerpt(self) -> None:
        fake = FakeJudgeLLM(score=0.75)
        judges = QualityJudgeEvaluators(llm=fake)
        result = judges.citation_grounding(
            {"query": "성능은?"},
            {
                "answer": "모델의 정확도는 개선되었다 [S1].",
                "sources": [
                    {
                        "label": "S1",
                        "excerpt": "제안 모델은 기준 모델보다 높은 정확도를 기록했다.",
                    }
                ],
            },
            {},
        )
        self.assertEqual(result.score, 0.75)
        self.assertEqual(result.metadata["cited_claim_count"], 1)
        self.assertIn("정확도", fake.prompts[0])

    def test_deep_research_completion_detects_node_failure(self) -> None:
        success = deep_research_completion(
            {},
            {"response": "분석 완료", "node_history": ["deep_research", "finish"], "errors": []},
            {},
        )
        failure = deep_research_completion(
            {},
            {
                "response": "작업을 완료하지 못했습니다.",
                "node_history": ["deep_research:failed", "finish"],
                "errors": ["DeepResearchAgent import failed"],
            },
            {},
        )
        self.assertEqual(success.score, 1.0)
        self.assertEqual(failure.score, 0.0)

    def test_pipeline_completion_requires_outputs_finish_and_no_errors(self) -> None:
        reference = {"expected_output_keys": ["response", "sources"]}
        complete = pipeline_completion(
            {},
            {
                "response": "답변",
                "sources": [{"label": "S1"}],
                "node_history": ["rag", "finish"],
                "errors": [],
            },
            reference,
        )
        missing = pipeline_completion(
            {},
            {"response": "답변", "sources": [], "node_history": ["rag", "finish"]},
            reference,
        )
        self.assertEqual(complete.score, 1.0)
        self.assertEqual(missing.score, 0.0)
        self.assertEqual(missing.metadata["missing_keys"], ["sources"])


if __name__ == "__main__":
    unittest.main()
