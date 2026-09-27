import { useEffect, useState } from 'react'
import { createSupervisorRun, getSupervisorRun, getSupervisorRuns } from './api'
import MarkdownContent from './MarkdownContent'

const ACTIVE = new Set(['pending', 'running'])

export default function SupervisorChat({ onSaved }) {
  const [message, setMessage] = useState('')
  const [runs, setRuns] = useState([])
  const [threadId, setThreadId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const active = runs.find((run) => ACTIVE.has(run.status))
  const activeId = active?.id

  useEffect(() => {
    let cancelled = false
    getSupervisorRuns().then((history) => {
      if (cancelled) return
      setRuns([...history].reverse())
      setThreadId(history[0]?.thread_id || null)
    }).catch((err) => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!activeId) return undefined
    let cancelled = false
    let timer
    const poll = async () => {
      try {
        const run = await getSupervisorRun(activeId)
        if (cancelled) return
        setRuns((current) => current.map((item) => item.id === run.id ? run : item))
        if (!ACTIVE.has(run.status)) {
          onSaved?.()
          return
        }
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
      if (!cancelled) timer = window.setTimeout(poll, 2000)
    }
    poll()
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [activeId, onSaved])

  const submit = async (event) => {
    event.preventDefault()
    if (!message.trim() || active || submitting || loading) return
    setSubmitting(true)
    setError('')
    try {
      const run = await createSupervisorRun(message.trim(), threadId)
      setThreadId(run.thread_id)
      setRuns((current) => [...current, run])
      setMessage('')
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="supervisor-chat">
      <header className="supervisor-chat__intro">
        <span className="eyebrow">Supervisor</span>
        <h2>논문 검색부터 요약·번역까지 요청하세요</h2>
        <p>검색 후 “두 번째 논문 요약해줘”처럼 이어서 요청할 수 있습니다.</p>
        <button type="button" disabled={!!active || submitting || loading}
          onClick={() => { setThreadId(null); setRuns([]); setError('') }}>새 대화</button>
      </header>
      <div className="supervisor-chat__messages" aria-live="polite">
        {loading && <p>이전 작업을 불러오는 중입니다.</p>}
        {!loading && !runs.length && <p>예: 대용량 언어 모델 관련 논문 3편 찾아줘</p>}
        {runs.map((run) => (
          <div key={run.id}>
            <article className="supervisor-message supervisor-message--user">
              <span>나</span><p>{run.query}</p>
            </article>
            <article className="supervisor-message supervisor-message--assistant">
              <span>Supervisor</span>
              <MarkdownContent text={ACTIVE.has(run.status)
                ? (run.status === 'pending' ? '작업을 기다리고 있습니다.' : '요청을 처리하고 있습니다.')
                : run.response || run.error_message || '요청을 처리했습니다.'} />
              {run.status === 'failed' && <p>요청을 다시 보내 재시도할 수 있습니다.</p>}
              {!!run.papers?.length && <ol className="supervisor-papers">
                {run.papers.map((paper) => <li key={paper.arxiv_id}>
                  <strong>{paper.title}</strong><span>arXiv:{paper.arxiv_id}</span>
                </li>)}
              </ol>}
            </article>
          </div>
        ))}
        {error && <p role="alert">{error}</p>}
      </div>
      <form className="supervisor-chat__form" onSubmit={submit}>
        <label htmlFor="supervisor-message">Supervisor에게 요청</label>
        <textarea id="supervisor-message" maxLength={2000} rows={3} value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="논문 주제나 이전 검색 결과에 대한 요청을 입력하세요." />
        <button type="submit" disabled={!!active || submitting || loading || !message.trim()}>
          {active || submitting ? '처리 중…' : '요청 실행'}
        </button>
      </form>
    </section>
  )
}
