"""Versioned evaluation cases covering artifacts, RAG, Deep Research and E2E flow."""

from __future__ import annotations

from typing import Any


DATASET_VERSION = "v2"

PAPERS: tuple[dict[str, Any], ...] = (
    {
        "paper_id": "1906.04972v1",
        "title": "Toward Interpretable Music Tagging with Self-Attention",
        "artifact_prefix": "Toward_Interpretable_Music_Tagging_with_Self-Atten",
        "expected_acronyms": ["AUROC", "AUPR"],
        "expected_numbers": ["15.2ms", "44.39"],
    },
    {
        "paper_id": "2006.00697v3",
        "title": "Translating Natural Language Instructions for Behavioral Robot Navigation with a Multi-Head Attention Mechanism",
        "artifact_prefix": "Translating_Natural_Language_Instructions_for_Beha",
        "expected_acronyms": ["Test-New", "M@0"],
        "expected_numbers": ["55.96%", "69.82"],
    },
    {
        "paper_id": "2007.13199v2",
        "title": "Double Multi-Head Attention for Speaker Verification",
        "artifact_prefix": "Double_Multi-Head_Attention_for_Speaker_Verificati",
        "expected_acronyms": ["CNN", "EER"],
        "expected_numbers": ["3.42%", "4.89%"],
    },
    {
        "paper_id": "2107.06493v1",
        "title": "Serialized Multi-Layer Multi-Head Attention for Neural Speaker Embedding",
        "artifact_prefix": "Serialized_Multi-Layer_Multi-Head_Attention_for_Ne",
        "expected_acronyms": ["SITW", "EER"],
        "expected_numbers": ["2.16%", "2.82%"],
    },
    {
        "paper_id": "2210.00939v6",
        "title": "Improving Sample Quality of Diffusion Models Using Self-Attention Guidance",
        "artifact_prefix": "Improving_Sample_Quality_of_Diffusion_Models_Using",
        "expected_acronyms": ["SAG", "FID", "sFID"],
        "expected_numbers": ["26.21", "20.08"],
    },
    {
        "paper_id": "2305.19798v2",
        "title": "Primal-Attention: Self-attention through Asymmetric Kernel SVD in Primal Representation",
        "artifact_prefix": "Primal-Attention_Self-attention_through_Asymmetric",
        "expected_acronyms": ["SVD", "KSVD"],
        "expected_numbers": ["35.4%", "1.59GB"],
    },
    {
        "paper_id": "2308.10917v1",
        "title": "PACS: Prediction and analysis of cancer subtypes from multi-omics data based on a multi-head attention mechanism model",
        "artifact_prefix": "PACS_Prediction_and_analysis_of_cancer_subtypes_fr",
        "expected_acronyms": ["PACS", "SMA"],
        "expected_numbers": ["0.981", "1.000"],
    },
    {
        "paper_id": "2310.08064v1",
        "title": "Age Estimation Based on Graph Convolutional Networks and Multi-head Attention Mechanisms",
        "artifact_prefix": "Age_Estimation_Based_on_Graph_Convolutional_Networ",
        "expected_acronyms": ["GCN", "K-NN"],
        "expected_numbers": ["3.47", "13%"],
    },
    {
        "paper_id": "2410.11842v3",
        "title": "MoH: Multi-Head Attention as Mixture-of-Head Attention",
        "artifact_prefix": "MoH_Multi-Head_Attention_as_Mixture-of-Head_Attent",
        "expected_acronyms": ["MoH", "MHA", "MoE"],
        "expected_numbers": ["50%", "45.4%"],
    },
    {
        "paper_id": "2511.13780v1",
        "title": "Self-Attention as Distributional Projection: A Unified Interpretation of Transformer Architecture",
        "artifact_prefix": "Self-Attention_as_Distributional_Projection_A_Unif",
        "expected_acronyms": ["PMI", "QSP", "PSP"],
        "expected_numbers": ["0.62", "0.38"],
    },
)

RAG_QUESTION_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("method", "「{title}」 논문의 연구 목적과 핵심 방법을 근거와 함께 설명해줘."),
    ("result", "「{title}」 논문의 주요 실험 결과와 한계를 근거와 함께 설명해줘."),
)

REFUSAL_CASES: tuple[dict[str, str], ...] = (
    {
        "case_id": "rag-refusal-quantum-gravity",
        "query": "저장된 논문만 근거로 양자 중력의 실험적 증거를 설명해줘.",
    },
    {
        "case_id": "rag-refusal-mars-weather",
        "query": "저장된 논문만 근거로 내일 화성의 정확한 날씨를 알려줘.",
    },
    {
        "case_id": "rag-refusal-stock-price",
        "query": "저장된 논문만 근거로 다음 달 특정 기업의 주가를 예측해줘.",
    },
)

DEEP_RESEARCH_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "deep-compare-attention",
        "query": "로컬 논문들을 딥리서치해서 다중 헤드 어텐션 구조 두 가지를 비교해줘.",
        "required_terms": ["어텐션", "비교"],
    },
    {
        "case_id": "deep-compare-speaker",
        "query": "로컬 화자 검증 논문들의 방법과 EER 결과를 딥리서치해서 비교해줘.",
        "required_terms": ["EER", "화자"],
    },
    {
        "case_id": "deep-method-limitations",
        "query": "로컬 논문 제안 방법의 장점과 한계를 딥리서치해서 교차 분석해줘.",
        "required_terms": ["장점", "한계"],
    },
    {
        "case_id": "deep-citation-trace",
        "query": "로컬 논문들의 핵심 수치와 인용 연결을 딥리서치해서 정리해줘.",
        "required_terms": ["수치", "인용"],
    },
    {
        "case_id": "deep-synthesis",
        "query": "로컬 어텐션 논문들을 딥리서치해서 공통 연구 흐름과 후속 연구 방향을 제안해줘.",
        "required_terms": ["공통", "후속"],
    },
)

