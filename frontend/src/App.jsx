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
    library: ['내 논문 서재', 'MySQL에 저장된 논문과 처리 상태를 한곳에서 확인합니다.'],
    search: ['arXiv 논문 검색', '새 논문을 검색하고 저장할 자료를 살펴봅니다.'],
    supervisor: ['Supervisor 챗봇', '한 문장으로 여러 논문 작업을 순서대로 실행합니다.'],
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
      <header className="app-header">
        <div>
          <span className="eyebrow">Paper Scholar</span>
          <h1>{pageTitle}</h1>
          <p>{pageDescription}</p>
        </div>
        <div className="app-header__account">
          <StatusBadge tone={health === 'online' ? 'success' : health === 'offline' ? 'danger' : 'neutral'}>
            <span className="status-dot" />
            {health === 'online' ? 'API 연결됨' : health === 'offline' ? 'API 연결 실패' : 'API 확인 중'}
          </StatusBadge>
          <span><strong>{user.username}</strong>님의 서재</span>
          <button type="button" onClick={logout}>로그아웃</button>
        </div>
      </header>

      <nav className="view-tabs" aria-label="주요 화면">
        <button
          type="button"
          className={activeView === 'library' ? 'view-tabs__active' : ''}
          onClick={() => setActiveView('library')}
        >
          내 서재
        </button>
        <button
          type="button"
          className={activeView === 'search' ? 'view-tabs__active' : ''}
          onClick={() => setActiveView('search')}
        >
          arXiv 검색
        </button>
        <button
          type="button"
          className={activeView === 'supervisor' ? 'view-tabs__active' : ''}
          onClick={() => setActiveView('supervisor')}
        >
          Supervisor
        </button>
      </nav>

      {activeView === 'library' && error && (
        <div className="error-banner" role="alert">{error}</div>
      )}

      {activeView === 'library' ? (
        <div className="workspace">
          <section className="library-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Library</span>
              <h2>보관 논문</h2>
            </div>
            <strong>{paperPage?.count ?? 0}편</strong>
          </div>

          <div className="paper-list" aria-busy={libraryLoading}>
            {libraryLoading && <div className="empty-state">논문 목록을 불러오는 중입니다.</div>}
            {!libraryLoading && paperPage?.results.length === 0 && (
              <div className="empty-state">저장된 논문이 없습니다.</div>
            )}
            {!libraryLoading && paperPage?.results.map((paper) => (
              <PaperCard
                key={paper.arxiv_id}
                paper={paper}
                isSelected={selectedId === paper.arxiv_id}
                onSelect={selectPaper}
              />
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
    </main>
  )
}

export default App
