import { useCallback, useEffect, useState } from 'react'
import { getHealth, getPaper, getPapers } from './api'
import PaperDetail from './PaperDetail'
import SearchPanel from './SearchPanel'
import SupervisorChat from './SupervisorChat'
import AuthPage from './AuthPage'
import { useAuth } from './auth-context'
import './App.css'

function StatusBadge({ children, tone = 'neutral' }) {
  return <span className={`status-badge status-badge--${tone}`}>{children}</span>
}

function PaperCard({ paper, isSelected, onSelect }) {
  return (
    <button
      className={`paper-card${isSelected ? ' paper-card--selected' : ''}`}
      type="button"
      onClick={() => onSelect(paper.arxiv_id)}
    >
      <span className="paper-card__id">arXiv:{paper.arxiv_id}</span>
      <strong>{paper.title}</strong>
      <span className="paper-card__authors">
        {paper.authors.length > 0 ? paper.authors.join(', ') : '저자 정보 없음'}
      </span>
      <span className="paper-card__meta">
        <StatusBadge tone={paper.section_count > 0 ? 'success' : 'neutral'}>
          본문 {paper.section_count}
        </StatusBadge>
        <StatusBadge tone={paper.has_summary ? 'success' : 'neutral'}>
          {paper.has_summary ? '요약 완료' : '요약 없음'}
        </StatusBadge>
        <StatusBadge tone={paper.translation_count > 0 ? 'success' : 'neutral'}>
          번역 {paper.translation_count}
        </StatusBadge>
      </span>
    </button>
  )
}

function TranslationCard({ paper, isSelected, onSelect }) {
  return (
    <button
      className={`translation-list-card${isSelected ? ' translation-list-card--selected' : ''}`}
      type="button"
      onClick={() => onSelect(paper.arxiv_id)}
    >
      <span className="translation-list-card__topline">
        <span className="paper-card__id">arXiv:{paper.arxiv_id}</span>
        <StatusBadge tone={paper.translation_count > 0 ? 'success' : 'neutral'}>
          {paper.translation_count > 0 ? '번역 완료' : '번역 대기'}
        </StatusBadge>
      </span>
      <strong>{paper.title}</strong>
      <span className="paper-card__authors">
        {paper.authors?.length > 0 ? paper.authors.join(', ') : '저자 정보 없음'}
      </span>
      <span className="translation-list-card__action">상세 결과 열기 <span aria-hidden="true">→</span></span>
    </button>
  )
}

function BrandMark() {
  return (
    <span className="brand-mark brand-mark--book" aria-hidden="true">
      <svg viewBox="0 0 72 62" role="presentation">
        <defs>
          <linearGradient id="paper-logo-blue" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#70b6db" />
            <stop offset="1" stopColor="#2f6f9d" />
          </linearGradient>
        </defs>
        <path className="brand-mark__spark" d="M36 2l3.7 10.3L50 16l-10.3 3.7L36 30l-3.7-10.3L22 16l10.3-3.7L36 2z" />
        <path className="brand-mark__book" d="M35.5 27.7C28.8 22.5 20.4 21 10 23.6v29.2c10.4-2.6 18.8-1.1 25.5 4.1V27.7z" />
        <path className="brand-mark__book" d="M36.5 27.7C43.2 22.5 51.6 21 62 23.6v29.2c-10.4-2.6-18.8-1.1-25.5 4.1V27.7z" />
        <path className="brand-mark__spine" d="M36 28v29" />
        <path className="brand-mark__line" d="M15 31c5.4-1 10.2-.2 14.5 2.4M15 39c5.4-1 10.2-.2 14.5 2.4M57 31c-5.4-1-10.2-.2-14.5 2.4M57 39c-5.4-1-10.2-.2-14.5 2.4" />
      </svg>
    </span>
  )
}

