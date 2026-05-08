import { useState, FormEvent } from 'react';

interface Props {
  onGoLogin: () => void;
  onSuccess: () => void;
}

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8001';

export function RegisterPage({ onGoLogin, onSuccess }: Props) {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [role, setRole] = useState<'user' | 'admin'>('user');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    if (!username.trim() || !email.trim() || !password.trim()) {
      setError('All fields are required');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const res = await fetch(`${API}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: username.trim(),
          email: email.trim(),
          password,
          role,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || 'Registration failed');
        return;
      }

      onSuccess();
    } catch {
      setError('Cannot connect to server');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-header">
          <h1>Create Account</h1>
          <p>Register to access the document system</p>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          {error && <div className="message error">{error}</div>}

          <div className="form-group">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="Choose a username"
              disabled={loading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="Enter email address"
              disabled={loading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="At least 6 characters"
              disabled={loading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="confirmPassword">Confirm Password</label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              placeholder="Repeat password"
              disabled={loading}
            />
          </div>

          <div className="form-group">
            <label>Role</label>
            <div className="role-selector">
              <label className={`role-option ${role === 'user' ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="role"
                  value="user"
                  checked={role === 'user'}
                  onChange={() => setRole('user')}
                  disabled={loading}
                />
                <div className="role-card">
                  <span className="role-icon">👤</span>
                  <strong>User</strong>
                  <small>Read & download PDFs</small>
                </div>
              </label>

              <label className={`role-option ${role === 'admin' ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="role"
                  value="admin"
                  checked={role === 'admin'}
                  onChange={() => setRole('admin')}
                  disabled={loading}
                />
                <div className="role-card">
                  <span className="role-icon">🛡️</span>
                  <strong>Admin</strong>
                  <small>Upload, manage & delete PDFs</small>
                </div>
              </label>
            </div>
          </div>

          <button type="submit" className="btn-primary btn-block" disabled={loading}>
            {loading ? 'Creating account...' : 'Create Account'}
          </button>
        </form>

        <div className="auth-footer">
          <span>Already have an account?</span>
          <button className="btn-link" onClick={onGoLogin}>Sign in</button>
        </div>
      </div>
    </div>
  );
}
