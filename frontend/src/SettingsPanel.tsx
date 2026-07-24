import { useState, useEffect } from 'react';

const API_BASE = 'http://127.0.0.1:8000';

export default function SettingsPanel() {
  const [settings, setSettings] = useState({
    zlibrary_email: '',
    zlibrary_password: '',
    zlibrary_remix_userid: '',
    zlibrary_remix_userkey: '',
    zlibrary_domain: '',
    zlibrary_proxy: ''
  });
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState('');
  const [testResult, setTestResult] = useState<{success: boolean; message: string} | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/settings`)
      .then(res => res.json())
      .then(data => {
        setSettings({
          zlibrary_email: data.email || '',
          zlibrary_password: data.password || '',
          zlibrary_remix_userid: data.remix_userid || '',
          zlibrary_remix_userkey: data.remix_userkey || '',
          zlibrary_domain: data.domain || '',
          zlibrary_proxy: data.proxy || ''
        });
      });
  }, []);

  const handleSave = async () => {
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/settings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(settings)
      });
      setMsg('设置已保存');
      setTestResult(null);
      setTimeout(() => setMsg(''), 3000);
    } catch (e) {
      setMsg('保存失败！');
    }
    setLoading(false);
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/settings/test-auth`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      });
      const result = await res.json();
      setTestResult({
        success: result.success,
        message: result.message
      });
    } catch (e) {
      setTestResult({ success: false, message: '测试请求失败，请确保 Web 服务正在运行' });
    }
    setTesting(false);
  };

  return (
    <section className="glass-panel">
      <h2 style={{ marginBottom: '1.5rem', fontSize: '1.5rem', color: '#f8fafc' }}>Z-Library 账户设置</h2>
      <div className="settings-form">
        <div className="form-group">
          <label>邮箱 (email)</label>
          <input
            value={settings.zlibrary_email}
            onChange={e => setSettings(s => ({...s, zlibrary_email: e.target.value}))}
            placeholder="your_email@example.com"
          />
        </div>
        <div className="form-group">
          <label>密码 (password)</label>
          <input
            type="password"
            value={settings.zlibrary_password}
            onChange={e => setSettings(s => ({...s, zlibrary_password: e.target.value}))}
            placeholder="••••••••"
          />
        </div>
        <div className="form-group">
          <label>Remix User ID (备用)</label>
          <input
            value={settings.zlibrary_remix_userid}
            onChange={e => setSettings(s => ({...s, zlibrary_remix_userid: e.target.value}))}
            placeholder="非必填"
          />
        </div>
        <div className="form-group">
          <label>Remix User Key (备用)</label>
          <input
            value={settings.zlibrary_remix_userkey}
            onChange={e => setSettings(s => ({...s, zlibrary_remix_userkey: e.target.value}))}
            placeholder="非必填"
          />
        </div>
        <div className="form-group" style={{ marginTop: '0.5rem', paddingTop: '0.5rem', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
          <label>API 域名（可选）</label>
          <input
            value={settings.zlibrary_domain}
            onChange={e => setSettings(s => ({...s, zlibrary_domain: e.target.value}))}
            placeholder="留空自动探测。例如: z-lib.id"
          />
          <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.4)', display: 'block', marginTop: '0.25rem' }}>
            国内用户可尝试 z-lib.id；留空则依次尝试 1lib.sk → z-lib.id → z-library.sk
          </span>
        </div>
        <div className="form-group">
          <label>代理（可选）</label>
          <input
            value={settings.zlibrary_proxy}
            onChange={e => setSettings(s => ({...s, zlibrary_proxy: e.target.value}))}
            placeholder="例如: socks5://127.0.0.1:1080 或 http://127.0.0.1:7890"
          />
          <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.4)', display: 'block', marginTop: '0.25rem' }}>
            如果直连失败，可配置代理（支持 SOCKS5 和 HTTP）
          </span>
        </div>
      </div>
      <div style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <button onClick={handleSave} disabled={loading}>
          {loading ? '正在保存...' : '保存设置'}
        </button>
        <button onClick={handleTest} disabled={testing}
          style={{ background: 'rgba(255,255,255,0.08)', borderColor: 'rgba(255,255,255,0.15)' }}>
          {testing ? '测试中...' : '测试连接'}
        </button>
        {msg && <span style={{ color: msg.includes('失败') ? 'var(--danger-color)' : 'var(--success-color)', fontSize: '0.9rem' }}>{msg}</span>}
      </div>
      {testResult && (
        <div style={{
          marginTop: '1rem',
          padding: '0.75rem 1rem',
          borderRadius: '8px',
          background: testResult.success ? 'rgba(0,200,83,0.1)' : 'rgba(255,68,68,0.1)',
          border: `1px solid ${testResult.success ? 'rgba(0,200,83,0.3)' : 'rgba(255,68,68,0.3)'}`,
          color: testResult.success ? '#4caf50' : '#ff6b6b',
          fontSize: '0.9rem',
        }}>
          {testResult.success ? '✅ ' : '❌ '}{testResult.message}
        </div>
      )}
    </section>
  );
}
