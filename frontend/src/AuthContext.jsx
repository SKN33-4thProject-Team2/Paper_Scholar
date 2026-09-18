import { useEffect, useMemo, useState } from 'react'
import {
  clearAuthTokens,
  getCurrentUser,
  hasAuthSession,
  loginUser,
  registerUser,
} from './api'
import { AuthContext } from './auth-context'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(() => hasAuthSession())

  useEffect(() => {
    let cancelled = false
    const restoreSession = async () => {
      if (!hasAuthSession()) {
        return
      }
      try {
        const currentUser = await getCurrentUser()
        if (!cancelled) setUser(currentUser)
      } catch {
        clearAuthTokens()
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    restoreSession()
    return () => {
      cancelled = true
    }
  }, [])

  const value = useMemo(() => ({
    user,
    loading,
    login: async ({ username, password }) => {
      await loginUser(username, password)
      const currentUser = await getCurrentUser()
      setUser(currentUser)
      return currentUser
    },
    register: async (payload) => {
      await registerUser(payload)
      await loginUser(payload.username, payload.password)
      const currentUser = await getCurrentUser()
      setUser(currentUser)
      return currentUser
    },
    logout: () => {
      clearAuthTokens()
      setUser(null)
    },
  }), [loading, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
