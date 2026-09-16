from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from orchestration.adapters import KeywordNode
from orchestration.evaluation import (
    citation_precision,
    reciprocal_rank,
    refusal_accuracy,
    retrieval_recall_at_k,
    route_sequence_accuracy,
)
from orchestration.graph import build_graph
from orchestration.routing import SupervisorRouter
from orchestration.state import initial_state


PAPER = {"paper_id": "paper-1", "id": "paper-1", "title": "RAG Paper"}
PAPERS = [
    PAPER,
    *[
        {"paper_id": f"paper-{index}", "id": f"paper-{index}", "title": f"Paper {index}"}
        for index in range(2, 16)
    ],
]


def fake_nodes():
    """현재 LangGraph 노드 계약을 네트워크·모델 호출 없이 검증한다."""

    def deep_search(state):
        if state.get("deep_search_selection_required"):
            return {
                "paper_ids": [],
                "sources": [],
                "deep_search_candidates": [PAPER],
                "selection_candidates": [PAPER],
                "selection_source": "deep_search",
                "deep_search_selection_required": True,
                "response": "심층 질문이 가능한 추출 논문 목록입니다.\n1. RAG Paper",
                "node_history": ["deep_search"],
            }
        return {
            "paper_ids": state.get("paper_ids") or ["paper-1"],
            "sources": [
                {
                    "label": "S1",
                    "id": "paper-1:conclusion",
                    "paper_id": "paper-1",
                    "title": "RAG Paper",
                    "document": "검색 증강 생성의 정확도를 개선했다.",
                }
            ],
            "deep_search_references": [],
            "deep_search_candidates": [],
            "deep_search_selection_required": False,
            "response": "선택한 논문에서 근거를 찾았습니다.",
            "node_history": ["deep_search"],
        }

    def search(state):
        limit = int(state.get("search_result_limit", 0)) or 1
        papers = PAPERS[:limit]
        save_count = int(state.get("save_paper_count", 0))
        if not save_count:
            return {
                "search_results": papers,
                "selection_candidates": papers,
                "selection_source": "search",
                "node_history": ["search"],
            }
        saved_papers = papers[:save_count]
        explain_paper = saved_papers[int(state.get("explain_paper_rank", 1)) - 1]
        return {
            "search_results": papers,
            "selected_papers": saved_papers,
            "selection_candidates": papers,
            "selection_source": "search",
            "paper_ids": [explain_paper["id"]],
            "download_paper_ids": [paper["id"] for paper in saved_papers],
            "deep_search_paper_id": explain_paper["id"],
            "node_history": ["search"],
        }

    return {
        "keyword": lambda state: {"keywords": ["RAG"], "node_history": ["keyword"]},
        "search": search,
        "library": lambda state: {
            "library_results": [PAPER],
            "selection_candidates": [PAPER],
            "selection_source": "library",
            "node_history": ["library"],
        },
        "download": lambda state: {
            "paper_ids": state.get("paper_ids") or ["paper-1"],
            "downloaded_paths": ["paper-1.pdf"],
            "node_history": ["download"],
        },
        "extract": lambda state: {
            "extracted_records": [{"id": "paper-1", "content": "paper body"}],
            "node_history": ["extract"],
        },
        "translate": lambda state: {
            "translated_paths": ["paper-1-ko.md"],
            "node_history": ["translate"],
        },
        "summarize": lambda state: {
            "summaries": [{"id": "paper-1", "markdown_path": "paper-1-summary.md"}],
            "node_history": ["summarize"],
        },
        "deep_search": deep_search,
        "deep_research": lambda state: {
            "response": "근거 기반으로 설명했습니다.",
            "deep_research_status": "success",
            "deep_research_answer": "근거 기반으로 설명했습니다.",
            "deep_research_sources": state.get("sources", []),
            "deep_research_paper_id": "paper-1",
            "node_history": ["deep_research"],
        },
    }


