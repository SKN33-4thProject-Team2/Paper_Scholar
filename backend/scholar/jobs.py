from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.utils import timezone

from .models import ProcessingJob, SupervisorRun


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


def enqueue_translation_job(job_id: int) -> None:
    _EXECUTOR.submit(_run_translation_job, job_id)


# Supervisor 실행은 검색부터 번역까지 여러 노드를 이어서 돌 수 있어 오래 걸린다.
# 논문 단위 작업 큐를 막지 않도록 실행기를 분리한다.
_SUPERVISOR_EXECUTOR = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="supervisor-run",
)


def enqueue_supervisor_run(run_id: int) -> None:
    _SUPERVISOR_EXECUTOR.submit(_run_supervisor_run, run_id)


def _run_supervisor_run(run_id: int) -> None:
    close_old_connections()
    try:
        run = SupervisorRun.objects.get(pk=run_id)
        run.status = SupervisorRun.Status.RUNNING
        run.started_at = timezone.now()
        run.error_message = ""
        run.save(update_fields=("status", "started_at", "error_message"))

        from .supervisor_service import run_supervisor, summarize_result

        result = summarize_result(
            run_supervisor(run.query, thread_id=run.thread_id)
        )

        run.response = result["response"]
        run.node_history = result["node_history"]
        run.papers = result["papers"]
        run.sources = result["sources"]
        if result["needs_input"]:
            run.status = SupervisorRun.Status.NEEDS_INPUT
        elif result["errors"]:
            run.status = SupervisorRun.Status.FAILED
            run.error_message = " | ".join(str(item) for item in result["errors"])
        else:
            run.status = SupervisorRun.Status.COMPLETED
        run.completed_at = timezone.now()
        run.save(
            update_fields=(
                "status",
                "response",
                "node_history",
                "papers",
                "sources",
                "error_message",
                "completed_at",
            )
        )
    except Exception as exc:
        SupervisorRun.objects.filter(pk=run_id).update(
            status=SupervisorRun.Status.FAILED,
            error_message=f"{type(exc).__name__}: {exc}",
            completed_at=timezone.now(),
        )
    finally:
        close_old_connections()


def extract_paper_content(arxiv_id: str) -> int:
    from tools.extractor_tool import extract_and_save

    return extract_and_save(arxiv_id, require_django_sync=True)


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
        from .services.translation_service import generate_summary_translation

        summary = generate_paper_summary(job.paper)
        generate_summary_translation(job.paper)
        job.status = ProcessingJob.Status.COMPLETED
        job.progress_current = 1
        job.model_name = summary.model_name
        job.completed_at = timezone.now()
        job.save(
            update_fields=(
                "status",
                "progress_current",
                "progress_total",
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


def _run_translation_job(job_id: int) -> None:
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

        from .services.translation_service import generate_full_text_translation

        translation = generate_full_text_translation(job.paper)
        job.status = ProcessingJob.Status.COMPLETED
        job.progress_current = translation.chunk_count
        job.progress_total = translation.chunk_count
        job.model_name = translation.model_name
        job.completed_at = timezone.now()
        job.save(
            update_fields=(
                "status",
                "progress_current",
                "progress_total",
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
