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
          <img className="brand-mark" src="/brand/symbol-white.svg" alt="" width="52" height="52" aria-hidden="true" />
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