class StateGraphTest(unittest.TestCase):
    def setUp(self):
        self.graph = build_graph(router=SupervisorRouter(use_llm=False), nodes=fake_nodes())

    def test_search_runs_only_keyword_and_search(self):
        result = self.graph.invoke(
            initial_state("arXiv에서 RAG 논문 1편 검색해줘"),
            config={"configurable": {"thread_id": "test-search"}},
        )
        self.assertEqual(result["node_history"], ["keyword", "search", "finish"])
        self.assertIn("RAG Paper", result["response"])

    def test_composite_request_saves_top_five_and_explains_top_one(self):
        result = self.graph.invoke(
            initial_state(
                "LLM 관련 논문 10개 찾고 그 중 5개 저장하고 최상위 논문 1개 설명해줘"
            ),
            config={"configurable": {"thread_id": "test-ranked-composite"}},
        )
        self.assertEqual(
            result["node_history"],
            [
                "keyword",
                "search",
                "download",
                "extract",
                "deep_search",
                "deep_research",
                "finish",
            ],
        )
        self.assertEqual(len(result["search_results"]), 10)
        self.assertEqual(len(result["selected_papers"]), 5)
        self.assertEqual(result["download_paper_ids"], [f"paper-{index}" for index in range(1, 6)])
        self.assertEqual(result["paper_ids"], ["paper-1"])
        self.assertEqual(result["errors"], [])

    def test_selected_downloaded_paper_extracts_without_other_stages(self):
        state = initial_state("1번 논문 추출해줘")
        state["selection_candidates"] = [PAPER]
        state["selection_source"] = "search"
        state["downloaded_paths"] = ["paper-1.pdf"]
        result = self.graph.invoke(
            state,
            config={"configurable": {"thread_id": "test-extract"}},
        )
        self.assertEqual(result["node_history"], ["extract", "finish"])
        self.assertEqual(result["errors"], [])

    def test_selected_paper_without_pdf_adds_only_download_dependency(self):
        router = SupervisorRouter(use_llm=False)
        state = initial_state("1번 논문 추출해줘")
        state["selection_candidates"] = [PAPER]
        state["selection_source"] = "search"
        self.assertEqual(router.decide(state).steps, ["download", "extract"])

    def test_extract_without_target_asks_human(self):
        result = self.graph.invoke(
            initial_state("논문 추출해줘"),
            config={"configurable": {"thread_id": "test-extract-human"}},
        )
        self.assertEqual(result["node_history"], ["human", "finish"])
        self.assertTrue(result["human_input_required"])
        self.assertIn("어느 논문", result["response"])

    def test_explainable_inventory_then_selected_paper_runs_deep_search_and_research(self):
        config = {"configurable": {"thread_id": "test-deep-research"}}
        first = self.graph.invoke(initial_state("설명 가능한 논문이 뭐가 있어?"), config=config)
        second = self.graph.invoke(initial_state("1번 논문 설명해줘"), config=config)
        self.assertEqual(first["node_history"], ["deep_search", "finish"])
        self.assertIn("1. RAG Paper", first["response"])
        self.assertEqual(second["node_history"], ["deep_search", "deep_research", "finish"])
        self.assertEqual(second["errors"], [])
        self.assertIn("근거 기반으로 설명했습니다", second["response"])

    def test_summary_keeps_only_required_data_dependencies(self):
        result = self.graph.invoke(
            initial_state("paper-1 논문을 요약해줘", paper_ids=["paper-1"]),
            config={"configurable": {"thread_id": "test-summary"}},
        )
        self.assertEqual(
            result["node_history"],
            ["extract", "translate", "summarize", "finish"],
        )
        self.assertEqual(result["errors"], [])

    def test_empty_search_rebuilds_keywords_once(self):
        search_calls = 0

        def search_node(state):
            nonlocal search_calls
            search_calls += 1
            papers = [] if search_calls == 1 else [PAPER]
            return {"search_results": papers, "node_history": ["search"]}

        nodes = fake_nodes()
        nodes["search"] = search_node
        graph = build_graph(router=SupervisorRouter(use_llm=False), nodes=nodes)
        result = graph.invoke(
            initial_state("arXiv에서 agent 논문 검색해줘"),
            config={"configurable": {"thread_id": "test-search-retry"}},
        )
        self.assertEqual(
            result["node_history"],
            ["keyword", "search", "keyword", "search", "finish"],
        )
        self.assertEqual(result["retry_counts"]["search"], 1)
        self.assertEqual(result["errors"], [])

    def test_keyword_retry_requests_alternative_terms(self):
        prompts = []

        class FakeKeywordTool:
            def generate_keywords(self, prompt):
                prompts.append(prompt)
                return {"keywords": ["alternative RAG"]}

        node = KeywordNode(factory=FakeKeywordTool)
        result = node(
            {
                "query": "RAG 논문",
                "keywords": ["retrieval augmented generation"],
                "retry_counts": {"search": 1},
            }
        )
        self.assertEqual(result["keywords"], ["alternative RAG"])
        self.assertIn("retrieval augmented generation", prompts[0])
        self.assertIn("겹치지 않는 대체 학술 용어", prompts[0])


class EvaluatorTest(unittest.TestCase):
    def test_deterministic_metrics(self):
        route = route_sequence_accuracy(
            {},
            {"steps": ["deep_search", "deep_research"]},
            {"expected_steps": ["deep_search", "deep_research"]},
        )
        recall = retrieval_recall_at_k(
            {}, {"sources": [{"id": "p1"}]}, {"relevant_source_ids": ["p1", "p2"]}
        )
        mrr = reciprocal_rank(
            {}, {"sources": [{"id": "x"}, {"id": "p1"}]}, {"relevant_source_ids": ["p1"]}
        )
        citation = citation_precision(
            {}, {"answer": "근거 [S1] [S9]", "sources": [{"label": "S1"}]}, {}
        )
        self.assertEqual(route.score, 1.0)
        self.assertEqual(recall.score, 0.5)
        self.assertEqual(mrr.score, 0.5)
        self.assertEqual(citation.score, 0.5)

    def test_not_applicable_metrics_do_not_inflate_score(self):
        result = retrieval_recall_at_k({}, {"sources": []}, {})
        self.assertIsNone(result.score)

    def test_retrieval_metrics_match_paper_and_document_ids(self):
        outputs = {"sources": [{"id": "paper-1:methodology", "paper_id": "paper-1"}]}
        reference = {"relevant_source_ids": ["paper-1"]}
        self.assertEqual(retrieval_recall_at_k({}, outputs, reference).score, 1.0)
        self.assertEqual(reciprocal_rank({}, outputs, reference).score, 1.0)

    def test_refusal_accuracy(self):
        result = refusal_accuracy(
            {},
            {"answer": "저장된 근거가 부족하여 답할 수 없습니다."},
            {"expected_refusal": True},
        )
        self.assertEqual(result.score, 1.0)


if __name__ == "__main__":
    unittest.main()
