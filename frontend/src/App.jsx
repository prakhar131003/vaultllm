import { useState, useEffect, useRef, useCallback } from 'react'

const API = ''

function Spinner({ size = 20 }) {
  return <div className="spinner" style={{ width: size, height: size }} />
}

function App() {
  const [active, setActive] = useState('upload')
  const [health, setHealth] = useState({ status: 'loading', llm_server: false, database: false })

  useEffect(() => {
    fetch(`${API}/api/health`)
      .then(r => r.json())
      .then(setHealth)
      .catch(() => setHealth({ status: 'error', llm_server: false, database: false }))
  }, [])

  return (
    <div className="app-layout">
      <Sidebar active={active} setActive={setActive} health={health} />
      <Main active={active} />
    </div>
  )
}

function Sidebar({ active, setActive, health }) {
  return (
    <nav className="sidebar">
      <div className="sidebar-logo">VaultLLM</div>

      {['upload', 'documents', 'chat'].map(t => (
        <button
          key={t}
          className={`nav-tab${active === t ? ' active' : ''}`}
          onClick={() => setActive(t)}
        >
          <span className="nav-icon">
            {t === 'upload' ? '\u2191' : t === 'documents' ? '\u2630' : '\uD83D\uDCAC'}
          </span>
          <span>{t === 'chat' ? 'Chat' : t.charAt(0).toUpperCase() + t.slice(1)}</span>
        </button>
      ))}

      <div className="health-indicators">
        <div className="sidebar-section-label">Status</div>
        <div className="health-item">
          <span className={`health-dot ${health.database ? 'ok' : 'error'}`} />
          <span className="health-label">DB</span>
          <span className="health-value">{health.database ? 'Online' : 'Offline'}</span>
        </div>
        <div className="health-item">
          <span className={`health-dot ${health.llm_server ? 'ok' : 'error'}`} />
          <span className="health-label">LLM</span>
          <span className="health-value">{health.llm_server ? 'Online' : 'Offline'}</span>
        </div>
      </div>
    </nav>
  )
}

function Main({ active }) {
  if (active === 'upload') return <Upload />
  if (active === 'documents') return <Documents />
  if (active === 'chat') return <ChatPage />
  return <Upload />
}

function Upload() {
  const [drag, setDrag] = useState(false)
  const [status, setStatus] = useState(null)
  const [progress, setProgress] = useState(0)

  async function handleFile(f) {
    const fd = new FormData()
    fd.append('file', f)
    setStatus('uploading')
    setProgress(0)
    const xhr = new XMLHttpRequest()
    xhr.upload.onprogress = e => { if (e.lengthComputable) setProgress(e.loaded / e.total) }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const r = JSON.parse(xhr.responseText)
        setStatus(`Uploaded "${r.title}" — ${r.chunks} chunks`)
      } else {
        try { const r = JSON.parse(xhr.responseText); setStatus(`Error: ${r.detail}`) } catch { setStatus(`Error: ${xhr.status}`) }
      }
    }
    xhr.onerror = () => setStatus('Upload failed')
    xhr.open('POST', `${API}/api/upload`)
    xhr.send(fd)
  }

  return (
    <div className="main-content">
      <h1>Upload Document</h1>
      <div
        className={`upload-zone${drag ? ' dragging' : ''}`}
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) handleFile(f) }}
        onClick={() => document.getElementById('file-input').click()}
      >
        <div className="upload-zone-content">
          <span className="upload-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          </span>
          <p className="upload-title">Drop a file here or click to browse</p>
          <p className="upload-hint">.txt .md .pdf</p>
          <input id="file-input" type="file" hidden onChange={e => { if (e.target.files[0]) handleFile(e.target.files[0]) }} accept=".txt,.md,.pdf" />
        </div>
      </div>

      {status === 'uploading' && (
        <div className="progress-container">
          <div className="progress-bar">
            <div className="progress-bar-fill" style={{ width: `${progress * 100}%` }} />
          </div>
          <div className="progress-label">{Math.round(progress * 100)}%</div>
        </div>
      )}

      {status && status !== 'uploading' && (
        <div className="status-message">{status}</div>
      )}
    </div>
  )
}

