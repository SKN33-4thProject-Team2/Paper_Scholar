"""기존 Streamlit·CLI 코드에서 Django Paper 모델을 사용하는 저장소."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import django
from django.apps import apps


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

if not apps.ready:
    django.setup()


from django.db import transaction

from scholar.models import Paper, PaperSection, PaperSummary, Translation


def normalize_arxiv_id(value: Any) -> str:
    """버전 접미사를 제거한 표준 arXiv ID를 반환합니다."""
    return re.sub(r"v\d+$", "", str(value or "").strip())


def _normalize_authors(value: Any) -> list[str]:
    """검색 결과의 저자 정보를 JSONField에 저장할 리스트로 변환합니다."""
    if isinstance(value, list):
        return [str(author).strip() for author in value if str(author).strip()]

    if isinstance(value, str):
        return [
            author.strip()
            for author in value.split(",")
            if author.strip()
        ]

    return []


def upsert_papers(
    papers: Iterable[Mapping[str, Any]],
) -> tuple[int, int]:
    """논문 목록을 MySQL에 추가하거나 기존 행을 갱신합니다."""
    created_count = 0
    updated_count = 0

    with transaction.atomic():
        for paper_data in papers:
            arxiv_id = normalize_arxiv_id(
                paper_data.get("arxiv_id")
                or paper_data.get("id")
                or ""
            )

            if not arxiv_id:
                continue

            _, created = Paper.objects.update_or_create(
                arxiv_id=arxiv_id,
                defaults={
                    "title": str(
                        paper_data.get("title") or arxiv_id
                    ).strip(),
                    "authors": _normalize_authors(
                        paper_data.get("authors")
                    ),
                    "abstract": str(
                        paper_data.get("abstract")
                        or paper_data.get("summary")
                        or ""
                    ).strip(),
                    "entry_url": str(
                        paper_data.get("entry_url")
                        or f"https://arxiv.org/abs/{arxiv_id}"
                    ).strip(),
                    "pdf_url": str(
                        paper_data.get("pdf_url") or ""
                    ).strip(),
                },
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

    return created_count, updated_count


def list_paper_ids() -> list[str]:
    """MySQL에 저장된 논문 ID를 기본 모델 정렬 순서로 반환합니다."""
    return list(Paper.objects.values_list("arxiv_id", flat=True))


def search_paper_ids(query: str) -> list[str]:
    """제목에 모든 검색어가 포함된 MySQL 논문 ID를 반환합니다."""
    keywords = [
        keyword
        for keyword in query.casefold().split()
        if len(keyword) > 1
    ]

    queryset = Paper.objects.all()
    for keyword in keywords:
        queryset = queryset.filter(title__icontains=keyword)

    return list(queryset.values_list("arxiv_id", flat=True))


def get_papers_by_ids(paper_ids: Iterable[str]) -> list[dict[str, Any]]:
    """요청받은 ID 순서대로 MySQL 논문 메타데이터를 반환합니다."""
    ordered_ids = [
        normalize_arxiv_id(paper_id)
        for paper_id in paper_ids
        if normalize_arxiv_id(paper_id)
    ]


def list_papers_with_sections() -> list[tuple[str, str]]:
    """본문 섹션이 저장된 MySQL 논문의 ID와 제목을 반환합니다."""
    return list(
        Paper.objects.filter(sections__isnull=False)
        .distinct()
        .values_list("arxiv_id", "title")
    )


def get_paper_sections(
    paper_id: str,
) -> tuple[str, list[tuple[int, str, str]]]:
    """MySQL에서 논문 제목과 순서가 보존된 본문 섹션을 조회합니다."""
    paper = Paper.objects.get(arxiv_id=normalize_arxiv_id(paper_id))
    sections = list(
        paper.sections.values_list(
            "section_order",
            "section_title",
            "section_text",
        )
    )
    return paper.title, sections


def get_paper_summaries(
    paper_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """MySQL 최종 요약을 요청 ID 순서 또는 최근 갱신 순서로 반환합니다."""
    queryset = PaperSummary.objects.select_related("paper")
    if paper_ids is None:
        summaries = list(queryset)
    else:
        ordered_ids = [
            normalize_arxiv_id(paper_id)
            for paper_id in paper_ids
            if normalize_arxiv_id(paper_id)
        ]
        summaries_by_id = {
            summary.paper.arxiv_id: summary
            for summary in queryset.filter(paper__arxiv_id__in=ordered_ids)
        }
        summaries = [
            summaries_by_id[paper_id]
            for paper_id in ordered_ids
            if paper_id in summaries_by_id
        ]

    return [
        {
            "paper_id": summary.paper.arxiv_id,
            "title": summary.paper.title,
            "summary_text": summary.summary_text,
        }
        for summary in summaries
    ]
    if not ordered_ids:
        return []

    papers_by_id = {
        paper.arxiv_id: paper
        for paper in Paper.objects.filter(arxiv_id__in=ordered_ids)
    }

    return [
        {
            "id": paper.arxiv_id,
            "title": paper.title,
            "authors": ", ".join(str(author) for author in paper.authors),
            "summary": paper.abstract,
            "pdf_url": paper.pdf_url,
        }
        for paper_id in ordered_ids
        if (paper := papers_by_id.get(paper_id)) is not None
    ]


def replace_paper_sections(
    paper_id: str,
    sections: Iterable[tuple[int, str, str, str]],
) -> int:
    """논문의 기존 MySQL 섹션을 새 추출 결과로 원자적으로 교체합니다."""
    arxiv_id = normalize_arxiv_id(paper_id)
    paper = Paper.objects.get(arxiv_id=arxiv_id)
    section_rows = [
        PaperSection(
            paper=paper,
            section_order=order,
            section_title=title or "",
            section_text=text or "",
            section_html=html or "",
        )
        for order, title, text, html in sections
    ]

    with transaction.atomic():
        PaperSection.objects.filter(paper=paper).delete()
        PaperSection.objects.bulk_create(section_rows)

    return len(section_rows)


def replace_many_paper_sections(
    sections_by_paper: Mapping[
        str,
        Iterable[tuple[int, str, str, str]],
    ],
) -> tuple[int, int, list[str]]:
    """여러 논문의 MySQL 섹션을 한 트랜잭션에서 일괄 교체합니다."""
    normalized_sections = {
        normalize_arxiv_id(paper_id): list(sections)
        for paper_id, sections in sections_by_paper.items()
        if normalize_arxiv_id(paper_id)
    }
    papers_by_id = Paper.objects.in_bulk(
        normalized_sections.keys(),
        field_name="arxiv_id",
    )
    missing_ids = [
        paper_id
        for paper_id in normalized_sections
        if paper_id not in papers_by_id
    ]

    section_rows = []
    for paper_id, sections in normalized_sections.items():
        paper = papers_by_id.get(paper_id)
        if paper is None:
            continue
        section_rows.extend(
            PaperSection(
                paper=paper,
                section_order=order,
                section_title=title or "",
                section_text=text or "",
                section_html=html or "",
            )
            for order, title, text, html in sections
        )

    synced_paper_ids = list(papers_by_id)
    with transaction.atomic():
        PaperSection.objects.filter(
            paper__arxiv_id__in=synced_paper_ids
        ).delete()
        PaperSection.objects.bulk_create(section_rows, batch_size=100)

    return len(synced_paper_ids), len(section_rows), missing_ids


def upsert_paper_summary(
    paper_id: str,
    *,
    summary_text: str,
    model_name: str = "",
    section_count: int = 0,
    chunk_count: int = 0,
) -> tuple[PaperSummary, bool]:
    """논문의 최종 요약을 MySQL에 생성하거나 갱신합니다."""
    paper = Paper.objects.get(arxiv_id=normalize_arxiv_id(paper_id))
    return PaperSummary.objects.update_or_create(
        paper=paper,
        defaults={
            "summary_text": summary_text,
            "model_name": model_name,
            "section_count": section_count,
            "chunk_count": chunk_count,
        },
    )


def upsert_translation(
    paper_id: str,
    *,
    source_text: str,
    translated_text: str,
    translation_type: str = Translation.TranslationType.FULL_TEXT,
    source_language: str = "en",
    target_language: str = "ko",
    model_name: str = "",
    chunk_count: int = 0,
) -> tuple[Translation, bool]:
    """논문의 번역 결과를 유형과 대상 언어 기준으로 생성하거나 갱신합니다."""
    paper = Paper.objects.get(arxiv_id=normalize_arxiv_id(paper_id))
    summary = None
    if translation_type == Translation.TranslationType.SUMMARY:
        summary = PaperSummary.objects.get(paper=paper)

    return Translation.objects.update_or_create(
        paper=paper,
        translation_type=translation_type,
        target_language=target_language,
        defaults={
            "summary": summary,
            "source_text": source_text,
            "translated_text": translated_text,
            "source_language": source_language,
            "model_name": model_name,
            "chunk_count": chunk_count,
        },
    )
