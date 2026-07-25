import { useState, useEffect } from 'react';

const API_BASE = 'http://127.0.0.1:8000';

type Props = {
  /** 配置成功后通知外层重新自检并进入主界面 */
  onDone: () => void;
};

/**
 * 首次运行向导。
 *
 * 设计取舍：只要邮箱 + 密码。后端用真浏览器登录一次，把 remix token 抓出来写进
 * .env，顺手导出 Cloudflare cookies。这样新用户不必打开 DevTools 翻 cookies——
 * 那一步是原来最大的门槛。已有 token 的老用户走「高级」折叠区。
 */
export default function SetupWizard({ onDone }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [proxy, setProxy] = useState('');
  const [domain, setDomain] = useState('');
  const [uid, setUid] = useState('');
  const [key, setKey] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [proxyHint, setProxyHint] = useState('');

  // 探测本机代理端口并预填，省得用户自己找端口号
  useEffect(() => {
    fetch(`${API_BASE}/api/proxy/detect`)
      .then(r => r.json())
      .then(d => {
        const first = d.candidates?.[0];
        if (first) {
          setProxy(first);
          setProxyHint(`已自动检测到本机代理 ${first}，如不对可以改`);
        } else {
          setProxyHint('没检测到本机代理。国内用户通常需要先打开代理软件');
        }
      })
      .catch(() => {});
  }, []);

  const usingToken = advanced && uid.trim() && key.trim();
  const canSubmit = usingToken
    ? true
    : email.trim().length > 0 && password.length > 0;

  const handleSubmit = async () => {
    setBusy(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/setup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email.trim(),
          password,
          remix_userid: uid.trim(),
          remix_userkey: key.trim(),
          proxy: proxy.trim(),
          domain: domain.trim(),
        }),
      });
      const data = await res.json();
      if (data.success) {
        onDone();
      } else {
        setError(data.message || '配置失败，请检查填写内容。');
      }
    } catch {
      setError('无法连接本地服务，请确认启动器还在运行。');
    }
    setBusy(false);
  };

  return (
    <section className="glass-panel" style={{ maxWidth: 620, margin: '0 auto' }}>
      <h2 style={{ marginBottom: '0.5rem', fontSize: '1.5rem', color: '#f8fafc' }}>
        欢迎，先连上你的 Z-Library 账号
      </h2>
      <p style={{ color: 'rgba(255,255,255,0.55)', fontSize: '0.9rem', marginBottom: '1.5rem', lineHeight: 1.6 }}>
        填邮箱和密码就行。剩下的（登录凭证、浏览器验证）都会自动完成，大约 20-40 秒。
        密码只写在本机的 .env 文件里，不会外传。
      </p>

      <div className="settings-form">
        <div className="form-group">
          <label>Z-Library 邮箱</label>
          <input
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="your_email@example.com"
            autoFocus
          />
        </div>
        <div className="form-group">
          <label>密码</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="••••••••"
          />
        </div>
        <div className="form-group">
          <label>代理</label>
          <input
            value={proxy}
            onChange={e => setProxy(e.target.value)}
            placeholder="http://127.0.0.1:7897"
          />
          <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.4)', display: 'block', marginTop: '0.25rem' }}>
            {proxyHint}
          </span>
        </div>
      </div>

      <button
        onClick={() => setAdvanced(a => !a)}
        style={{
          marginTop: '1rem',
          background: 'transparent',
          border: 'none',
          color: 'rgba(255,255,255,0.45)',
          fontSize: '0.8rem',
          padding: 0,
          cursor: 'pointer',
        }}
      >
        {advanced ? '收起高级选项' : '高级：我已有 Remix Token / 想指定域名'}
      </button>

      {advanced && (
        <div className="settings-form" style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
          <div className="form-group">
            <label>Remix User ID</label>
            <input value={uid} onChange={e => setUid(e.target.value)} placeholder="填了就跳过登录步骤" />
          </div>
          <div className="form-group">
            <label>Remix User Key</label>
            <input value={key} onChange={e => setKey(e.target.value)} placeholder="与上一项配对使用" />
          </div>
          <div className="form-group">
            <label>API 域名</label>
            <input value={domain} onChange={e => setDomain(e.target.value)} placeholder="留空自动探测" />
            <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.4)', display: 'block', marginTop: '0.25rem' }}>
              z-lib.id 是钓鱼站，请勿填写
            </span>
          </div>
        </div>
      )}

      <div style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button onClick={handleSubmit} disabled={busy || !canSubmit}>
          {busy ? '正在连接（约 20-40 秒）...' : '连接并开始使用'}
        </button>
      </div>

      {error && (
        <div style={{
          marginTop: '1rem',
          padding: '0.75rem 1rem',
          borderRadius: 8,
          background: 'rgba(255,68,68,0.1)',
          border: '1px solid rgba(255,68,68,0.3)',
          color: '#ff6b6b',
          fontSize: '0.9rem',
          lineHeight: 1.6,
          whiteSpace: 'pre-wrap',
        }}>
          {error}
        </div>
      )}
    </section>
  );
}
