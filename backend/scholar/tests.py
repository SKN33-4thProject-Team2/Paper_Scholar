from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from .models import (
    LibraryEntry,
    Paper,
    PaperSection,
    PaperSummary,
    ProcessingJob,
    Translation,
)


User = get_user_model()


class TranslationMarkupFallbackTest(SimpleTestCase):
    def test_translation_falls_back_to_piecewise_text_when_tokens_are_lost(self):
        from .services.translation_service import translate_chunk_preserving_markup

        class TokenDroppingService:
            def translate(self, prompt):
                if "__APRAG_PROTECTED_000001__" in prompt:
                    return "보호 토큰을 누락한 번역"
                return "번역된 텍스트"

        translated = translate_chunk_preserving_markup(
            TokenDroppingService(),
            r"Before \(x + y\) after.",
        )

        self.assertIn(r"\(x + y\)", translated)
        self.assertNotIn("__APRAG_PROTECTED_", translated)
        self.assertGreaterEqual(translated.count("번역된 텍스트"), 2)


class SummaryProviderFallbackTest(SimpleTestCase):
    def test_retryable_nvidia_error_falls_back_to_single_call_ollama(self):
        from .services.summary_service import generate_paper_summary

        nvidia_tool = Mock()
        nvidia_tool.summarize.side_effect = RuntimeError(
            'NVIDIA API 오류 503: {"error":{"message":"Service temporarily overloaded"}}'
        )
        ollama_tool = Mock()
        ollama_tool.summarize.return_value = SimpleNamespace(model="qwen2.5:3b")
        stored_summary = Mock(model_name="qwen2.5:3b")
        paper = SimpleNamespace(arxiv_id="1504.03867", title="Example paper")

        with (
            patch(
                "src.tools.summary_tool_v2.SummaryTool",
                side_effect=(nvidia_tool, ollama_tool),
            ) as summary_tool_class,
            patch(
                "scholar.services.summary_service.PaperSummary.objects.get",
                return_value=stored_summary,
            ),
        ):
            result = generate_paper_summary(paper)

        self.assertIs(result, stored_summary)
        self.assertEqual(
            summary_tool_class.call_args_list,
            [
                call(single_call=True),
                call(provider="ollama", model="qwen2.5:3b", single_call=True),
            ],
        )
        nvidia_tool.summarize.assert_called_once_with(
            "1504.03867", title="Example paper"
        )
        ollama_tool.summarize.assert_called_once_with(
            "1504.03867", title="Example paper"
        )

    def test_non_retryable_nvidia_error_is_not_hidden(self):
        from .services.summary_service import generate_paper_summary

        nvidia_tool = Mock()
        nvidia_tool.summarize.side_effect = RuntimeError("NVIDIA API 오류 401")
        paper = SimpleNamespace(arxiv_id="1504.03867", title="Example paper")

        with patch(
            "src.tools.summary_tool_v2.SummaryTool",
            return_value=nvidia_tool,
        ) as summary_tool_class:
            with self.assertRaisesRegex(RuntimeError, "401"):
                generate_paper_summary(paper)

        summary_tool_class.assert_called_once_with(single_call=True)


