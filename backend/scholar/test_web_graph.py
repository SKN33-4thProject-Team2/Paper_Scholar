from uuid import uuid4
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase
from .models import SupervisorRun, LibraryEntry, Paper
from .web_graph import run_web_graph
from .supervisor_service import SupervisorPlanner


class WebGraphTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='graph-user')
        self.thread = str(uuid4())
        self.papers = [dict(arxiv_id=f'1234.0000{i}', title=f'Paper {i}', authors=[], abstract='', pdf_url='') for i in (1, 2)]

    def run_turn(self, text):
        run = SupervisorRun.objects.create(user=self.user, thread_id=self.thread, query=text, status='running')
        with patch.object(SupervisorPlanner, '_parse_intent', side_effect=SupervisorPlanner._fallback_intent):
            result = run_web_graph(run)
        run.status = 'completed'
        run.save(update_fields=['status'])
        return result

    @patch('scholar.views.search_with_keywords')
    def test_real_graph_search_and_followup_survive_new_graph(self, search):
        search.return_value = self.papers
        result = self.run_turn('대용량 언어 모델에 관한 모델 찾아줘')
        self.assertIn('search', result['node_history'])
        self.assertEqual(search.call_args.args[0], ['large language model', 'LLM'])
        self.assertFalse(LibraryEntry.objects.exists())
        result = self.run_turn('두 번째 논문 저장해줘')
        self.assertNotIn('search', result['node_history'])
        self.assertEqual(result['paper_ids'], ['1234.00002'])
        self.assertEqual(LibraryEntry.objects.get().paper.arxiv_id, '1234.00002')
        self.assertEqual(search.call_count, 1)

    @patch('scholar.views.search_with_keywords')
    def test_other_user_cannot_reuse_conversation_context(self, search):
        search.return_value = self.papers
        self.run_turn('LLM 논문 2편 찾아줘')
        self.user = get_user_model().objects.create_user(username='other')
        result = self.run_turn('두 번째 논문 저장해줘')
        self.assertTrue(result['human_input_required'])
        self.assertFalse(LibraryEntry.objects.exists())

    @patch('scholar.views.search_with_keywords')
    def test_missing_rank_asks_without_running_tools(self, search):
        result = self.run_turn('두 번째 논문 요약해줘')
        self.assertTrue(result['human_input_required'])
        search.assert_not_called()


class SupervisorRunAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='api-user')
        self.client.force_authenticate(self.user)

    @patch('scholar.jobs.enqueue_supervisor_run')
    def test_submit_poll_and_reject_concurrent_run(self, enqueue):
        response = self.client.post('/api/supervisor/runs/', {'message': 'RAG 관련 검색'})
        self.assertEqual(response.status_code, 202)
        run_id = response.data['id']
        self.assertEqual(self.client.get(f'/api/supervisor/runs/{run_id}/').status_code, 200)
        self.assertEqual(self.client.post('/api/supervisor/runs/', {'message': 'LLM 관련 검색'}).status_code, 409)
        other = get_user_model().objects.create_user(username='other')
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(f'/api/supervisor/runs/{run_id}/').status_code, 404)
        self.assertEqual(self.client.get('/api/supervisor/runs/').data, [])
