from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import SupervisorRun
from .supervisor_service import build_plan


class SupervisorPlanServiceTest(APITestCase):
    """계획 수립은 LangGraph Supervisor 라우팅이 담당한다."""

    def test_multi_stage_request_plans_every_needed_agent(self):
        plan = build_plan("RAG 논문 3편 찾아서 요약하고 번역해줘")

        self.assertFalse(plan["needs_clarification"])
        self.assertEqual(
            plan["actions"],
            ["keyword", "search", "download", "summarize", "translate"],
        )
        self.assertEqual(plan["steps"][0]["name"], "검색 키워드 생성")

    def test_search_and_save_request_includes_download(self):
        plan = build_plan("논문 3편 찾아서 저장해줘")

        self.assertIn("download", plan["actions"])

    def test_ambiguous_request_asks_back_instead_of_running(self):
        plan = build_plan("요약해줘")

        self.assertTrue(plan["needs_clarification"])
        self.assertEqual(plan["actions"], ["human"])
        self.assertTrue(plan["clarification_question"])


class SupervisorPlanAPITest(APITestCase):
    def test_plan_endpoint_returns_routed_actions(self):
        response = self.client.post(
            reverse("scholar:supervisor-plan"),
            {"query": "RAG 논문 3편 찾아서 요약하고 번역해줘"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("summarize", response.data["actions"])

    def test_plan_endpoint_rejects_blank_query(self):
        response = self.client.post(
            reverse("scholar:supervisor-plan"), {"query": ""}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SupervisorRunAPITest(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="runner", password="Test1234!"
        )
        self.client.force_authenticate(self.user)

    @patch("scholar.supervisor_views.enqueue_supervisor_run")
    def test_run_creates_record_and_enqueues_graph(self, enqueue_mock):
        response = self.client.post(
            reverse("scholar:supervisor-run"),
            {"query": "RAG 논문 3편 찾아서 요약하고 번역해줘"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        run = SupervisorRun.objects.get(pk=response.data["id"])
        self.assertEqual(run.user, self.user)
        self.assertEqual(run.status, SupervisorRun.Status.PENDING)
        self.assertTrue(run.thread_id)
        enqueue_mock.assert_called_once_with(run.id)

    @patch("scholar.supervisor_views.enqueue_supervisor_run")
    def test_ambiguous_request_does_not_run_the_graph(self, enqueue_mock):
        response = self.client.post(
            reverse("scholar:supervisor-run"), {"query": "요약해줘"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["status"], SupervisorRun.Status.NEEDS_INPUT)
        self.assertTrue(response.data["response"])
        enqueue_mock.assert_not_called()

    def test_run_requires_authentication(self):
        self.client.force_authenticate(None)

        response = self.client.post(
            reverse("scholar:supervisor-run"), {"query": "논문 찾아줘"}, format="json"
        )

        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_run_detail_is_scoped_to_its_owner(self):
        other = get_user_model().objects.create_user(
            username="other", password="Test1234!"
        )
        run = SupervisorRun.objects.create(
            user=other, thread_id="t-1", query="논문 찾아줘"
        )

        response = self.client.get(
            reverse("scholar:supervisor-run-detail", args=[run.id])
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
