import { useEffect, useMemo, useState } from 'react'
import { getProcessingJob, savePapers, searchArxiv } from './api'

const JOB_LABELS = {
  pending: '추출 대기',
  running: '본문 추출 중',
  completed: '본문 추출 완료',
  failed: '본문 추출 실패',
}

function JobStatus({ job }) {
  if (!job) return null

  const tone = job.status === 'completed'
    ? 'success'
    : job.status === 'failed'
      ? 'danger'
      : 'neutral'

  return (
    <span className={`status-badge status-badge--${tone}`} title={job.error_message || ''}>
      <span className="status-dot" />
      {JOB_LABELS[job.status] || job.status}
    </span>
  )
}

function SearchResultCard({ paper, selected, onToggle, job }) {
  return (
    <article className={`search-result-card${selected ? ' search-result-card--selected' : ''}`}>
      <div className="search-result-card__heading">
        <div className="search-result-card__topline">
          <label className="paper-checkbox">
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggle(paper.arxiv_id)}
            />
            <span>저장 선택</span>
          </label>
          <JobStatus job={job} />
        </div>
        <span className="eyebrow">arXiv:{paper.arxiv_id}</span>
        <h3>{paper.title}</h3>
        <p>{paper.authors.length > 0 ? paper.authors.join(', ') : '저자 정보 없음'}</p>
      </div>
      <p className="search-result-card__abstract">
        {paper.abstract || '등록된 초록이 없습니다.'}
      </p>
      <div className="search-result-card__actions">
        <a
          href={`https://arxiv.org/abs/${paper.arxiv_id}`}
          target="_blank"
          rel="noreferrer"
        >
          arXiv 보기
        </a>
        {paper.pdf_url && (
          <a href={paper.pdf_url} target="_blank" rel="noreferrer">
            PDF 열기
          </a>
        )}
      </div>
    </article>
  )
}

