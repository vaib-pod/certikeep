import { useState } from 'react'
import Layout from '../components/Layout'
import { api } from '../api'

export default function Chat() {
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const ask = async (e) => {
    e.preventDefault(); const q = question.trim(); if(!q) return
    setMessages(m=>[...m,{role:'user',text:q}]); setQuestion(''); setLoading(true)
    try { const data = await api.chat(q); setMessages(m=>[...m,{role:'assistant',text:data.answer,sources:data.sources}]) }
    catch(e) { setMessages(m=>[...m,{role:'assistant',text:`Error: ${e.message}`,sources:[]}]) }
    finally { setLoading(false) }
  }
  return <Layout><h1>Ask CertiKeep ✦</h1><p className="muted">Ask questions only about the documents in your vault.</p><div className="chat-box">{messages.length===0 && <div className="empty-chat">Try: “Which certificates do I have from IITG?” or “When was my Python certificate issued?”</div>}{messages.map((m,i)=><div className={`chat-message ${m.role}`} key={i}><div>{m.text}</div>{m.sources?.length>0 && <div className="sources"><b>Sources</b>{m.sources.map((s,j)=><div key={j}>[{j+1}] {s.title} — {s.filename}</div>)}</div>}</div>)}{loading&&<div className="chat-message assistant">Thinking from your documents...</div>}</div><form className="chat-input" onSubmit={ask}><input value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Ask anything about your documents..."/><button className="pixel-btn primary">Ask →</button></form></Layout>
}
