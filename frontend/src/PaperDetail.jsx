import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import 'katex/dist/katex.min.css'
import {
  extractPaper,
  getProcessingJob,
  getPaperSections,
  getPaperSummary,
  getPaperTranslations,
  summarizePaper,
  translatePaper,
} from './api'
import PaperChat from './PaperChat'

const EMPTY_ARTIFACTS = {
  paperId: null,
  sections: null,
  summary: null,
  translations: null,
}

const TRANSLATION_TYPE_LABELS = {
  abstract: '초록',
  summary: '요약',
  section: '본문 섹션',
  full_text: '전체 본문',
}

function normalizeMathMarkdown(value = '') {
  return value
    .replace(/\\\[([\s\S]*?)\\\]/g, (_match, math) => `$$\n${math.trim()}\n$$`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_match, math) => `$${math.trim()}$`)
}

function MarkdownContent({ text }) {
  return (
    <div className="artifact-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
      >
        {normalizeMathMarkdown(text)}
      </ReactMarkdown>
    </div>
  )
}

function OverviewTab({ paper }) {
  return (
    <div className="paper-tab-content">
      <section>
        <h3>초록</h3>
        <p className="paper-detail__abstract">
          {paper.abstract || '등록된 초록이 없습니다.'}
        </p>
      </section>
      <div className="paper-detail__links">
        {paper.entry_url && (
          <a href={paper.entry_url} target="_blank" rel="noreferrer">arXiv 보기</a>
        )}
        {paper.pdf_url && (
          <a href={paper.pdf_url} target="_blank" rel="noreferrer">PDF 열기</a>
        )}
      </div>
    </div>
  )
}

function isHtmlUnavailableError(message = '') {
  return (
    message.includes('arXiv HTML을 찾을 수 없습니다 (404 Not Found)')
    || message.includes('HTML 렌더링이 제공되지')
  )
}

function SectionsTab({ paper, sections, job, onGenerate }) {
  const sectionList = Array.isArray(sections) ? sections : []
  const isRunning = job?.status === 'pending' || job?.status === 'running'
  const htmlUnavailable = (
    job?.status === 'failed' && isHtmlUnavailableError(job.error_message)
  )
  const pdfUrl = paper.pdf_url || `https://arxiv.org/pdf/${paper.arxiv_id}`
  if (sectionList.length === 0) {
    return (
      <div className="sections-tab">
        <div className="artifact-actions">
          <div>
            <strong>
              {htmlUnavailable
                ? 'HTML 본문 미지원'
                : isRunning
                ? '본문 추출 중'
                : job?.status === 'failed'
                  ? '본문 추출 실패'
                  : '본문 추출 필요'}
            </strong>
            {htmlUnavailable ? (
              <>
                <span>이 논문은 arXiv HTML 본문을 제공하지 않아 자동 추출이 어렵습니다.</span>
                <span>PDF 원문을 직접 확인해 주세요.</span>
              </>
            ) : (
              <span>
                {job?.status === 'failed'
                  ? job.error_message
                  : '논문 원문에서 본문 섹션을 추출합니다.'}
              </span>
            )}
          </div>
          {htmlUnavailable ? (
            <a
              className="artifact-action-link"
              href={pdfUrl}
              target="_blank"
              rel="noreferrer"
            >
              PDF 원문 보기
            </a>
          ) : (
            <button type="button" disabled={isRunning} onClick={onGenerate}>
              {isRunning ? '추출 중…' : job?.status === 'failed' ? '다시 시도' : '본문 추출'}
            </button>
          )}
        </div>
        {!htmlUnavailable && (
          <div className="artifact-empty">아직 추출된 본문 섹션이 없습니다.</div>
        )}
      </div>
    )
  }

  return (
    <div className="section-list">
      {sectionList.map((section) => (
        <section
          className="section-card"
          key={`${section.section_order}-${section.section_title}`}
        >
          <span className="section-card__order">SECTION {section.section_order}</span>
          <h3>{section.section_title || '제목 없는 섹션'}</h3>
          <p>{section.section_text || '본문 내용이 없습니다.'}</p>
        </section>
      ))}
    </div>
  )
}

