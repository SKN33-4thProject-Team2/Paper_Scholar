import { useState } from 'react'
import { askPaper } from './api'
import MarkdownContent from './MarkdownContent'

export default function PaperChat({ paper }) {
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submitQuestion = async (event) => {
    event.preventDefault()
    const cleanQuestion = question.trim()
    if (cleanQuestion.length < 2 || loading) return

    setMessages((current) => [
      ...current,
      { id: `question-${Date.now()}`, role: 'user', text: cleanQuestion },
    ])
    setQuestion('')
    setError('')
    setLoading(true)

    try {
      const result = await askPaper(paper.arxiv_id, cleanQuestion)
      setMessages((current) => [
        ...current,
        {
          id: `answer-${Date.now()}`,
          role: 'assistant',
          text: result.answer,
          sources: result.sources || [],
          model: result.model,
        },
      ])
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="paper-chat">
      <div className="paper-chat__intro">
        <strong>이 논문에 질문하기</strong>
        <span>저장된 본문 섹션에서 근거를 찾아 답변합니다.</span>
      </div>

      <div className="paper-chat__messages" aria-live="polite">
        {messages.length === 0 && (
          <div className="paper-chat__empty">
            예: “이 논문의 핵심 방법과 실험 결과를 설명해 줘”
          </div>
        )}
        {messages.map((message) => (
          <article
            className={`paper-chat__message paper-chat__message--${message.role}`}
            key={message.id}
          >
            <span>{message.role === 'user' ? '나' : '논문 답변'}</span>
            {message.role === 'assistant' ? (
              <MarkdownContent text={message.text} />
            ) : (
              <p>{message.text}</p>
            )}
            {message.model && <small>모델 {message.model}</small>}
            {message.sources?.length > 0 && (
              <details className="paper-chat__sources">
                <summary>근거 {message.sources.length}개 보기</summary>
                <ol>
                  {message.sources.map((source) => (
                    <li key={`${message.id}-${source.index}`}>
                      <MarkdownContent text={source.text} />
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </article>
        ))}
        {loading && (
          <div className="paper-chat__thinking">본문에서 근거를 찾고 있습니다…</div>
        )}
      </div>

      {error && <div className="error-banner" role="alert">{error}</div>}
      {paper.section_count === 0 && (
        <div className="artifact-empty">질문하려면 먼저 본문을 추출해야 합니다.</div>
      )}
      {paper.section_count > 0 && (
        <form className="paper-chat__form" onSubmit={submitQuestion}>
          <label htmlFor="paper-question">질문</label>
          <textarea
            id="paper-question"
            rows="3"
            maxLength="2000"
            placeholder="선택한 논문의 내용에 관해 질문해 주세요."
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <button type="submit" disabled={loading || question.trim().length < 2}>
            {loading ? '답변 생성 중…' : '질문 보내기'}
          </button>
        </form>
      )}
    </div>
  )
}