class AuthenticationAPITest(APITestCase):
    def setUp(self):
        self.registration = {
            "username": "paper-reader",
            "email": "reader@example.com",
            "password": "StrongPass!2468",
            "password_confirm": "StrongPass!2468",
        }

    def test_register_login_refresh_and_current_user(self):
        register_response = self.client.post(
            reverse("scholar:auth-register"),
            self.registration,
            format="json",
        )
        token_response = self.client.post(
            reverse("scholar:auth-token"),
            {
                "username": self.registration["username"],
                "password": self.registration["password"],
            },
            format="json",
        )

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token_response.data['access']}"
        )
        me_response = self.client.get(reverse("scholar:auth-me"))
        refresh_response = self.client.post(
            reverse("scholar:auth-token-refresh"),
            {"refresh": token_response.data["refresh"]},
            format="json",
        )

        self.assertEqual(register_response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("password", register_response.data)
        self.assertEqual(token_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.data["username"], "paper-reader")
        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh_response.data)

    def test_registration_rejects_duplicate_identity_and_password_mismatch(self):
        self.client.post(
            reverse("scholar:auth-register"),
            self.registration,
            format="json",
        )
        duplicate_response = self.client.post(
            reverse("scholar:auth-register"),
            self.registration,
            format="json",
        )
        mismatch_response = self.client.post(
            reverse("scholar:auth-register"),
            {
                **self.registration,
                "username": "another-reader",
                "email": "another@example.com",
                "password_confirm": "DifferentPass!2468",
            },
            format="json",
        )

        self.assertEqual(duplicate_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", duplicate_response.data)
        self.assertIn("email", duplicate_response.data)
        self.assertEqual(mismatch_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password_confirm", mismatch_response.data)

    def test_current_user_requires_authentication(self):
        response = self.client.get(reverse("scholar:auth-me"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AuthenticatedAPITestCase(APITestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            username="authenticated-test-user",
            password="StrongPass!2468",
        )
        self.client.force_authenticate(self.user)
        for paper in Paper.objects.all():
            LibraryEntry.objects.get_or_create(user=self.user, paper=paper)

    def add_to_library(self, paper):
        LibraryEntry.objects.get_or_create(user=self.user, paper=paper)
        return paper


class PaperAPITest(AuthenticatedAPITestCase):
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
        cls.legacy_paper = Paper.objects.create(
            arxiv_id="hep-ex/0306056",
            title="Legacy arXiv paper",
            authors=["Test Author"],
        )
        PaperSection.objects.create(
            paper=cls.legacy_paper,
            section_order=1,
            section_title="Introduction",
            section_text="Legacy paper body",
        )

    def test_list_papers_returns_paginated_mysql_shape(self):
        response = self.client.get(reverse("scholar:paper-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)
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

    def test_detail_accepts_legacy_arxiv_id_with_slash(self):
        response = self.client.get(
            reverse(
                "scholar:paper-detail",
                kwargs={"arxiv_id": self.legacy_paper.arxiv_id},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["arxiv_id"], "hep-ex/0306056")

    def test_child_route_accepts_legacy_arxiv_id_with_slash(self):
        response = self.client.get(
            reverse(
                "scholar:paper-sections",
                kwargs={"arxiv_id": self.legacy_paper.arxiv_id},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["section_text"], "Legacy paper body")

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


class ArxivSearchAPITest(AuthenticatedAPITestCase):
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


class PaperSaveAPITest(AuthenticatedAPITestCase):
    def setUp(self):
        super().setUp()
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
            user=self.user,
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
            user=self.user,
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
        self.add_to_library(paper)

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
            user=self.user,
        )
        _, second_jobs = save_papers_and_create_jobs(
            self.payload["papers"],
            extract_content=True,
            user=self.user,
        )

        self.assertEqual(first_jobs[0].id, second_jobs[0].id)
        self.assertEqual(first_jobs[0].status, ProcessingJob.Status.PENDING)
        self.assertEqual(first_jobs[0].user, self.user)
        self.assertTrue(
            LibraryEntry.objects.filter(user=self.user, paper__arxiv_id="1706.03762").exists()
        )
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
            user=self.user,
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


class DjangoPaperRepositoryTest(AuthenticatedAPITestCase):
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


class PaperSummarizeAPITest(AuthenticatedAPITestCase):
    def setUp(self):
        super().setUp()
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
        self.add_to_library(self.paper)
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
        self.add_to_library(empty_paper)
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


class PaperTranslateAPITest(AuthenticatedAPITestCase):
    def setUp(self):
        super().setUp()
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
        self.add_to_library(self.paper)
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


class PaperQuestionAPITest(AuthenticatedAPITestCase):
    def setUp(self):
        super().setUp()
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
        self.add_to_library(self.paper)
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
        self.add_to_library(empty_paper)
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


class PersonalLibraryAPITest(APITestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            username="reader-a",
            password="StrongPass!2468",
        )
        self.user_b = User.objects.create_user(
            username="reader-b",
            password="StrongPass!2468",
        )
        self.shared_paper = Paper.objects.create(
            arxiv_id="2605.00001",
            title="Shared artifact paper",
            authors=["Shared Author"],
        )
        self.private_paper = Paper.objects.create(
            arxiv_id="2605.00002",
            title="Reader A paper",
            authors=["Private Author"],
        )
        PaperSection.objects.create(
            paper=self.shared_paper,
            section_order=1,
            section_title="Method",
            section_text="Shared section",
        )
        PaperSummary.objects.create(
            paper=self.shared_paper,
            summary_text="Shared summary",
            model_name="test-model",
        )
        LibraryEntry.objects.create(user=self.user_a, paper=self.shared_paper)
        LibraryEntry.objects.create(user=self.user_b, paper=self.shared_paper)
        LibraryEntry.objects.create(user=self.user_a, paper=self.private_paper)

    def test_anonymous_user_cannot_access_library_or_search(self):
        list_response = self.client.get(reverse("scholar:paper-list"))
        search_response = self.client.post(
            reverse("scholar:arxiv-search"),
            {"query": "transformer"},
            format="json",
        )

        self.assertEqual(list_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(search_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_each_user_sees_only_their_library(self):
        self.client.force_authenticate(self.user_a)
        user_a_response = self.client.get(reverse("scholar:paper-list"))
        self.client.force_authenticate(self.user_b)
        user_b_response = self.client.get(reverse("scholar:paper-list"))

        self.assertEqual(user_a_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {paper["arxiv_id"] for paper in user_a_response.data["results"]},
            {self.shared_paper.arxiv_id, self.private_paper.arxiv_id},
        )
        self.assertEqual(
            [paper["arxiv_id"] for paper in user_b_response.data["results"]],
            [self.shared_paper.arxiv_id],
        )

    def test_artifacts_are_shared_only_with_library_members(self):
        summary_url = reverse(
            "scholar:paper-summary",
            kwargs={"arxiv_id": self.shared_paper.arxiv_id},
        )
        private_detail_url = reverse(
            "scholar:paper-detail",
            kwargs={"arxiv_id": self.private_paper.arxiv_id},
        )

        self.client.force_authenticate(self.user_b)
        shared_summary_response = self.client.get(summary_url)
        private_detail_response = self.client.get(private_detail_url)

        self.assertEqual(shared_summary_response.status_code, status.HTTP_200_OK)
        self.assertEqual(shared_summary_response.data["summary_text"], "Shared summary")
        self.assertEqual(private_detail_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_job_status_requires_membership_in_the_paper(self):
        job = ProcessingJob.objects.create(
            user=self.user_a,
            paper=self.private_paper,
            job_type=ProcessingJob.JobType.EXTRACT,
            status=ProcessingJob.Status.RUNNING,
        )
        url = reverse("scholar:processing-job-detail", kwargs={"pk": job.id})

        self.client.force_authenticate(self.user_b)
        denied_response = self.client.get(url)
        self.client.force_authenticate(self.user_a)
        allowed_response = self.client.get(url)

        self.assertEqual(denied_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(allowed_response.status_code, status.HTTP_200_OK)


class PaperWorkflowIntegrationTest(AuthenticatedAPITestCase):
    @patch("scholar.services.rag_service.answer_paper_question")
    @patch("scholar.views.enqueue_translation_job")
    @patch("scholar.views.enqueue_summary_job")
    def test_artifact_generation_and_question_workflow(
        self,
        summary_enqueue_mock,
        translation_enqueue_mock,
        answer_mock,
    ):
        paper = Paper.objects.create(
            arxiv_id="2604.00001",
            title="Integrated workflow paper",
            authors=["Workflow Author"],
            abstract="Workflow abstract",
        )
        PaperSection.objects.create(
            paper=paper,
            section_order=1,
            section_title="Method",
            section_text="Grounded workflow evidence.",
        )
        self.add_to_library(paper)

        detail_response = self.client.get(
            reverse(
                "scholar:paper-detail",
                kwargs={"arxiv_id": paper.arxiv_id},
            )
        )
        summarize_response = self.client.post(
            reverse(
                "scholar:paper-summarize",
                kwargs={"arxiv_id": paper.arxiv_id},
            ),
            {},
            format="json",
        )
        summary = PaperSummary.objects.create(
            paper=paper,
            summary_text="Integrated summary",
            model_name="summary-model",
            section_count=1,
            chunk_count=1,
        )
        summary_response = self.client.get(
            reverse(
                "scholar:paper-summary",
                kwargs={"arxiv_id": paper.arxiv_id},
            )
        )
        translate_response = self.client.post(
            reverse(
                "scholar:paper-translate",
                kwargs={"arxiv_id": paper.arxiv_id},
            ),
            {"target_language": "ko"},
            format="json",
        )
        Translation.objects.create(
            paper=paper,
            summary=summary,
            source_text=summary.summary_text,
            translated_text="통합 요약",
            target_language="ko",
        )
        translations_response = self.client.get(
            reverse(
                "scholar:paper-translations",
                kwargs={"arxiv_id": paper.arxiv_id},
            )
        )
        answer_mock.return_value = {
            "arxiv_id": paper.arxiv_id,
            "question": "핵심 근거는 무엇인가요?",
            "answer": "본문 근거를 사용합니다.",
            "sources": [{"index": 1, "text": "Grounded workflow evidence."}],
            "model": "rag-model",
        }
        question_response = self.client.post(
            reverse(
                "scholar:paper-question",
                kwargs={"arxiv_id": paper.arxiv_id},
            ),
            {"question": "핵심 근거는 무엇인가요?"},
            format="json",
        )

        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data["section_count"], 1)
        self.assertEqual(summarize_response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(summary_response.data["summary_text"], "Integrated summary")
        self.assertEqual(translate_response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(translations_response.data[0]["translated_text"], "통합 요약")
        self.assertEqual(question_response.status_code, status.HTTP_200_OK)
        self.assertEqual(question_response.data["sources"][0]["index"], 1)
        summary_enqueue_mock.assert_called_once()
        translation_enqueue_mock.assert_called_once()
        answer_mock.assert_called_once()
