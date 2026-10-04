import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import Layout from '../components/Layout'
import DocumentCard from '../components/DocumentCard'

const EMPTY_FORM = { title: '', category: 'Certificates', file: null }

export default function Dashboard() {
  const [documents, setDocuments] = useState([])
  const [results, setResults] = useState([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState('')
  const [activeSection, setActiveSection] = useState('Home')
  const [searchActive, setSearchActive] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)

  const load = async () => setDocuments(await api.listDocuments())

  useEffect(() => {
    load().catch((error) => setMessage(error.message))
  }, [])

  useEffect(() => {
    if (!uploadOpen) return
    const closeOnEscape = (event) => {
      if (event.key === 'Escape' && !uploading) setUploadOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [uploadOpen, uploading])

  const counts = useMemo(
    () => ({
      Certificates: documents.filter((doc) => doc.category === 'Certificates').length,
      IDs: documents.filter((doc) => doc.category === 'IDs').length,
      'Other Docs': documents.filter((doc) => doc.category === 'Other Docs').length,
    }),
    [documents],
  )

  const visibleDocuments = useMemo(() => {
    if (activeSection === 'Home') {
      return [...documents]
        .sort((a, b) => new Date(b.uploaded_at) - new Date(a.uploaded_at))
        .slice(0, 6)
    }
    return documents.filter((doc) => doc.category === activeSection)
  }, [documents, activeSection])

  const search = async (event) => {
    event.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    setMessage('')
    try {
      const matches = await api.search(query)
      setResults(matches.slice(0, 2))
      setSearchActive(true)
    } catch (error) {
      setMessage(error.message)
    } finally {
      setLoading(false)
    }
  }

  const chooseSection = (section) => {
    setActiveSection(section)
    setSearchActive(false)
    setResults([])
    setQuery('')
    setMessage('')
  }

  const openUpload = () => {
    const category = activeSection === 'Home' ? 'Certificates' : activeSection
    setForm({ ...EMPTY_FORM, category })
    setUploadOpen(true)
  }

  const closeUpload = () => {
    if (uploading) return
    setUploadOpen(false)
    setForm(EMPTY_FORM)
  }

  const upload = async (event) => {
    event.preventDefault()
    if (!form.file) return

    const data = new FormData()
    data.append('title', form.title || form.file.name)
    data.append('category', form.category)
    data.append('file', form.file)

    setUploading(true)
    setMessage('')

    try {
      const doc = await api.uploadDocument(data)
      await load()
      setUploadOpen(false)
      setForm(EMPTY_FORM)
      setActiveSection(doc.category || form.category)
      setSearchActive(false)
      setResults([])
      setMessage(
        doc.ai_indexed
          ? 'Uploaded and AI indexed successfully.'
          : 'Document stored successfully. AI indexing is pending/unavailable; you can retry later.',
      )
    } catch (error) {
      setMessage(error.message)
    } finally {
      setUploading(false)
    }
  }

  const remove = async (id) => {
    if (!window.confirm('Delete this document?')) return
    await api.deleteDocument(id)
    await load()
    setResults((current) => current.filter((doc) => doc.id !== id))
  }

  const reindex = async (id) => {
    setMessage('Retrying AI indexing...')
    try {
      await api.reindexDocument(id)
      await load()
      setMessage('AI indexing completed successfully.')
    } catch (error) {
      setMessage(error.message)
    }
  }

  const sectionTitle = activeSection === 'Home' ? 'Recent documents' : activeSection

  return (
    <Layout
      counts={counts}
      activeSection={activeSection}
      onSectionChange={chooseSection}
      onUpload={openUpload}
    >
      <div className="dashboard-heading">
        <div>
          <h1>Welcome back! 👋</h1>
          <p className="muted">Your document vault is ready.</p>
        </div>
        <button type="button" className="mobile-upload-btn" onClick={openUpload}>
          ＋ Upload
        </button>
      </div>

      <form className="search-bar" onSubmit={search}>
        <span>⌕</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Find my Python certificate from IITG..."
        />
        <button aria-label="Search your vault">{loading ? '...' : '→'}</button>
      </form>

      {message && <div className="notice">{message}</div>}

      {searchActive ? (
        <section className="document-section">
          <div className="section-heading-row">
            <div>
              <h2>AI search results</h2>
              <p className="muted small-muted">Showing the two closest matches.</p>
            </div>
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setSearchActive(false)
                setResults([])
                setQuery('')
              }}
            >
              Clear search
            </button>
          </div>

          {results.length === 0 ? (
            <div className="empty-state">
              <strong>No close match found.</strong>
              <span>Try describing the organization, document type, topic, or year.</span>
            </div>
          ) : (
            results.map((result) => (
              <DocumentCard key={result.id} doc={result} score={result.score} />
            ))
          )}
        </section>
      ) : (
        <section className="document-section">
          <div className="section-heading-row">
            <div>
              <h2>{sectionTitle}</h2>
              {activeSection === 'Home' && (
                <p className="muted small-muted">Your latest documents, all in one place.</p>
              )}
            </div>
            {activeSection !== 'Home' && (
              <span className="section-count">
                {counts[activeSection] ?? 0} {(counts[activeSection] ?? 0) === 1 ? 'document' : 'documents'}
              </span>
            )}
          </div>

          {visibleDocuments.length === 0 ? (
            <div className="empty-state">
              <strong>No documents here yet.</strong>
              <span>Upload your first {activeSection === 'Home' ? 'document' : activeSection.toLowerCase()}.</span>
              <button type="button" className="pixel-btn primary" onClick={openUpload}>
                ＋ Upload document
              </button>
            </div>
          ) : (
            visibleDocuments.map((doc) => (
              <DocumentCard
                key={doc.id}
                doc={doc}
                onDelete={remove}
                onReindex={reindex}
              />
            ))
          )}
        </section>
      )}

      {uploadOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeUpload()
          }}
        >
          <section className="upload-modal" role="dialog" aria-modal="true" aria-labelledby="upload-title">
            <div className="upload-modal-header">
              <div>
                <h2 id="upload-title">Upload a document</h2>
                <p>Store it once and let CertiKeep index it for search.</p>
              </div>
              <button type="button" className="modal-close" onClick={closeUpload} aria-label="Close upload dialog">
                ×
              </button>
            </div>

            <form className="modal-upload-form" onSubmit={upload}>
              <label>
                Document title
                <input
                  placeholder="e.g. Frontend course certificate"
                  value={form.title}
                  onChange={(event) => setForm({ ...form, title: event.target.value })}
                />
              </label>

              <label>
                Category
                <select
                  value={form.category}
                  onChange={(event) => setForm({ ...form, category: event.target.value })}
                >
                  <option>Certificates</option>
                  <option>IDs</option>
                  <option>Other Docs</option>
                </select>
              </label>

              <label className="file-field">
                File
                <input
                  type="file"
                  accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
                  onChange={(event) => setForm({ ...form, file: event.target.files?.[0] || null })}
                  required
                />
              </label>

              <div className="upload-modal-actions">
                <button type="button" className="modal-secondary" onClick={closeUpload} disabled={uploading}>
                  Cancel
                </button>
                <button className="pixel-btn primary" disabled={uploading || !form.file}>
                  {uploading ? 'Processing...' : 'Upload + AI index'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </Layout>
  )
}
