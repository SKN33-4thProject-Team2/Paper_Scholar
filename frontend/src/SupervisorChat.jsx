import { useState } from 'react'
import {
  createSupervisorPlan,
  getProcessingJob,
  savePapers,
  searchArxiv,
  summarizePaper,
  translatePaper,
} from './api'


const ACTION_LABELS = {
  search: '논문 검색',
  save: '내 서재 저장',
  extract: '본문 추출',
  summarize: '요약 생성',
  translate: '한국어 번역',
}

const TERMINAL_JOB_STATUSES = new Set(['completed', 'failed'])

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

async function waitForJob(initialJob, onUpdate) {
  let job = initialJob
  onUpdate?.(job)
  for (let attempt = 0; attempt < 900; attempt += 1) {
    if (TERMINAL_JOB_STATUSES.has(job.status)) return job
    await wait(2000)
    job = await getProcessingJob(job.id)
    onUpdate?.(job)
  }
  throw new Error(`${initialJob.arxiv_id} 작업 확인 시간이 초과되었습니다.`)
}

async function runJobs(starters, onProgress) {
  const startedJobs = await Promise.all(starters.map((start) => start()))
  const results = await Promise.all(startedJobs.map((started, index) => (
    waitForJob(started.job, (job) => {
      onProgress?.(index, starters.length, job)
    })
  )))
  results.forEach((completed) => {
    if (completed.status === 'failed') {
      throw new Error(
        `${completed.arxiv_id} 작업 실패: ${completed.error_message || '원인을 확인할 수 없습니다.'}`,
      )
    }
  })
  return results
}

function PaperResults({ papers }) {
  if (!papers?.length) return null
  return (
    <ol className="supervisor-papers">
      {papers.map((paper) => (
        <li key={paper.arxiv_id}>
          <strong>{paper.title}</strong>
          <span>arXiv:{paper.arxiv_id}</span>
        </li>
      ))}
    </ol>
  )
}

export default function SupervisorChat({ onSaved }) {
  const [message, setMessage] = useState('')
  const [messages, setMessages] = useState([])
  const [working, setWorking] = useState(false)

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

    const userMessage = {
      id: window.crypto.randomUUID(),
      role: 'user',
      text: cleanMessage,
    }
    setMessages((current) => [...current, userMessage])
    setMessage('')
    setWorking(true)
    const assistantId = addAssistant({ text: '요청을 분석하고 있습니다.', status: 'running' })

    try {
      const plan = await createSupervisorPlan(cleanMessage)
      if (plan.needs_clarification) {
        updateAssistant(assistantId, {
          text: plan.clarification_question,
          status: 'completed',
          plan,
        })
        return
      }

      updateAssistant(assistantId, {
        text: `‘${plan.query}’ 주제로 실행 계획을 만들었습니다.`,
        status: 'running',
        plan,
        progress: `논문 ${plan.max_results}편을 검색하는 중입니다.`,
      })
      const searchResponse = await searchArxiv({
        query: plan.query,
        max_results: plan.max_results,
        sort_by: 'r',
      })
      const papers = searchResponse.results || []
      if (papers.length === 0) {
        updateAssistant(assistantId, {
          text: `‘${plan.query}’ 검색 결과가 없습니다. 다른 주제로 요청해 주세요.`,
          status: 'completed',
          plan,
          papers: [],
          progress: '',
        })
        return
      }

      if (!plan.save_to_library) {
        updateAssistant(assistantId, {
          text: `${papers.length}편을 찾았습니다. 저장이나 요약·번역이 필요하면 이어서 요청해 주세요.`,
          status: 'completed',
          plan,
          papers,
          progress: '',
        })
        return
      }

      updateAssistant(assistantId, {
        papers,
        progress: `${papers.length}편을 내 서재에 저장하고 있습니다.`,
      })
      const saveResponse = await savePapers(papers, plan.extract_content)
      onSaved?.()

      let availablePaperIds = papers.map((paper) => paper.arxiv_id)
      if (plan.extract_content) {
        const extractionJobs = saveResponse.jobs || []
        const extractionResults = await Promise.all(extractionJobs.map((job, index) => (
          waitForJob(job, (currentJob) => {
            updateAssistant(assistantId, {
              progress: `본문 추출 ${index + 1}/${extractionJobs.length}: ${currentJob.status}`,
            })
          })
        )))
        const failed = extractionResults.filter((job) => job.status === 'failed')
        if (failed.length > 0) {
          throw new Error(
            failed.map((job) => `${job.arxiv_id}: ${job.error_message}`).join(' | '),
          )
        }
        availablePaperIds = extractionResults.map((job) => job.arxiv_id)
      }

      if (plan.summarize) {
        updateAssistant(assistantId, { progress: '논문 요약 작업을 시작합니다.' })
        await runJobs(
          availablePaperIds.map((arxivId) => () => summarizePaper(arxivId, false)),
          (index, total, job) => updateAssistant(assistantId, {
            progress: `요약 ${index + 1}/${total}: ${job.status}`,
          }),
        )
      }

      if (plan.translate) {
        updateAssistant(assistantId, { progress: '요약 한국어 번역을 시작합니다.' })
        await runJobs(
          availablePaperIds.map((arxivId) => (
            () => translatePaper(arxivId, plan.target_language, false)
          )),
          (index, total, job) => updateAssistant(assistantId, {
            progress: `번역 ${index + 1}/${total}: ${job.status}`,
          }),
        )
      }

      onSaved?.()
      updateAssistant(assistantId, {
        text: `${papers.length}편에 대한 요청을 완료했습니다. 내 서재에서 결과를 확인할 수 있습니다.`,
        status: 'completed',
        plan,
        papers,
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
          Supervisor는 계획만 세우고, 실제 작업은 기존 검색·저장·본문 추출·요약·번역 기능으로 실행합니다.
        </p>
      </header>

      <div className="supervisor-chat__messages" aria-live="polite">
        {messages.length === 0 && (
          <div className="supervisor-chat__empty">
            예: “RAG 논문 하나와 비슷한 논문 3편을 찾아서 요약·번역하고 내 서재에 저장해줘.”
          </div>
        )}
        {messages.map((item) => (
          <article
            className={`supervisor-message supervisor-message--${item.role}`}
            key={item.id}
          >
            <span>{item.role === 'user' ? '나' : 'Supervisor'}</span>
            <p>{item.text}</p>
            {item.plan?.actions?.length > 0 && (
              <div className="supervisor-plan">
                {item.plan.actions.map((action) => (
                  <span key={action}>{ACTION_LABELS[action] || action}</span>
                ))}
              </div>
            )}
            {item.progress && <small>{item.progress}</small>}
            <PaperResults papers={item.papers} />
          </article>
        ))}
        {working && <div className="supervisor-chat__working">기존 기능을 순서대로 실행 중입니다.</div>}
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
