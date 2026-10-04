import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, clearToken } from '../api'
import WindowDots from './WindowDots'
import ChatWidget from './ChatWidget'

const SECTION_META = [
  { key: 'Certificates', label: 'Certificates', color: 'yellow' },
  { key: 'IDs', label: 'IDs', color: 'cyan' },
  { key: 'Other Docs', label: 'Other Docs', color: 'green' },
]

export default function Layout({
  children,
  counts = {},
  activeSection = 'Home',
  onSectionChange,
  onUpload,
}) {
  const navigate = useNavigate()
  const [user, setUser] = useState(null)

  useEffect(() => {
    let cancelled = false

    api.me()
      .then((data) => {
        if (!cancelled) setUser(data)
      })
      .catch(() => {
        if (!cancelled) setUser(null)
      })

    return () => {
      cancelled = true
    }
  }, [])

  const logout = () => {
    if (window.confirm('Log out? Your documents will stay safely stored in your vault.')) {
      clearToken()
      navigate('/')
    }
  }

  const chooseSection = (section) => {
    onSectionChange?.(section)
  }

  const displayName = user?.name?.trim() || 'My profile'
  const initial = displayName.charAt(0).toUpperCase()

  return (
    <div className="app-shell">
      <WindowDots />
      <div className="brand">
        CertiKeep<span className="spark">✦</span>
      </div>

      <aside className="sidebar">
        <div className="sidebar-profile" aria-label="Signed in user">
          <div className="sidebar-profile-avatar" aria-hidden="true">{initial}</div>
          <div className="sidebar-profile-copy">
            <span className="sidebar-profile-kicker">Profile</span>
            <strong>{displayName}</strong>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Document navigation">
          <button
            type="button"
            className={`sidebar-link sidebar-home ${activeSection === 'Home' ? 'active' : ''}`}
            onClick={() => chooseSection('Home')}
          >
            <span className="sidebar-icon">⌂</span>
            <span>Home</span>
          </button>

          <div className="sidebar-label">Your vault</div>

          {SECTION_META.map((section) => (
            <button
              type="button"
              key={section.key}
              className={`sidebar-link sidebar-category category-${section.color} ${activeSection === section.key ? 'active' : ''}`}
              onClick={() => chooseSection(section.key)}
            >
              <span className={`sidebar-dot ${section.color}`} aria-hidden="true" />
              <span>{section.label}</span>
              <span className="sidebar-count">{counts[section.key] ?? 0}</span>
            </button>
          ))}

          <button type="button" className="sidebar-upload" onClick={onUpload}>
            <span>＋</span>
            <span>Upload document</span>
          </button>
        </nav>

        <button type="button" className="sidebar-logout" onClick={logout}>
          <span>↪</span>
          <span>Log out</span>
        </button>
      </aside>

      <main className="content">{children}</main>
      <ChatWidget />
    </div>
  )
}
