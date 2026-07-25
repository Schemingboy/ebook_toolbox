import { useState, useEffect } from 'react';

const API_BASE = 'http://127.0.0.1:8000';

interface Preferences {
  format_priority: string[];
  language_priority: string[];
  prefer_newer_year: boolean;
  size_preference: string;
  min_rating: number;
}

const DEFAULTS: Preferences = {
  format_priority: ['epub', 'pdf', 'mobi', 'azw3'],
  language_priority: [],
  prefer_newer_year: true,
  size_preference: 'none',
  min_rating: 0,
};

export default function PreferencesPanel() {
  const [prefs, setPrefs] = useState<Preferences>(DEFAULTS);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    fetch(`${API_BASE}/api/preferences`)
      .then(res => res.json())
      .then((data: Partial<Preferences>) => {
        setPrefs({ ...DEFAULTS, ...data });
      })
      .catch(() => {});
  }, []);

  const moveFormat = (index: number, dir: -1 | 1) => {
    setPrefs(p => {
      const list = [...p.format_priority];
      const target = index + dir;
      if (target < 0 || target >= list.length) return p;
      [list[index], list[target]] = [list[target], list[index]];
      return { ...p, format_priority: list };
    });
  };

  const handleSave = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(prefs),
      });
      const saved = await res.json();
      setPrefs({ ...DEFAULTS, ...saved });
      setMsg('偏好已保存');
      setTimeout(() => setMsg(''), 3000);
    } catch {
      setMsg('保存失败！');
    }
    setLoading(false);
  };

  const inputStyle = {
    width: '100%',
    background: 'rgba(0,0,0,0.4)',
    border: '1px solid var(--glass-border)',
    borderRadius: '6px',
    padding: '0.65rem',
    color: '#fff',
    fontSize: '0.85rem',
    fontFamily: 'inherit',
  };

  return (
    <section className="glass-panel">
      <h2 style={{ marginBottom: '0.5rem', fontSize: '1.5rem', color: '#f8fafc' }}>版本优先级</h2>
      <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: '0.85rem', marginBottom: '1.5rem' }}>
        搜到同一本书的多个版本时，按这里的规则自动挑选。仅对「按书名搜索下载」和「按 ISBN 下载」生效。
      </p>

      <div className="settings-form">
        {/* 格式优先级 */}
        <div className="form-group">
          <label>格式优先级（越靠上越优先）</label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginTop: '0.5rem' }}>
            {prefs.format_priority.map((fmt, i) => (
              <div key={fmt} style={{
                display: 'flex', alignItems: 'center', gap: '0.5rem',
                background: 'rgba(0,0,0,0.3)', border: '1px solid var(--glass-border)',
                borderRadius: '6px', padding: '0.4rem 0.65rem',
              }}>
                <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: '0.8rem', width: '1.2rem' }}>{i + 1}</span>
                <span style={{ flex: 1, color: '#fff', fontSize: '0.9rem', textTransform: 'uppercase' }}>{fmt}</span>
                <button
                  type="button"
                  onClick={() => moveFormat(i, -1)}
                  disabled={i === 0}
                  style={{ padding: '0.15rem 0.5rem', fontSize: '0.8rem', opacity: i === 0 ? 0.3 : 1 }}
                  aria-label={`上移 ${fmt}`}
                >↑</button>
                <button
                  type="button"
                  onClick={() => moveFormat(i, 1)}
                  disabled={i === prefs.format_priority.length - 1}
                  style={{ padding: '0.15rem 0.5rem', fontSize: '0.8rem', opacity: i === prefs.format_priority.length - 1 ? 0.3 : 1 }}
                  aria-label={`下移 ${fmt}`}
                >↓</button>
              </div>
            ))}
          </div>
        </div>

        {/* 语言偏好 */}
        <div className="form-group">
          <label>语言偏好（可选，逗号分隔；留空 = 不管语言）</label>
          <input
            style={inputStyle}
            value={prefs.language_priority.join(', ')}
            onChange={e => setPrefs(p => ({
              ...p,
              language_priority: e.target.value.split(',').map(s => s.trim()).filter(Boolean),
            }))}
            placeholder="例如: english, chinese（留空则不按语言筛选）"
          />
          <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.4)', display: 'block', marginTop: '0.25rem' }}>
            默认留空，格式优先不管语言。
          </span>
        </div>

        {/* 年份偏好 */}
        <div className="param-checkbox-group">
          <input
            type="checkbox"
            id="prefer_newer_year"
            checked={prefs.prefer_newer_year}
            onChange={e => setPrefs(p => ({ ...p, prefer_newer_year: e.target.checked }))}
          />
          <label className="checkbox-label" htmlFor="prefer_newer_year">优先选较新的年份</label>
        </div>

        {/* 体积偏好 */}
        <div className="form-group">
          <label>体积偏好</label>
          <select
            style={inputStyle}
            value={prefs.size_preference}
            onChange={e => setPrefs(p => ({ ...p, size_preference: e.target.value }))}
          >
            <option value="none">不考虑体积</option>
            <option value="larger">偏好更大文件（通常更清晰/完整）</option>
            <option value="smaller">偏好更小文件（省空间）</option>
          </select>
        </div>

        {/* 最低评分 */}
        <div className="form-group">
          <label>最低评分过滤（0 = 不过滤）</label>
          <input
            style={inputStyle}
            type="number"
            min={0}
            max={5}
            step={0.1}
            value={prefs.min_rating}
            onChange={e => setPrefs(p => ({ ...p, min_rating: parseFloat(e.target.value) || 0 }))}
          />
        </div>
      </div>

      <div style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button onClick={handleSave} disabled={loading}>
          {loading ? '正在保存...' : '保存偏好'}
        </button>
        {msg && <span style={{ color: msg.includes('失败') ? 'var(--danger-color)' : 'var(--success-color)', fontSize: '0.9rem' }}>{msg}</span>}
      </div>
    </section>
  );
}
