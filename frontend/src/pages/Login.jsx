import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { supabase } from '../supabase'
import WindowDots from '../components/WindowDots'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      })

      if (signInError) throw signInError
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setError(err.message || 'Could not log in')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page page-frame">
      <WindowDots />
      <div className="brand">CertiKeep<span className="spark">✦</span></div>

      <form className="auth-card" onSubmit={submit}>
        <h1>Welcome back</h1>
        <p>Log in to your CertiKeep account</p>

        {error && <div className="error">{error}</div>}

        <label>
          Email
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            type="email"
            autoComplete="email"
            required
          />
        </label>

        <label>
          Password
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            autoComplete="current-password"
            required
          />
        </label>

        <button className="pixel-btn primary" type="submit" disabled={loading}>
          {loading ? 'Logging in...' : 'Log In →'}
        </button>

        <small>New here? <Link to="/register">Create an account</Link></small>
      </form>
    </div>
  )
}
