import { useState } from 'react'
import { useAuth } from './auth-context'

const EMPTY_FORM = {
  username: '',
  email: '',
  password: '',
  passwordConfirm: '',
}

export default function AuthPage() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const updateField = (event) => {
    setForm((current) => ({
      ...current,
      [event.target.name]: event.target.value,
    }))
  }

  const switchMode = (nextMode) => {
    setMode(nextMode)
    setError('')
    setForm(EMPTY_FORM)
  }

  const submit = async (event) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      if (mode === 'register') {
        await register({
          username: form.username.trim(),
          email: form.email.trim(),
          password: form.password,
          password_confirm: form.passwordConfirm,
        })
      } else {
        await login({
          username: form.username.trim(),
          password: form.password,
        })
      }
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-story">
        <div className="auth-story__brand">
          <span className="brand-mark brand-mark--book" aria-hidden="true">
            <svg viewBox="0 0 72 62" role="presentation">
              <defs>
                <linearGradient id="paper-logo-blue-auth" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="#70b6db" />
                  <stop offset="1" stopColor="#2f6f9d" />
                </linearGradient>
              </defs>
              <path className="brand-mark__spark" d="M36 2l3.7 10.3L50 16l-10.3 3.7L36 30l-3.7-10.3L22 16l10.3-3.7L36 2z" />
              <path className="brand-mark__book brand-mark__book--auth" d="M35.5 27.7C28.8 22.5 20.4 21 10 23.6v29.2c10.4-2.6 18.8-1.1 25.5 4.1V27.7z" />
              <path className="brand-mark__book brand-mark__book--auth" d="M36.5 27.7C43.2 22.5 51.6 21 62 23.6v29.2c-10.4-2.6-18.8-1.1-25.5 4.1V27.7z" />
              <path className="brand-mark__spine" d="M36 28v29" />
              <path className="brand-mark__line" d="M15 31c5.4-1 10.2-.2 14.5 2.4M15 39c5.4-1 10.2-.2 14.5 2.4M57 31c-5.4-1-10.2-.2-14.5 2.4M57 39c-5.4-1-10.2-.2-14.5 2.4" />
            </svg>
          </span>
          <span><strong><span>Paper</span> <em>Scholar</em></strong><small>학술 논문 작업실</small></span>
        </div>
        <div className="auth-story__copy">
          <span className="eyebrow">RESEARCH, MADE CLEAR</span>
          <h1>논문을 찾고,<br />이해하고, 정리하는 시간.</h1>
          <p>검색부터 본문 추출·요약·번역까지<br />나의 연구 흐름을 한곳에서 관리해 보세요.</p>
          <div className="auth-story__topics"><span>논문 검색</span><span>본문 요약</span><span>한국어 번역</span></div>
        </div>
        <p className="auth-story__footnote">근거가 있는 연구를 위한 개인 작업실</p>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <div>
            <span className="eyebrow">MY PAPER WORKSPACE</span>
            <h1>{mode === 'login' ? '내 서재로 돌아가기' : '개인 서재 만들기'}</h1>
            <p>저장한 논문과 요약·번역 결과를 계정별로 관리합니다.</p>
          </div>

          <div className="auth-tabs" role="tablist" aria-label="인증 방식">
            <button
              type="button"
              className={mode === 'login' ? 'auth-tabs__active' : ''}
              onClick={() => switchMode('login')}
            >
              로그인
            </button>
            <button
              type="button"
              className={mode === 'register' ? 'auth-tabs__active' : ''}
              onClick={() => switchMode('register')}
            >
              회원가입
            </button>
          </div>

          {error && <div className="error-banner" role="alert">{error}</div>}
          <form className="auth-form" onSubmit={submit}>
            <label>
              아이디
              <input
                autoComplete="username"
                name="username"
                required
                value={form.username}
                onChange={updateField}
              />
            </label>
            {mode === 'register' && (
              <label>
                이메일
                <input
                  autoComplete="email"
                  name="email"
                  required
                  type="email"
                  value={form.email}
                  onChange={updateField}
                />
              </label>
            )}
            <label>
              비밀번호
              <input
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                minLength="8"
                name="password"
                required
                type="password"
                value={form.password}
                onChange={updateField}
              />
            </label>
            {mode === 'register' && (
              <label>
                비밀번호 확인
                <input
                  autoComplete="new-password"
                  minLength="8"
                  name="passwordConfirm"
                  required
                  type="password"
                  value={form.passwordConfirm}
                  onChange={updateField}
                />
              </label>
            )}
            <button type="submit" disabled={submitting}>
              {submitting
                ? '처리 중…'
                : mode === 'login' ? '로그인' : '회원가입 후 로그인'}
            </button>
          </form>
        </div>
      </section>
    </main>
  )
}
