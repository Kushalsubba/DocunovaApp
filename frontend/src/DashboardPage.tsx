import { useState, useEffect, FormEvent } from 'react';
import { AdminDocumentsPanel } from './AdminDocumentsPanel';
import { UserChatBot } from './UserChatBot';

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8001';

interface UserInfo {
  id: string;
  username: string;
  email: string;
  role: 'admin' | 'user';
}

interface SearchResult {
  id: string;
  score: number;
  filename: string;
  file_path: string;
  file_type: string;
  snippet: string;
  author: string | null;
  creation_date: string | null;
  page_count: number;
  page_number: number;
}

interface Props {
  user: UserInfo;
  token: string;
  onLogout: () => void;
}

type View = 'main' | 'add-user' | 'change-password';

// ── Top-level router ──────────────────────────────────────────────────────────

export function DashboardPage({ user, token, onLogout }: Props) {
  const [view, setView] = useState<View>('main');

  if (view === 'add-user' && user.role === 'admin') {
    return (
      <AddUserView
        token={token}
        onBack={() => setView('main')}
      />
    );
  }

  if (view === 'change-password') {
    return (
      <ChangePasswordView
        token={token}
        onBack={() => setView('main')}
      />
    );
  }

  return (
    <MainView
      user={user}
      token={token}
      onLogout={onLogout}
      onAddUser={() => setView('add-user')}
      onChangePassword={() => setView('change-password')}
    />
  );
}

// ── Main dashboard view ───────────────────────────────────────────────────────