function SummaryTab({ summary, job, canSummarize, onGenerate }) {
  const isRunning = job?.status === 'pending' || job?.status === 'running'
  const statusLabels = {
    pending: '요약 대기 중',
    running: '요약 생성 중',
    completed: '요약 생성 완료',
    failed: '요약 생성 실패',
  }
  return (
    <div className="summary-tab">
      <div className="artifact-actions">
        <div>
          <strong>{job ? statusLabels[job.status] : '논문 요약'}</strong>
          <span>
            {job?.status === 'failed'
              ? job.error_message
              : '추출된 본문을 기반으로 최종 요약을 생성합니다.'}
          </span>
        </div>
        <button
          type="button"
          disabled={!canSummarize || isRunning}
          onClick={onGenerate}
        >
          {isRunning ? '생성 중…' : summary ? '요약 다시 생성' : '요약 생성'}
        </button>
      </div>
      {!canSummarize && (
        <div className="artifact-empty">요약하려면 먼저 본문을 추출해야 합니다.</div>
      )}
      {canSummarize && !summary && !isRunning && (
        <div className="artifact-empty">아직 생성된 논문 요약이 없습니다.</div>
      )}
      {summary && (
        <section className="summary-card">
          <div className="artifact-meta">
            <span>모델 {summary.model_name || '정보 없음'}</span>
            <span>섹션 {summary.section_count}개</span>
            <span>청크 {summary.chunk_count}개</span>
          </div>
          <MarkdownContent text={summary.summary_text} />
        </section>
      )}
    </div>
  )
}

function TranslationsTab({ translations, job, canTranslate, onGenerate }) {
  const isRunning = job?.status === 'pending' || job?.status === 'running'
  const statusLabels = {
    pending: '번역 대기 중',
    running: '번역 생성 중',
    completed: '번역 생성 완료',
    failed: '번역 생성 실패',
  }
  return (
    <div className="translation-tab">
      <div className="artifact-actions">
        <div>
          <strong>{job ? statusLabels[job.status] : '요약 번역'}</strong>
          <span>
            {job?.status === 'failed'
              ? job.error_message
              : '최종 논문 요약을 한국어로 번역합니다.'}
          </span>
        </div>
        <button
          type="button"
          disabled={!canTranslate || isRunning}
          onClick={onGenerate}
        >
          {isRunning
            ? '번역 중…'
            : translations.length > 0
              ? '번역 다시 생성'
              : '한국어 번역 생성'}
        </button>
      </div>
      {!canTranslate && (
        <div className="artifact-empty">번역하려면 먼저 요약을 생성해야 합니다.</div>
      )}
      {canTranslate && translations.length === 0 && !isRunning && (
        <div className="artifact-empty">아직 생성된 번역 결과가 없습니다.</div>
      )}
      {translations.length > 0 && (
        <div className="translation-list">
          {translations.map((translation) => (
            <section className="translation-card" key={translation.id}>
              <div className="artifact-meta">
                <strong>
                  {TRANSLATION_TYPE_LABELS[translation.translation_type]
                    || translation.translation_type}
                </strong>
                <span>
                  {translation.source_language} → {translation.target_language}
                </span>
                {translation.model_name && <span>모델 {translation.model_name}</span>}
              </div>
              <MarkdownContent text={translation.translated_text} />
            </section>
          ))}
        </div>
      )}
    </div>
  )
}

