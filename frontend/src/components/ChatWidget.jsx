import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

export default function ChatWidget() {
  const [open, setOpen] = useState(false)
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const endRef = useRef(null)

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, open])

  const ask = async (e) => {
    e.preventDefault()
    const q = question.trim()
    if (!q || loading) return

    setMessages((m) => [...m, { role: 'user', text: q }])
    setQuestion('')
    setLoading(true)

    try {
      const data = await api.chat(q)
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          text: data.answer,
          sources: data.sources || [],
        },
      ])
    } catch (error) {
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          text: `Could not reach Ask CertiKeep: ${error.message}`,
          sources: [],
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      {open && (
        <section className="chat-widget-panel" aria-label="Ask CertiKeep chat">
          <header className="chat-widget-header">
            <div>
              <strong>Ask CertiKeep</strong>
              <span>Answers from your vault</span>
            </div>
            <button
              type="button"
              className="chat-widget-close"
              onClick={() => setOpen(false)}
              aria-label="Close Ask CertiKeep"
            >
              ×
            </button>
          </header>

          <div className="chat-widget-messages">
            {messages.length === 0 && (
              <div className="chat-widget-empty">
                <b>Ask about your documents.</b>
                <span>Try “When was my Frontend certificate issued?”</span>
              </div>
            )}

            {messages.map((message, index) => (
              <div className={`chat-widget-message ${message.role}`} key={index}>
                <div>{message.text}</div>

                {message.sources?.length > 0 && (
                  <div className="chat-widget-sources">
                    <b>Sources</b>
                    {message.sources.map((source, sourceIndex) => (
                      <div key={sourceIndex}>
                        [{sourceIndex + 1}] {source.title || source.filename}
                        {source.filename && source.title !== source.filename
                          ? ` — ${source.filename}`
                          : ''}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="chat-widget-message assistant chat-widget-thinking">
                Looking through your documents…
              </div>
            )}
            <div ref={endRef} />
          </div>

          <form className="chat-widget-input" onSubmit={ask}>
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about your documents…"
              aria-label="Ask CertiKeep a question"
            />
            <button type="submit" disabled={loading || !question.trim()}>
              ↑
            </button>
          </form>
        </section>
      )}

      <button
        type="button"
        className={`chat-widget-launcher ${open ? 'is-open' : ''}`}
        onClick={() => setOpen((value) => !value)}
        aria-label={open ? 'Close Ask CertiKeep' : 'Open Ask CertiKeep'}
        title="Ask CertiKeep"
      >
        {open ? '×' : '✦'}
      </button>
    </>
  )
}