function Documents() {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState({})
  const [chunks, setChunks] = useState({})

  function load() {
    setLoading(true)
    fetch(`${API}/api/documents`)
      .then(r => r.json())
      .then(d => setDocs(d.documents))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  async function remove(id) {
    await fetch(`${API}/api/documents/${id}`, { method: 'DELETE' })
    setDocs(prev => prev.filter(d => d.id !== id))
    setExpanded(prev => { const n = {...prev}; delete n[id]; return n })
    setChunks(prev => { const n = {...prev}; delete n[id]; return n })
  }

  async function toggleExpand(id) {
    if (expanded[id]) {
      setExpanded(prev => ({...prev, [id]: false}))
      return
    }
    if (!chunks[id]) {
      try {
        const r = await fetch(`${API}/api/documents/${id}`)
        const data = await r.json()
        setChunks(prev => ({...prev, [id]: data.chunks}))
      } catch { return }
    }
    setExpanded(prev => ({...prev, [id]: true}))
  }

  return (
    <div className="main-content">
      <div className="documents-header">
        <h1>Documents</h1>
        <button className="btn-secondary" onClick={load} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {loading ? <Spinner size={16} /> : '\u21BB'}
          <span>Refresh</span>
        </button>
      </div>

      {loading ? (
        <div className="empty-state" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
          <Spinner size={24} />
          <span>Loading documents...</span>
        </div>
      ) : docs.length === 0 ? (
        <div className="empty-state">No documents.</div>
      ) : (
        <div className="documents-grid">
          {docs.map(d => (
            <div key={d.id}>
              <div className="doc-card" onClick={() => toggleExpand(d.id)} style={{ cursor: 'pointer' }}>
                <div>
                  <div className="doc-card-title">{d.title}</div>
                  <div className="doc-card-meta">{d.chunk_count} chunks &middot; {d.created_at}</div>
                </div>
                <button className="doc-delete-btn" onClick={e => { e.stopPropagation(); remove(d.id) }}>Delete</button>
              </div>
              {expanded[d.id] && chunks[d.id] && (
                <div className="doc-chunks">
                  {chunks[d.id].map((c, i) => (
                    <div key={c.id} className="doc-chunk-item">
                      <div className="doc-chunk-header">Chunk {i + 1}</div>
                      <div className="doc-chunk-text">{c.content}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ChatPage() {
  const [conversations, setConversations] = useState([])
  const [activeConvId, setActiveConvId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [creating, setCreating] = useState(false)
  const [editingConv, setEditingConv] = useState(null)
  const [editTitle, setEditTitle] = useState('')
  const editRef = useRef(null)
  const endRef = useRef(null)
  const msgId = useRef(0)

  const loadConversations = useCallback(() => {
    fetch(`${API}/api/conversations`)
      .then(r => r.json())
      .then(d => setConversations(d.conversations || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  const loadMessages = useCallback((convId) => {
    if (!convId) { setMessages([]); return }
    fetch(`${API}/api/conversations/${convId}/messages`)
      .then(r => r.json())
      .then(d => {
        const msgs = (d.messages || []).map(m => ({
          ...m,
          sources: typeof m.sources === 'string' ? (() => { try { return JSON.parse(m.sources) } catch { return null } })() : m.sources
        }))
        setMessages(msgs)
      })
      .catch(() => setMessages([]))
  }, [])

  useEffect(() => {
    loadMessages(activeConvId)
  }, [activeConvId, loadMessages])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streaming])

  async function createNewChat() {
    setCreating(true)
    try {
      const r = await fetch(`${API}/api/conversations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Chat' })
      })
      const conv = await r.json()
      setActiveConvId(conv.id)
      setMessages([])
      loadConversations()
    } catch {}
    setCreating(false)
  }

  async function createBranch(convId, msgId) {
    setCreating(true)
    try {
      const r = await fetch(`${API}/api/conversations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: `Branch from ${msgId}`,
          parent_conversation_id: convId,
          branch_point_message_id: msgId
        })
      })
      const conv = await r.json()
      setActiveConvId(conv.id)
      loadConversations()
      const r2 = await fetch(`${API}/api/conversations/${conv.id}/messages`)
      const d = await r2.json()
      const msgs = (d.messages || []).map(m => ({
        ...m,
        sources: typeof m.sources === 'string' ? (() => { try { return JSON.parse(m.sources) } catch { return null } })() : m.sources
      }))
      setMessages(msgs)
    } catch {}
    setCreating(false)
  }

  async function renameConv(convId, title) {
    await fetch(`${API}/api/conversations/${convId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title })
    })
    loadConversations()
  }

  function startEdit(conv, e) {
    e.stopPropagation()
    setEditingConv(conv.id)
    setEditTitle(conv.title)
  }

  function submitEdit() {
    if (editingConv && editTitle.trim()) {
      renameConv(editingConv, editTitle.trim())
    }
    setEditingConv(null)
    setEditTitle('')
  }

  useEffect(() => {
    if (editingConv && editRef.current) {
      editRef.current.focus()
      editRef.current.select()
    }
  }, [editingConv])

  useEffect(() => {
    function handleKey(e) {
      if (e.key === 'Escape') { setEditingConv(null); setEditTitle('') }
      if (e.key === 'Enter') { submitEdit() }
    }
    if (editingConv) {
      window.addEventListener('keydown', handleKey)
      return () => window.removeEventListener('keydown', handleKey)
    }
  }, [editingConv, editTitle])

  async function deleteConv(convId, e) {
    e.stopPropagation()
    await fetch(`${API}/api/conversations/${convId}`, { method: 'DELETE' })
    if (activeConvId === convId) {
      setActiveConvId(null)
      setMessages([])
    }
    loadConversations()
  }

  async function send() {
    if (!input.trim() || loading || !activeConvId) return
    const q = input
    setInput('')
    setMessages(m => [...m, { role: 'user', content: q }])
    setLoading(true)

    const id = ++msgId.current
    setMessages(m => [...m, { role: 'assistant', id, answer: '', sources: null, processing_time_ms: 0 }])

    try {
      const r = await fetch(`${API}/api/query/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, top_k: 5, conversation_id: activeConvId }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)

      const reader = r.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6)
          try {
            const evt = JSON.parse(payload)
            if (evt.type === 'token') {
              setStreaming(true)
              setMessages(m => m.map(msg =>
                msg.id === id ? { ...msg, answer: msg.answer + evt.content } : msg
              ))
            } else if (evt.type === 'done') {
              setStreaming(false)
              setMessages(m => m.map(msg =>
                msg.id === id ? { ...msg, sources: evt.sources, processing_time_ms: evt.processing_time_ms } : msg
              ))
              loadConversations()
            }
          } catch { }
        }
      }
    } catch {
      setMessages(m => m.map(msg =>
        msg.id === id ? { ...msg, answer: 'Error: Could not get response.' } : msg
      ))
    }
    setLoading(false)
    setStreaming(false)
  }

  function renderConvItem(conv, depth = 0) {
    const isActive = conv.id === activeConvId
    const isEditing = editingConv === conv.id
    const children = conversations.filter(c => c.parent_conversation_id === conv.id)
    return (
      <div key={conv.id}>
        <div
          className={`conv-item${isActive ? ' active' : ''}`}
          onClick={() => {
            if (!isEditing) { setActiveConvId(conv.id); setMessages([]) }
          }}
          style={{ paddingLeft: 10 + depth * 20 }}
        >
          {depth > 0 && <div className="conv-branch-indent" />}
          {isEditing ? (
            <input
              ref={editRef}
              className="conv-edit-input"
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              onBlur={submitEdit}
              onClick={e => e.stopPropagation()}
            />
          ) : (
            <span className="conv-item-title" onDoubleClick={e => startEdit(conv, e)}>{conv.title}</span>
          )}
          {conv.child_count > 0 && !isEditing && <span className="conv-item-badge">{conv.child_count}</span>}
          {!isEditing && (
            <>
              <button
                className="conv-item-rename"
                onClick={e => startEdit(conv, e)}
                title="Rename"
              >&#9998;</button>
              <button
                className="conv-item-delete"
                onClick={e => deleteConv(conv.id, e)}
                title="Delete conversation"
              >&times;</button>
            </>
          )}
        </div>
        {children.map(c => renderConvItem(c, depth + 1))}
      </div>
    )
  }

  return (
    <div className="chat-layout">
      <div className="conv-sidebar">
        <div className="conv-sidebar-header">
          <h3>Conversations</h3>
          <button
            className="new-chat-btn"
            onClick={createNewChat}
            disabled={creating}
          >
            {creating ? <Spinner size={12} /> : '+ New'}
          </button>
        </div>
        {conversations.length === 0 ? (
          <div className="conv-empty">No conversations yet. Create one to start.</div>
        ) : (
          conversations
            .filter(c => c.parent_conversation_id === null)
            .map(c => renderConvItem(c))
        )}
      </div>

      {!activeConvId ? (
        <div className="chat-main">
          <div className="chat-empty">
            Select a conversation or create a new one
          </div>
        </div>
      ) : (
        <div className="chat-main">
          <div className="chat-messages">
            {messages.length === 0 && (
              <div className="chat-empty">
                <span>Ask a question about your documents</span>
                <span className="chat-empty-hint">Press Enter to send</span>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`chat-bubble ${m.role}`}>
                <div className="chat-bubble-content">
                  {m.role === 'user' ? (
                    <p>{m.content}</p>
                  ) : (
                    <>
                      <p>
                        {m.answer}
                        {(loading && m.id === msgId.current && !streaming) || (streaming && m.id === msgId.current) ? (
                          <Spinner size={14} />
                        ) : null}
                      </p>
                      {m.sources && m.sources.length > 0 && (
                        <details style={{ marginTop: 8 }}>
                          <summary className="sources-toggle">Sources ({m.sources.length})</summary>
                          {m.sources.map((s, j) => (
                            <div key={j} className="source-item">
                              <p className="source-meta">{s.document_title} &middot; score: {s.score.toFixed(3)}</p>
                              <p className="source-text">{s.content.slice(0, 200)}...</p>
                            </div>
                          ))}
                        </details>
                      )}
                      {m.processing_time_ms > 0 && (
                        <p className="processing-time">{m.processing_time_ms}ms</p>
                      )}
                    </>
                  )}
                </div>
                {m.role === 'assistant' && m.answer && !m.id?.toString().startsWith('tmp') && (
                  <div className="chat-bubble-actions">
                    <button
                      className="branch-btn"
                      onClick={() => createBranch(activeConvId, m.id)}
                      title="Branch from this message"
                    >
                      Branch
                    </button>
                  </div>
                )}
              </div>
            ))}
            <div ref={endRef} />
          </div>

          <div className="chat-input-area">
            <div className="chat-input-row">
              <textarea
                className="chat-input"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
                placeholder="Ask a question..."
                rows={1}
              />
              <button className="chat-send-btn" onClick={send} disabled={loading || !activeConvId}>
                {loading ? <Spinner size={16} /> : 'Send'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