export default function PaperDetail({ paper, loading, onPaperUpdated }) {
  const [activeTab, setActiveTab] = useState('overview')
  const [artifacts, setArtifacts] = useState(EMPTY_ARTIFACTS)
  const [artifactLoading, setArtifactLoading] = useState(false)
  const [artifactError, setArtifactError] = useState('')
  const [extractionJob, setExtractionJob] = useState(null)
  const [summaryJob, setSummaryJob] = useState(null)
  const [translationJob, setTranslationJob] = useState(null)

  const paperArtifacts = artifacts.paperId === paper?.arxiv_id
    ? artifacts
    : EMPTY_ARTIFACTS
  const currentExtractionJob = extractionJob?.arxiv_id === paper?.arxiv_id
    ? extractionJob
    : paper?.latest_extraction_job || null
  const extractionJobId = currentExtractionJob?.id
  const extractionJobStatus = currentExtractionJob?.status
  const summaryJobId = summaryJob?.id
  const summaryJobStatus = summaryJob?.status
  const translationJobId = translationJob?.id
  const translationJobStatus = translationJob?.status

  useEffect(() => {
    if (!summaryJobId || !['pending', 'running'].includes(summaryJobStatus)) {
      return undefined
    }

    let cancelled = false
    const pollSummaryJob = async () => {
      try {
        const job = await getProcessingJob(summaryJobId)
        if (cancelled) return
        setSummaryJob(job)
        if (job.status === 'completed') {
          const summary = await getPaperSummary(paper.arxiv_id)
          if (cancelled) return
          setArtifacts((current) => ({
            ...(current.paperId === paper.arxiv_id ? current : EMPTY_ARTIFACTS),
            paperId: paper.arxiv_id,
            summary,
          }))
          await onPaperUpdated?.(paper.arxiv_id)
        }
      } catch (requestError) {
        if (!cancelled) setArtifactError(requestError.message)
      }
    }

    const timer = window.setInterval(pollSummaryJob, 2000)
    pollSummaryJob()
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [paper?.arxiv_id, summaryJobId, summaryJobStatus, onPaperUpdated])

  useEffect(() => {
    if (
      !translationJobId
      || !['pending', 'running'].includes(translationJobStatus)
    ) {
      return undefined
    }

    let cancelled = false
    const pollTranslationJob = async () => {
      try {
        const job = await getProcessingJob(translationJobId)
        if (cancelled) return
        setTranslationJob(job)
        if (job.status === 'completed') {
          const translations = await getPaperTranslations(paper.arxiv_id)
          if (cancelled) return
          setArtifacts((current) => ({
            ...(current.paperId === paper.arxiv_id ? current : EMPTY_ARTIFACTS),
            paperId: paper.arxiv_id,
            translations,
          }))
          await onPaperUpdated?.(paper.arxiv_id)
        }
      } catch (requestError) {
        if (!cancelled) setArtifactError(requestError.message)
      }
    }

    const timer = window.setInterval(pollTranslationJob, 2000)
    pollTranslationJob()
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [paper?.arxiv_id, translationJobId, translationJobStatus, onPaperUpdated])

  useEffect(() => {
    if (
      !extractionJobId
      || !['pending', 'running'].includes(extractionJobStatus)
    ) {
      return undefined
    }

    let cancelled = false
    const pollExtractionJob = async () => {
      try {
        const job = await getProcessingJob(extractionJobId)
        if (cancelled) return
        setExtractionJob(job)
        if (job.status === 'completed') {
          const sections = await getPaperSections(paper.arxiv_id)
          if (cancelled) return
          setArtifacts((current) => ({
            ...(current.paperId === paper.arxiv_id ? current : EMPTY_ARTIFACTS),
            paperId: paper.arxiv_id,
            sections,
          }))
          await onPaperUpdated?.(paper.arxiv_id)
        }
      } catch (requestError) {
        if (!cancelled) setArtifactError(requestError.message)
      }
    }

    const timer = window.setInterval(pollExtractionJob, 2000)
    pollExtractionJob()
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [paper?.arxiv_id, extractionJobId, extractionJobStatus, onPaperUpdated])

  const selectTab = async (tabId) => {
    setActiveTab(tabId)
    setArtifactError('')
    const cachedArtifact = tabId === 'overview' || tabId === 'chat'
      ? true
      : tabId === 'summary' && !paper.has_summary
        ? false
        : paperArtifacts[tabId]
    if (cachedArtifact !== null) return

    const fetchers = {
      sections: getPaperSections,
      summary: getPaperSummary,
      translations: getPaperTranslations,
    }
    setArtifactLoading(true)
    try {
      const data = await fetchers[tabId](paper.arxiv_id)
      setArtifacts((current) => ({
        ...(current.paperId === paper.arxiv_id ? current : EMPTY_ARTIFACTS),
        paperId: paper.arxiv_id,
        [tabId]: data,
      }))
    } catch (requestError) {
      setArtifactError(requestError.message)
    } finally {
      setArtifactLoading(false)
    }
  }

  const generateSummary = async () => {
    const hasSummary = Boolean(paper.has_summary || paperArtifacts.summary)
    setArtifactError('')
    try {
      const response = await summarizePaper(paper.arxiv_id, hasSummary)
      setSummaryJob(response.job)
      if (response.job.status === 'completed') {
        const summary = await getPaperSummary(paper.arxiv_id)
        setArtifacts((current) => ({
          ...(current.paperId === paper.arxiv_id ? current : EMPTY_ARTIFACTS),
          paperId: paper.arxiv_id,
          summary,
        }))
        await onPaperUpdated?.(paper.arxiv_id)
      }
    } catch (requestError) {
      setArtifactError(requestError.message)
    }
  }

  const generateExtraction = async () => {
    setArtifactError('')
    try {
      const response = await extractPaper(paper.arxiv_id)
      setExtractionJob(response.job)
      if (response.job.status === 'completed') {
        const sections = await getPaperSections(paper.arxiv_id)
        setArtifacts((current) => ({
          ...(current.paperId === paper.arxiv_id ? current : EMPTY_ARTIFACTS),
          paperId: paper.arxiv_id,
          sections,
        }))
        await onPaperUpdated?.(paper.arxiv_id)
      }
    } catch (requestError) {
      setArtifactError(requestError.message)
    }
  }

  const generateTranslation = async () => {
    const hasTranslation = Boolean(
      paper.translation_count > 0
      || paperArtifacts.translations?.length > 0
    )
    setArtifactError('')
    try {
      const response = await translatePaper(
        paper.arxiv_id,
        'ko',
        hasTranslation,
      )
      setTranslationJob(response.job)
      if (response.job.status === 'completed') {
        const translations = await getPaperTranslations(paper.arxiv_id)
        setArtifacts((current) => ({
          ...(current.paperId === paper.arxiv_id ? current : EMPTY_ARTIFACTS),
          paperId: paper.arxiv_id,
          translations,
        }))
        await onPaperUpdated?.(paper.arxiv_id)
      }
    } catch (requestError) {
      setArtifactError(requestError.message)
    }
  }

  if (loading) {
    return <div className="empty-state">논문 상세 정보를 불러오는 중입니다.</div>
  }
  if (!paper) {
    return <div className="empty-state">목록에서 논문을 선택해 주세요.</div>
  }

  const tabs = [
    { id: 'overview', label: '개요' },
    { id: 'sections', label: `본문 섹션 ${paper.section_count}` },
    { id: 'summary', label: paper.has_summary ? '요약 완료' : '요약' },
    { id: 'translations', label: `번역 ${paper.translation_count}` },
    { id: 'chat', label: '질의응답' },
  ]

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

      <nav className="paper-tabs" aria-label="논문 상세 콘텐츠" role="tablist">
        {tabs.map((tab) => (
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={activeTab === tab.id ? 'paper-tabs__active' : ''}
            disabled={artifactLoading}
            key={tab.id}
            onClick={() => selectTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <div className="paper-tab-panel" role="tabpanel" aria-busy={artifactLoading}>
        {artifactError && <div className="error-banner" role="alert">{artifactError}</div>}
        {artifactLoading && <div className="artifact-empty">콘텐츠를 불러오는 중입니다.</div>}
        {!artifactLoading && !artifactError && activeTab === 'overview' && (
          <OverviewTab paper={paper} />
        )}
        {!artifactLoading && !artifactError && activeTab === 'sections' && (
          <SectionsTab
            paper={paper}
            sections={paperArtifacts.sections || []}
            job={currentExtractionJob}
            onGenerate={generateExtraction}
          />
        )}
        {!artifactLoading && !artifactError && activeTab === 'summary' && (
          <SummaryTab
            summary={paperArtifacts.summary}
            job={summaryJob}
            canSummarize={paper.section_count > 0}
            onGenerate={generateSummary}
          />
        )}
        {!artifactLoading && !artifactError && activeTab === 'translations' && (
          <TranslationsTab
            translations={paperArtifacts.translations || []}
            job={translationJob}
            canTranslate={Boolean(paper.has_summary || paperArtifacts.summary)}
            onGenerate={generateTranslation}
          />
        )}
        {!artifactLoading && !artifactError && activeTab === 'chat' && (
          <PaperChat key={paper.arxiv_id} paper={paper} />
        )}
      </div>
    </article>
  )
}
