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

from scholar.models import Paper


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
