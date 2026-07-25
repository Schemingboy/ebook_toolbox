import { useState, useEffect, useCallback } from 'react';
import './App.css';
import SettingsPanel from './SettingsPanel';
import PreferencesPanel from './PreferencesPanel';
import ScriptRunner from './ScriptRunner';
import SetupWizard from './SetupWizard';
import HealthBar from './HealthBar';

const API_BASE = 'http://127.0.0.1:8000';

type Gate = 'loading' | 'setup' | 'ready' | 'offline';

function App() {
  // 启动先问后端环境状态：缺 .env / 缺凭据就进向导，否则直接进主界面。
  // 这样新用户不会看到一个报错的空壳，而是被引导着填完就能跑。
  const [gate, setGate] = useState<Gate>('loading');

  const probe = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/doctor`);
      const data = await res.json();
      setGate(data.needs_setup ? 'setup' : 'ready');
    } catch {
      setGate('offline');
    }
  }, []);

  useEffect(() => {
    probe();
  }, [probe]);

  if (gate === 'loading') {
    return (
      <div className="app-container">
        <header className="header">
          <h1>Z-Library 批量下载</h1>
          <p>正在检查运行环境…</p>
        </header>
      </div>
    );
  }

  if (gate === 'offline') {
    return (
      <div className="app-container">
        <header className="header">
          <h1>Z-Library 批量下载</h1>
          <p>连不上本地服务。请关掉这个页面，重新双击 start.cmd 启动。</p>
        </header>
      </div>
    );
  }

  if (gate === 'setup') {
    return (
      <div className="app-container">
        <header className="header">
          <h1>Z-Library 批量下载</h1>
          <p>第一次使用，先花一分钟连上你的 Z-Library 账号</p>
        </header>
        <SetupWizard onDone={() => setGate('ready')} />
      </div>
    );
  }

  return (
    <div className="app-container">
      <header className="header">
        <h1>Z-Library 批量下载</h1>
        <p>喂一串书名或 ISBN，自动逐本搜索下载</p>
      </header>

      <HealthBar onNeedSetup={() => setGate('setup')} />
      <ScriptRunner />
      <SettingsPanel />
      <PreferencesPanel />
    </div>
  );
}

export default App;
