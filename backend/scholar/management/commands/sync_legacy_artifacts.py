from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError


PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.django_paper_repository import (  # noqa: E402
    normalize_arxiv_id,
    upsert_paper_summary,
    upsert_translation,
)


DEFAULT_SUMMARY_DB = PROJECT_ROOT / "data" / "paper_summary" / "summary.db"
DEFAULT_TRANSLATE_DB = PROJECT_ROOT / "data" / "paper_translate" / "translate.db"


class Command(BaseCommand):
    help = "기존 SQLite 요약·번역 결과를 MySQL로 동기화합니다."

    def add_arguments(self, parser):
        parser.add_argument(
            "--summary-db",
            type=Path,
            default=DEFAULT_SUMMARY_DB,
            help="이관할 summary.db 경로",
        )
        parser.add_argument(
            "--translate-db",
            type=Path,
            default=DEFAULT_TRANSLATE_DB,
            help="이관할 translate.db 경로",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="MySQL에 쓰지 않고 이관 대상만 검사합니다.",
        )

    @staticmethod
    def _read_rows(path: Path, query: str, label: str) -> list[sqlite3.Row]:
        if not path.is_file():
            raise CommandError(f"{label} SQLite DB를 찾을 수 없습니다: {path}")
        try:
            with sqlite3.connect(path) as connection:
                connection.row_factory = sqlite3.Row
                return connection.execute(query).fetchall()
        except sqlite3.Error as exc:
            raise CommandError(f"{label} SQLite DB를 읽을 수 없습니다: {exc}") from exc

    def handle(self, *args, **options):
        summary_db = options["summary_db"].expanduser().resolve()
        translate_db = options["translate_db"].expanduser().resolve()

        summary_rows = self._read_rows(
            summary_db,
            """
            SELECT paper_id, summary_text, model, section_count, chunk_count
            FROM paper_summaries
            ORDER BY rowid
            """,
            "요약",
        )
        translation_rows = self._read_rows(
            translate_db,
            """
            SELECT paper_id, source_summary, translated_summary, chunk_count
            FROM translations
            ORDER BY rowid
            """,
            "번역",
        )

        self.stdout.write(
            f"SQLite 요약 {len(summary_rows)}건, 번역 {len(translation_rows)}건을 "
            "확인했습니다."
        )
        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING("DRY RUN: MySQL은 변경하지 않았습니다.")
            )
            return

        summary_created = summary_updated = 0
        summary_missing: list[str] = []
        for row in summary_rows:
            paper_id = normalize_arxiv_id(row["paper_id"])
            try:
                _summary, created = upsert_paper_summary(
                    paper_id,
                    summary_text=str(row["summary_text"] or ""),
                    model_name=str(row["model"] or ""),
                    section_count=int(row["section_count"] or 0),
                    chunk_count=int(row["chunk_count"] or 0),
                )
            except ObjectDoesNotExist:
                summary_missing.append(paper_id)
                continue
            except Exception as exc:
                raise CommandError(
                    f"요약 동기화 중 오류가 발생했습니다 ({paper_id}): {exc}"
                ) from exc
            summary_created += int(created)
            summary_updated += int(not created)

        translation_created = translation_updated = 0
        translation_missing: list[str] = []
        for row in translation_rows:
            paper_id = normalize_arxiv_id(row["paper_id"])
            try:
                _translation, created = upsert_translation(
                    paper_id,
                    source_text=str(row["source_summary"] or ""),
                    translated_text=str(row["translated_summary"] or ""),
                    translation_type="summary",
                    chunk_count=int(row["chunk_count"] or 0),
                )
            except ObjectDoesNotExist:
                translation_missing.append(paper_id)
                continue
            except Exception as exc:
                raise CommandError(
                    f"번역 동기화 중 오류가 발생했습니다 ({paper_id}): {exc}"
                ) from exc
            translation_created += int(created)
            translation_updated += int(not created)

        self.stdout.write(
            self.style.SUCCESS(
                "MySQL 결과 동기화 완료: "
                f"요약 신규 {summary_created}건/갱신 {summary_updated}건, "
                f"번역 신규 {translation_created}건/갱신 {translation_updated}건"
            )
        )
        missing_ids = sorted(set(summary_missing + translation_missing))
        if missing_ids:
            self.stdout.write(
                self.style.WARNING(
                    "MySQL Paper 또는 요약이 없어 건너뛴 논문: "
                    + ", ".join(missing_ids)
                )
            )