function Sidebar({ activeView, onChange, user }) {
  const items = [
    { id: 'library', label: '내 논문 서재', caption: '저장한 논문과 결과' },
    { id: 'search', label: '논문 검색', caption: 'arXiv에서 새 논문 찾기' },
    { id: 'translations', label: '논문 번역 리스트', caption: '번역 결과 확인' },
    { id: 'supervisor', label: '딥서치 내용 & 요약', caption: 'Supervisor에게 질문하기' },
  ]

  return (
    <aside className="app-sidebar">
      <div className="sidebar-brand">
        <BrandMark />
        <div>
          <strong><span>Paper</span> <em>Scholar</em></strong>
          <span>학술 논문 작업실</span>
        </div>
      </div>

      <button className="sidebar-new" type="button" onClick={() => onChange('supervisor')}>
        <span aria-hidden="true">＋</span>
        새 논문 질문 시작
      </button>

      <p className="sidebar-label">WORKSPACE</p>
      <nav className="sidebar-nav" aria-label="Paper Scholar 메뉴">
        {items.map((item, index) => (
          <button
            type="button"
            key={`${item.label}-${index}`}
            className={activeView === item.id ? 'is-active' : ''}
            onClick={() => onChange(item.id)}
          >
            <span className="sidebar-nav__icon" aria-hidden="true">{['⌂', '⌕', '▤', '✦'][index]}</span>
            <span>
              <strong>{item.label}</strong>
              <small>{item.caption}</small>
            </span>
          </button>
        ))}
      </nav>

      <div className="sidebar-note">
        <span className="sidebar-note__dot" />
        <span>검색부터 요약·번역까지<br />논문 작업을 한곳에서 관리하세요.</span>
      </div>

      <div className="sidebar-account">
        <span className="account-avatar">{user.username?.slice(0, 1).toUpperCase()}</span>
        <span className="account-copy">
          <strong>{user.username}</strong>
          <small>개인 논문 서재</small>
        </span>
      </div>
    </aside>
  )
}

function PaperContextPanel({ activeView, selectedPaper, paperPage, health, onSelectPaper, onChangeView }) {
  const context = activeView === 'search'
    ? { eyebrow: 'SEARCH GUIDE', title: '논문 검색', body: '키워드와 결과 수를 입력해 arXiv 논문을 찾아보세요.', steps: ['검색어 입력', '결과 선택', '서재 저장 및 본문 추출'] }
    : activeView === 'translations'
      ? { eyebrow: 'TRANSLATION LIST', title: '번역 결과를 모아보기', body: '번역이 완료된 논문을 선택하면 상세 결과에서 원문과 번역문을 확인할 수 있습니다.', steps: ['번역 논문 선택', '결과 탭 열기', '원문과 번역 비교'] }
      : activeView === 'supervisor'
      ? { eyebrow: 'DEEP SEARCH', title: '논문 작업을 대화로', body: '검색·저장·추출·요약·번역을 한 문장으로 요청할 수 있습니다.', steps: ['자연어로 요청', '계획 확인', '처리 결과 확인'] }
      : { eyebrow: 'YOUR LIBRARY', title: '논문을 선택해 주세요', body: '저장된 논문을 선택하면 처리 상태와 상세 작업을 확인할 수 있습니다.', steps: ['논문 선택', '본문·요약 확인', '필요한 작업 실행'] }

  const papers = paperPage?.results || []
  const questionPapers = papers.filter((paper) => paper.section_count > 0)

  const selectQuestionPaper = (arxivId) => {
    onSelectPaper?.(arxivId)
    onChangeView?.('library')
  }

  return (
    <aside className={`context-panel${selectedPaper ? ' context-panel--has-selection' : ' context-panel--empty'}`}>
      <div className="context-panel__topline">
        <p className="context-panel__eyebrow">{selectedPaper ? 'SELECTED PAPER' : context.eyebrow}</p>
        <span className={`context-connection context-connection--compact ${health === 'online' ? 'is-online' : ''}`}>
          <i className="context-status-dot" />
          {health === 'online' ? '연결됨' : health === 'offline' ? '오프라인' : '확인 중'}
        </span>
      </div>

      {selectedPaper ? (
        <section className="context-selected-paper">
          <div className="context-paper-icon">PDF</div>
          <h2>{selectedPaper.title}</h2>
          <p className="context-paper__authors">
            {selectedPaper.authors?.length ? selectedPaper.authors.join(', ') : '저자 정보 없음'}
          </p>
          <a className="context-paper__link" href={`https://arxiv.org/abs/${selectedPaper.arxiv_id}`} target="_blank" rel="noreferrer">
            arXiv 원문 보기 <span aria-hidden="true">↗</span>
          </a>
          <div className="context-divider" />
          <p className="context-panel__eyebrow">PROCESSING STATUS</p>
          <div className="context-status-list">
            <span><i className="context-status-dot is-done" />메타데이터 저장</span>
            <span><i className={`context-status-dot ${selectedPaper.section_count > 0 ? 'is-done' : ''}`} />본문 추출 {selectedPaper.section_count > 0 ? '완료' : '대기'}</span>
            <span><i className={`context-status-dot ${selectedPaper.has_summary ? 'is-done' : ''}`} />요약 {selectedPaper.has_summary ? '완료' : '미생성'}</span>
            <span><i className={`context-status-dot ${selectedPaper.translation_count > 0 ? 'is-done' : ''}`} />번역 {selectedPaper.translation_count > 0 ? '완료' : '미생성'}</span>
          </div>
        </section>
      ) : (
        <section className="context-guide">
          <div className="context-empty-icon" aria-hidden="true">?</div>
          <h2>{context.title}</h2>
          <p>{context.body}</p>
          <ol className="context-steps">
            {context.steps.map((step, index) => <li key={step}><span>{String(index + 1).padStart(2, '0')}</span>{step}</li>)}
          </ol>
        </section>
      )}

      <section className="context-qa">
        <nav className="context-breadcrumb" aria-label="논문 작업 위치">
          <button type="button" onClick={() => onChangeView?.('library')}>내 서재</button>
          <span aria-hidden="true">›</span>
          <strong>문답 가능</strong>
        </nav>
        <div className="context-section-heading">
          <div>
            <p className="context-panel__eyebrow">MY LIBRARY</p>
            <h3>문답 가능한 논문</h3>
          </div>
          <span>{questionPapers.length}</span>
        </div>
        <p className="context-section-note">본문 추출이 끝난 논문은 바로 질문할 수 있습니다.</p>
        <div className="context-paper-list">
          {questionPapers.slice(0, 5).map((paper, index) => (
            <button
              className={`context-paper-item${selectedPaper?.arxiv_id === paper.arxiv_id ? ' is-selected' : ''}`}
              key={paper.arxiv_id}
              type="button"
              onClick={() => selectQuestionPaper(paper.arxiv_id)}
            >
              <span>{String(index + 1).padStart(2, '0')}</span>
              <strong>{paper.title}</strong>
              <i aria-hidden="true">›</i>
            </button>
          ))}
          {questionPapers.length === 0 && <div className="context-paper-list__empty">아직 문답 가능한 논문이 없습니다.</div>}
        </div>
      </section>

      <section className="context-examples">
        <p className="context-panel__eyebrow">QUICK START</p>
        <h3>이렇게 요청해 보세요</h3>
        <div className="context-example-list">
          <button type="button" onClick={() => onChangeView?.('supervisor')}>“RAG 논문 5편 찾아줘”</button>
          <button type="button" onClick={() => onChangeView?.('supervisor')}>“선택한 논문을 3줄로 요약해줘”</button>
          <button type="button" onClick={() => onChangeView?.('supervisor')}>“본문 근거를 들어 설명해줘”</button>
        </div>
      </section>

      {selectedPaper && <p className="context-hint">상세 화면의 ‘질의응답’ 탭에서 선택한 논문에 대해 질문할 수 있습니다.</p>}
    </aside>
  )
}

