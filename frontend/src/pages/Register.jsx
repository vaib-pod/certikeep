import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, setToken } from '../api'
import WindowDots from '../components/WindowDots'

export default function Register() {
  const [form, setForm] = useState({ name:'', email:'', password:'' })
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const submit = async (e) => {
    e.preventDefault(); setError('')
    try { const data = await api.register(form); setToken(data.access_token); navigate('/dashboard') }
    catch (err) { setError(err.message) }
  }
  return <div className="auth-page page-frame"><WindowDots/><div className="brand">CertiKeep<span className="spark">✦</span></div><form className="auth-card signup" onSubmit={submit}><h1>Create your vault</h1><p>Keep important documents organized and searchable.</p>{error && <div className="error">{error}</div>}<label>Full name<input value={form.name} onChange={e=>setForm({...form,name:e.target.value})} required/></label><label>Email<input type="email" value={form.email} onChange={e=>setForm({...form,email:e.target.value})} required/></label><label>Password<input type="password" minLength="8" value={form.password} onChange={e=>setForm({...form,password:e.target.value})} required/></label><button className="pixel-btn primary" type="submit">Create Account</button><small>Already have an account? <Link to="/login">Log in</Link></small></form></div>
}
