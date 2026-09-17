from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.utils import timezone

from .models import ProcessingJob


# 개발·단일 서버용 실행기입니다. 배포 환경에서는 Celery/RQ 같은 외부 작업 큐로
# 교체하더라도 API와 ProcessingJob 응답 형식은 그대로 유지할 수 있습니다.
_EXECUTOR = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="paper-processing",
)


def enqueue_extraction_job(job_id: int) -> None:
    _EXECUTOR.submit(_run_extraction_job, job_id)


def enqueue_summary_job(job_id: int) -> None:
    _EXECUTOR.submit(_run_summary_job, job_id)


def extract_paper_content(arxiv_id: str) -> int:
    from tools.extractor_tool import extract_and_save

    return extract_and_save(arxiv_id)


def _run_extraction_job(job_id: int) -> None:
    close_old_connections()
    try:
        job = ProcessingJob.objects.select_related("paper").get(pk=job_id)
        job.status = ProcessingJob.Status.RUNNING
        job.started_at = timezone.now()
        job.progress_current = 0
        job.progress_total = 1
        job.error_message = ""
        job.save(
            update_fields=(
                "status",
                "started_at",
                "progress_current",
                "progress_total",
                "error_message",
            )
        )

        extract_paper_content(job.paper.arxiv_id)

        job.status = ProcessingJob.Status.COMPLETED
        job.progress_current = 1
        job.completed_at = timezone.now()
        job.save(
            update_fields=(
                "status",
                "progress_current",
                "completed_at",
            )
        )
    except Exception as exc:
        ProcessingJob.objects.filter(pk=job_id).update(
            status=ProcessingJob.Status.FAILED,
            error_message=str(exc),
            completed_at=timezone.now(),
        )
    finally:
        close_old_connections()


def _run_summary_job(job_id: int) -> None:
    close_old_connections()
    try:
        job = ProcessingJob.objects.select_related("paper").get(pk=job_id)
        job.status = ProcessingJob.Status.RUNNING
        job.started_at = timezone.now()
        job.progress_current = 0
        job.progress_total = 1
        job.error_message = ""
        job.save(
            update_fields=(
                "status",
                "started_at",
                "progress_current",
                "progress_total",
                "error_message",
            )
        )

        from .services.summary_service import generate_paper_summary

        summary = generate_paper_summary(job.paper)
        job.status = ProcessingJob.Status.COMPLETED
        job.progress_current = 1
        job.model_name = summary.model_name
        job.completed_at = timezone.now()
        job.save(
            update_fields=(
                "status",
                "progress_current",
                "model_name",
                "completed_at",
            )
        )
    except Exception as exc:
        ProcessingJob.objects.filter(pk=job_id).update(
            status=ProcessingJob.Status.FAILED,
            error_message=str(exc),
            completed_at=timezone.now(),
        )
    finally:
        close_old_connections()
