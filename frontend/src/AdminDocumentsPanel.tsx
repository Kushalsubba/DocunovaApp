import { useState, useEffect, useRef } from 'react';

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8001';

const CATEGORIES = ['Policies', 'Rules', 'Memorandum', 'Letters', 'Excel Files', 'Word Files'];

interface DocumentItem {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  status: string;
  created_at: string | null;
  category: string | null;
}

interface Props {
  token: string;
  onRefresh?: () => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function AdminDocumentsPanel({ token, onRefresh }: Props) {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [deleteFilename, setDeleteFilename] = useState('');
  const [uploadMsg, setUploadMsg] = useState('');
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadCategory, setUploadCategory] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [popup, setPopup] = useState<{title: string, message: string, type: 'success' | 'error' | null}>({title: '', message: '', type: null});
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [sortField, setSortField] = useState<keyof DocumentItem>('created_at');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 10;

  const authH = { Authorization: `Bearer ${token}` };


  const openInNewTab = async (docId: string) => {
    try {
      const res = await fetch(`${API}/api/documents/${docId}/file`, { headers: authH });
      if (!res.ok) return;
      const url = URL.createObjectURL(await res.blob());
      window.open(url, '_blank');
    } catch {
      // silently ignore
    }
  };

  // Load documents
  const loadDocuments = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/documents`, { headers: authH });
      if (res.ok) {
        const docs = await res.json();
        setDocuments(docs);
      }
    } catch (err) {
      console.error('Failed to load documents:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDocuments();
  }, []);

  // Handle file upload
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (fileInputRef.current) fileInputRef.current.value = '';

    if (!uploadCategory) {
      setPopup({ title: 'Missing Category', message: 'Category of documents is not mentioned. Please select a category.', type: 'error' });
      return;
    }

    if (documents.some(doc => doc.filename === file.name)) {
      setPopup({ title: 'Duplicate Document', message: `The document you are trying to upload already exists with the name "${file.name}".`, type: 'error' });
      return;
    }

    const allowedExts = ['.pdf', '.png', '.jpeg', '.jpg', '.doc', '.docx', '.xls', '.xlsx', '.csv'];
    if (!allowedExts.some(ext => file.name.toLowerCase().endsWith(ext))) {
      setPopup({ title: 'Invalid File', message: 'Unsupported file format.', type: 'error' });
      return;
    }

    setUploadLoading(true);
    setUploadMsg('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('category', uploadCategory);
      const res = await fetch(`${API}/api/documents/upload`, {
        method: 'POST',
        headers: authH,
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) {
        setPopup({ title: 'Upload Failed', message: data.detail || 'Upload failed', type: 'error' });
        return;
      }
      setPopup({ title: 'Success', message: `✓ "${file.name}" uploaded successfully`, type: 'success' });
      setTimeout(() => {
        loadDocuments();
        setPopup({ title: '', message: '', type: null });
        setSelectedDocs(new Set());
      }, 2000);
    } catch {
      setPopup({ title: 'Connection Error', message: 'Upload failed — server unreachable', type: 'error' });
    } finally {
      setUploadLoading(false);
    }
  };

  // Delete single document
  const deleteDocument = async (docId: string, filename: string) => {
    setDeleteConfirmId(docId);
    setDeleteFilename(filename);
  };

  const confirmDelete = async () => {
    if (!deleteConfirmId) return;
    try {
      const res = await fetch(`${API}/api/documents/${deleteConfirmId}`, {
        method: 'DELETE',
        headers: authH,
      });
      if (res.ok) {
        setDocuments(prev => prev.filter(d => d.id !== deleteConfirmId));
        setSelectedDocs(prev => {
          const newSet = new Set(prev);
          newSet.delete(deleteConfirmId);
          return newSet;
        });
        setUploadMsg(`✓ "${deleteFilename}" deleted successfully`);
        setTimeout(() => setUploadMsg(''), 3000);
      }
    } finally {
      setDeleteConfirmId(null);
      setDeleteFilename('');
    }
  };

  // Delete multiple selected documents
  const deleteMultiple = async () => {
    if (selectedDocs.size === 0) return;
    const count = selectedDocs.size;
    if (!window.confirm(`Delete ${count} document(s)? This cannot be undone.`)) return;

    let deleted = 0;
    for (const docId of selectedDocs) {
      try {
        const res = await fetch(`${API}/api/documents/${docId}`, {
          method: 'DELETE',
          headers: authH,
        });
        if (res.ok) deleted++;
      } catch (err) {
        console.error(`Failed to delete ${docId}:`, err);
      }
    }

    if (deleted > 0) {
      setDocuments(prev => prev.filter(d => !selectedDocs.has(d.id)));
      setSelectedDocs(new Set());
      setUploadMsg(`✓ ${deleted} document(s) deleted successfully`);
      setTimeout(() => setUploadMsg(''), 3000);
    }
  };

  // Toggle document selection
  const toggleSelection = (docId: string) => {
    const newSet = new Set(selectedDocs);
    if (newSet.has(docId)) {
      newSet.delete(docId);
    } else {
      newSet.add(docId);
    }
    setSelectedDocs(newSet);
  };

  // Toggle all (operates on filtered set)
  const toggleAll = () => {
    if (selectedDocs.size === filteredDocuments.length && filteredDocuments.length > 0) {
      setSelectedDocs(new Set());
    } else {
      setSelectedDocs(new Set(filteredDocuments.map(d => d.id)));
    }
  };

  const handleSort = (field: keyof DocumentItem) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  const filteredDocuments = filterCategory
    ? documents.filter(d => d.category === filterCategory)
    : documents;

  const sortedDocuments = [...filteredDocuments].sort((a, b) => {
    let valA = a[sortField];
    let valB = b[sortField];
    if (valA === null) valA = '';
    if (valB === null) valB = '';
    if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
    if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
    return 0;
  });

  const totalPages = Math.ceil(sortedDocuments.length / itemsPerPage);
  const paginatedDocuments = sortedDocuments.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );

  return (
    <div className="admin-documents-panel">
      {/* Upload Section */}
      <div className="admin-upload-section">
        <h3>Add Documents</h3>
        <div style={{ marginBottom: '1rem' }}>
          <label style={{ marginRight: '1rem', fontWeight: 'bold' }}>Category:</label>
          <select 
            value={uploadCategory} 
            onChange={e => setUploadCategory(e.target.value)}
            disabled={uploadLoading}
            style={{ padding: '0.5rem', borderRadius: '4px', border: '1px solid #d1d5db' }}
          >
            <option value="" disabled>Select a Category</option>
            <option value="Policies">Policies</option>
            <option value="Rules">Rules</option>
            <option value="Memorandum">Memorandum</option>
            <option value="Letters">Letters</option>
            <option value="Excel Files">Excel Files</option>
            <option value="Word Files">Word Files</option>
          </select>
        </div>
        <label className={`file-drop ${uploadLoading ? 'disabled' : ''}`}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.png,.jpeg,.jpg,.doc,.docx,.xls,.xlsx,.csv"
            onChange={handleFileSelect}
            disabled={uploadLoading}
            style={{ display: 'none' }}
          />
          <span className="file-drop-icon">📤</span>
          <span>{uploadLoading ? 'Uploading…' : 'Click to upload a document'}</span>
        </label>
        <div className="upload-size-info">
          <span>ℹ</span>
          PDFs and images over <strong>2 MB</strong> will be compressed automatically.
        </div>
        {uploadMsg && (
          <div className={`upload-msg ${uploadMsg.includes('✓') ? 'success' : 'error'}`}>
            {uploadMsg}
          </div>
        )}
      </div>

      {/* Documents Table */}
      <div className="admin-documents-section">
        <div className="admin-section-header">
          <h3>Documents Library ({filteredDocuments.length}{filterCategory ? ` of ${documents.length}` : ''})</h3>
          <div className="admin-actions">
            {selectedDocs.size > 0 && (
              <button
                className="btn-sm btn-danger"
                onClick={deleteMultiple}
                title={`Delete ${selectedDocs.size} selected document(s)`}
              >
                Delete {selectedDocs.size} Selected
              </button>
            )}
            <button className="btn-sm btn-refresh" onClick={loadDocuments}>
              Refresh
            </button>
          </div>
        </div>

        {/* Category filter bar */}
        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '0.5rem',
          padding: '0.75rem 0',
          borderBottom: '1px solid var(--border)',
          marginBottom: '0.75rem',
        }}>
          {/* All button */}
          <button
            onClick={() => { setFilterCategory(''); setCurrentPage(1); }}
            style={{
              padding: '0.35rem 0.85rem',
              borderRadius: '999px',
              border: filterCategory === '' ? '2px solid var(--accent)' : '1.5px solid #d1d5db',
              background: filterCategory === '' ? 'var(--accent)' : '#fff',
              color: filterCategory === '' ? '#fff' : 'var(--txt-2)',
              fontWeight: 600,
              fontSize: '0.8rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '0.35rem',
              transition: 'all 0.15s',
            }}
          >
            All
            <span style={{
              background: filterCategory === '' ? 'rgba(255,255,255,0.3)' : '#e5e7eb',
              color: filterCategory === '' ? '#fff' : '#374151',
              borderRadius: '999px',
              padding: '0 0.45rem',
              fontSize: '0.72rem',
              fontWeight: 700,
            }}>
              {documents.length}
            </span>
          </button>

          {/* Per-category buttons */}
          {CATEGORIES.map(cat => {
            const count = documents.filter(d => d.category === cat).length;
            const active = filterCategory === cat;
            return (
              <button
                key={cat}
                onClick={() => { setFilterCategory(cat); setCurrentPage(1); }}
                style={{
                  padding: '0.35rem 0.85rem',
                  borderRadius: '999px',
                  border: active ? '2px solid var(--accent)' : '1.5px solid #d1d5db',
                  background: active ? 'var(--accent)' : '#fff',
                  color: active ? '#fff' : 'var(--txt-2)',
                  fontWeight: 600,
                  fontSize: '0.8rem',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  transition: 'all 0.15s',
                  opacity: count === 0 ? 0.45 : 1,
                }}
              >
                {cat}
                <span style={{
                  background: active ? 'rgba(255,255,255,0.3)' : '#e5e7eb',
                  color: active ? '#fff' : '#374151',
                  borderRadius: '999px',
                  padding: '0 0.45rem',
                  fontSize: '0.72rem',
                  fontWeight: 700,
                }}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {loading ? (
          <div className="message info">Loading documents…</div>
        ) : documents.length === 0 ? (
          <div className="message info">No documents yet. Upload a PDF to get started.</div>
        ) : filteredDocuments.length === 0 ? (
          <div className="message info">No documents found in the <strong>{filterCategory}</strong> category.</div>
        ) : (
          <div className="documents-table-wrapper">
            <table className="documents-table">
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      checked={selectedDocs.size === filteredDocuments.length && filteredDocuments.length > 0}
                      onChange={toggleAll}
                      title="Select all documents"
                    />
                  </th>
                  <th>Document ID</th>
                  <th onClick={() => handleSort('filename')} style={{ cursor: 'pointer' }}>
                    Document Name {sortField === 'filename' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </th>
                  <th onClick={() => handleSort('category')} style={{ cursor: 'pointer' }}>
                    Category {sortField === 'category' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </th>
                  <th onClick={() => handleSort('file_size')} style={{ cursor: 'pointer' }}>
                    Size {sortField === 'file_size' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </th>
                  <th onClick={() => handleSort('created_at')} style={{ cursor: 'pointer' }}>
                    Date of Upload {sortField === 'created_at' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {paginatedDocuments.map(doc => (
                  <tr key={doc.id} className={selectedDocs.has(doc.id) ? 'selected' : ''}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selectedDocs.has(doc.id)}
                        onChange={() => toggleSelection(doc.id)}
                      />
                    </td>
                    <td className="doc-id" title={doc.id}>{doc.id.slice(0, 8)}…</td>
                    <td
                      className="filename"
                      style={{ cursor: 'pointer', color: 'var(--primary-color, #2563eb)', textDecoration: 'underline' }}
                      onClick={() => openInNewTab(doc.id)}
                      title="Click to open document"
                    >{doc.filename}</td>
                    <td>{doc.category || '-'}</td>
                    <td>{formatSize(doc.file_size)}</td>
                    <td>
                      {doc.created_at
                        ? new Date(doc.created_at).toLocaleDateString()
                        : '-'}
                    </td>
                    <td className="actions">
                      <button
                        className="btn-sm btn-danger"
                        onClick={() => deleteDocument(doc.id, doc.filename)}
                        title="Delete this document"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            
            {totalPages > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', marginTop: '1rem', gap: '1rem' }}>
                <button 
                  className="btn-outline" 
                  disabled={currentPage === 1}
                  onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
                >
                  Previous
                </button>
                <span>Page {currentPage} of {totalPages}</span>
                <button 
                  className="btn-outline" 
                  disabled={currentPage === totalPages}
                  onClick={() => setCurrentPage(prev => Math.min(prev + 1, totalPages))}
                >
                  Next
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {deleteConfirmId && (
        <div className="modal-overlay" onClick={() => setDeleteConfirmId(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Delete Document?</h3>
            </div>
            <div className="modal-body">
              <p>
                Are you sure you want to delete <strong>{deleteFilename}</strong>?
              </p>
              <p className="warning-text">This action cannot be undone.</p>
            </div>
            <div className="modal-footer">
              <button
                className="btn-outline"
                onClick={() => setDeleteConfirmId(null)}
              >
                Cancel
              </button>
              <button className="btn-danger" onClick={confirmDelete}>
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Generic Popup Modal */}
      {popup.type && (
        <div className="modal-overlay" onClick={() => setPopup({ title: '', message: '', type: null })}>
          <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '400px' }}>
            <div className="modal-header">
              <h3 style={{ color: popup.type === 'error' ? 'var(--danger-color, #dc3545)' : 'var(--success-color, #28a745)' }}>
                {popup.title}
              </h3>
            </div>
            <div className="modal-body">
              <p>{popup.message}</p>
            </div>
            <div className="modal-footer" style={{ justifyContent: 'center' }}>
              <button
                className="btn-primary"
                onClick={() => setPopup({ title: '', message: '', type: null })}
                style={{ width: '100%' }}
              >
                {popup.type === 'success' ? 'OK' : 'Got it'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
