import { useState } from 'react'
import {
  getPaperSections,
  getPaperSummary,
  getPaperTranslations,
} from './api'

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

function SectionsTab({ sections }) {
  if (sections.length === 0) {
    return <div className="artifact-empty">아직 추출된 본문 섹션이 없습니다.</div>
  }

  return (
    <div className="section-list">
      {sections.map((section) => (
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

function SummaryTab({ summary }) {
  if (!summary) {
    return <div className="artifact-empty">아직 생성된 논문 요약이 없습니다.</div>
  }

  return (
    <section className="summary-card">
      <div className="artifact-meta">
        <span>모델 {summary.model_name || '정보 없음'}</span>
        <span>섹션 {summary.section_count}개</span>
        <span>청크 {summary.chunk_count}개</span>
      </div>
      <p>{summary.summary_text}</p>
    </section>
  )
}

function TranslationsTab({ translations }) {
  if (translations.length === 0) {
    return <div className="artifact-empty">아직 생성된 번역 결과가 없습니다.</div>
  }

  return (
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
          <p>{translation.translated_text}</p>
        </section>
      ))}
    </div>
  )
}

export default function PaperDetail({ paper, loading }) {
  const [activeTab, setActiveTab] = useState('overview')
  const [artifacts, setArtifacts] = useState(EMPTY_ARTIFACTS)
  const [artifactLoading, setArtifactLoading] = useState(false)
  const [artifactError, setArtifactError] = useState('')

  const paperArtifacts = artifacts.paperId === paper?.arxiv_id
    ? artifacts
    : EMPTY_ARTIFACTS

  const selectTab = async (tabId) => {
    setActiveTab(tabId)
    setArtifactError('')
    const cachedArtifact = tabId === 'overview'
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
          <SectionsTab sections={paperArtifacts.sections || []} />
        )}
        {!artifactLoading && !artifactError && activeTab === 'summary' && (
          <SummaryTab summary={paperArtifacts.summary} />
        )}
        {!artifactLoading && !artifactError && activeTab === 'translations' && (
          <TranslationsTab translations={paperArtifacts.translations || []} />
        )}
      </div>
    </article>
  )
}
