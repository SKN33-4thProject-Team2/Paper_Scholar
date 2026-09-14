from __future__ import annotations

import sys
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from orchestration.evaluation import (
    citation_precision,
    reciprocal_rank,
    refusal_accuracy,
    retrieval_recall_at_k,
    route_sequence_accuracy,
)
from orchestration.adapters import DeepResearchNode, KeywordNode
from orchestration.graph import build_graph
from orchestration.rag_chain import SummaryRAGChain
from orchestration.routing import SupervisorRouter
from orchestration.routing import SupervisorDecision
from orchestration.state import initial_state


class FakeStore:
    def search(self, query, *, limit=5, paper_id=None):
        return [
            {
                "id": "paper-1:conclusion",
                "document": "이 연구는 검색 증강 생성의 정확도를 개선했다.",
                "metadata": {
                    "paper_id": "paper-1",
                    "title": "RAG Paper",
                    "section": "conclusion",
                },
                "distance": 0.1,
            }
        ]


def fake_nodes():
    return {
        "keyword": lambda state: {"keywords": ["RAG"], "node_history": ["keyword"]},
        "search": lambda state: {
            "search_results": [{"id": "paper-1", "title": "RAG Paper"}],
            "node_history": ["search"],
        },
        "library": lambda state: {"node_history": ["library"]},
        "download": lambda state: {"node_history": ["download"]},
        "extract": lambda state: {"node_history": ["extract"]},
        "translate": lambda state: {"node_history": ["translate"]},
        "summarize": lambda state: {"node_history": ["summarize"]},
        "rag": lambda state: {
            "response": "RAG answer",
            "sources": [{"paper_id": "paper-1", "title": "RAG Paper"}],
            "node_history": ["rag"],
        },
        "deep_research": lambda state: (
            {
                "response": "설명 가능한 분석 논문 목록입니다.\n1. RAG Paper",
                "rag_candidates": [{"paper_id": "paper-1", "title": "RAG Paper"}],
                "rag_selection_required": False,
                "deep_research_status": "selection_required",
                "deep_research_local_only": True,
                "node_history": ["deep_research"],
            }
            if state.get("rag_selection_required")
            else {
                "response": "일부 내용은 확인할 수 없지만 근거 기반으로 설명했습니다.",
                "deep_research_status": "success",
                "deep_research_answer": "일부 내용은 확인할 수 없지만 근거 기반으로 설명했습니다.",
                "deep_research_sources": ["paper evidence"],
                "deep_research_local_only": bool(state.get("deep_research_local_only")),
                "node_history": ["deep_research"],
            }
        ),
    }