function MainView({
  user,
  token,
  onLogout,
  onAddUser,
  onChangePassword,
}: {
  user: UserInfo;
  token: string;
  onLogout: () => void;
  onAddUser: () => void;
  onChangePassword: () => void;
}) {
  const authH = { Authorization: `Bearer ${token}` };

  const [reextractMsg, setReextractMsg] = useState('');

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState('');

  // PDF viewer
  const [viewerDocId, setViewerDocId] = useState<string | null>(null);
  const [viewerFilename, setViewerFilename] = useState('');
  const [viewerPage, setViewerPage] = useState(1);
  const [pdfBlobUrl, setPdfBlobUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfError, setPdfError] = useState('');

  // Delete confirmation
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [deleteFilename, setDeleteFilename] = useState('');

  // Revoke blob URL when viewer closes
  useEffect(() => {
    if (!viewerDocId && pdfBlobUrl) {
      URL.revokeObjectURL(pdfBlobUrl);
      setPdfBlobUrl(null);
    }
  }, [viewerDocId]);

  // ── Search ────────────────────────────────────────────────────────────────

  const handleSearch = async () => {
    const q = searchQuery.trim();
    if (!q) return;
    setSearchLoading(true);
    setSearchError('');
    try {
      const res = await fetch(`${API}/api/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authH },
        body: JSON.stringify({ query: q, limit: 20 }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || 'Search failed');
      }
      const data = await res.json();
      setSearchResults(data.results || []);
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : 'Search failed');
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  };

  const clearSearch = () => {
    setSearchQuery('');
    setSearchResults(null);
    setSearchError('');
  };

  // ── PDF viewer ────────────────────────────────────────────────────────────

  const openViewer = async (docId: string, filename: string, page = 1) => {
    if (pdfBlobUrl) { URL.revokeObjectURL(pdfBlobUrl); setPdfBlobUrl(null); }
    setViewerDocId(docId);
    setViewerFilename(filename);
    setViewerPage(page);
    setPdfLoading(true);
    setPdfError('');
    try {
      const res = await fetch(`${API}/api/documents/${docId}/file`, { headers: authH });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      setPdfBlobUrl(URL.createObjectURL(await res.blob()));
    } catch (err) {
      setPdfError(err instanceof Error ? err.message : 'Could not load PDF');
    } finally {
      setPdfLoading(false);
    }
  };

  const closeViewer = () => { setViewerDocId(null); setPdfError(''); };

  const downloadDocument = async (docId: string, filename: string) => {
    const res = await fetch(`${API}/api/documents/${docId}/download`, { headers: authH });
    if (!res.ok) return;
    const url = URL.createObjectURL(await res.blob());
    Object.assign(document.createElement('a'), { href: url, download: filename }).click();
    URL.revokeObjectURL(url);
  };

  // ── Delete ────────────────────────────────────────────────────────────────

  const confirmDelete = (docId: string, filename: string) => {
    setDeleteConfirmId(docId);
    setDeleteFilename(filename);
  };

  const executeDelete = async () => {
    if (!deleteConfirmId) return;
    try {
      const res = await fetch(`${API}/api/documents/${deleteConfirmId}`, {
        method: 'DELETE', headers: authH,
      });
      if (res.ok) {
        setSearchResults(prev => prev ? prev.filter(r => r.id !== deleteConfirmId) : prev);
      }
    } finally {
      setDeleteConfirmId(null);
      setDeleteFilename('');
    }
  };

  // ── Re-extract content (admin) ────────────────────────────────────────────

  const triggerReextract = async () => {
    setReextractMsg('Re-extraction started — this may take a minute for scanned PDFs…');
    try {
      const res = await fetch(`${API}/api/admin/reextract`, {
        method: 'POST', headers: authH,
      });
      if (res.ok) {
        setReextractMsg('Re-extraction running in background. Refresh search in a moment.');
      } else {
        setReextractMsg('Re-extraction failed.');
      }
    } catch {
      setReextractMsg('Server unreachable.');
    }
  };

  // ── Shared action buttons ─────────────────────────────────────────────────

  const DocActions = ({ docId, filename, status, page = 1 }: {
    docId: string; filename: string; status?: string; page?: number;
  }) => {
    const ok = status !== 'failed';
    return (
      <div className="doc-actions">
        {ok && <button className="btn-sm btn-view" onClick={() => openViewer(docId, filename, page)}>View</button>}
        {ok && <button className="btn-sm btn-download" onClick={() => downloadDocument(docId, filename)}>Download</button>}
        {!ok && <span className="doc-missing">File unavailable</span>}
        {user.role === 'admin' && (
          <button className="btn-sm btn-danger" onClick={() => confirmDelete(docId, filename)}>Delete</button>
        )}
      </div>
    );
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="app-shell">

      {/* Header */}
      <header className="topbar">
        <div className="topbar-brand">
          <div className="topbar-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
              <line x1="10" y1="9" x2="8" y2="9"/>
            </svg>
          </div>
          <div>
            <h1>Seek Docs APP</h1>
            <p>
              Signed in as <strong>{user.username}</strong>
              <span className={`role-badge ${user.role}`}>{user.role}</span>
            </p>
          </div>
        </div>
        <div className="topbar-actions">
          {user.role === 'admin' && (
            <button className="btn-outline" onClick={onAddUser}>Add User</button>
          )}
          <button className="btn-outline" onClick={onChangePassword}>Change Password</button>
          <button className="btn-outline btn-logout" onClick={onLogout}>Sign Out</button>
        </div>
      </header>

      <div className="content">


      {/* Search (user only) */}
      {user.role === 'user' && (
        <>
          <section className="search-panel">
            <input
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="Search PDF content to find documents…"
            />
            <button onClick={handleSearch} disabled={searchLoading}>
              {searchLoading ? 'Searching…' : 'Search'}
            </button>
            {searchResults !== null && (
              <button className="btn-clear" onClick={clearSearch}>Clear</button>
            )}
          </section>

          {searchError && <div className="message error">{searchError}</div>}
        </>
      )}

      {/* ── User view: prompt before search ── */}
      {user.role === 'user' && searchResults === null && !searchLoading && (
        <div className="user-prompt">
          <span className="user-prompt-icon">🔍</span>
          <p>Enter keywords to search inside PDF documents.<br />
            Matching documents and the page where your text was found will appear here.</p>
        </div>
      )}

      {/* Search results (both roles) */}
      {searchResults !== null && (
        <section className="results-list">
          <div className="section-title">
            Search results — {searchResults.length} found
          </div>
          {searchResults.length === 0 ? (
            <div className="message info">No documents match your query.</div>
          ) : (
            searchResults.map(result => (
              <article key={result.id} className="result-card">
                <div className="result-header">
                  <h2
                    className="doc-name clickable"
                    onClick={() => openViewer(result.id, result.filename, result.page_number)}
                  >
                    {result.filename}
                  </h2>
                  <span className="badge page-badge">Page {result.page_number}</span>
                  <span className="badge">Score: {result.score.toFixed(2)}</span>
                </div>
                {result.snippet && (
                  <p className="result-snippet"
                    dangerouslySetInnerHTML={{ __html: result.snippet }} />
                )}
                <div className="result-footer">
                  {result.author && <span>Author: {result.author}</span>}
                  {result.creation_date && (
                    <span>Date: {new Date(result.creation_date).toLocaleDateString()}</span>
                  )}
                  {result.page_count > 0 && <span>Total pages: {result.page_count}</span>}
                </div>
                <DocActions
                  docId={result.id}
                  filename={result.filename}
                  status="indexed"
                  page={result.page_number}
                />
              </article>
            ))
          )}
        </section>
      )}

      {/* ── User view: Docunova Chatbot for regular users ── */}
      {user.role === 'user' && searchResults === null && !searchLoading && (
        <UserChatBot token={token} onOpenSource={(id, filename, page) => openViewer(id, filename, page)} />
      )}

      {/* ── Admin view: Documents management panel ── */}
      {user.role === 'admin' && searchResults === null && (
        <>
          <AdminDocumentsPanel token={token} />
          
          {/* Re-extract button for admin */}
          <div style={{ marginTop: '1.5rem', textAlign: 'center' }}>
            <button className="btn-sm btn-reextract" onClick={triggerReextract}
              title="Re-run OCR/text extraction on all PDFs so their content is searchable">
              Re-extract Content
            </button>
            {reextractMsg && (
              <div className="message info" style={{ marginTop: '1rem' }}>{reextractMsg}</div>
            )}
          </div>
        </>
      )}

      </div>{/* end .content */}

      {/* PDF Viewer Modal */}
      {viewerDocId && (
        <div className="modal-overlay" onClick={closeViewer}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-group">
                <span className="modal-title">{viewerFilename}</span>
                {viewerPage > 1 && (
                  <span className="modal-page-hint">Opens at page {viewerPage}</span>
                )}
              </div>
              <div className="modal-header-actions">
                {pdfBlobUrl && (
                  <button className="btn-sm btn-download"
                    onClick={() => downloadDocument(viewerDocId, viewerFilename)}>
                    Download
                  </button>
                )}
                <button className="modal-close" onClick={closeViewer}>✕</button>
              </div>
            </div>
            {pdfLoading ? (
              <div className="pdf-loading">Loading PDF…</div>
            ) : pdfBlobUrl ? (
              <iframe
                src={`${pdfBlobUrl}#page=${viewerPage}`}
                className="pdf-iframe"
                title={viewerFilename}
              />
            ) : (
              <div className="pdf-error">{pdfError || 'Could not load the PDF file.'}</div>
            )}
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirmId && (
        <div className="modal-overlay">
          <div className="confirm-modal">
            <h3>Delete Document</h3>
            <p>
              Are you sure you want to delete <strong>{deleteFilename}</strong>?
              This action cannot be undone.
            </p>
            <div className="confirm-actions">
              <button className="btn-danger" onClick={executeDelete}>Delete</button>
              <button className="btn-secondary" onClick={() => setDeleteConfirmId(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Add User view (admin only) ────────────────────────────────────────────────

function AddUserView({ token, onBack }: { token: string; onBack: () => void }) {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<'user' | 'admin'>('user');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !email.trim() || !password.trim()) {
      setError('All fields are required');
      return;
    }
    if (password.length < 4) {
      setError('Password must be at least 4 characters');
      return;
    }

    setLoading(true);
    setError('');
    setSuccess('');
    try {
      const res = await fetch(`${API}/api/auth/register`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ username: username.trim(), email: email.trim(), password, role }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail || 'Failed to create user'); return; }
      setSuccess(`User "${data.username}" created successfully as ${data.role}.`);
      setUsername(''); setEmail(''); setPassword('');
    } catch {
      setError('Server unreachable');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <h1>Add User</h1>
          <p>Create a new account</p>
        </div>
        <button className="btn-outline" onClick={onBack}>← Back</button>
      </header>

      <div className="content">
      <div className="form-page-card">
        <form onSubmit={handleSubmit} className="auth-form">
          {error && <div className="message error">{error}</div>}
          {success && <div className="message success">{success}</div>}

          <div className="form-group">
            <label>Username</label>
            <input value={username} onChange={e => setUsername(e.target.value)}
              placeholder="Choose a username" disabled={loading} />
          </div>

          <div className="form-group">
            <label>Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder="Email address" disabled={loading} />
          </div>

          <div className="form-group">
            <label>Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)}
              placeholder="At least 4 characters" disabled={loading} />
          </div>

          <div className="form-group">
            <label>Role</label>
            <div className="role-selector">
              <label className={`role-option ${role === 'user' ? 'selected' : ''}`}>
                <input type="radio" name="role" value="user" checked={role === 'user'}
                  onChange={() => setRole('user')} disabled={loading} style={{ display: 'none' }} />
                <div className="role-card">
                  <span className="role-icon">👤</span>
                  <strong>User</strong>
                  <small>Search &amp; download PDFs</small>
                </div>
              </label>
              <label className={`role-option ${role === 'admin' ? 'selected' : ''}`}>
                <input type="radio" name="role" value="admin" checked={role === 'admin'}
                  onChange={() => setRole('admin')} disabled={loading} style={{ display: 'none' }} />
                <div className="role-card">
                  <span className="role-icon">🛡️</span>
                  <strong>Admin</strong>
                  <small>Upload, manage &amp; delete PDFs</small>
                </div>
              </label>
            </div>
          </div>

          <div className="form-actions">
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? 'Creating…' : 'Create User'}
            </button>
            <button type="button" className="btn-secondary" onClick={onBack}>Cancel</button>
          </div>
        </form>
      </div>
      </div>{/* end .content */}
    </div>
  );
}

