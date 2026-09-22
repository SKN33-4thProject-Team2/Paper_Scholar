import { useState } from 'react'
import { getSupervisorRun, startSupervisorRun } from './api'

// 실행은 백엔드의 LangGraph Supervisor가 전부 담당한다. 화면은 요청을 한 번
// 보내고 상태만 폴링하며, 어떤 기능을 쓸지는 그래프가 결정한다.
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'needs_input'])

const NODE_LABELS = {
  keyword: '검색 키워드 생성',
  search: 'arXiv 논문 검색',
  library: '내 서재 조회',
  download: '논문 저장·다운로드',
  extract: '본문 추출',
  summarize: '요약 생성',
  translate: '한국어 번역',
  deep_search: '본문 근거 검색',
  deep_research: '근거 기반 답변',
  human: '추가 정보 요청',
}

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function PaperResults({ papers }) {
  if (!papers?.length) return null
  return (
    <ol className="supervisor-papers">
      {papers.map((paper) => (
        <li key={paper.arxiv_id || paper.title}>
          <strong>{paper.title}</strong>
          {paper.arxiv_id && <span>arXiv:{paper.arxiv_id}</span>}
        </li>
      ))}
    </ol>
  )
}

export default function SupervisorChat({ onSaved }) {
  const [message, setMessage] = useState('')
  const [messages, setMessages] = useState([])
  const [working, setWorking] = useState(false)
  // 같은 thread_id로 이어 보내면 그래프가 직전 턴의 선택 논문을 기억한다.
  const [threadId, setThreadId] = useState('')

  const addAssistant = (payload) => {
    const id = window.crypto.randomUUID()
    setMessages((current) => [...current, { id, role: 'assistant', ...payload }])
    return id
  }

  const updateAssistant = (id, payload) => {
    setMessages((current) => current.map((item) => (
      item.id === id ? { ...item, ...payload } : item
    )))
  }

  const submit = async (event) => {
    event.preventDefault()
    const cleanMessage = message.trim()
    if (!cleanMessage || working) return

    setMessages((current) => [...current, {
      id: window.crypto.randomUUID(),
      role: 'user',
      text: cleanMessage,
    }])
    setMessage('')
    setWorking(true)
    const assistantId = addAssistant({ text: '요청을 분석하고 있습니다.', status: 'running' })

    try {
      let run = await startSupervisorRun(cleanMessage, threadId)
      if (run.thread_id) setThreadId(run.thread_id)

      const planSteps = (run.plan || []).map((step) => step.name || step.action)
      updateAssistant(assistantId, {
        text: run.status === 'needs_input'
          ? run.response
          : '실행 계획을 세웠습니다. 필요한 기능만 순서대로 실행합니다.',
        status: run.status === 'needs_input' ? 'completed' : 'running',
        plan: planSteps,
      })

      let guard = 0
      while (!TERMINAL_STATUSES.has(run.status) && guard < 900) {
        guard += 1
        await wait(2000)
        run = await getSupervisorRun(run.id)
        const done = (run.node_history || []).map((node) => NODE_LABELS[node] || node)
        updateAssistant(assistantId, {
          progress: done.length ? `진행: ${done.join(' → ')}` : '실행을 준비하고 있습니다.',
        })
      }

      if (run.status === 'failed') {
        throw new Error(run.error_message || '요청을 완료하지 못했습니다.')
      }

      onSaved?.()
      updateAssistant(assistantId, {
        text: run.response || '요청을 처리했지만 반환할 결과가 없습니다.',
        status: 'completed',
        plan: (run.node_history || []).map((node) => NODE_LABELS[node] || node),
        papers: run.papers,
        progress: '',
      })
    } catch (error) {
      updateAssistant(assistantId, {
        text: error.message,
        status: 'failed',
        progress: '',
      })
    } finally {
      setWorking(false)
    }
  }

  return (
    <section className="supervisor-chat">
      <header className="supervisor-chat__intro">
        <span className="eyebrow">Supervisor</span>
        <h2>논문 작업을 한 문장으로 요청하세요</h2>
        <p>
          LangGraph Supervisor가 요청을 읽고 검색·저장·본문 추출·요약·번역·근거 검색 중
          필요한 기능만 골라 실행합니다.
        </p>
      </header>

      <div className="supervisor-chat__messages" aria-live="polite">
        {messages.length === 0 && (
          <div className="supervisor-chat__empty">
            예: “RAG 논문 3편 찾아서 요약하고 번역해줘.”
          </div>
        )}
        {messages.map((item) => (
          <article
            className={`supervisor-message supervisor-message--${item.role}`}
            key={item.id}
          >
            <span>{item.role === 'user' ? '나' : 'Supervisor'}</span>
            <p>{item.text}</p>
            {item.plan?.length > 0 && (
              <div className="supervisor-plan">
                {item.plan.map((label, index) => (
                  <span key={`${item.id}-${index}-${label}`}>{label}</span>
                ))}
              </div>
            )}
            {item.progress && <small>{item.progress}</small>}
            <PaperResults papers={item.papers} />
          </article>
        ))}
        {working && <div className="supervisor-chat__working">Supervisor가 필요한 기능을 실행 중입니다.</div>}
      </div>

      <form className="supervisor-chat__form" onSubmit={submit}>
        <label htmlFor="supervisor-message">Supervisor에게 요청</label>
        <textarea
          id="supervisor-message"
          maxLength={2000}
          placeholder="찾을 논문 주제와 저장·요약·번역 여부를 한 문장으로 입력하세요."
          rows={3}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <button type="submit" disabled={working || !message.trim()}>
          {working ? '실행 중…' : '요청 실행'}
        </button>
      </form>
    </section>
  )
}
