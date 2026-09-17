"""기존 Streamlit·CLI 코드에서 Django Paper 모델을 사용하는 저장소."""

from __future__ import annotations

import os
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
            arxiv_id = str(
                paper_data.get("arxiv_id")
                or paper_data.get("id")
                or ""
            ).strip()

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