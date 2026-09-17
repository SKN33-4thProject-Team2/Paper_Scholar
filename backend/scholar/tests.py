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

    def test_list_papers_returns_paginated_mysql_shape(self):
        response = self.client.get(reverse("scholar:paper-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        paper = response.data["results"][0]
        self.assertEqual(paper["arxiv_id"], "1702.01806")
        self.assertEqual(paper["section_count"], 1)
        self.assertEqual(paper["translation_count"], 1)
        self.assertTrue(paper["has_summary"])

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
