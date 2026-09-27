"""User-scoped Django adapters for the existing Supervisor StateGraph.

Only JSON conversation context is persisted. Each turn gets a fresh graph;
no process-local checkpoint can mix users or disappear across web workers.
"""
from __future__ import annotations

import re

from .models import LibraryEntry, Paper, PaperSummary, Translation
from .supervisor_service import SupervisorPlanner


class WebRouter:
    def decide(self, state):
        from orchestration.routing import SupervisorDecision
        query = state['query']
        candidates = state.get('selection_candidates', [])
        ordinal = re.search(r'(\d+)\s*번', query)
        words = re.search(r'(첫|두|세|네|다섯)\s*번째', query)
        rank = int(ordinal.group(1)) if ordinal else (
            {'첫': 1, '두': 2, '세': 3, '네': 4, '다섯': 5}[words.group(1)] if words else 0
        )
        reference = rank or any(x in query for x in ('이 논문', '그 논문', '방금', '그거', '이거', '찾은'))
        action = any(x in query for x in ('요약', '번역', '저장', '추출'))
        # Action-only turns may use an explicitly selected prior target.
        action_only = re.fullmatch(r'\s*(?:요약|번역|저장|추출)(?:해줘|해주세요)?[.!?]?\s*', query)
        if reference or action_only:
            ids = list(state.get('paper_ids', []))
            if rank:
                ids = [candidates[rank - 1]['arxiv_id']] if 1 <= rank <= len(candidates) else []
            elif not ids and len(candidates) == 1:
                ids = [candidates[0]['arxiv_id']]
            if not ids or not action:
                return SupervisorDecision(steps=['human'], reason='대상 확인',
                    human_question='검색 결과의 논문 번호와 원하는 작업을 알려주세요. 예: 두 번째 논문 요약해줘')
            steps = ['download']  # Idempotently attach the selected paper to this user's library.
            if '추출' in query:
                steps.append('extract')
            if '요약' in query:
                steps.append('summarize')
            if '번역' in query:
                steps.append('translate')
            return SupervisorDecision(steps=steps, reason='이전 결과에 대한 후속 작업', selected_paper_ids=ids)
        plan = SupervisorPlanner().plan(query)
        if plan.needs_clarification:
            return SupervisorDecision(steps=['human'], reason='주제 확인', human_question=plan.clarification_question)
        steps = ['keyword', 'search']
        if plan.save_to_library:
            steps.append('download')
        if plan.summarize:
            steps.append('summarize')
        if plan.translate:
            steps.append('translate')
        return SupervisorDecision(steps=steps, reason='검색 요청 실행', search_result_limit=plan.max_results)


def run_web_graph(run):
    from orchestration.graph import build_graph
    from orchestration.state import initial_state
    from src.services.search_intent import search_keywords
    from .models import SupervisorRun

    previous = SupervisorRun.objects.filter(user=run.user, thread_id=run.thread_id,
        pk__lt=run.pk).exclude(context={}).order_by('-pk').first()
    context = dict(previous.context) if previous else {}
    state = {**context, **initial_state(run.query, thread_id=run.thread_id,
                                     paper_ids=context.get('paper_ids', []))}
    # Artifact flags are re-derived per selected target, not copied from another paper.
    state.update(extracted_records=[], summaries=[], translated_paths=[], downloaded_paths=[])

    def keyword(state):
        return {'keywords': search_keywords(state['query']), 'node_history': ['keyword']}

    def search(state):
        from .views import search_with_keywords
        papers = search_with_keywords(state['keywords'], state.get('search_result_limit') or 5,
            'n' if any(x in state['query'] for x in ('최신', '최근')) else 'r')
        return {'search_results': papers, 'selection_candidates': papers, 'paper_ids': [],
                'selected_papers': [], 'node_history': ['search']}

    def save(state):
        from src.services.django_paper_repository import upsert_papers
        ids = state.get('paper_ids', [])
        candidates = state.get('selection_candidates', [])
        papers = [p for p in candidates if p['arxiv_id'] in ids] if ids else state.get('search_results', [])
        if papers:
            upsert_papers(papers)
            for item in papers:
                paper = Paper.objects.get(arxiv_id=item['arxiv_id'])
                LibraryEntry.objects.get_or_create(user=run.user, paper=paper)
            ids = [p['arxiv_id'] for p in papers]
        selected = list(Paper.objects.filter(arxiv_id__in=ids, library_entries__user=run.user))
        if not selected or len(selected) != len(set(ids)):
            raise ValueError('선택한 논문을 내 서재에서 확인할 수 없습니다.')
        return {'paper_ids': ids, 'selected_papers': papers, 'node_history': ['download'],
                'response': f'논문 {len(ids)}편을 내 서재에 저장했습니다.'}

    def targets(state):
        ids = state.get('paper_ids', [])
        papers = list(Paper.objects.filter(arxiv_id__in=ids, library_entries__user=run.user))
        if not papers or len(papers) != len(set(ids)):
            raise ValueError('논문 접근 권한을 확인할 수 없습니다.')
        return papers

    def extract(state):
        from .jobs import extract_paper_content
        records = []
        for paper in targets(state):
            if not paper.sections.exists():
                extract_paper_content(paper.arxiv_id)
            if not paper.sections.exists():
                raise ValueError('추출된 본문이 없습니다.')
            records.append({'paper_id': paper.arxiv_id})
        return {'extracted_records': records, 'node_history': ['extract'],
                'response': f'논문 {len(records)}편의 본문을 준비했습니다.'}

    def summarize(state):
        from .services.summary_service import generate_paper_summary
        summaries = []
        for paper in targets(state):
            summary = PaperSummary.objects.filter(paper=paper).first() or generate_paper_summary(paper)
            summaries.append({'paper_id': paper.arxiv_id, 'summary_id': summary.pk})
        return {'summaries': summaries, 'node_history': ['summarize'],
                'response': f'논문 {len(summaries)}편의 요약을 완료했습니다. 내 서재에서 확인하세요.'}

    def translate(state):
        from .services.translation_service import generate_summary_translation
        papers = targets(state)
        for paper in papers:
            summary = PaperSummary.objects.get(paper=paper)
            if not Translation.objects.filter(paper=paper, translation_type='summary',
                    target_language='ko', source_text=summary.summary_text).exists():
                generate_summary_translation(paper)
        return {'node_history': ['translate'],
                'response': f'논문 {len(papers)}편의 한국어 번역을 완료했습니다. 내 서재에서 확인하세요.'}

    nodes = {'keyword': keyword, 'search': search, 'download': save,
             'extract': extract, 'summarize': summarize, 'translate': translate}
    graph = build_graph(router=WebRouter(), nodes=nodes)
    result = state
    for result in graph.stream(state, {'configurable': {'thread_id': run.thread_id},
                                       'recursion_limit': 60}, stream_mode='values'):
        # Persist conversation data after each step, including partial failures.
        context = {key: result.get(key, []) for key in ('selection_candidates', 'paper_ids', 'search_results')}
        SupervisorRun.objects.filter(pk=run.pk, status='running').update(
            context=context, node_history=result.get('node_history', []))
    return dict(result)
