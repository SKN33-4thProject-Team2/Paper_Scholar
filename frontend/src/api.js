const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
).replace(/\/$/, '')

async function request(pathOrUrl, options = {}) {
  const url = pathOrUrl.startsWith('http')
    ? pathOrUrl
    : `${API_BASE_URL}${pathOrUrl}`
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = body.detail || ''
    } catch {
      detail = ''
    }
    throw new Error(detail || `API 요청에 실패했습니다. (${response.status})`)
  }

  return response.json()
}

export function getHealth() {
  return request('/health/')
}

export function getPapers(url) {
  return request(url || '/papers/')
}

export function getPaper(arxivId) {
  return request(`/papers/${encodeURIComponent(arxivId)}/`)
}

export function getPaperSections(arxivId) {
  return request(`/papers/${encodeURIComponent(arxivId)}/sections/`)
}

export function getPaperSummary(arxivId) {
  return request(`/papers/${encodeURIComponent(arxivId)}/summary/`)
}

export function summarizePaper(arxivId, force = false) {
  return request(`/papers/${encodeURIComponent(arxivId)}/summarize/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force }),
  })
}

export function getPaperTranslations(arxivId) {
  return request(`/papers/${encodeURIComponent(arxivId)}/translations/`)
}

export function translatePaper(arxivId, targetLanguage = 'ko', force = false) {
  return request(`/papers/${encodeURIComponent(arxivId)}/translate/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      target_language: targetLanguage,
      force,
    }),
  })
}

export function searchArxiv(params) {
  return request('/search/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
}

export function savePapers(papers, extractContent = true) {
  return request('/papers/save/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      papers,
      extract_content: extractContent,
    }),
  })
}

export function getProcessingJob(jobId) {
  return request(`/jobs/${encodeURIComponent(jobId)}/`)
}
