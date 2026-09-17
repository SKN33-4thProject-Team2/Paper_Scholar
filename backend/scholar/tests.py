from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Paper, PaperSection, PaperSummary, Translation


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
