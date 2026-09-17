import { useState } from 'react'
import { searchArxiv } from './api'

function SearchResultCard({ paper }) {
  return (
    <article className="search-result-card">
      <div className="search-result-card__heading">
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

export default function SearchPanel() {
  const [query, setQuery] = useState('')
  const [sortBy, setSortBy] = useState('r')
  const [maxResults, setMaxResults] = useState(10)
  const [searchResponse, setSearchResponse] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submitSearch = async (event) => {
    event.preventDefault()
    const cleanQuery = query.trim()
    if (!cleanQuery) {
      setError('검색어를 입력해 주세요.')
      return
    }

    setLoading(true)
    setError('')
    try {
      setSearchResponse(await searchArxiv({
        query: cleanQuery,
        max_results: Number(maxResults),
        sort_by: sortBy,
      }))
    } catch (requestError) {
      setError(requestError.message)
      setSearchResponse(null)
    } finally {
      setLoading(false)
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
              <div className="search-results__list">
                {searchResponse.results.map((paper) => (
                  <SearchResultCard key={paper.arxiv_id} paper={paper} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}