PIPELINE_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "pipeline-search",
        "query": "arXiv에서 graph RAG 논문을 검색해줘.",
        "expected_steps": ["keyword", "search"],
        "expected_output_keys": ["search_results"],
    },
    {
        "case_id": "pipeline-library",
        "query": "내 서재에 저장된 논문 목록을 보여줘.",
        "expected_steps": ["library"],
        "expected_output_keys": ["library_results"],
    },
    {
        "case_id": "pipeline-translate",
        "query": "2007.13199v2 논문을 번역해줘.",
        "paper_ids": ["2007.13199v2"],
        "expected_steps": ["extract", "translate"],
        "expected_output_keys": ["translated_paths"],
    },
    {
        "case_id": "pipeline-summary",
        "query": "2007.13199v2 논문을 요약해줘.",
        "paper_ids": ["2007.13199v2"],
        "expected_steps": ["extract", "translate", "summarize"],
        "expected_output_keys": ["summaries"],
    },
    {
        "case_id": "pipeline-rag",
        "query": "저장된 요약을 근거와 출처를 붙여 설명해줘.",
        "expected_steps": ["rag"],
        "expected_output_keys": ["response", "sources"],
    },
    {
        "case_id": "pipeline-deep-research",
        "query": "로컬 논문들을 비교해서 심층 분석해줘.",
        "expected_steps": ["deep_research"],
        "expected_output_keys": ["response"],
    },
    {
        "case_id": "pipeline-search-retry",
        "query": "arXiv에서 매우 희귀한 가상 연구 주제의 논문을 검색해줘.",
        "expected_steps": ["keyword", "search"],
        "expected_output_keys": ["response"],
    },
    {
        "case_id": "pipeline-rag-fallback",
        "query": "저장된 근거가 부족하면 심층 분석으로 전환해서 설명해줘.",
        "expected_steps": ["rag", "deep_research"],
        "expected_output_keys": ["response"],
    },
)


def _artifact_example(paper: dict[str, Any]) -> dict[str, Any]:
    prefix = paper["artifact_prefix"]
    return {
        "inputs": {
            "suite": "artifacts",
            "case_id": f"artifact-{paper['paper_id']}",
            "paper_id": paper["paper_id"],
            "translation_path": f"data/paper_list/processed_outputs/{prefix}_full_translated.md",
            "summary_path": f"data/paper_list/processed_outputs/{prefix}_summary.md",
        },
        "outputs": {
            "title": paper["title"],
            "expected_translation_terms": paper["expected_acronyms"],
            "expected_acronyms": paper["expected_acronyms"],
            "expected_numbers": paper["expected_numbers"],
        },
    }


def build_examples(suite: str = "all") -> list[dict[str, Any]]:
    """Return versioned LangSmith-compatible examples for a selected suite."""

    examples: list[dict[str, Any]] = []
    examples.extend(_artifact_example(paper) for paper in PAPERS)

    for paper in PAPERS:
        for suffix, template in RAG_QUESTION_TEMPLATES:
            examples.append(
                {
                    "inputs": {
                        "suite": "rag",
                        "case_id": f"rag-{paper['paper_id']}-{suffix}",
                        "query": template.format(title=paper["title"]),
                    },
                    "outputs": {
                        "relevant_source_ids": [paper["paper_id"]],
                        "expected_refusal": False,
                    },
                }
            )
    examples.extend(
        {
            "inputs": {"suite": "rag", "case_id": case["case_id"], "query": case["query"]},
            "outputs": {"expected_refusal": True},
        }
        for case in REFUSAL_CASES
    )
    examples.extend(
        {
            "inputs": {"suite": "deep_research", **case},
            "outputs": {
                "required_terms": case["required_terms"],
                "expected_steps": ["deep_research"],
            },
        }
        for case in DEEP_RESEARCH_CASES
    )
    examples.extend(
        {
            "inputs": {
                "suite": "pipeline",
                "case_id": case["case_id"],
                "query": case["query"],
                "paper_ids": list(case.get("paper_ids", [])),
            },
            "outputs": {
                "expected_steps": case["expected_steps"],
                "expected_output_keys": case["expected_output_keys"],
            },
        }
        for case in PIPELINE_CASES
    )

    if suite == "all":
        return examples
    allowed = {"artifacts", "rag", "deep_research", "pipeline"}
    if suite not in allowed:
        raise ValueError(f"지원하지 않는 평가 suite입니다: {suite}")
    return [example for example in examples if example["inputs"]["suite"] == suite]


def dataset_counts() -> dict[str, int]:
    counts = {suite: len(build_examples(suite)) for suite in ("artifacts", "rag", "deep_research", "pipeline")}
    counts["papers"] = len(PAPERS)
    counts["total"] = sum(counts[suite] for suite in ("artifacts", "rag", "deep_research", "pipeline"))
    return counts


__all__ = [
    "DATASET_VERSION",
    "PAPERS",
    "build_examples",
    "dataset_counts",
]