function App() {
  const { user, loading: authLoading, logout } = useAuth()
  const [activeView, setActiveView] = useState('library')
  const [health, setHealth] = useState('checking')
  const [paperPage, setPaperPage] = useState(null)
  const [loadedUserId, setLoadedUserId] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [selectedPaper, setSelectedPaper] = useState(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')

  const loadPapers = useCallback(async (url) => {
    setLoading(true)
    setError('')
    try {
      setPaperPage(await getPapers(url))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    getHealth()
      .then(() => setHealth('online'))
      .catch(() => setHealth('offline'))
  }, [])

  useEffect(() => {
    if (authLoading || !user) {
      return
    }

    getPapers()
      .then((data) => {
        setPaperPage(data)
        setError('')
      })
      .catch((requestError) => setError(requestError.message))
      .finally(() => {
        setLoadedUserId(user.id)
        setLoading(false)
      })
  }, [authLoading, user])

  const libraryLoading = loading || loadedUserId !== user?.id
  const pageTitles = {
    library: ['내 논문 서재', '저장한 논문과 처리 결과를 한곳에서 확인합니다.'],
    search: ['논문 검색', 'arXiv에서 연구 주제에 맞는 논문을 찾아보세요.'],
    translations: ['논문 번역 리스트', '번역을 마친 논문과 작업 상태를 확인합니다.'],
    supervisor: ['딥서치 내용 & 요약', '한 문장으로 논문 검색부터 요약·번역까지 요청합니다.'],
  }
  const [pageTitle, pageDescription] = pageTitles[activeView]

  const selectPaper = async (arxivId) => {
    setSelectedId(arxivId)
    setDetailLoading(true)
    setError('')
    try {
      setSelectedPaper(await getPaper(arxivId))
    } catch (requestError) {
      setError(requestError.message)
      setSelectedPaper(null)
    } finally {
      setDetailLoading(false)
    }
  }

  if (authLoading) {
    return <div className="auth-loading">로그인 정보를 확인하는 중입니다.</div>
  }
  if (!user) {
    return <AuthPage />
  }

  return (
    <main className="app-shell">
      <Sidebar activeView={activeView} onChange={setActiveView} user={user} />
      <section className="app-main">
        <header className="app-header">
          <div className="app-header__title">
            <span className="eyebrow">PAPER SCHOLAR / {activeView === 'supervisor' ? 'DEEP SEARCH' : activeView.toUpperCase()}</span>
            <h1>{pageTitle}</h1>
            <p>{pageDescription}</p>
          </div>
          <div className="app-header__account">
            <StatusBadge tone={health === 'online' ? 'success' : health === 'offline' ? 'danger' : 'neutral'}>
              <span className="status-dot" />
              {health === 'online' ? 'API 연결됨' : health === 'offline' ? 'API 연결 실패' : 'API 확인 중'}
            </StatusBadge>
            <button type="button" onClick={logout}>로그아웃</button>
          </div>
        </header>

        {(activeView === 'library' || activeView === 'translations') && error && (
          <div className="error-banner" role="alert">{error}</div>
        )}

        <div className="app-content">
        {activeView === 'library' || activeView === 'translations' ? (
          <div className="workspace">
            <section className="library-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">{activeView === 'translations' ? 'Translations' : 'Library'}</span>
              <h2>{activeView === 'translations' ? '번역한 논문' : '보관 논문'}</h2>
            </div>
            <strong>{activeView === 'translations'
              ? (paperPage?.results || []).filter((paper) => paper.translation_count > 0).length
              : paperPage?.count ?? 0}편</strong>
          </div>

          <div className="paper-list" aria-busy={libraryLoading}>
            {libraryLoading && <div className="empty-state">논문 목록을 불러오는 중입니다.</div>}
            {!libraryLoading && activeView === 'library' && paperPage?.results.length === 0 && (
              <div className="empty-state">저장된 논문이 없습니다.</div>
            )}
            {!libraryLoading && activeView === 'translations' && (paperPage?.results || []).filter((paper) => paper.translation_count > 0).length === 0 && (
              <div className="empty-state">아직 번역된 논문이 없습니다.<br />논문 상세 화면에서 번역을 시작해 보세요.</div>
            )}
            {!libraryLoading && activeView === 'library' && paperPage?.results.map((paper) => (
              <PaperCard key={paper.arxiv_id} paper={paper} isSelected={selectedId === paper.arxiv_id} onSelect={selectPaper} />
            ))}
            {!libraryLoading && activeView === 'translations' && (paperPage?.results || []).filter((paper) => paper.translation_count > 0).map((paper) => (
              <TranslationCard key={paper.arxiv_id} paper={paper} isSelected={selectedId === paper.arxiv_id} onSelect={selectPaper} />
            ))}
          </div>

          <nav className="pagination" aria-label="논문 목록 페이지">
            <button type="button" disabled={!paperPage?.previous || libraryLoading} onClick={() => loadPapers(paperPage.previous)}>
              이전
            </button>
            <button type="button" disabled={!paperPage?.next || libraryLoading} onClick={() => loadPapers(paperPage.next)}>
              다음
            </button>
          </nav>
          </section>

          <section className="detail-panel">
            <PaperDetail
              key={selectedPaper?.arxiv_id || 'empty'}
              paper={selectedPaper}
              loading={detailLoading}
            />
          </section>
          </div>
        ) : activeView === 'search' ? (
          <SearchPanel onSaved={loadPapers} />
        ) : (
          <SupervisorChat onSaved={loadPapers} />
        )}
        </div>
      </section>
      <PaperContextPanel
        activeView={activeView}
        selectedPaper={selectedPaper}
        paperPage={paperPage}
        health={health}
        onSelectPaper={selectPaper}
        onChangeView={setActiveView}
      />
    </main>
  )
}

export default App
