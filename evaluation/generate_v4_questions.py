"""Generate up to 100 Deep Search Q&A cases over the corpus_v4 (200-paper) set.

Read-only w.r.t. src/backend/frontend: this script only imports the app's
own LLM client (langchain_openai) and reads evaluation/corpus_v4's own
extraction DB. All output is written under evaluation/corpus_v4/generated/.

Design: for each sampled paper we pick ONE page whose text is substantial,
then ask an LLM to write a question answerable ONLY from that page. Because
the question is generated FROM the chosen page, that page is the ground-truth
"relevant source" for retrieval-quality scoring (Recall@K / MRR) without a
separate manual labeling pass.
"""

from __future__ import annotations

import argparse
import json
import random
from typing import Any

from pydantic import BaseModel, Field

from v4_runtime import GENERATED_ROOT, load_manifest, load_paper_sections

OUTPUT_PATH = GENERATED_ROOT / "questions_v4.jsonl"
MIN_PAGE_CHARS = 400
PAPERS_PER_TOPIC = 20  # 5 topics x 20 = 100 questions total


class GeneratedQuestion(BaseModel):
    question: str = Field(description="한국어로 작성된, 해당 페이지 내용만으로 답할 수 있는 구체적인 질문")
    reference_answer: str = Field(description="위 질문에 대한 한두 문장짜리 한국어 정답 요약")


def _pick_page(sections: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        section
        for section in sections
        if len(str(section.get("section_text") or "").strip()) >= MIN_PAGE_CHARS
    ]
    if not candidates:
        return None
    # Prefer early-but-not-first pages: page 1 is often just title/author block,
    # later pages skew toward references. The middle of the paper tends to hold
    # concrete method/result content that supports a specific, checkable question.
    candidates.sort(key=lambda section: section["section_order"])
    midpoint = len(candidates) // 2
    return candidates[midpoint]


def _select_papers(manifest: list[dict[str, Any]], *, per_topic: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for paper in manifest:
        by_topic.setdefault(str(paper.get("topic") or ""), []).append(paper)
    selected: list[dict[str, Any]] = []
    for topic, papers in sorted(by_topic.items()):
        pool = list(papers)
        rng.shuffle(pool)
        selected.extend(pool[:per_topic])
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-topic", type=int, default=PAPERS_PER_TOPIC)
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--limit", type=int, default=None, help="디버그용: 생성 개수 제한")
    parser.add_argument(
        "--append",
        action="store_true",
        help="기존 questions_v4.jsonl에 이미 있는 paper_id는 건너뛰고, 새로 뽑힌 논문만 이어서 추가",
    )
    args = parser.parse_args()

    from langchain_openai import ChatOpenAI

    judge = ChatOpenAI(model=args.model, temperature=0.3).with_structured_output(GeneratedQuestion)

    manifest = load_manifest()
    papers = _select_papers(manifest, per_topic=args.per_topic, seed=args.seed)
    if args.limit:
        papers = papers[: args.limit]

    existing_ids: set[str] = set()
    if args.append and OUTPUT_PATH.is_file():
        for line in OUTPUT_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing_ids.add(str(json.loads(line)["paper_id"]))
        papers = [paper for paper in papers if str(paper["paper_id"]) not in existing_ids]

    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped: list[str] = []
    mode = "a" if args.append else "w"
    with OUTPUT_PATH.open(mode, encoding="utf-8") as handle:
        for paper in papers:
            paper_id = str(paper["paper_id"])
            sections = load_paper_sections(paper_id)
            page = _pick_page(sections)
            if page is None:
                skipped.append(paper_id)
                continue
            page_text = str(page["section_text"]).strip()
            prompt = (
                "다음은 학술 논문 한 페이지의 본문입니다. 이 페이지의 내용만 알면 답할 수 있는, "
                "구체적이고 사실 확인이 가능한 한국어 질문을 하나 만들어 주세요. "
                "예/아니오로 답하는 질문이나 '이 논문의 기여는 무엇인가'처럼 지나치게 포괄적인 질문은 피하세요.\n\n"
                f"논문 제목: {paper.get('title', '')}\n\n"
                f"페이지 본문:\n{page_text[:4000]}"
            )
            try:
                result = judge.invoke(prompt)
            except Exception as exc:
                skipped.append(f"{paper_id} (LLM 오류: {exc})")
                continue

            record = {
                "paper_id": paper_id,
                "topic": paper.get("topic"),
                "title": paper.get("title"),
                "question": result.question,
                "reference_answer": result.reference_answer,
                "expected_section": f"page_{page['section_order']}",
                "expected_section_order": int(page["section_order"]),
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1

    print(f"작성된 질문: {written}개 -> {OUTPUT_PATH}")
    if skipped:
        print(f"건너뜀: {len(skipped)}개")
        for item in skipped[:20]:
            print(f"  - {item}")


if __name__ == "__main__":
    main()