class StateGraphTest(unittest.TestCase):
    def test_search_plan_executes_in_order(self):
        graph = build_graph(router=SupervisorRouter(use_llm=False), nodes=fake_nodes())
        result = graph.invoke(
            initial_state("arxiv에서 RAG 논문 검색해줘"),
            config={"configurable": {"thread_id": "test-search"}},
        )
        self.assertEqual(result["node_history"], ["keyword", "search", "finish"])
        self.assertIn("RAG Paper", result["response"])

    def test_summary_plan_keeps_extract_translate_order(self):
        router = SupervisorRouter(use_llm=False)
        decision = router.decide(initial_state("paper-1 논문을 요약해줘", paper_ids=["paper-1"]))
        self.assertEqual(decision.steps, ["extract", "translate", "summarize"])

    def test_explicit_routes_do_not_overplan(self):
        router = SupervisorRouter(use_llm=True)
        cases = [
            ("내 서재에 저장된 논문 목록을 보여줘", ["library"]),
            ("설명 가능한 논문이 뭐가 있어?", ["deep_research"]),
            ("저장된 요약을 근거와 출처를 붙여 설명해줘", ["rag"]),
            ("로컬 논문들을 비교해서 심층 분석해줘", ["rag"]),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(router.decide(initial_state(query)).steps, expected)

    def test_explainable_inventory_shows_titles_without_deep_research(self):
        graph = build_graph(router=SupervisorRouter(use_llm=False), nodes=fake_nodes())
        result = graph.invoke(
            initial_state("설명 가능한 논문이 뭐가 있어?"),
            config={"configurable": {"thread_id": "test-explainable-inventory"}},
        )
        self.assertEqual(result["node_history"], ["deep_research", "finish"])
        self.assertIn("1. RAG Paper", result["response"])
        self.assertEqual(result["rag_candidates"][0]["paper_id"], "paper-1")

    def test_selected_rag_title_runs_deep_research_on_the_next_turn(self):
        graph = build_graph(router=SupervisorRouter(use_llm=False), nodes=fake_nodes())
        config = {"configurable": {"thread_id": "test-rag-title-selection"}}

        first = graph.invoke(
            initial_state("설명 가능한 분석 논문 보여줘", thread_id="test-rag-title-selection"),
            config=config,
        )
        second = graph.invoke(
            initial_state("1번 논문 설명해줘", thread_id="test-rag-title-selection"),
            config=config,
        )

        self.assertEqual(first["node_history"], ["deep_research", "finish"])
        self.assertEqual(second["node_history"], ["deep_research", "finish"])
        self.assertIn("근거 기반으로 설명했습니다", second["response"])

    def test_explicit_paper_runs_deep_research_without_rag(self):
        graph = build_graph(router=SupervisorRouter(use_llm=False), nodes=fake_nodes())
        result = graph.invoke(
            initial_state(
                "이 논문을 바로 심층 분석해줘",
                paper_ids=["paper-1"],
            ),
            config={"configurable": {"thread_id": "test-direct-deep-research"}},
        )
        self.assertEqual(result["node_history"], ["deep_research", "finish"])

    def test_empty_search_rebuilds_keywords_and_retries(self):
        search_calls = 0

        def search_node(state):
            nonlocal search_calls
            search_calls += 1
            papers = [] if search_calls == 1 else [{"id": "paper-2", "title": "Retry Paper"}]
            return {"search_results": papers, "node_history": ["search"]}

        nodes = fake_nodes()
        nodes["search"] = search_node
        graph = build_graph(router=SupervisorRouter(use_llm=False), nodes=nodes)
        result = graph.invoke(
            initial_state("arxiv에서 agent 논문 검색해줘"),
            config={"configurable": {"thread_id": "test-search-retry"}},
        )
        self.assertEqual(
            result["node_history"],
            ["keyword", "search", "keyword", "search", "finish"],
        )
        self.assertEqual(result["retry_counts"]["search"], 1)
        self.assertIn("Retry Paper", result["response"])

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

    def test_rag_without_sources_rebuilds_paper_then_runs_deep_research(self):
        rag_calls = 0

        def rag_node(state):
            nonlocal rag_calls
            rag_calls += 1
            return {
                "response": "근거를 찾지 못했습니다." if rag_calls == 1 else "RAG answer",
                "sources": [] if rag_calls == 1 else [{"paper_id": "paper-1"}],
                "node_history": ["rag"],
            }

        nodes = fake_nodes()
        nodes["rag"] = rag_node
        nodes["download"] = lambda state: {
            "paper_ids": ["paper-1"],
            "downloaded_paths": ["paper-1.pdf"],
            "node_history": ["download"],
        }
        nodes["extract"] = lambda state: {
            "extracted_records": [{"id": "paper-1", "content": "body"}],
            "node_history": ["extract"],
        }
        nodes["translate"] = lambda state: {
            "translated_paths": ["paper-1-ko.md"],
            "node_history": ["translate"],
        }
        nodes["summarize"] = lambda state: {
            "summaries": [{"id": "paper-1"}],
            "node_history": ["summarize"],
        }
        graph = build_graph(router=SupervisorRouter(use_llm=False), nodes=nodes)
        result = graph.invoke(
            initial_state("저장된 요약을 근거와 출처를 붙여 설명해줘"),
            config={"configurable": {"thread_id": "test-rag-fallback"}},
        )
        self.assertEqual(
            result["node_history"],
            [
                "rag",
                "keyword",
                "search",
                "download",
                "extract",
                "translate",
                "summarize",
                "rag",
                "deep_research",
                "finish",
            ],
        )
        self.assertIn("근거 기반으로 설명했습니다", result["response"])

    def test_rag_with_sources_runs_deep_research_even_when_rag_refuses(self):
        nodes = fake_nodes()
        nodes["rag"] = lambda state: {
            "rag_answer": "저장된 근거가 부족하여 답할 수 없습니다.",
            "response": "저장된 근거가 부족하여 답할 수 없습니다.",
            "sources": [{"id": "weak-source"}],
            "node_history": ["rag"],
        }
        graph = build_graph(router=SupervisorRouter(use_llm=False), nodes=nodes)
        result = graph.invoke(
            initial_state("저장된 요약을 근거와 출처를 붙여 설명해줘"),
            config={"configurable": {"thread_id": "test-rag-refusal-fallback"}},
        )
        self.assertEqual(result["node_history"], ["rag", "deep_research", "finish"])

    def test_deep_research_receives_the_rag_selected_paper(self):
        class FakeDeepResearchAgent:
            def __init__(self):
                self.selected = []

            def select_paper(self, selection):
                self.selected.append(selection)
                return {
                    "status": "selected",
                    "message": "selected",
                    "paper": {"id": "paper-1", "title": "RAG Paper"},
                }

            def ask(self, question):
                return {
                    "status": "success",
                    "message": "answered",
                    "answer": "Deep answer",
                    "sources": ["paper evidence"],
                    "paper": {"id": "paper-1", "title": "RAG Paper"},
                }

        agent = FakeDeepResearchAgent()
        node = DeepResearchNode(factory=lambda: agent)
        result = node(
            {
                "query": "방법론을 설명해줘",
                "sources": [{"paper_id": "paper-1", "title": "RAG Paper"}],
            }
        )
        self.assertEqual(agent.selected, ["paper-1"])
        self.assertEqual(result["deep_research_status"], "success")
        self.assertEqual(result["deep_research_paper_id"], "paper-1")
        self.assertEqual(result["deep_research_sources"], ["paper evidence"])

    def test_deep_research_accepts_an_explicit_paper_without_rag(self):
        class FakeDeepResearchAgent:
            def __init__(self):
                self.selected = []

            def select_paper(self, selection):
                self.selected.append(selection)
                return {
                    "status": "selected",
                    "paper": {"id": "paper-1", "title": "RAG Paper"},
                }

            def ask(self, question):
                return {
                    "status": "success",
                    "answer": "Direct deep answer",
                    "sources": ["paper evidence"],
                    "paper": {"id": "paper-1", "title": "RAG Paper"},
                }

        agent = FakeDeepResearchAgent()
        node = DeepResearchNode(factory=lambda: agent)
        result = node(
            {
                "query": "이 논문을 바로 심층 분석해줘",
                "paper_ids": ["paper-1"],
            }
        )
        self.assertEqual(agent.selected, ["paper-1"])
        self.assertEqual(result["deep_research_status"], "success")
        self.assertEqual(result["deep_research_paper_id"], "paper-1")

    def test_deep_research_uses_the_selected_rag_candidate_number(self):
        class FakeDeepResearchAgent:
            def __init__(self):
                self.selected = []

            def select_paper(self, selection):
                self.selected.append(selection)
                return {
                    "status": "selected",
                    "paper": {"id": selection, "title": "Selected Paper"},
                }

            def ask(self, question):
                return {
                    "status": "success",
                    "answer": "Selected answer",
                    "sources": ["selected evidence"],
                    "paper": {"id": self.selected[-1], "title": "Selected Paper"},
                }

        agent = FakeDeepResearchAgent()
        node = DeepResearchNode(factory=lambda: agent)
        result = node(
            {
                "query": "2번 논문 설명해줘",
                "rag_candidates": [
                    {"paper_id": "paper-1", "title": "First Paper"},
                    {"paper_id": "paper-2", "title": "Second Paper"},
                ],
            }
        )
        self.assertEqual(agent.selected, ["paper-2"])
        self.assertEqual(result["deep_research_paper_id"], "paper-2")

    def test_deep_research_without_evidence_returns_to_supervisor_search(self):
        deep_calls = 0

        def deep_research_node(state):
            nonlocal deep_calls
            deep_calls += 1
            if deep_calls == 1:
                return {
                    "response": "설명 근거가 없습니다.",
                    "deep_research_status": "success",
                    "deep_research_answer": "설명 근거가 없습니다.",
                    "deep_research_sources": [],
                    "node_history": ["deep_research"],
                }
            return {
                "response": "추가 논문을 근거로 설명했습니다.",
                "deep_research_status": "success",
                "deep_research_answer": "추가 논문을 근거로 설명했습니다.",
                "deep_research_sources": ["additional evidence"],
                "node_history": ["deep_research"],
            }

        nodes = fake_nodes()
        nodes["deep_research"] = deep_research_node
        nodes["download"] = lambda state: {
            "paper_ids": ["paper-2"],
            "downloaded_paths": ["paper-2.pdf"],
            "node_history": ["download"],
        }
        nodes["extract"] = lambda state: {
            "extracted_records": [{"id": "paper-2", "content": "body"}],
            "node_history": ["extract"],
        }
        nodes["translate"] = lambda state: {
            "translated_paths": ["paper-2-ko.md"],
            "node_history": ["translate"],
        }
        nodes["summarize"] = lambda state: {
            "summaries": [{"id": "paper-2"}],
            "node_history": ["summarize"],
        }
        graph = build_graph(router=SupervisorRouter(use_llm=False), nodes=nodes)
        result = graph.invoke(
            initial_state("저장된 논문을 심층 분석해줘"),
            config={"configurable": {"thread_id": "test-deep-research-retry"}},
        )
        self.assertEqual(
            result["node_history"],
            [
                "rag",
                "deep_research",
                "keyword",
                "search",
                "download",
                "extract",
                "translate",
                "summarize",
                "rag",
                "deep_research",
                "finish",
            ],
        )
        self.assertEqual(result["retry_counts"]["deep_research"], 1)
        self.assertIn("추가 논문을 근거로 설명했습니다", result["response"])

    def test_missing_translation_input_inserts_extract_node(self):
        class TranslateOnlyRouter:
            def decide(self, state):
                return SupervisorDecision(steps=["translate"], reason="번역만 계획")

        nodes = fake_nodes()
        nodes["extract"] = lambda state: {
            "extracted_records": [{"id": "paper-1", "content": "paper body"}],
            "node_history": ["extract"],
        }
        nodes["translate"] = lambda state: {
            "translated_paths": ["paper-1-ko.md"],
            "node_history": ["translate"],
        }
        graph = build_graph(router=TranslateOnlyRouter(), nodes=nodes)
        result = graph.invoke(
            initial_state("번역", paper_ids=["paper-1"]),
            config={"configurable": {"thread_id": "test-translation-prerequisite"}},
        )
        self.assertEqual(result["node_history"], ["extract", "translate", "finish"])

    def test_retry_limit_stops_an_infinite_search_loop(self):
        nodes = fake_nodes()
        nodes["search"] = lambda state: {"search_results": [], "node_history": ["search"]}
        graph = build_graph(router=SupervisorRouter(use_llm=False), nodes=nodes)
        result = graph.invoke(
            initial_state("arxiv에서 없는 논문 검색해줘", max_retries=1),
            config={"configurable": {"thread_id": "test-search-limit"}},
        )
        self.assertEqual(
            result["node_history"],
            ["keyword", "search", "keyword", "search", "finish"],
        )
        self.assertTrue(result["errors"])
        self.assertIn("찾지 못했습니다", result["response"])


class RAGChainTest(unittest.TestCase):
    def test_returns_answer_and_sources(self):
        fake_llm = RunnableLambda(lambda prompt: AIMessage(content="정확도가 개선되었습니다 [S1]."))
        chain = SummaryRAGChain(store_factory=FakeStore, llm=fake_llm)
        result = chain.invoke("결과가 뭐야?")
        self.assertEqual(result["sources"][0]["label"], "S1")
        self.assertIn("[S1]", result["answer"])


class EvaluatorTest(unittest.TestCase):
    def test_deterministic_metrics(self):
        route = route_sequence_accuracy({}, {"steps": ["rag"]}, {"expected_steps": ["rag"]})
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

    def test_retrieval_metrics_match_paper_id_and_document_id(self):
        outputs = {
            "sources": [
                {"id": "paper-1:methodology", "paper_id": "paper-1"},
            ]
        }
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
