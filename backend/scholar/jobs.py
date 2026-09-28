"""DB-backed queue. Web processes only persist jobs; run_jobs executes them."""
from __future__ import annotations

import logging
from datetime import timedelta
from threading import Event, Thread

from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from .models import ProcessingJob, SupervisorRun

logger = logging.getLogger(__name__)


def enqueue_extraction_job(job_id: int) -> None:
    # The committed pending row IS the durable queue entry.
    logger.info('Extraction queued: %s', job_id)


def enqueue_summary_job(job_id: int) -> None:
    logger.info('Summary queued: %s', job_id)


def enqueue_translation_job(job_id: int) -> None:
    logger.info('Translation queued: %s', job_id)


def enqueue_supervisor_run(run_id: int) -> None:
    logger.info('Supervisor queued: %s', run_id)


def recover_stale_jobs() -> int:
    """Make interrupted work retryable; never silently replay billable calls."""
    cutoff = timezone.now() - timedelta(minutes=2)
    total = 0
    for model in (ProcessingJob, SupervisorRun):
        total += model.objects.filter(status='running').filter(
            Q(heartbeat_at__lt=cutoff) | Q(heartbeat_at__isnull=True, started_at__lt=cutoff)
            | Q(heartbeat_at__isnull=True, started_at__isnull=True)
        ).update(status='failed', completed_at=timezone.now(),
                 error_message='작업 실행이 중단되었습니다. 요청을 다시 보내 재시도해 주세요.')
    return total


def _execute(model, pk, operation):
    close_old_connections()
    now = timezone.now()
    # Atomic compare-and-swap prevents two worker processes claiming one job.
    claimed = model.objects.filter(pk=pk, status='pending').update(
        status='running', started_at=now, heartbeat_at=now, error_message='')
    if not claimed:
        return
    stopped = Event()

    def heartbeat():
        try:
            while not stopped.wait(15):
                close_old_connections()
                model.objects.filter(pk=pk, status='running').update(heartbeat_at=timezone.now())
        except Exception:
            logger.exception('Worker heartbeat failed')
        finally:
            close_old_connections()

    keeper = Thread(target=heartbeat, daemon=True)
    keeper.start()
    try:
        values = operation(model.objects.get(pk=pk))
        model.objects.filter(pk=pk, status='running').update(
            completed_at=timezone.now(), **values)
    except Exception as exc:
        logger.exception('Job failed: %s/%s', model.__name__, pk)
        model.objects.filter(pk=pk, status='running').update(
            status='failed', completed_at=timezone.now(),
            error_message=str(exc))
    finally:
        stopped.set()
        keeper.join(timeout=2)
        close_old_connections()


def extract_paper_content(arxiv_id: str) -> int:
    from tools.extractor_tool import extract_and_save
    return extract_and_save(arxiv_id, require_django_sync=True)


def _run_extraction_job(job_id: int) -> None:
    def operation(job):
        extract_paper_content(job.paper.arxiv_id)
        return dict(status='completed', progress_current=1, progress_total=1)
    _execute(ProcessingJob, job_id, operation)


def _run_summary_job(job_id: int) -> None:
    def operation(job):
        from .services.summary_service import generate_paper_summary
        summary = generate_paper_summary(job.paper)
        return dict(status='completed', progress_current=1, progress_total=1, model_name=summary.model_name)
    _execute(ProcessingJob, job_id, operation)


def _run_translation_job(job_id: int) -> None:
    def operation(job):
        from .services.translation_service import generate_summary_translation
        translation = generate_summary_translation(job.paper)
        return dict(status='completed', progress_current=1, progress_total=1, model_name=translation.model_name)
    _execute(ProcessingJob, job_id, operation)


def _run_supervisor_run(run_id: int) -> None:
    def operation(run):
        from .web_graph import run_web_graph
        result = run_web_graph(run)
        errors = result.get('errors', [])
        return dict(
            status='failed' if errors else 'needs_input' if result.get('human_input_required') else 'completed',
            response=result.get('response', ''), node_history=result.get('node_history', []),
            papers=result.get('search_results', []), sources=result.get('sources', []),
            error_message=' | '.join(errors),
        )
    _execute(SupervisorRun, run_id, operation)


def run_next_job() -> bool:
    recover_stale_jobs()
    paper_job = ProcessingJob.objects.filter(status='pending').order_by('created_at', 'pk').first()
    graph_job = SupervisorRun.objects.filter(status='pending').order_by('created_at', 'pk').first()
    if graph_job and (not paper_job or graph_job.created_at < paper_job.created_at):
        _run_supervisor_run(graph_job.pk)
    elif paper_job:
        runner = {'extract': _run_extraction_job, 'summarize': _run_summary_job,
                  'translate': _run_translation_job}.get(paper_job.job_type)
        if runner:
            runner(paper_job.pk)
        else:
            ProcessingJob.objects.filter(pk=paper_job.pk, status='pending').update(
                status='failed', error_message='지원하지 않는 작업 종류입니다.', completed_at=timezone.now())
    else:
        return False
    return True
