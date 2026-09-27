from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from .models import Paper, ProcessingJob, SupervisorRun
from .jobs import _run_extraction_job, recover_stale_jobs, run_next_job


class DurableQueueTests(TestCase):
    def setUp(self):
        self.paper = Paper.objects.create(arxiv_id='1234.5678', title='Test')

    @patch('scholar.jobs.extract_paper_content')
    def test_pending_row_executes_once(self, extract):
        job = ProcessingJob.objects.create(paper=self.paper, job_type='extract')
        self.assertTrue(run_next_job())
        _run_extraction_job(job.pk)
        extract.assert_called_once_with(self.paper.arxiv_id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        self.assertFalse(run_next_job())

    def test_interrupted_work_fails_but_live_work_and_pending_survive(self):
        old = timezone.now() - timedelta(minutes=3)
        stale = ProcessingJob.objects.create(paper=self.paper, job_type='extract', status='running', heartbeat_at=old)
        live = ProcessingJob.objects.create(paper=self.paper, job_type='summarize', status='running', heartbeat_at=timezone.now())
        pending = ProcessingJob.objects.create(paper=self.paper, job_type='translate')
        graph = SupervisorRun.objects.create(thread_id='test', query='test', status='running', started_at=old)
        self.assertEqual(recover_stale_jobs(), 2)
        for obj in (stale, live, pending, graph):
            obj.refresh_from_db()
        self.assertEqual((stale.status, live.status, pending.status, graph.status),
                         ('failed', 'running', 'pending', 'failed'))
