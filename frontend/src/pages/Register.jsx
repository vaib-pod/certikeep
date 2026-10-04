import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { supabase } from '../supabase'
import WindowDots from '../components/WindowDots'

export default function Register() {
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setNotice('')
    setLoading(true)

    try {
      const { data, error: signUpError } = await supabase.auth.signUp({
        email: form.email.trim(),
        password: form.password,
        options: {
          data: {
            full_name: form.name.trim(),
          },
        },
      })

      if (signUpError) throw signUpError

      if (data.session) {
        navigate('/dashboard', { replace: true })
        return
      }

      setNotice('Account created. Check your email to confirm your account, then log in.')
    } catch (err) {
      setError(err.message || 'Could not create account')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page page-frame">
      <WindowDots />
      <div className="brand">CertiKeep<span className="spark">✦</span></div>

      <form className="auth-card signup" onSubmit={submit}>
        <h1>Create your vault</h1>
        <p>Keep important documents organized and searchable.</p>

        {error && <div className="error">{error}</div>}
        {notice && <div className="auth-notice">{notice}</div>}

        <label>
          Full name
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            autoComplete="name"
            required
          />
        </label>

        <label>
          Email
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            autoComplete="email"
            required
          />
        </label>

        <label>
          Password
          <input
            type="password"
            minLength="8"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            autoComplete="new-password"
            required
          />
        </label>

        <button className="pixel-btn primary" type="submit" disabled={loading}>
          {loading ? 'Creating account...' : 'Create Account'}
        </button>

        <small>Already have an account? <Link to="/login">Log in</Link></small>
      </form>
    </div>
  )
}
