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


class SearchEntryPointTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(get_user_model().objects.create_user(username='search-user'))

    @patch('src.feature.search.ArxivSearchBot')
    def test_plain_search_normalizes_korean_and_preserves_versions(self, bot):
        bot.return_value.search_papers.return_value = []
        cases = {
            '대용량 언어 모델에 관한 모델 찾아줘': 'large language model',
            'LLM에 관한 논문 찾아줘': 'large language model',
            'RAG 관련 검색': 'retrieval augmented generation',
            '반도체 관련 검색': 'semiconductor',
            'GPT-4 관련 검색': 'GPT-4',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                response = self.client.post('/api/search/', {'query': text}, format='json')
                self.assertEqual(response.status_code, 200)
                query = bot.return_value.search_papers.call_args.kwargs['final_query']
                self.assertIn(expected, query)
                self.assertNotIn('관련', query)
                self.assertNotIn('찾아', query)

    @patch('src.services.search_intent._keyword_model', side_effect=RuntimeError('offline'))
    def test_failed_conversion_returns_actionable_error(self, model):
        response = self.client.post('/api/search/', {'query': '미지의 한국어 연구 주제 관련 검색'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('변환하지 못했습니다', response.data['detail'])


class WebPipelineTests(TestCase):
    setUp = WebGraphTests.setUp
    run_turn = WebGraphTests.run_turn

    @patch('scholar.services.translation_service.generate_summary_translation')
    @patch('scholar.services.summary_service.generate_paper_summary')
    @patch('scholar.jobs.extract_paper_content')
    @patch('scholar.views.search_with_keywords')
    def test_search_summary_then_contextual_translation(self, search, extract, summarize, translate):
        from .models import PaperSection, PaperSummary
        search.return_value = self.papers

        def extracted(arxiv_id):
            paper = Paper.objects.get(arxiv_id=arxiv_id)
            PaperSection.objects.create(paper=paper, section_order=1, section_title='Body', section_text='body')
            return 1

        def summarized(paper):
            return PaperSummary.objects.create(paper=paper, summary_text='summary')

        extract.side_effect = extracted
        summarize.side_effect = summarized
        self.run_turn('LLM 관련 논문 2편 찾아줘')
        result = self.run_turn('두 번째 논문 요약해줘')
        self.assertFalse(result.get('errors'))
        extract.assert_called_once_with('1234.00002')
        self.assertEqual(summarize.call_count, 1)
        result = self.run_turn('그거 번역해줘')
        self.assertFalse(result.get('errors'))
        self.assertIn('번역', result['response'])
        translate.assert_called_once()
        self.assertEqual(translate.call_args.args[0].arxiv_id, '1234.00002')
        # Existing extraction and summary are reused on the next turn.
        self.assertEqual(extract.call_count, 1)
        self.assertEqual(summarize.call_count, 1)
        self.assertEqual(search.call_count, 1)
