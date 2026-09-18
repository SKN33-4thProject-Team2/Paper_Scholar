from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.django_paper_repository import (  # noqa: E402
    normalize_arxiv_id,
    upsert_papers,
)


DEFAULT_SQLITE_PATH = (
    PROJECT_ROOT / "data" / "paper_list" / "saved_papers.db"
)


class Command(BaseCommand):
    help = "기존 SQLite 서재의 논문 메타데이터를 MySQL Paper 테이블로 동기화합니다."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sqlite-path",
            type=Path,
            default=DEFAULT_SQLITE_PATH,
            help="이관할 saved_papers.db 경로",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="MySQL에 쓰지 않고 이관 대상만 검사합니다.",
        )

    def handle(self, *args, **options):
        sqlite_path = options["sqlite_path"].expanduser().resolve()
        if not sqlite_path.is_file():
            raise CommandError(f"SQLite 서재를 찾을 수 없습니다: {sqlite_path}")

        try:
            with sqlite3.connect(sqlite_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT id, title, authors, summary, pdf_url
                    FROM papers
                    ORDER BY created_at DESC
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise CommandError(f"SQLite 서재를 읽을 수 없습니다: {exc}") from exc

        papers_by_id = {}
        for row in rows:
            arxiv_id = normalize_arxiv_id(row["id"])
            if not arxiv_id or arxiv_id in papers_by_id:
                continue
            papers_by_id[arxiv_id] = {
                "id": arxiv_id,
                "title": row["title"],
                "authors": row["authors"],
                "summary": row["summary"],
                "pdf_url": row["pdf_url"],
            }

        papers = list(papers_by_id.values())
        self.stdout.write(
            f"SQLite {len(rows)}건을 확인했습니다. "
            f"표준 arXiv ID 기준 이관 대상은 {len(papers)}건입니다."
        )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("DRY RUN: MySQL은 변경하지 않았습니다."))
            return

        created_count, updated_count = upsert_papers(papers)
        self.stdout.write(
            self.style.SUCCESS(
                "MySQL 논문 동기화 완료: "
                f"신규 {created_count}건, 갱신 {updated_count}건"
            )
        )
