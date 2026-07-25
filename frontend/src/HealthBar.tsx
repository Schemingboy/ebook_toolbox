import { useState, useEffect, useCallback } from 'react';

const API_BASE = 'http://127.0.0.1:8000';

type Check = {
  name: string;
  level: string;
  message: string;
  hint: string;
  fixed: boolean;
  detail: Record<string, unknown>;
};

const LABELS: Record<string, string> = {
  dependencies: '依赖',
  browser: '浏览器',
  env_file: '配置',
  credentials: '账号',
  proxy: '代理',
  cookies: 'Cookies',
  quota: '配额',
};

/**
 * 环境状态条：把「能不能跑」摊在界面上，而不是等任务失败才知道。
 * Cookies 过期也不用你动手 —— 跑任务时会自动刷新，这里只做可见性 + 手动兜底。
 */
export default function HealthBar({ onNeedSetup }: { onNeedSetup: () => void }) {
  const [checks, setChecks] = useState<Check[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/doctor`);
      const data = await res.json();
      setChecks(data.checks || []);
      if (data.needs_setup) onNeedSetup();
    } catch {
      setMsg('无法连接本地服务');
    }
    setLoading(false);
  }, [onNeedSetup]);

  useEffect(() => {
    load();
  }, [load]);

  const handleRefreshCookies = async () => {
    setRefreshing(true);
    setMsg('正在刷新 Cookies（约 10-30 秒）…');
    try {
      const res = await fetch(`${API_BASE}/api/cookies/refresh`, { method: 'POST' });
      const data = await res.json();
      setMsg(data.success ? 'Cookies 已刷新' : `刷新失败：${data.message}`);
    } catch {
      setMsg('刷新请求失败');
    }
    setRefreshing(false);
    load();
    setTimeout(() => setMsg(''), 6000);
  };

  const dot = (level: string) =>
    level === 'ok' ? '#4caf50' : level === 'warn' ? '#ffb74d' : '#ff6b6b';

  return (
    <section className="glass-panel" style={{ paddingTop: '1rem', paddingBottom: '1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <strong style={{ fontSize: '0.9rem', color: '#f8fafc' }}>环境状态</strong>

        {loading && <span style={{ fontSize: '0.85rem', opacity: 0.6 }}>检查中…</span>}

        {!loading &&
          checks.map(c => (
            <span
              key={c.name}
              title={c.hint ? `${c.message}\n→ ${c.hint}` : c.message}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                fontSize: '0.8rem',
                padding: '0.2rem 0.6rem',
                borderRadius: '999px',
                background: 'rgba(255,255,255,0.06)',
                cursor: 'help',
              }}
            >
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: dot(c.level),
                  display: 'inline-block',
                }}
              />
              {LABELS[c.name] || c.name}
            </span>
          ))}

        <span style={{ flex: 1 }} />

        <button
          onClick={load}
          disabled={loading}
          style={{
            background: 'rgba(255,255,255,0.08)',
            borderColor: 'rgba(255,255,255,0.15)',
            padding: '0.35rem 0.8rem',
            fontSize: '0.8rem',
          }}
        >
          重新检查
        </button>
        <button
          onClick={handleRefreshCookies}
          disabled={refreshing}
          style={{
            background: 'rgba(255,255,255,0.08)',
            borderColor: 'rgba(255,255,255,0.15)',
            padding: '0.35rem 0.8rem',
            fontSize: '0.8rem',
          }}
        >
          {refreshing ? '刷新中…' : '刷新 Cookies'}
        </button>
      </div>

      {msg && (
        <div style={{ marginTop: '0.6rem', fontSize: '0.82rem', opacity: 0.85 }}>{msg}</div>
      )}

      {!loading && checks.some(c => c.level === 'error') && (
        <div
          style={{
            marginTop: '0.7rem',
            fontSize: '0.82rem',
            color: '#ff9b9b',
            lineHeight: 1.6,
          }}
        >
          {checks
            .filter(c => c.level === 'error')
            .map(c => (
              <div key={c.name}>
                ✗ {c.message}
                {c.hint ? ` — ${c.hint}` : ''}
              </div>
            ))}
        </div>
      )}
    </section>
  );
}
