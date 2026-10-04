import { supabase } from './supabase'

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

async function getAccessToken() {
  const { data, error } = await supabase.auth.getSession()
  if (error) throw error
  return data.session?.access_token || null
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {})
  const token = await getAccessToken()

  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_URL}${path}`, { ...options, headers })

  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail || `Request failed (${response.status})`)
  }

  return response.status === 204 ? null : response.json()
}

export const api = {
  me: () => request('/auth/me'),
  listDocuments: () => request('/documents'),
  uploadDocument: (formData) => request('/documents', { method: 'POST', body: formData }),
  deleteDocument: (id) => request(`/documents/${id}`, { method: 'DELETE' }),
  reindexDocument: (id) => request(`/documents/${id}/reindex`, { method: 'POST' }),
  search: (query) => request(`/search?q=${encodeURIComponent(query)}&limit=2`),
  chat: (question) => request('/chat', { method: 'POST', body: JSON.stringify({ question }) }),

  async fileBlob(id, download = false) {
    const token = await getAccessToken()
    const response = await fetch(`${API_URL}/documents/${id}/file?download=${download}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })

    if (!response.ok) throw new Error('Could not fetch file')
    return response.blob()
  },
}
