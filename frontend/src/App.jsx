import { useCallback, useEffect, useState } from 'react'
import { getHealth, getPaper, getPapers } from './api'
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

function PaperDetail({ paper, loading }) {
  if (loading) {
    return <div className="empty-state">논문 상세 정보를 불러오는 중입니다.</div>
  }
  if (!paper) {
    return <div className="empty-state">목록에서 논문을 선택해 주세요.</div>
  }

  return (
    <article className="paper-detail">
      <div>
        <span className="eyebrow">arXiv:{paper.arxiv_id}</span>
        <h2>{paper.title}</h2>
        <p className="paper-detail__authors">
          {paper.authors.length > 0 ? paper.authors.join(', ') : '저자 정보 없음'}
        </p>
      </div>
      <div className="paper-detail__stats">
        <div><strong>{paper.section_count}</strong><span>본문 섹션</span></div>
        <div><strong>{paper.has_summary ? '완료' : '대기'}</strong><span>요약</span></div>
        <div><strong>{paper.translation_count}</strong><span>번역 결과</span></div>
      </div>
      <section>
        <h3>초록</h3>
        <p className="paper-detail__abstract">
          {paper.abstract || '등록된 초록이 없습니다.'}
        </p>
      </section>
      <div className="paper-detail__links">
        {paper.entry_url && <a href={paper.entry_url} target="_blank" rel="noreferrer">arXiv 보기</a>}
        {paper.pdf_url && <a href={paper.pdf_url} target="_blank" rel="noreferrer">PDF 열기</a>}
      </div>
    </article>
  )
}

function App() {
  const [health, setHealth] = useState('checking')
  const [paperPage, setPaperPage] = useState(null)
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
    getPapers()
      .then((data) => setPaperPage(data))
      .catch((requestError) => setError(requestError.message))
      .finally(() => setLoading(false))
  }, [])

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

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <span className="eyebrow">Paper Scholar</span>
          <h1>내 논문 서재</h1>
          <p>MySQL에 저장된 논문과 처리 상태를 한곳에서 확인합니다.</p>
        </div>
        <StatusBadge tone={health === 'online' ? 'success' : health === 'offline' ? 'danger' : 'neutral'}>
          <span className="status-dot" />
          {health === 'online' ? 'API 연결됨' : health === 'offline' ? 'API 연결 실패' : 'API 확인 중'}
        </StatusBadge>
      </header>

      {error && <div className="error-banner" role="alert">{error}</div>}

      <div className="workspace">
        <section className="library-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Library</span>
              <h2>보관 논문</h2>
            </div>
            <strong>{paperPage?.count ?? 0}편</strong>
          </div>

          <div className="paper-list" aria-busy={loading}>
            {loading && <div className="empty-state">논문 목록을 불러오는 중입니다.</div>}
            {!loading && paperPage?.results.length === 0 && (
              <div className="empty-state">저장된 논문이 없습니다.</div>
            )}
            {!loading && paperPage?.results.map((paper) => (
              <PaperCard
                key={paper.arxiv_id}
                paper={paper}
                isSelected={selectedId === paper.arxiv_id}
                onSelect={selectPaper}
              />
            ))}
          </div>

          <nav className="pagination" aria-label="논문 목록 페이지">
            <button type="button" disabled={!paperPage?.previous || loading} onClick={() => loadPapers(paperPage.previous)}>
              이전
            </button>
            <button type="button" disabled={!paperPage?.next || loading} onClick={() => loadPapers(paperPage.next)}>
              다음
            </button>
          </nav>
        </section>

        <section className="detail-panel">
          <PaperDetail paper={selectedPaper} loading={detailLoading} />
        </section>
      </div>
    </main>
  )
}

export default App
