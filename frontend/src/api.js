const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
).replace(/\/$/, '')

const ACCESS_TOKEN_KEY = 'paper-scholar-access-token'
const REFRESH_TOKEN_KEY = 'paper-scholar-refresh-token'
let refreshPromise = null

export function hasAuthSession() {
  return Boolean(
    window.localStorage.getItem(ACCESS_TOKEN_KEY)
    || window.localStorage.getItem(REFRESH_TOKEN_KEY),
  )
}

export function setAuthTokens(tokens) {
  window.localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access)
  window.localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh)
}

export function clearAuthTokens() {
  window.localStorage.removeItem(ACCESS_TOKEN_KEY)
  window.localStorage.removeItem(REFRESH_TOKEN_KEY)
}

async function refreshAccessToken() {
  const refresh = window.localStorage.getItem(REFRESH_TOKEN_KEY)
  if (!refresh) return null
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE_URL}/auth/token/refresh/`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh }),
    })
      .then(async (response) => {
        if (!response.ok) throw new Error('로그인이 만료되었습니다.')
        const tokens = await response.json()
        window.localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access)
        return tokens.access
      })
      .catch((error) => {
        clearAuthTokens()
        throw error
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

async function request(pathOrUrl, options = {}) {
  const {
    auth = true,
    retryAuth = true,
    ...fetchOptions
  } = options
  const url = pathOrUrl.startsWith('http')
    ? pathOrUrl
    : `${API_BASE_URL}${pathOrUrl}`
  const accessToken = window.localStorage.getItem(ACCESS_TOKEN_KEY)
  const response = await fetch(url, {
    ...fetchOptions,
    headers: {
      Accept: 'application/json',
      ...(auth && accessToken
        ? { Authorization: `Bearer ${accessToken}` }
        : {}),
      ...fetchOptions.headers,
    },
  })

  if (response.status === 401 && auth && retryAuth) {
    const refreshedToken = await refreshAccessToken()
    if (refreshedToken) {
      return request(pathOrUrl, { ...options, retryAuth: false })
    }
  }

  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = body.detail || Object.values(body).flat().join(' ')
    } catch {
      detail = ''
    }
    throw new Error(detail || `API 요청에 실패했습니다. (${response.status})`)
  }

  return response.json()
}

export function registerUser(payload) {
  return request('/auth/register/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    auth: false,
    retryAuth: false,
  })
}

export async function loginUser(username, password) {
  const tokens = await request('/auth/token/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
    auth: false,
    retryAuth: false,
  })
  setAuthTokens(tokens)
  return tokens
}

export function getCurrentUser() {
  return request('/auth/me/')
}

export function getHealth() {
  return request('/health/', { auth: false, retryAuth: false })
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

export function askPaper(arxivId, question) {
  return request(`/papers/${encodeURIComponent(arxivId)}/ask/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
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

export function createSupervisorPlan(message) {
  return request('/supervisor/plan/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
}
