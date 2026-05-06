import { useState, useEffect } from 'react';
import { LoginPage } from './LoginPage';
import { DashboardPage } from './DashboardPage';

interface UserInfo {
  id: string;
  username: string;
  email: string;
  role: 'admin' | 'user';
}

const API = 'http://localhost:8001';

function App() {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);

  // Restore session from localStorage on first load
  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    if (!savedToken) { setBootstrapping(false); return; }

    fetch(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${savedToken}` } })
      .then(res => (res.ok ? res.json() : Promise.reject()))
      .then((u: UserInfo) => { setUser(u); setToken(savedToken); })
      .catch(() => localStorage.removeItem('token'))
      .finally(() => setBootstrapping(false));
  }, []);

  const handleLogin = (u: UserInfo, t: string) => {
    localStorage.setItem('token', t);
    setUser(u);
    setToken(t);
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    setUser(null);
    setToken(null);
  };

  if (bootstrapping) {
    return (
      <div className="auth-shell">
        <div className="auth-card" style={{ textAlign: 'center', padding: '3rem' }}>
          <p style={{ color: '#6b7280' }}>Loading…</p>
        </div>
      </div>
    );
  }

  if (user && token) {
    return <DashboardPage user={user} token={token} onLogout={handleLogout} />;
  }

  return <LoginPage onLogin={handleLogin} />;
}

export default App;
