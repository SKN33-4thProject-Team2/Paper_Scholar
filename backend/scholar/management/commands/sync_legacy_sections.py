from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.django_paper_repository import (  # noqa: E402
    normalize_arxiv_id,
    replace_many_paper_sections,
)


DEFAULT_SQLITE_PATH = (
    PROJECT_ROOT / "data" / "paper_extract" / "extracted_papers.db"
)


class Command(BaseCommand):
    help = "기존 SQLite 본문 섹션을 MySQL PaperSection 테이블로 동기화합니다."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sqlite-path",
            type=Path,
            default=DEFAULT_SQLITE_PATH,
            help="이관할 extracted_papers.db 경로",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="MySQL에 쓰지 않고 이관 대상만 검사합니다.",
        )

    def handle(self, *args, **options):
        sqlite_path = options["sqlite_path"].expanduser().resolve()
        if not sqlite_path.is_file():
            raise CommandError(f"추출 SQLite DB를 찾을 수 없습니다: {sqlite_path}")

        try:
            with sqlite3.connect(sqlite_path) as connection:
                rows = connection.execute(
                    """
                    SELECT paper_id, section_order, section_title,
                           section_text, section_html
                    FROM paper_sections
                    ORDER BY paper_id, section_order
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise CommandError(f"추출 SQLite DB를 읽을 수 없습니다: {exc}") from exc

        sections_by_paper = defaultdict(list)
        for paper_id, order, title, text, html in rows:
            arxiv_id = normalize_arxiv_id(paper_id)
            if not arxiv_id:
                continue
            sections_by_paper[arxiv_id].append(
                (order, title, text, html)
            )

        self.stdout.write(
            f"SQLite 논문 {len(sections_by_paper)}편, "
            f"본문 섹션 {len(rows)}개를 확인했습니다."
        )

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING("DRY RUN: MySQL은 변경하지 않았습니다.")
            )
            return

        paper_count, section_count, missing_ids = replace_many_paper_sections(
            sections_by_paper
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"MySQL 본문 동기화 완료: 논문 {paper_count}편, "
                f"섹션 {section_count}개"
            )
        )
        if missing_ids:
            self.stdout.write(
                self.style.WARNING(
                    "MySQL Paper가 없어 건너뛴 논문: "
                    + ", ".join(missing_ids)
                )
            )
