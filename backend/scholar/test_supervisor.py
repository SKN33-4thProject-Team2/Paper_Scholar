from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .supervisor_service import SupervisorPlan, SupervisorPlanner


User = get_user_model()


class SupervisorPlannerTest(APITestCase):
    def test_fallback_builds_existing_feature_pipeline(self):
        planner = SupervisorPlanner(llm=object())

        plan = planner.plan(
            "RAG 논문 하나와 비슷한 논문 3개도 찾아서 번역 요약하고 내서재에 저장해줘"
        )

        self.assertEqual(plan.query, "RAG")
        self.assertEqual(plan.max_results, 4)
        self.assertEqual(plan.related_count, 3)
        self.assertEqual(
            plan.actions,
            ["search", "save", "extract", "summarize", "translate"],
        )

    def test_ambiguous_topic_requests_clarification(self):
        planner = SupervisorPlanner(llm=object())

        plan = planner.plan("무슨 논문 조회하고 비슷한 것 3개도 저장해줘")

        self.assertTrue(plan.needs_clarification)
        self.assertIn("어떤 주제", plan.clarification_question)


class SupervisorPlanAPITest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="supervisor-user",
            password="StrongPass!2468",
        )
        self.url = reverse("scholar:supervisor-plan")

    def test_authentication_is_required(self):
        response = self.client.post(self.url, {"message": "RAG 논문 찾아줘"})

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_blank_or_one_character_message_is_rejected(self):
        self.client.force_authenticate(self.user)

        for message in ("", "R"):
            with self.subTest(message=message):
                response = self.client.post(
                    self.url,
                    {"message": message},
                    format="json",
                )

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("scholar.supervisor_views.SupervisorPlanner.plan")
    def test_authenticated_user_receives_validated_plan(self, plan_mock):
        plan_mock.return_value = SupervisorPlan(
            query="retrieval augmented generation",
            max_results=4,
            related_count=3,
            actions=["search", "save", "extract", "summarize", "translate"],
            save_to_library=True,
            extract_content=True,
            summarize=True,
            translate=True,
        )
        self.client.force_authenticate(self.user)

        response = self.client.post(
            self.url,
            {"message": "RAG 논문과 비슷한 논문 3개를 요약 번역해서 저장해줘"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["max_results"], 4)
        self.assertEqual(response.data["actions"][-2:], ["summarize", "translate"])
