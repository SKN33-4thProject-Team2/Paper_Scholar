from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch

from .models import (
    Paper,
    PaperSection,
    PaperSummary,
    ProcessingJob,
    Translation,
)


class PaperAPITest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.paper = Paper.objects.create(
            arxiv_id="1702.01806",
            title="Attention Is All You Need",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            abstract="Transformer architecture paper.",
            entry_url="https://arxiv.org/abs/1702.01806",
            pdf_url="https://arxiv.org/pdf/1702.01806",
        )
        PaperSection.objects.create(
            paper=cls.paper,
            section_order=2,
            section_title="Method",
            section_text="Method body",
        )
        PaperSection.objects.create(
            paper=cls.paper,
            section_order=1,
            section_title="Introduction",
            section_text="Section body",
        )
        summary = PaperSummary.objects.create(
            paper=cls.paper,
            summary_text="Paper summary",
            model_name="test-model",
            section_count=1,
            chunk_count=1,
        )
        Translation.objects.create(
            paper=cls.paper,
            summary=summary,
            translation_type=Translation.TranslationType.SUMMARY,
            source_text="Paper summary",
            translated_text="논문 요약",
            target_language="ko",
        )
        cls.empty_paper = Paper.objects.create(
            arxiv_id="2401.00001",
            title="Paper without artifacts",
            authors=[],
        )

    def test_list_papers_returns_paginated_mysql_shape(self):
        response = self.client.get(reverse("scholar:paper-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        paper = next(
            item
            for item in response.data["results"]
            if item["arxiv_id"] == self.paper.arxiv_id
        )
        self.assertEqual(paper["arxiv_id"], "1702.01806")
        self.assertEqual(paper["section_count"], 2)
        self.assertEqual(paper["translation_count"], 1)
        self.assertTrue(paper["has_summary"])

    def test_health_check_returns_service_status(self):
        response = self.client.get(reverse("scholar:health"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {"status": "ok", "service": "paper-scholar-api"},
        )

    def test_allowed_frontend_origin_receives_cors_header(self):
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            with self.subTest(origin=origin):
                response = self.client.get(
                    reverse("scholar:health"),
                    HTTP_ORIGIN=origin,
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(
                    response.headers["Access-Control-Allow-Origin"],
                    origin,
                )

    def test_detail_accepts_arxiv_id_with_period(self):
        response = self.client.get(
            reverse(
                "scholar:paper-detail",
                kwargs={"arxiv_id": self.paper.arxiv_id},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["arxiv_id"], "1702.01806")
        self.assertEqual(response.data["entry_url"], self.paper.entry_url)

    def test_detail_returns_404_for_unknown_paper(self):
        response = self.client.get(
            reverse(
                "scholar:paper-detail",
                kwargs={"arxiv_id": "9999.99999"},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_sections_are_returned_in_section_order(self):
        response = self.client.get(
            reverse(
                "scholar:paper-sections",
                kwargs={"arxiv_id": self.paper.arxiv_id},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [section["section_order"] for section in response.data],
            [1, 2],
        )
        self.assertEqual(response.data[0]["arxiv_id"], self.paper.arxiv_id)

    def test_summary_returns_final_summary(self):
        response = self.client.get(
            reverse(
                "scholar:paper-summary",
                kwargs={"arxiv_id": self.paper.arxiv_id},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["summary_text"], "Paper summary")
        self.assertEqual(response.data["model_name"], "test-model")

    def test_summary_returns_404_when_paper_has_no_summary(self):
        response = self.client.get(
            reverse(
                "scholar:paper-summary",
                kwargs={"arxiv_id": self.empty_paper.arxiv_id},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_translations_include_type_and_language(self):
        response = self.client.get(
            reverse(
                "scholar:paper-translations",
                kwargs={"arxiv_id": self.paper.arxiv_id},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["translation_type"], "summary")
        self.assertEqual(response.data[0]["target_language"], "ko")
        self.assertEqual(response.data[0]["translated_text"], "논문 요약")

    def test_translations_can_be_filtered(self):
        url = reverse(
            "scholar:paper-translations",
            kwargs={"arxiv_id": self.paper.arxiv_id},
        )

        response = self.client.get(
            url,
            {"type": "full_text", "target_language": "ko"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_child_resources_return_404_for_unknown_paper(self):
        for route_name in ("paper-sections", "paper-translations"):
            with self.subTest(route_name=route_name):
                response = self.client.get(
                    reverse(
                        f"scholar:{route_name}",
                        kwargs={"arxiv_id": "9999.99999"},
                    )
                )
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ArxivSearchAPITest(APITestCase):
    @patch("scholar.views.run_arxiv_search")
    def test_search_reuses_existing_arxiv_service(self, search_mock):
        search_mock.return_value = [
            {
                "arxiv_id": "1706.03762",
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani", "Noam Shazeer"],
                "abstract": "Transformer abstract",
                "pdf_url": "https://arxiv.org/pdf/1706.03762",
            }
        ]

        response = self.client.post(
            reverse("scholar:arxiv-search"),
            {
                "query": "transformer",
                "max_results": 5,
                "sort_by": "n",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["arxiv_id"], "1706.03762")
        self.assertEqual(
            response.data["results"][0]["authors"],
            ["Ashish Vaswani", "Noam Shazeer"],
        )
        search_mock.assert_called_once_with(
            query="transformer",
            max_results=5,
            sort_by="n",
        )

    @patch("scholar.views.run_arxiv_search")
    def test_search_rejects_invalid_parameters(self, search_mock):
        invalid_requests = (
            {"query": "", "max_results": 5, "sort_by": "r"},
            {"query": "transformer", "max_results": 16, "sort_by": "r"},
            {"query": "transformer", "max_results": 5, "sort_by": "unknown"},
        )

        for payload in invalid_requests:
            with self.subTest(payload=payload):
                response = self.client.post(
                    reverse("scholar:arxiv-search"),
                    payload,
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        search_mock.assert_not_called()

    @patch("scholar.views.run_arxiv_search")
    def test_search_returns_bad_gateway_when_service_fails(self, search_mock):
        search_mock.side_effect = RuntimeError("temporary failure")

        response = self.client.post(
            reverse("scholar:arxiv-search"),
            {"query": "transformer"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("temporary failure", response.data["detail"])


class PaperSaveAPITest(APITestCase):
    def setUp(self):
        self.payload = {
            "papers": [
                {
                    "arxiv_id": "1706.03762",
                    "title": "Attention Is All You Need",
                    "authors": ["Ashish Vaswani", "Noam Shazeer"],
                    "abstract": "Transformer abstract",
                    "pdf_url": "https://arxiv.org/pdf/1706.03762",
                }
            ],
            "extract_content": True,
        }

    @patch("scholar.views.save_papers_and_create_jobs")
    def test_save_returns_extraction_job(self, save_mock):
        paper = Paper.objects.create(
            arxiv_id="1706.03762",
            title="Attention Is All You Need",
            authors=["Ashish Vaswani", "Noam Shazeer"],
        )
        job = ProcessingJob.objects.create(
            paper=paper,
            job_type=ProcessingJob.JobType.EXTRACT,
            status=ProcessingJob.Status.PENDING,
            progress_total=1,
        )
        save_mock.return_value = ("논문을 저장했습니다.", [job])

        response = self.client.post(
            reverse("scholar:paper-save"),
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["message"], "논문을 저장했습니다.")
        self.assertEqual(response.data["jobs"][0]["id"], job.id)
        self.assertEqual(
            response.data["jobs"][0]["arxiv_id"],
            "1706.03762",
        )
        self.assertEqual(response.data["jobs"][0]["status"], "pending")
        save_mock.assert_called_once_with(
            self.payload["papers"],
            extract_content=True,
        )

    @patch("scholar.views.save_papers_and_create_jobs")
    def test_save_without_extraction_returns_no_jobs(self, save_mock):
        save_mock.return_value = ("메타데이터를 저장했습니다.", [])
        self.payload["extract_content"] = False

        response = self.client.post(
            reverse("scholar:paper-save"),
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["jobs"], [])
        save_mock.assert_called_once_with(
            self.payload["papers"],
            extract_content=False,
        )

    @patch("scholar.views.save_papers_and_create_jobs")
    def test_save_rejects_empty_or_duplicate_selection(self, save_mock):
        invalid_payloads = (
            {"papers": [], "extract_content": True},
            {
                "papers": self.payload["papers"] * 2,
                "extract_content": True,
            },
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(
                    reverse("scholar:paper-save"),
                    payload,
                    format="json",
                )
                self.assertEqual(
                    response.status_code,
                    status.HTTP_400_BAD_REQUEST,
                )

        save_mock.assert_not_called()

    @patch("scholar.views.save_papers_and_create_jobs")
    def test_save_reports_pipeline_failure(self, save_mock):
        save_mock.side_effect = RuntimeError("database unavailable")

        response = self.client.post(
            reverse("scholar:paper-save"),
            self.payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        self.assertIn("database unavailable", response.data["detail"])

    def test_processing_job_detail_returns_current_status(self):
        paper = Paper.objects.create(
            arxiv_id="2401.00001",
            title="Job status paper",
            authors=[],
        )
        job = ProcessingJob.objects.create(
            paper=paper,
            job_type=ProcessingJob.JobType.EXTRACT,
            status=ProcessingJob.Status.RUNNING,
            progress_current=0,
            progress_total=1,
        )

        response = self.client.get(
            reverse(
                "scholar:processing-job-detail",
                kwargs={"pk": job.id},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], job.id)
        self.assertEqual(response.data["arxiv_id"], "2401.00001")
        self.assertEqual(response.data["job_type"], "extract")
        self.assertEqual(response.data["status"], "running")

    def test_processing_job_detail_returns_404_for_unknown_job(self):
        response = self.client.get(
            reverse(
                "scholar:processing-job-detail",
                kwargs={"pk": 999999},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("scholar.views.enqueue_extraction_job")
    @patch("src.feature.search.ArxivSearchBot")
    def test_save_service_enqueues_missing_extraction_once(
        self,
        bot_class_mock,
        enqueue_mock,
    ):
        from .views import save_papers_and_create_jobs

        Paper.objects.create(
            arxiv_id="1706.03762",
            title="Attention Is All You Need",
            authors=["Ashish Vaswani", "Noam Shazeer"],
        )
        bot_class_mock.return_value.save_papers.return_value = "saved"

        _, first_jobs = save_papers_and_create_jobs(
            self.payload["papers"],
            extract_content=True,
        )
        _, second_jobs = save_papers_and_create_jobs(
            self.payload["papers"],
            extract_content=True,
        )

        self.assertEqual(first_jobs[0].id, second_jobs[0].id)
        self.assertEqual(first_jobs[0].status, ProcessingJob.Status.PENDING)
        enqueue_mock.assert_called_once_with(first_jobs[0].id)

    @patch("scholar.views.enqueue_extraction_job")
    @patch("src.feature.search.ArxivSearchBot")
    def test_save_service_marks_existing_sections_completed(
        self,
        bot_class_mock,
        enqueue_mock,
    ):
        from .views import save_papers_and_create_jobs

        paper = Paper.objects.create(
            arxiv_id="1706.03762",
            title="Attention Is All You Need",
            authors=["Ashish Vaswani", "Noam Shazeer"],
        )
        PaperSection.objects.create(
            paper=paper,
            section_order=1,
            section_title="Introduction",
            section_text="Body",
        )
        bot_class_mock.return_value.save_papers.return_value = "saved"

        _, jobs = save_papers_and_create_jobs(
            self.payload["papers"],
            extract_content=True,
        )

        self.assertEqual(jobs[0].status, ProcessingJob.Status.COMPLETED)
        self.assertEqual(jobs[0].progress_current, 1)
        self.assertEqual(jobs[0].progress_total, 1)
        enqueue_mock.assert_not_called()

    @patch("scholar.jobs.extract_paper_content")
    def test_extraction_worker_completes_job(self, extract_mock):
        from .jobs import _run_extraction_job

        paper = Paper.objects.create(
            arxiv_id="2501.00001",
            title="Worker test paper",
            authors=[],
        )
        job = ProcessingJob.objects.create(
            paper=paper,
            job_type=ProcessingJob.JobType.EXTRACT,
            progress_total=1,
        )

        _run_extraction_job(job.id)
        job.refresh_from_db()

        extract_mock.assert_called_once_with("2501.00001")
        self.assertEqual(job.status, ProcessingJob.Status.COMPLETED)
        self.assertEqual(job.progress_current, 1)
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.completed_at)

    @patch("scholar.jobs.extract_paper_content")
    def test_extraction_worker_records_failure(self, extract_mock):
        from .jobs import _run_extraction_job

        extract_mock.side_effect = RuntimeError("extract failed")
        paper = Paper.objects.create(
            arxiv_id="2501.00002",
            title="Worker failure paper",
            authors=[],
        )
        job = ProcessingJob.objects.create(
            paper=paper,
            job_type=ProcessingJob.JobType.EXTRACT,
            progress_total=1,
        )

        _run_extraction_job(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, ProcessingJob.Status.FAILED)
        self.assertEqual(job.error_message, "extract failed")
        self.assertIsNotNone(job.completed_at)


class DjangoPaperRepositoryTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Paper.objects.create(
            arxiv_id="1706.03762",
            title="Attention Is All You Need",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            abstract="Transformer abstract",
            pdf_url="https://arxiv.org/pdf/1706.03762",
        )
        Paper.objects.create(
            arxiv_id="2410.22997",
            title="Prompt Engineering for Service Robotics",
            authors=["Jonas Bode"],
            abstract="Robotics abstract",
            pdf_url="https://arxiv.org/pdf/2410.22997",
        )

    def test_get_papers_by_ids_preserves_order_and_normalizes_versions(self):
        from src.services.django_paper_repository import get_papers_by_ids

        papers = get_papers_by_ids(
            ["2410.22997v2", "missing-id", "1706.03762v7"]
        )

        self.assertEqual(
            [paper["id"] for paper in papers],
            ["2410.22997", "1706.03762"],
        )
        self.assertEqual(papers[1]["authors"], "Ashish Vaswani, Noam Shazeer")
        self.assertEqual(papers[1]["summary"], "Transformer abstract")
        self.assertEqual(
            papers[1]["pdf_url"],
            "https://arxiv.org/pdf/1706.03762",
        )

    def test_get_papers_by_ids_returns_empty_list_for_empty_input(self):
        from src.services.django_paper_repository import get_papers_by_ids

        self.assertEqual(get_papers_by_ids([]), [])


class PaperSummarizeAPITest(APITestCase):
    def setUp(self):
        self.paper = Paper.objects.create(
            arxiv_id="2601.00001",
            title="Summary API paper",
            authors=["Test Author"],
        )
        PaperSection.objects.create(
            paper=self.paper,
            section_order=1,
            section_title="Introduction",
            section_text="Summary source body",
        )
        self.url = reverse(
            "scholar:paper-summarize",
            kwargs={"arxiv_id": self.paper.arxiv_id},
        )

    @patch("scholar.views.enqueue_summary_job")
    def test_summarize_creates_pending_job(self, enqueue_mock):
        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        job = ProcessingJob.objects.get(pk=response.data["job"]["id"])
        self.assertEqual(job.job_type, ProcessingJob.JobType.SUMMARIZE)
        self.assertEqual(job.status, ProcessingJob.Status.PENDING)
        enqueue_mock.assert_called_once_with(job.id)

    @patch("scholar.views.enqueue_summary_job")
    def test_summarize_reuses_active_job(self, enqueue_mock):
        active_job = ProcessingJob.objects.create(
            paper=self.paper,
            job_type=ProcessingJob.JobType.SUMMARIZE,
            status=ProcessingJob.Status.RUNNING,
            progress_total=1,
        )

        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["job"]["id"], active_job.id)
        enqueue_mock.assert_not_called()

    @patch("scholar.views.enqueue_summary_job")
    def test_existing_summary_requires_force_to_regenerate(self, enqueue_mock):
        PaperSummary.objects.create(
            paper=self.paper,
            summary_text="Existing summary",
            model_name="test-model",
            section_count=1,
            chunk_count=1,
        )

        existing_response = self.client.post(self.url, {}, format="json")
        forced_response = self.client.post(
            self.url,
            {"force": True},
            format="json",
        )

        self.assertEqual(existing_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            existing_response.data["job"]["status"],
            ProcessingJob.Status.COMPLETED,
        )
        self.assertEqual(forced_response.status_code, status.HTTP_202_ACCEPTED)
        forced_job_id = forced_response.data["job"]["id"]
        enqueue_mock.assert_called_once_with(forced_job_id)

    @patch("scholar.views.enqueue_summary_job")
    def test_summarize_rejects_paper_without_sections(self, enqueue_mock):
        empty_paper = Paper.objects.create(
            arxiv_id="2601.00002",
            title="Empty paper",
            authors=[],
        )
        response = self.client.post(
            reverse(
                "scholar:paper-summarize",
                kwargs={"arxiv_id": empty_paper.arxiv_id},
            ),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        enqueue_mock.assert_not_called()

    @patch("scholar.services.summary_service.generate_paper_summary")
    def test_summary_worker_completes_job(self, generate_mock):
        from .jobs import _run_summary_job

        summary = PaperSummary.objects.create(
            paper=self.paper,
            summary_text="Generated summary",
            model_name="summary-model",
            section_count=1,
            chunk_count=1,
        )
        generate_mock.return_value = summary
        job = ProcessingJob.objects.create(
            paper=self.paper,
            job_type=ProcessingJob.JobType.SUMMARIZE,
            progress_total=1,
        )

        _run_summary_job(job.id)
        job.refresh_from_db()

        generate_mock.assert_called_once_with(self.paper)
        self.assertEqual(job.status, ProcessingJob.Status.COMPLETED)
        self.assertEqual(job.progress_current, 1)
        self.assertEqual(job.model_name, "summary-model")

    @patch("scholar.services.summary_service.generate_paper_summary")
    def test_summary_worker_records_failure(self, generate_mock):
        from .jobs import _run_summary_job

        generate_mock.side_effect = RuntimeError("summary failed")
        job = ProcessingJob.objects.create(
            paper=self.paper,
            job_type=ProcessingJob.JobType.SUMMARIZE,
            progress_total=1,
        )

        _run_summary_job(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, ProcessingJob.Status.FAILED)
        self.assertEqual(job.error_message, "summary failed")


class PaperTranslateAPITest(APITestCase):
    def setUp(self):
        self.paper = Paper.objects.create(
            arxiv_id="2602.00001",
            title="Translation API paper",
            authors=["Test Author"],
        )
        self.summary = PaperSummary.objects.create(
            paper=self.paper,
            summary_text="English summary",
            model_name="summary-model",
            section_count=1,
            chunk_count=1,
        )
        self.url = reverse(
            "scholar:paper-translate",
            kwargs={"arxiv_id": self.paper.arxiv_id},
        )

    @patch("scholar.views.enqueue_translation_job")
    def test_translate_creates_pending_job(self, enqueue_mock):
        response = self.client.post(
            self.url,
            {"target_language": "ko"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        job = ProcessingJob.objects.get(pk=response.data["job"]["id"])
        self.assertEqual(job.job_type, ProcessingJob.JobType.TRANSLATE)
        self.assertEqual(job.status, ProcessingJob.Status.PENDING)
        enqueue_mock.assert_called_once_with(job.id)

    @patch("scholar.views.enqueue_translation_job")
    def test_translate_reuses_active_job(self, enqueue_mock):
        active_job = ProcessingJob.objects.create(
            paper=self.paper,
            job_type=ProcessingJob.JobType.TRANSLATE,
            status=ProcessingJob.Status.RUNNING,
            progress_total=1,
        )

        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["job"]["id"], active_job.id)
        enqueue_mock.assert_not_called()

    @patch("scholar.views.enqueue_translation_job")
    def test_existing_translation_requires_force_to_regenerate(self, enqueue_mock):
        Translation.objects.create(
            paper=self.paper,
            summary=self.summary,
            translation_type=Translation.TranslationType.SUMMARY,
            source_text="English summary",
            translated_text="한국어 요약",
            target_language="ko",
            model_name="translation-model",
            chunk_count=1,
        )

        existing_response = self.client.post(self.url, {}, format="json")
        forced_response = self.client.post(
            self.url,
            {"force": True},
            format="json",
        )

        self.assertEqual(existing_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            existing_response.data["job"]["status"],
            ProcessingJob.Status.COMPLETED,
        )
        self.assertEqual(forced_response.status_code, status.HTTP_202_ACCEPTED)
        enqueue_mock.assert_called_once_with(forced_response.data["job"]["id"])

    @patch("scholar.views.enqueue_translation_job")
    def test_translate_requires_summary_and_supported_language(self, enqueue_mock):
        self.summary.delete()
        missing_response = self.client.post(self.url, {}, format="json")
        invalid_response = self.client.post(
            self.url,
            {"target_language": "ja"},
            format="json",
        )

        self.assertEqual(missing_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(invalid_response.status_code, status.HTTP_400_BAD_REQUEST)
        enqueue_mock.assert_not_called()

    @patch("scholar.services.translation_service.generate_summary_translation")
    def test_translation_worker_completes_job(self, generate_mock):
        from .jobs import _run_translation_job

        translation = Translation.objects.create(
            paper=self.paper,
            summary=self.summary,
            translation_type=Translation.TranslationType.SUMMARY,
            source_text="English summary",
            translated_text="한국어 요약",
            target_language="ko",
            model_name="translation-model",
            chunk_count=1,
        )
        generate_mock.return_value = translation
        job = ProcessingJob.objects.create(
            paper=self.paper,
            job_type=ProcessingJob.JobType.TRANSLATE,
            progress_total=1,
        )

        _run_translation_job(job.id)
        job.refresh_from_db()

        generate_mock.assert_called_once_with(self.paper)
        self.assertEqual(job.status, ProcessingJob.Status.COMPLETED)
        self.assertEqual(job.progress_current, 1)
        self.assertEqual(job.model_name, "translation-model")

    @patch("scholar.services.translation_service.generate_summary_translation")
    def test_translation_worker_records_failure(self, generate_mock):
        from .jobs import _run_translation_job

        generate_mock.side_effect = RuntimeError("translation failed")
        job = ProcessingJob.objects.create(
            paper=self.paper,
            job_type=ProcessingJob.JobType.TRANSLATE,
            progress_total=1,
        )

        _run_translation_job(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, ProcessingJob.Status.FAILED)
        self.assertEqual(job.error_message, "translation failed")


class PaperQuestionAPITest(APITestCase):
    def setUp(self):
        self.paper = Paper.objects.create(
            arxiv_id="2603.00001",
            title="RAG API paper",
            authors=["Test Author"],
            abstract="Paper abstract",
        )
        PaperSection.objects.create(
            paper=self.paper,
            section_order=1,
            section_title="Method",
            section_text="The paper uses retrieval augmented generation.",
        )
        self.url = reverse(
            "scholar:paper-question",
            kwargs={"arxiv_id": self.paper.arxiv_id},
        )

    @patch("scholar.services.rag_service.answer_paper_question")
    def test_question_returns_answer_and_sources(self, answer_mock):
        answer_mock.return_value = {
            "arxiv_id": self.paper.arxiv_id,
            "question": "어떤 방법을 사용했나요?",
            "answer": "검색 증강 생성을 사용했습니다.",
            "sources": [{"index": 1, "text": "Method evidence"}],
            "model": "test-model",
        }

        response = self.client.post(
            self.url,
            {"question": "어떤 방법을 사용했나요?"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["answer"], "검색 증강 생성을 사용했습니다.")
        self.assertEqual(response.data["sources"][0]["index"], 1)
        answer_mock.assert_called_once()
        called_paper, called_question = answer_mock.call_args.args
        self.assertEqual(called_paper.id, self.paper.id)
        self.assertEqual(called_question, "어떤 방법을 사용했나요?")

    @patch("scholar.services.rag_service.answer_paper_question")
    def test_question_validates_input_and_requires_sections(self, answer_mock):
        invalid_response = self.client.post(
            self.url,
            {"question": " "},
            format="json",
        )
        empty_paper = Paper.objects.create(
            arxiv_id="2603.00002",
            title="Empty RAG paper",
            authors=[],
        )
        empty_response = self.client.post(
            reverse(
                "scholar:paper-question",
                kwargs={"arxiv_id": empty_paper.arxiv_id},
            ),
            {"question": "이 논문은 무엇인가요?"},
            format="json",
        )

        self.assertEqual(invalid_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(empty_response.status_code, status.HTTP_409_CONFLICT)
        answer_mock.assert_not_called()

    @patch("scholar.services.rag_service.answer_paper_question")
    def test_question_reports_answer_service_failure(self, answer_mock):
        answer_mock.side_effect = RuntimeError("model unavailable")

        response = self.client.post(
            self.url,
            {"question": "핵심 결과는 무엇인가요?"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("model unavailable", response.data["detail"])

    def test_rag_service_builds_mysql_context_and_normalizes_sources(self):
        from .services.rag_service import answer_paper_question

        class FakeAnswerer:
            def __init__(self):
                self.paper = None

            def answer(self, paper, _question):
                self.paper = paper
                return {
                    "answer": "Grounded answer",
                    "sources": ["First source", "Second source"],
                    "model": "fake-model",
                }

        answerer = FakeAnswerer()
        result = answer_paper_question(
            self.paper,
            "What method is used?",
            answerer=answerer,
        )

        self.assertEqual(answerer.paper["id"], self.paper.arxiv_id)
        self.assertIn("retrieval augmented", answerer.paper["method"])
        self.assertEqual(result["sources"][1]["index"], 2)
        self.assertEqual(result["model"], "fake-model")
