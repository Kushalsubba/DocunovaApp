import { useState, useRef, useEffect } from 'react';

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8001';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Array<{ filename: string; id: string; score: number; page_number?: number; excerpt?: string }>;
  timestamp: number;
}

interface Props {
  token: string;
  onOpenSource?: (docId: string, filename: string, page: number) => void;
}

export function UserChatBot({ token, onOpenSource }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Store the active AbortController so the Stop button can cancel mid-flight
  const controllerRef = useRef<AbortController | null>(null);
  // Monotonically-increasing counter; each request captures its own ID.
  // The finally block only resets loading if no newer request has started.
  const reqIdRef = useRef(0);
  const authH = { Authorization: `Bearer ${token}` };

  const downloadSource = async (sourceId: string, filename: string) => {
    try {
      const res = await fetch(`${API}/api/documents/${sourceId}/download`, { headers: authH });
      if (!res.ok) return;
      const url = URL.createObjectURL(await res.blob());
      Object.assign(document.createElement('a'), { href: url, download: filename }).click();
      URL.revokeObjectURL(url);
    } catch {
      // silently ignore
    }
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Cancel the in-flight request and immediately free the input
  const stopRequest = () => {
    // Bump the counter so any pending finally block won't override our reset
    reqIdRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    setLoading(false);
    setError('');
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    const query = inputText.trim();
    if (!query || loading) return;

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev, userMessage]);
    setInputText('');
    setLoading(true);
    setError('');

    // Capture this request's ID — finally only resets state for the latest request
    const thisReqId = ++reqIdRef.current;
    const controller = new AbortController();
    controllerRef.current = controller;
    // Hard timeout: auto-abort after 90 s if backend never responds
    const timeoutId = setTimeout(() => controller.abort(), 90000);

    try {
      const res = await fetch(`${API}/api/chat/rag`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authH },
        body: JSON.stringify({ query, max_context_tokens: 3000 }),
        signal: controller.signal,
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.detail || 'Failed to get response');
        return;
      }

      setMessages(prev => [...prev, {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: data.response,
        sources: data.sources ?? [],
        timestamp: Date.now(),
      }]);
      // Reset loading in the same synchronous block as setMessages so React
      // batches them into one render — prevents the "still thinking" flash.
      setLoading(false);
      controllerRef.current = null;
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        // Only show timeout message when the auto-timeout fired (not the Stop button,
        // which already cleared controllerRef before the abort was processed)
        if (controllerRef.current !== null) {
          setError('Request timed out. The AI model took too long. Please try again.');
        }
      } else {
        setError(err instanceof Error ? err.message : 'Failed to connect to server');
      }
    } finally {
      clearTimeout(timeoutId);
      // Covers error / abort / !res.ok paths; also guards against the stop+resubmit
      // race condition where a newer request has already taken over.
      if (thisReqId === reqIdRef.current) {
        controllerRef.current = null;
        setLoading(false);        // no-op if success path already reset it
        setTimeout(() => inputRef.current?.focus(), 0);
      }
    }
  };

  const clearChat = () => {
    stopRequest();
    setMessages([]);
    setError('');
  };

  return (
    <div className="user-chatbot">
      <div className="chatbot-header">
        <div className="chatbot-title">
          <span className="chatbot-icon">🤖</span>
          <div>
            <h2>Docunova</h2>
            <p>Ask questions about your documents</p>
          </div>
        </div>
        <div className="chatbot-header-actions">
          {loading && (
            <button className="btn-sm btn-stop" onClick={stopRequest} title="Stop and type a new query">
              ⏹ Stop
            </button>
          )}
          {messages.length > 0 && !loading && (
            <button className="btn-sm btn-clear" onClick={clearChat}>
              Clear Chat
            </button>
          )}
        </div>
      </div>

      <div className="chatbot-messages">
        {messages.length === 0 ? (
          <div className="chatbot-welcome">
            <span className="welcome-icon">📚</span>
            <h3>Welcome to Docunova</h3>
            <p>Please ask any question about your uploaded documents and I'll search through them...</p>
            <div className="example-prompts">
              <p style={{ marginBottom: '0.5rem', fontSize: '0.9rem', color: '#6b7280' }}>Example questions:</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <button className="example-prompt-btn"
                  onClick={() => setInputText('What are the key findings in the documents?')}>
                  "What are the key findings in the documents?"
                </button>
                <button className="example-prompt-btn"
                  onClick={() => setInputText('Summarize the main topics covered.')}>
                  "Summarize the main topics covered."
                </button>
                <button className="example-prompt-btn"
                  onClick={() => setInputText('What recommendations are mentioned?')}>
                  "What recommendations are mentioned?"
                </button>
              </div>
            </div>
          </div>
        ) : (
          messages.map(msg => (
            <div key={msg.id} className={`message ${msg.role}`}>
              <div className="message-avatar">{msg.role === 'user' ? '👤' : '🤖'}</div>
              <div className="message-content">
                <div className="message-text">{msg.content}</div>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="message-sources">
                    <strong>Read from {msg.sources.length} document{msg.sources.length !== 1 ? 's' : ''}:</strong>
                    <ul>
                      {msg.sources.map((source, idx) => (
                        <li key={idx} className="source-item">
                          <div className="source-header">
                            <span
                              className={onOpenSource ? 'source-name clickable' : 'source-name'}
                              onClick={() => onOpenSource && onOpenSource(source.id, source.filename, source.page_number || 1)}
                              title="Click to open document"
                            >
                              📄 {source.filename}
                            </span>
                            <span className="source-page">Page {source.page_number || 1}</span>
                            <button
                              className="btn-sm btn-download source-download-btn"
                              onClick={() => downloadSource(source.id, source.filename)}
                              title={`Download ${source.filename}`}
                            >
                              Download
                            </button>
                          </div>
                          {source.excerpt && (
                            <div className="source-excerpt">
                              "{source.excerpt}{source.excerpt.length >= 300 ? '…' : ''}"
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          ))
        )}

        {error && (
          <div className="message-error">
            <span className="error-icon">⚠️</span>
            <div>{error}</div>
          </div>
        )}

        {loading && (
          <div className="message assistant loading">
            <div className="message-avatar">🤖</div>
            <div className="message-content">
              <div className="typing-indicator">
                <span></span><span></span><span></span>
              </div>
              <div className="typing-label">Searching documents…</div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSendMessage} className="chatbot-input-form">
        <input
          ref={inputRef}
          type="text"
          value={inputText}
          onChange={e => setInputText(e.target.value)}
          placeholder={loading ? 'Type your next query (press Stop to cancel current)…' : 'Ask a question about your documents…'}
          className="chatbot-input"
        />
        {loading ? (
          <button type="button" className="chatbot-stop-btn" onClick={stopRequest} title="Stop and send a new query">
            ⏹
          </button>
        ) : (
          <button type="submit" disabled={!inputText.trim()} className="chatbot-send-btn">
            📤
          </button>
        )}
      </form>
    </div>
  );
}