export default function SearchPanel({ onSaved }) {
  const [query, setQuery] = useState('')
  const [sortBy, setSortBy] = useState('r')
  const [maxResults, setMaxResults] = useState(10)
  const [searchResponse, setSearchResponse] = useState(null)
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const [extractContent, setExtractContent] = useState(true)
  const [jobs, setJobs] = useState({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const results = useMemo(
    () => searchResponse?.results || [],
    [searchResponse],
  )
  const selectedPapers = useMemo(
    () => results.filter((paper) => selectedIds.has(paper.arxiv_id)),
    [results, selectedIds],
  )
  const allSelected = results.length > 0 && selectedPapers.length === results.length
  const activeJobIds = useMemo(
    () => Object.values(jobs)
      .filter((job) => job.status === 'pending' || job.status === 'running')
      .map((job) => job.id),
    [jobs],
  )

  useEffect(() => {
    if (activeJobIds.length === 0) return undefined

    let cancelled = false
    const pollJobs = async () => {
      const updates = await Promise.allSettled(
        activeJobIds.map((jobId) => getProcessingJob(jobId)),
      )
      if (cancelled) return

      const completedUpdates = updates
        .filter((result) => result.status === 'fulfilled')
        .map((result) => result.value)

      if (completedUpdates.length === 0) return

      setJobs((current) => {
        const next = { ...current }
        let changed = false
        completedUpdates.forEach((job) => {
          const previous = current[job.arxiv_id]
          if (JSON.stringify(previous) !== JSON.stringify(job)) {
            next[job.arxiv_id] = job
            changed = true
          }
        })
        return changed ? next : current
      })

      if (completedUpdates.some((job) => job.status === 'completed')) {
        onSaved?.()
      }
    }

    const timer = window.setInterval(pollJobs, 2000)
    pollJobs()
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [activeJobIds, onSaved])

  const submitSearch = async (event) => {
    event.preventDefault()
    const cleanQuery = query.trim()
    if (!cleanQuery) {
      setError('검색어를 입력해 주세요.')
      return
    }

    setLoading(true)
    setError('')
    setNotice('')
    try {
      const response = await searchArxiv({
        query: cleanQuery,
        max_results: Number(maxResults),
        sort_by: sortBy,
      })
      setSearchResponse(response)
      setSelectedIds(new Set())
      setJobs({})
    } catch (requestError) {
      setError(requestError.message)
      setSearchResponse(null)
    } finally {
      setLoading(false)
    }
  }

  const togglePaper = (arxivId) => {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (next.has(arxivId)) next.delete(arxivId)
      else next.add(arxivId)
      return next
    })
  }

  const toggleAll = () => {
    setSelectedIds(
      allSelected
        ? new Set()
        : new Set(results.map((paper) => paper.arxiv_id)),
    )
  }

  const saveSelectedPapers = async () => {
    if (selectedPapers.length === 0) {
      setError('저장할 논문을 한 편 이상 선택해 주세요.')
      return
    }

    setSaving(true)
    setError('')
    setNotice('')
    try {
      const response = await savePapers(selectedPapers, extractContent)
      setJobs((current) => {
        const next = { ...current }
        response.jobs.forEach((job) => {
          next[job.arxiv_id] = job
        })
        return next
      })
      setSelectedIds(new Set())
      setNotice(
        extractContent && response.jobs.length > 0
          ? `${selectedPapers.length}편을 저장했습니다. 본문 추출 상태를 자동으로 확인합니다.`
          : `${selectedPapers.length}편의 메타데이터를 서재에 저장했습니다.`,
      )
      onSaved?.()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="search-workspace">
      <form className="search-form" onSubmit={submitSearch}>
        <div className="search-form__intro">
          <span className="eyebrow">arXiv Search</span>
          <h2>새 논문 찾기</h2>
          <p>기존 Paper Scholar 검색 기능으로 arXiv 논문 제목을 검색합니다.</p>
        </div>

        <label className="search-form__query">
          <span>검색어</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="예: transformer, retrieval augmented generation"
            maxLength={300}
          />
        </label>

        <div className="search-form__options">
          <label>
            <span>정렬</span>
            <select value={sortBy} onChange={(event) => setSortBy(event.target.value)}>
              <option value="r">관련도순</option>
              <option value="n">최신순</option>
            </select>
          </label>
          <label>
            <span>결과 수</span>
            <select value={maxResults} onChange={(event) => setMaxResults(event.target.value)}>
              <option value="5">5편</option>
              <option value="10">10편</option>
              <option value="15">15편</option>
            </select>
          </label>
          <button type="submit" disabled={loading}>
            {loading ? '검색 중…' : '논문 검색'}
          </button>
        </div>
      </form>

      {error && <div className="error-banner" role="alert">{error}</div>}
      {notice && <div className="success-banner" role="status">{notice}</div>}

      <div className="search-results" aria-busy={loading}>
        {!searchResponse && !loading && (
          <div className="empty-state">검색 조건을 입력하면 결과가 여기에 표시됩니다.</div>
        )}
        {loading && <div className="empty-state">arXiv에서 논문을 검색하고 있습니다.</div>}
        {!loading && searchResponse && (
          <>
            <div className="search-results__heading">
              <div>
                <span className="eyebrow">Search Results</span>
                <h2>‘{searchResponse.query}’ 검색 결과</h2>
              </div>
              <strong>{searchResponse.count}편</strong>
            </div>
            {searchResponse.results.length === 0 ? (
              <div className="empty-state">조건에 맞는 논문을 찾지 못했습니다.</div>
            ) : (
              <>
                <div className="selection-toolbar">
                  <label className="paper-checkbox paper-checkbox--all">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                    />
                    <span>전체 선택</span>
                  </label>
                  <span className="selection-toolbar__count">
                    {selectedPapers.length}편 선택
                  </span>
                  <label className="paper-checkbox selection-toolbar__extract">
                    <input
                      type="checkbox"
                      checked={extractContent}
                      onChange={(event) => setExtractContent(event.target.checked)}
                    />
                    <span>저장 후 본문 추출</span>
                  </label>
                  <button
                    type="button"
                    disabled={selectedPapers.length === 0 || saving}
                    onClick={saveSelectedPapers}
                  >
                    {saving ? '저장 중…' : '선택 논문 저장'}
                  </button>
                </div>
                <div className="search-results__list">
                  {searchResponse.results.map((paper) => (
                    <SearchResultCard
                      key={paper.arxiv_id}
                      paper={paper}
                      selected={selectedIds.has(paper.arxiv_id)}
                      onToggle={togglePaper}
                      job={jobs[paper.arxiv_id]}
                    />
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </section>
  )
}