// ── Change Password view ──────────────────────────────────────────────────────

function ChangePasswordView({ token, onBack }: { token: string; onBack: () => void }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!current || !next || !confirm) { setError('All fields are required'); return; }
    if (next !== confirm) { setError('New passwords do not match'); return; }
    if (next.length < 4) { setError('New password must be at least 4 characters'); return; }

    setLoading(true);
    setError('');
    setSuccess('');
    try {
      const res = await fetch(`${API}/api/auth/change-password`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail || 'Failed to change password'); return; }
      setSuccess('Password changed successfully.');
      setCurrent(''); setNext(''); setConfirm('');
    } catch {
      setError('Server unreachable');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <h1>Change Password</h1>
          <p>Update your account password</p>
        </div>
        <button className="btn-outline" onClick={onBack}>← Back</button>
      </header>

      <div className="content">
      <div className="form-page-card">
        <form onSubmit={handleSubmit} className="auth-form">
          {error && <div className="message error">{error}</div>}
          {success && <div className="message success">{success}</div>}

          <div className="form-group">
            <label>Current Password</label>
            <input type="password" value={current} onChange={e => setCurrent(e.target.value)}
              placeholder="Enter current password" disabled={loading} />
          </div>

          <div className="form-group">
            <label>New Password</label>
            <input type="password" value={next} onChange={e => setNext(e.target.value)}
              placeholder="At least 4 characters" disabled={loading} />
          </div>

          <div className="form-group">
            <label>Confirm New Password</label>
            <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)}
              placeholder="Repeat new password" disabled={loading} />
          </div>

          <div className="form-actions">
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? 'Saving…' : 'Change Password'}
            </button>
            <button type="button" className="btn-secondary" onClick={onBack}>Cancel</button>
          </div>
        </form>
      </div>
      </div>{/* end .content */}
    </div>
  );
}
