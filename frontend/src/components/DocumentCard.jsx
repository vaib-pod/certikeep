import { api } from '../api'

export default function DocumentCard({ doc, onDelete, onReindex, score }) {
  const preview = async () => {
    const blob = await api.fileBlob(doc.id, false)
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank')
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }
  const download = async () => {
    const blob = await api.fileBlob(doc.id, true)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = doc.original_name; a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <div className="doc-card">
      <div className="doc-icon">▤</div>
      <div className="doc-info">
        <strong>{doc.title}</strong>
        <span className={`tag ${doc.category === 'Certificates' ? 'tag-yellow' : doc.category === 'IDs' ? 'tag-cyan' : 'tag-green'}`}>{doc.category}</span>
        <small>{doc.original_name}{score !== undefined ? ` • match ${Math.round(score * 100)}%` : ''}</small>
        {doc.ai_indexed ? <small className="ai-ready">✓ AI indexed</small> : <small className="ai-pending">⚠ Stored safely • AI indexing pending</small>}
      </div>
      <div className="doc-actions">
        <button onClick={preview}>Preview</button>
        <button onClick={download}>Download</button>
        {!doc.ai_indexed && onReindex && <button onClick={() => onReindex(doc.id)}>Retry AI</button>}
        {onDelete && <button className="danger" onClick={() => onDelete(doc.id)}>Delete</button>}
      </div>
    </div>
  )
}
