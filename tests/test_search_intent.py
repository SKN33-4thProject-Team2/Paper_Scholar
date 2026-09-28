import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.services.search_intent import (
    SearchIntentError, build_search_query, extract_topic, search_keywords,
)


class SearchIntentTests(unittest.TestCase):
    def test_korean_variants_share_academic_terms(self):
        for text in ('대용량 언어 모델에 관한 모델 찾아줘', '대규모 언어 모델 관련 논문 찾아줘',
                     'LLM에 관한 논문 찾아줘'):
            with self.subTest(text=text):
                self.assertEqual(search_keywords(text), ['large language model', 'LLM'])

    def test_preserves_scientific_terms(self):
        for text, topic in [('RAG 관련 검색', 'RAG'), ('반도체 관련 검색', '반도체'),
                            ('GPT-4 관련 검색', 'GPT-4'),
                            ('검색 증강 생성 관련 논문 찾아줘', '검색 증강 생성'),
                            ('상관관계 분석', '상관관계 분석')]:
            with self.subTest(text=text):
                self.assertEqual(extract_topic(text), topic)

    def test_unknown_korean_topic_uses_model_and_keeps_qualifiers(self):
        model = Mock()
        model.invoke.return_value = SimpleNamespace(keywords=['large language model compression'])
        self.assertEqual(search_keywords('대규모 언어 모델 압축 관련 논문 찾아줘', model=model),
                         ['large language model compression'])
        self.assertIn('압축', model.invoke.call_args.args[0])

    def test_failure_never_searches_the_original_sentence(self):
        model = Mock()
        model.invoke.side_effect = RuntimeError('offline')
        with self.assertRaises(SearchIntentError):
            search_keywords('새로운 한국어 주제 관련 논문 찾아줘', model=model)

    def test_rejects_untranslated_or_instruction_output(self):
        for terms in [['관련 논문'], ['papers related to LLM'], []]:
            with self.subTest(terms=terms):
                model = Mock()
                model.invoke.return_value = SimpleNamespace(keywords=terms)
                with self.assertRaises(SearchIntentError):
                    search_keywords('새 주제', model=model)

    def test_known_topics_work_without_api(self):
        with patch('src.services.search_intent._keyword_model', side_effect=AssertionError):
            self.assertEqual(search_keywords('GPT-4 관련 검색'), ['GPT-4'])
            self.assertEqual(search_keywords('반도체 관련 검색'), ['semiconductor'])

    def test_title_and_abstract_query(self):
        self.assertEqual(build_search_query(['GPT-4']), '(ti:"GPT-4" OR abs:"GPT-4")')
