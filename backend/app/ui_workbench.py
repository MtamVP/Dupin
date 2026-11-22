"""Antigravity-Style Streaming Multi-Agent OSINT Interface with Verified Dossier Board & Map Picker."""

WORKBENCH_HTML = """<!DOCTYPE html>
<html lang="vi" data-theme="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Stalker++ — AI Investigation Agent</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg: #141519;
      --bg-sidebar: #111216;
      --bg-card: #1c1d22;
      --bg-subtle: #23252c;
      --bg-hover: #2a2d36;
      --border: #2a2d36;
      --border-strong: #3a3e4b;
      --ink: #eceef2;
      --ink-secondary: #a8aebd;
      --ink-muted: #767d8f;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --accent-soft: rgba(59, 130, 246, 0.16);
      --ok: #22c55e;
      --ok-soft: rgba(34, 197, 94, 0.14);
      --neg: #f87171;
      --neg-soft: rgba(239, 68, 68, 0.14);
      --font-sans: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      --font-mono: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
      --ease: 150ms cubic-bezier(0.2, 0, 0, 1);
    }

    [data-theme="light"] {
      --bg: #ffffff;
      --bg-sidebar: #f6f7f9;
      --bg-card: #ffffff;
      --bg-subtle: #f1f3f6;
      --bg-hover: #e8ebf0;
      --border: #e2e5ec;
      --border-strong: #cbd2df;
      --ink: #111318;
      --ink-secondary: #4b5262;
      --ink-muted: #767f92;
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --accent-soft: #eff6ff;
      --ok: #15803d;
      --ok-soft: #dcfce7;
      --neg: #b91c1c;
      --neg-soft: #fee2e2;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--font-sans);
      background: var(--bg);
      color: var(--ink);
      height: 100vh;
      display: flex;
      overflow: hidden;
      -webkit-font-smoothing: antialiased;
    }

    svg.ico {
      width: 15px; height: 15px; stroke: currentColor; fill: none;
      stroke-width: 1.75; stroke-linecap: round; stroke-linejoin: round; flex-shrink: 0;
    }

    /* Left Sidebar */
    .sidebar {
      width: 244px;
      background: var(--bg-sidebar);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
    }
    .sidebar-top {
      padding: 14px 12px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 9px;
      font-weight: 700;
      font-size: 0.92rem;
      letter-spacing: -0.02em;
    }
    .brand-mark {
      width: 24px; height: 24px; border-radius: 6px;
      background: var(--accent); color: #ffffff;
      display: grid; place-items: center;
      font-family: var(--font-mono); font-size: 0.72rem; font-weight: 600;
    }
    .new-chat-btn {
      margin: 12px;
      height: 36px;
      border-radius: 8px;
      border: 1px solid var(--border-strong);
      background: var(--bg-card);
      color: var(--ink);
      font-family: var(--font-sans);
      font-size: 0.81rem;
      font-weight: 500;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      cursor: pointer;
      transition: background var(--ease);
    }
    .new-chat-btn:hover { background: var(--bg-hover); }

    .ws-list {
      flex: 1;
      overflow-y: auto;
      padding: 0 8px 12px;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .ws-item {
      padding: 6px 8px 6px 10px;
      border-radius: 7px;
      font-size: 0.81rem;
      color: var(--ink-secondary);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      border: 1px solid transparent;
      transition: background var(--ease), color var(--ease);
    }
    .ws-item:hover { background: var(--bg-hover); color: var(--ink); }
    .ws-item.active { background: var(--bg-card); border-color: var(--border); color: var(--ink); font-weight: 600; }
    .ws-name { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ws-actions { display: flex; gap: 2px; opacity: 0; transition: opacity var(--ease); }
    .ws-item:hover .ws-actions, .ws-item.active .ws-actions { opacity: 1; }
    .ws-icon-btn {
      width: 24px; height: 24px; border: none; border-radius: 5px;
      background: transparent; color: var(--ink-muted);
      display: grid; place-items: center; cursor: pointer;
    }
    .ws-icon-btn:hover { background: var(--bg-subtle); color: var(--ink); }
    .ws-icon-btn.del:hover { background: var(--neg-soft); color: var(--neg); }
    .ws-icon-btn svg.ico { width: 13px; height: 13px; }

    /* Center Chat Workspace */
    .workspace {
      flex: 1;
      display: flex;
      flex-direction: column;
      min-width: 0;
      position: relative;
    }
    .topbar {
      height: 50px;
      padding: 0 18px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .topbar-title { font-size: 0.87rem; font-weight: 600; color: var(--ink); }
    .topbar-actions { display: flex; align-items: center; gap: 8px; }
    .btn {
      height: 31px;
      padding: 0 10px;
      border-radius: 7px;
      border: 1px solid var(--border);
      background: var(--bg-card);
      color: var(--ink);
      font-family: var(--font-sans);
      font-size: 0.78rem;
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      transition: background var(--ease), border-color var(--ease);
    }
    .btn:hover { background: var(--bg-hover); border-color: var(--border-strong); }
    .btn.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }
    .btn.icon-only { width: 31px; padding: 0; justify-content: center; }

    /* Chat Stream */
    .chat-scroll {
      flex: 1;
      overflow-y: auto;
      padding: 24px 20px 18px;
    }
    .chat-inner {
      max-width: 780px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .welcome { margin: 7vh auto 0; text-align: center; max-width: 600px; }
    .welcome h2 { font-size: 1.42rem; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 10px; }
    .welcome p { color: var(--ink-secondary); font-size: 0.88rem; line-height: 1.6; margin-bottom: 20px; }
    .starter-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; text-align: left; }
    .starter-card {
      padding: 12px 14px; border-radius: 10px; border: 1px solid var(--border);
      background: var(--bg-card); cursor: pointer; transition: border-color var(--ease), background var(--ease);
    }
    .starter-card:hover { border-color: var(--border-strong); background: var(--bg-hover); }
    .starter-label { font-size: 0.71rem; font-weight: 600; color: var(--ink-muted); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.04em; }
    .starter-text { font-size: 0.81rem; color: var(--ink); line-height: 1.4; }

    .msg { display: flex; flex-direction: column; gap: 8px; }
    .msg.user { align-items: flex-end; }
    .msg.user .bubble {
      background: var(--bg-subtle);
      border: 1px solid var(--border);
      padding: 10px 14px;
      border-radius: 14px 14px 4px 14px;
      max-width: 84%;
      font-size: 0.89rem;
      line-height: 1.5;
      white-space: pre-wrap;
    }
    .msg.assistant { align-items: flex-start; }
    .assistant-card { width: 100%; display: flex; flex-direction: column; gap: 11px; }
    .assistant-text { font-size: 0.9rem; line-height: 1.65; color: var(--ink); }
    .assistant-text p { margin-bottom: 8px; }
    .assistant-text p:last-child { margin-bottom: 0; }

    .stream-box {
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--bg-card);
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 0.8rem;
      color: var(--ink-secondary);
    }
    .stream-line { display: flex; align-items: center; gap: 8px; font-family: var(--font-mono); font-size: 0.74rem; }
    .pulse-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: pulse 1.1s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

    .clue-row { display: flex; flex-wrap: wrap; gap: 6px; }
    .clue-pill {
      font-family: var(--font-mono); font-size: 0.71rem; padding: 3px 8px;
      border-radius: 6px; background: var(--bg-subtle); border: 1px solid var(--border);
      color: var(--ink-secondary); display: inline-flex; align-items: center; gap: 5px;
    }
    .clue-pill.neg { background: var(--neg-soft); border-color: transparent; color: var(--neg); }
    .clue-pill.ok { background: var(--ok-soft); border-color: transparent; color: var(--ok); }

    details.reasoning {
      border: 1px solid var(--border); border-radius: 8px;
      background: var(--bg-card); padding: 8px 12px; font-size: 0.77rem;
    }
    details.reasoning summary { cursor: pointer; font-weight: 600; color: var(--ink-secondary); list-style: none; }
    .trace-list { margin-top: 8px; display: flex; flex-direction: column; gap: 5px; border-top: 1px solid var(--border); padding-top: 8px; }
    .trace-row { font-family: var(--font-mono); font-size: 0.71rem; color: var(--ink-secondary); line-height: 1.4; }
    .trace-row b { color: var(--accent); }

    .sub-heading { font-size: 0.71rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-muted); }
    .source-card {
      padding: 9px 11px; border-radius: 8px; border: 1px solid var(--border);
      background: var(--bg-card); display: flex; justify-content: space-between; align-items: flex-start; gap: 10px;
    }
    .source-main { flex: 1; min-width: 0; }
    .source-url { font-family: var(--font-mono); font-size: 0.72rem; color: var(--accent); text-decoration: none; word-break: break-all; }
    .source-url:hover { text-decoration: underline; }
    .source-snip { font-size: 0.79rem; color: var(--ink-secondary); margin-top: 3px; line-height: 1.4; }
    .pin-btn {
      flex-shrink: 0; height: 26px; padding: 0 8px; border-radius: 6px;
      border: 1px solid var(--border-strong); background: var(--bg-subtle); color: var(--ink);
      font-size: 0.72rem; font-weight: 500; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;
    }
    .pin-btn:hover { border-color: var(--accent); color: var(--accent); }
    .pin-btn.pinned, .pin-btn:disabled {
      background: var(--ok-soft); border-color: transparent; color: var(--ok);
      cursor: default; pointer-events: none; font-weight: 600;
    }

    .dork-row {
      display: flex; align-items: center; justify-content: space-between; gap: 8px;
      padding: 7px 10px; border-radius: 7px; border: 1px solid var(--border); background: var(--bg-card);
    }
    .dork-q { font-family: var(--font-mono); font-size: 0.73rem; color: var(--ink); word-break: break-word; }
    .dork-open {
      font-size: 0.72rem; color: var(--accent); text-decoration: none; font-weight: 600;
      padding: 3px 8px; border-radius: 5px; border: 1px solid var(--border); background: var(--bg-subtle);
    }
    .dork-open:hover { border-color: var(--accent); }

    /* Antigravity-Style Composer Box */
    .composer-wrap { padding: 10px 20px 18px; background: var(--bg); }
    .composer {
      max-width: 780px;
      margin: 0 auto;
      border: 1px solid var(--border-strong);
      border-radius: 16px;
      background: var(--bg-card);
      padding: 12px 14px 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      position: relative;
      transition: border-color var(--ease);
    }
    .composer:focus-within { border-color: var(--accent); }
    .ctx-chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .ctx-chip {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 3px 8px; border-radius: 6px; font-size: 0.73rem;
      background: var(--accent-soft); color: var(--accent); border: 1px solid rgba(59,130,246,0.3);
    }
    .ctx-chip button { border: none; background: transparent; color: inherit; cursor: pointer; font-weight: 700; }

    .composer textarea {
      width: 100%; border: none; outline: none; resize: none;
      background: transparent; color: var(--ink); font-family: var(--font-sans);
      font-size: 0.92rem; line-height: 1.5; min-height: 46px; max-height: 180px;
    }
    .composer-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding-top: 2px;
    }
    .composer-left, .composer-right { display: flex; align-items: center; gap: 6px; }
    .plus-btn {
      width: 30px; height: 30px; border-radius: 8px; border: none;
      background: transparent; color: var(--ink-secondary);
      display: grid; place-items: center; cursor: pointer; transition: background var(--ease), color var(--ease);
    }
    .plus-btn:hover { background: var(--bg-hover); color: var(--ink); }

    .model-select {
      height: 30px; border: none; border-radius: 7px;
      background: transparent; color: var(--ink-secondary);
      font-family: var(--font-sans); font-size: 0.8rem; font-weight: 500;
      padding: 0 8px; cursor: pointer; outline: none;
    }
    .model-select:hover { background: var(--bg-hover); color: var(--ink); }
    .model-select option { background: var(--bg-card); color: var(--ink); }

    .mode-toggle {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      height: 30px;
      padding: 0 8px;
      border-radius: 8px;
      cursor: pointer;
      user-select: none;
      font-size: 0.78rem;
      font-weight: 500;
      color: var(--ink-secondary);
      transition: background var(--ease), color var(--ease);
    }
    .mode-toggle:hover { background: var(--bg-hover); color: var(--ink); }
    .switch-track {
      width: 30px;
      height: 17px;
      border-radius: 99px;
      background: var(--border-strong);
      position: relative;
      transition: background var(--ease);
    }
    .switch-track.on { background: var(--accent); }
    .switch-thumb {
      width: 13px;
      height: 13px;
      border-radius: 50%;
      background: #ffffff;
      position: absolute;
      top: 2px;
      left: 2px;
      transition: transform var(--ease);
    }
    .switch-track.on .switch-thumb { transform: translateX(13px); }

    .send-circle {
      width: 34px; height: 34px; border-radius: 50%; border: none;
      background: var(--accent); color: #ffffff;
      display: grid; place-items: center; cursor: pointer;
      transition: background var(--ease), transform var(--ease);
    }
    .send-circle:hover { background: var(--accent-hover); }
    .send-circle:disabled { opacity: 0.45; cursor: not-allowed; }

    /* Antigravity Add-Context Popover Menu */
    .context-menu {
      display: none;
      position: absolute;
      bottom: 52px;
      left: 10px;
      width: 230px;
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      border-radius: 12px;
      padding: 6px;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
      z-index: 40;
      flex-direction: column;
      gap: 2px;
    }
    .context-menu.open { display: flex; }
    .ctx-menu-head { padding: 6px 10px; font-size: 0.72rem; font-weight: 600; color: var(--ink-muted); }
    .ctx-menu-item {
      padding: 8px 10px; border-radius: 8px; border: none; background: transparent;
      color: var(--ink); font-family: var(--font-sans); font-size: 0.82rem;
      display: flex; align-items: center; justify-content: space-between;
      cursor: pointer; text-align: left; width: 100%;
    }
    .ctx-menu-item:hover { background: var(--bg-hover); }
    .ctx-menu-item-l { display: flex; align-items: center; gap: 9px; }

    /* Right Panel: Verified Dossier Board (Replaces Graph!) */
    .dossier-panel {
      width: 360px;
      border-left: 1px solid var(--border);
      background: var(--bg-sidebar);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
    }
    .dossier-panel.hidden { display: none; }
    .dossier-head {
      height: 50px; padding: 0 14px; border-bottom: 1px solid var(--border);
      background: var(--bg); display: flex; align-items: center; justify-content: space-between;
      font-size: 0.83rem; font-weight: 600;
    }
    .dossier-hint {
      padding: 10px 14px; font-size: 0.74rem; color: var(--ink-muted);
      border-bottom: 1px solid var(--border); line-height: 1.45;
    }
    .dossier-list {
      flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px;
    }
    .dossier-item {
      background: var(--bg-card); border: 1px solid var(--border); border-left: 3px solid var(--ok);
      border-radius: 8px; padding: 9px 11px; display: flex; flex-direction: column; gap: 4px;
    }
    .dossier-item-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 6px; }
    .dossier-key { font-size: 0.72rem; font-weight: 600; color: var(--ink-muted); text-transform: uppercase; letter-spacing: 0.03em; }
    .dossier-val { font-size: 0.83rem; color: var(--ink); line-height: 1.4; word-break: break-word; }
    .dossier-src { font-family: var(--font-mono); font-size: 0.68rem; color: var(--accent); text-decoration: none; word-break: break-all; }
    .dossier-add-box {
      padding: 12px; border-top: 1px solid var(--border); background: var(--bg);
      display: flex; flex-direction: column; gap: 6px;
    }
    .dossier-add-box input {
      height: 32px; border-radius: 7px; border: 1px solid var(--border-strong);
      background: var(--bg-card); color: var(--ink); padding: 0 9px; font-size: 0.79rem; outline: none;
    }
  </style>
</head>
<body>
  <!-- Left Sidebar: Sessions -->
  <aside class="sidebar">
    <div class="sidebar-top">
      <div class="brand">
        <span class="brand-mark">S+</span>
        <span>Stalker++</span>
      </div>
      <button class="btn icon-only" title="Đổi giao diện Sáng / Tối" onclick="toggleTheme()">
        <svg class="ico" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
      </button>
    </div>

    <button class="new-chat-btn" onclick="createNewSession()">
      <svg class="ico" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>
      Cuộc điều tra mới
    </button>

    <div id="wsList" class="ws-list"></div>
  </aside>

  <!-- Center: Antigravity-Style Streaming Agent Chat -->
  <section class="workspace">
    <header class="topbar">
      <div id="activeWsTitle" class="topbar-title">Stalker++ Agent</div>
      <div class="topbar-actions">
        <button class="btn" onclick="openAiSettings()">
          <svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          Kết nối & AI Hub
        </button>
        <button id="toggleDossierBtn" class="btn active" onclick="toggleDossierPanel()">
          <svg class="ico" viewBox="0 0 24 24"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          Hồ sơ tổng hợp (<span id="dossierCount">0</span>)
        </button>
      </div>
    </header>

    <div id="chatScroll" class="chat-scroll">
      <div id="chatInner" class="chat-inner"></div>
    </div>

    <!-- Antigravity-Style Input Composer -->
    <div class="composer-wrap">
      <div class="composer">
        <!-- Hidden file inputs -->
        <input type="file" id="imgFileInput" accept="image/*" style="display:none;" onchange="handleImageFile(event)" />
        <input type="file" id="docFileInput" accept=".txt,.md,.csv,.json,.log" style="display:none;" onchange="handleTextFile(event)" />

        <!-- Add Context Popover (Exact Antigravity Pattern) -->
        <div id="addContextMenu" class="context-menu">
          <div class="ctx-menu-head">Add Context</div>
          <button class="ctx-menu-item" onclick="closeContextMenu(); document.getElementById('docFileInput').click();">
            <span class="ctx-menu-item-l">
              <svg class="ico" viewBox="0 0 24 24"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
              Files (TXT / CSV / MD)
            </span>
          </button>
          <button class="ctx-menu-item" onclick="closeContextMenu(); document.getElementById('imgFileInput').click();">
            <span class="ctx-menu-item-l">
              <svg class="ico" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
              Ảnh / Chụp màn hình
            </span>
          </button>
          <button class="ctx-menu-item" onclick="closeContextMenu(); openMapPicker();">
            <span class="ctx-menu-item-l">
              <svg class="ico" viewBox="0 0 24 24"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
              Bản đồ (Chọn tọa độ)
            </span>
          </button>
          <button class="ctx-menu-item" onclick="closeContextMenu(); promptBrowserUrl();">
            <span class="ctx-menu-item-l">
              <svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
              Browser / URL công khai
            </span>
          </button>
          <button class="ctx-menu-item" onclick="closeContextMenu(); openAiSettings();">
            <span class="ctx-menu-item-l">
              <svg class="ico" viewBox="0 0 24 24"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
              MCP & API Keys
            </span>
            <span style="color:var(--accent); font-size:0.74rem; font-weight:600;">Set up</span>
          </button>
        </div>

        <!-- Attached Context Chips -->
        <div id="ctxChips" class="ctx-chips" style="display:none;"></div>

        <textarea
          id="promptInput"
          rows="2"
          placeholder="Nhập thông tin cần tìm cách nhau bằng dấu phẩy (tên, trường, ngày sinh, MSSV, -loại trừ) hoặc Ctrl+V dán ảnh..."
          onkeydown="handleKey(event)"
          onpaste="handlePasteImage(event)"
        ></textarea>

        <div class="composer-bar">
          <div class="composer-left">
            <button class="plus-btn" title="Add Context" onclick="toggleContextMenu(event)">
              <svg class="ico" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            </button>
            <select id="modelSelect" class="model-select" aria-label="Model selector">
              <option value="gemini-3.5-flash-lite" selected>Gemini 3.5 Flash-Lite (Mặc định)</option>
              <option value="gemini-4-hydrogen">Gemini 4 Hydrogen</option>
              <option value="gemini-3.6-flash">Gemini 3.6 Flash</option>
              <option value="gemini-3.1-flash-lite">Gemini 3.1 Flash-Lite</option>
              <option value="gemini-3.8-flash">Gemini 3.8 Flash</option>
            </select>
          </div>
          <div class="composer-right">
            <label class="mode-toggle" onclick="toggleDeepMode()" title="Bật/tắt chế độ đào sâu Deep ReAct (Studocu / Scribd / PDF)">
              <span>Deep ReAct</span>
              <span id="deepSwitchTrack" class="switch-track on"><span class="switch-thumb"></span></span>
            </label>
            <button id="sendBtn" class="send-circle" title="Gửi tìm kiếm (Enter)" onclick="sendPrompt()">
              <svg class="ico" viewBox="0 0 24 24"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- Right Panel: Verified Dossier Board (User-Curated Ground Truth) -->
  <aside id="dossierPanel" class="dossier-panel">
    <div class="dossier-head">
      <span>Hồ sơ Tổng hợp (Đã xác nhận)</span>
      <button class="btn icon-only" title="Xuất CSV" onclick="exportCsv()">
        <svg class="ico" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      </button>
    </div>
    <div class="dossier-hint">
      Đánh dấu <b>+ Lưu vào Hồ sơ</b> từ kết quả tìm được hoặc tự thêm tay bên dưới. Mọi thông tin đã xác nhận ở đây sẽ <b>tự động nạp vào quy trình tìm kiếm tiếp theo</b>.
    </div>
    <div id="dossierList" class="dossier-list"></div>
    <div class="dossier-add-box">
      <div style="display:grid; grid-template-columns:1fr 1.3fr; gap:6px;">
        <input id="dosKey" placeholder="Trường (vd: Lớp, MSSV)" />
        <input id="dosVal" placeholder="Giá trị đã xác nhận..." />
      </div>
      <div style="display:flex; gap:6px;">
        <input id="dosSrc" placeholder="URL nguồn (tùy chọn)" style="flex:1;" />
        <button class="btn active" onclick="addManualDossier()">+ Thêm</button>
      </div>
    </div>
  </aside>

  <!-- Google Maps Iframe Picker Modal -->
  <div id="mapModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); z-index:60; align-items:center; justify-content:center; padding:16px;">
    <div style="background:var(--bg-card); border:1px solid var(--border-strong); border-radius:14px; width:720px; max-width:96vw; overflow:hidden; display:flex; flex-direction:column;">
      <div style="padding:13px 16px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
        <div>
          <b style="font-size:0.92rem;">Tìm địa điểm trên Google Maps (Iframe)</b>
          <div style="font-size:0.74rem; color:var(--ink-muted);">Nhập địa chỉ, tên trường hoặc dán link Google Maps để xem bản đồ & tự động lấy tọa độ</div>
        </div>
        <button class="btn icon-only" onclick="closeMapPicker()">×</button>
      </div>
      <div style="padding:10px 16px; display:flex; gap:8px; border-bottom:1px solid var(--border); background:var(--bg-sidebar);">
        <input id="mapSearchInput" placeholder="Nhập địa chỉ (vd: 31 Thành Mỹ, Tân Bình, TP.HCM hoặc 279 Nguyễn Tri Phương)..." onkeydown="if(event.key==='Enter'){event.preventDefault();searchGoogleMap();}" style="flex:1; height:34px; border-radius:7px; border:1px solid var(--border-strong); background:var(--bg); color:var(--ink); padding:0 10px; font-size:0.82rem;" />
        <button class="btn active" onclick="searchGoogleMap()">Tìm trên Maps</button>
      </div>
      <iframe id="gmapsIframe" src="https://maps.google.com/maps?q=Ho+Chi+Minh+City&t=&z=13&ie=UTF8&iwloc=&output=embed" style="width:100%; height:350px; border:none;" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>
      <div style="padding:12px 16px; display:flex; flex-direction:column; gap:8px; border-top:1px solid var(--border);">
        <div style="display:grid; grid-template-columns:1.4fr 1fr; gap:8px;">
          <input id="mapLabelInput" placeholder="Nhãn địa điểm đính kèm..." style="height:34px; border-radius:7px; border:1px solid var(--border-strong); background:var(--bg); color:var(--ink); padding:0 10px; font-size:0.8rem;" />
          <input id="mapCoordDisplay" placeholder="Tọa độ (lat, lng) — tự điền hoặc nhập tay" style="height:34px; border-radius:7px; border:1px solid var(--border-strong); background:var(--bg); color:var(--accent); font-family:var(--font-mono); padding:0 10px; font-size:0.78rem;" />
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <a id="openGmapsLink" href="https://www.google.com/maps" target="_blank" rel="noopener" style="font-size:0.78rem; color:var(--accent); text-decoration:none; font-weight:500;">Mở lớn trên Google Maps ↗</a>
          <div style="display:flex; gap:8px;">
            <button class="btn" onclick="closeMapPicker()">Hủy</button>
            <button class="btn active" onclick="confirmMapPoint()">Xác nhận địa điểm</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 3-Tab Integration Hub Modal (API Key Rotation Pool + Host Local + MCP) -->
  <div id="aiModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); z-index:60; align-items:center; justify-content:center; padding:16px;">
    <div style="background:var(--bg-card); border:1px solid var(--border-strong); border-radius:14px; width:720px; max-width:96vw; max-height:88vh; display:flex; flex-direction:column; overflow:hidden;">
      <div style="padding:14px 18px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
        <div>
          <b style="font-size:0.95rem;">Kết nối & AI Hub</b>
          <div style="font-size:0.74rem; color:var(--ink-muted);">API Key Pool xoay vòng (n8n), Host Local (Ollama/SearXNG) & MCP cho AI Agent</div>
        </div>
        <button class="btn icon-only" onclick="closeAiSettings()">×</button>
      </div>

      <div style="display:flex; gap:6px; padding:10px 18px 0; border-bottom:1px solid var(--border); background:var(--bg-sidebar);">
        <button class="btn active" id="hubTab-keys" style="border-bottom-left-radius:0; border-bottom-right-radius:0;" onclick="switchHubTab('keys')">API Key Pool (Xoay vòng)</button>
        <button class="btn" id="hubTab-local" style="border-bottom-left-radius:0; border-bottom-right-radius:0;" onclick="switchHubTab('local')">Host Local (Ollama / SearXNG)</button>
        <button class="btn" id="hubTab-mcp" style="border-bottom-left-radius:0; border-bottom-right-radius:0;" onclick="switchHubTab('mcp')">AI Agents & MCP</button>
      </div>

      <div style="padding:16px 18px; overflow-y:auto; flex:1;">
        <div id="hubPane-keys" style="display:flex; flex-direction:column; gap:12px;">
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; background:var(--bg-sidebar); border:1px solid var(--border); padding:12px; border-radius:8px;">
            <input id="newKeyName" placeholder="Tên API (vd: Gemini Free #1)" style="height:34px; border-radius:7px; border:1px solid var(--border-strong); background:var(--bg); color:var(--ink); padding:0 10px; font-size:0.8rem;" />
            <select id="newKeyProvider" style="height:34px; border-radius:7px; border:1px solid var(--border-strong); background:var(--bg); color:var(--ink); padding:0 8px; font-size:0.8rem;">
              <option value="gemini">Gemini (Google AI Search + Vision)</option>
              <option value="serper">Serper.dev (Google Search JSON)</option>
              <option value="openai">OpenAI-Compatible</option>
              <option value="github">GitHub Token</option>
            </select>
            <input id="newKeySecret" type="password" placeholder="Dán API Key..." style="height:34px; border-radius:7px; border:1px solid var(--border-strong); background:var(--bg); color:var(--ink); padding:0 10px; font-size:0.8rem;" />
            <div style="display:flex; gap:6px;">
              <input id="newKeyModel" placeholder="Model mặc định (tùy chọn)" style="flex:1; height:34px; border-radius:7px; border:1px solid var(--border-strong); background:var(--bg); color:var(--ink); padding:0 10px; font-size:0.8rem;" />
              <button class="btn active" onclick="addPoolKey()">+ Thêm Key</button>
            </div>
          </div>
          <div id="keyPoolList" style="display:flex; flex-direction:column; gap:6px;"></div>
        </div>

        <div id="hubPane-local" style="display:none; flex-direction:column; gap:12px;">
          <select id="localActiveMode" style="width:100%; height:34px; border-radius:7px; border:1px solid var(--border-strong); background:var(--bg); color:var(--ink); padding:0 8px; font-size:0.82rem;">
            <option value="auto">Tự động (Gemini Pool → Serper/SearXNG → ddgs)</option>
            <option value="gemini_pool">Luôn dùng Gemini API Pool</option>
            <option value="ollama_local">100% Host Local (Ollama + SearXNG/ddgs)</option>
            <option value="metasearch_only">Chỉ Metasearch (Không gọi LLM)</option>
          </select>
          <div style="display:flex; gap:6px;">
            <input id="localOllamaUrl" value="http://localhost:11434" style="flex:1; height:34px; border-radius:7px; border:1px solid var(--border-strong); background:var(--bg); color:var(--ink); padding:0 10px; font-size:0.8rem;" />
            <button class="btn" onclick="probeOllama()">Quét Ollama</button>
          </div>
          <input id="localOllamaModel" value="qwen2.5:7b" placeholder="Ollama model" style="width:100%; height:34px; border-radius:7px; border:1px solid var(--border-strong); background:var(--bg); color:var(--ink); padding:0 10px; font-size:0.8rem;" />
          <div id="ollamaProbeStatus" style="font-size:0.74rem; color:var(--ink-muted);"></div>
          <div style="display:flex; gap:6px;">
            <input id="localSearxngUrl" placeholder="SearXNG Local URL (vd: http://localhost:8888)" style="flex:1; height:34px; border-radius:7px; border:1px solid var(--border-strong); background:var(--bg); color:var(--ink); padding:0 10px; font-size:0.8rem;" />
            <button class="btn" onclick="probeSearxng()">Test SearXNG</button>
          </div>
          <div id="searxngProbeStatus" style="font-size:0.74rem; color:var(--ink-muted);">
            Khi điền URL, SearXNG sẽ chạy <b>song song với ddgs</b> (Consensus Fusion). Chạy nhanh: <code style="font-family:var(--font-mono);">cd searxng &amp;&amp; docker compose up -d</code>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span id="localSaveStatus" style="font-size:0.75rem; color:var(--ink-muted);"></span>
            <button class="btn active" onclick="saveLocalHost()">Lưu Host Local</button>
          </div>
        </div>

        <div id="hubPane-mcp" style="display:none; flex-direction:column; gap:10px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:0.78rem; color:var(--ink-secondary);">Kết nối Antigravity, Claude Code, Codex qua MCP</span>
            <button class="btn" onclick="testMcpHandshake()">Test MCP</button>
          </div>
          <div id="mcpTestOut" style="font-family:var(--font-mono); font-size:0.72rem; color:var(--accent);"></div>
          <div>
            <div style="display:flex; justify-content:space-between; margin-bottom:4px;"><b style="font-size:0.75rem;">Antigravity (mcp_config.json)</b><button class="btn" style="height:22px;font-size:0.7rem;" onclick="copyText('mcpAntigravity')">Copy</button></div>
            <pre id="mcpAntigravity" style="background:var(--bg-sidebar); border:1px solid var(--border); border-radius:7px; padding:8px; font-family:var(--font-mono); font-size:0.7rem; overflow-x:auto;"></pre>
          </div>
          <div>
            <div style="display:flex; justify-content:space-between; margin-bottom:4px;"><b style="font-size:0.75rem;">Claude Code (CLI)</b><button class="btn" style="height:22px;font-size:0.7rem;" onclick="copyText('mcpClaude')">Copy</button></div>
            <pre id="mcpClaude" style="background:var(--bg-sidebar); border:1px solid var(--border); border-radius:7px; padding:8px; font-family:var(--font-mono); font-size:0.7rem; overflow-x:auto;"></pre>
          </div>
          <div>
            <div style="display:flex; justify-content:space-between; margin-bottom:4px;"><b style="font-size:0.75rem;">Codex / Cursor (HTTP MCP)</b><button class="btn" style="height:22px;font-size:0.7rem;" onclick="copyText('mcpCodex')">Copy</button></div>
            <pre id="mcpCodex" style="background:var(--bg-sidebar); border:1px solid var(--border); border-radius:7px; padding:8px; font-family:var(--font-mono); font-size:0.7rem; overflow-x:auto;"></pre>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    let activeWorkspaceId = null;
    let workspaces = [];
    let dossierItems = [];
    let deepModeEnabled = true;

    // Context attachments
    let attachedImageB64 = null;
    let attachedImageMime = 'image/png';
    let attachedImageName = '';
    let attachedFileText = null;
    let attachedFileName = '';
    let attachedGeoPoint = null;

    // Map picker state
    let leafletMap = null;
    let mapMarker = null;
    let tempLat = 10.762622;
    let tempLng = 106.660172;

    function escapeHtml(str) {
      return String(str || '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
    }

    function formatMd(text) {
      return escapeHtml(text)
        .replace(/\\*\\*(.+?)\\*\\*/g, '<b>$1</b>')
        .replace(/`([^`]+)`/g, '<code style="font-family:var(--font-mono);font-size:0.84em;background:var(--bg-subtle);padding:1px 4px;border-radius:4px;">$1</code>')
        .split('\\n\\n')
        .map(p => `<p>${p}</p>`)
        .join('');
    }

    function toggleTheme() {
      const root = document.documentElement;
      root.setAttribute('data-theme', root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
    }

    function toggleDossierPanel() {
      const panel = document.getElementById('dossierPanel');
      const btn = document.getElementById('toggleDossierBtn');
      panel.classList.toggle('hidden');
      btn.classList.toggle('active', !panel.classList.contains('hidden'));
    }

    function toggleDeepMode() {
      deepModeEnabled = !deepModeEnabled;
      document.getElementById('deepSwitchTrack').classList.toggle('on', deepModeEnabled);
    }

    function toggleContextMenu(e) {
      e.stopPropagation();
      document.getElementById('addContextMenu').classList.toggle('open');
    }

    function closeContextMenu() {
      document.getElementById('addContextMenu').classList.remove('open');
    }
    document.addEventListener('click', closeContextMenu);

    function renderContextChips() {
      const box = document.getElementById('ctxChips');
      const chips = [];
      if (attachedImageB64) {
        chips.push(`<span class="ctx-chip">Ảnh: ${escapeHtml(attachedImageName || 'Screenshot')} <button onclick="attachedImageB64=null;renderContextChips()">×</button></span>`);
      }
      if (attachedFileText) {
        chips.push(`<span class="ctx-chip">File: ${escapeHtml(attachedFileName)} <button onclick="attachedFileText=null;renderContextChips()">×</button></span>`);
      }
      if (attachedGeoPoint) {
        chips.push(`<span class="ctx-chip">Bản đồ: ${escapeHtml(attachedGeoPoint.label || 'Tọa độ')} (${attachedGeoPoint.lat.toFixed(4)}, ${attachedGeoPoint.lng.toFixed(4)}) <button onclick="attachedGeoPoint=null;renderContextChips()">×</button></span>`);
      }
      box.innerHTML = chips.join('');
      box.style.display = chips.length ? 'flex' : 'none';
    }

    function handleImageFile(e) {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      const reader = new FileReader();
      reader.onload = () => {
        const parts = String(reader.result || '').split(',');
        attachedImageB64 = parts.length > 1 ? parts[1] : null;
        attachedImageMime = f.type || 'image/png';
        attachedImageName = f.name || 'Image';
        renderContextChips();
      };
      reader.readAsDataURL(f);
    }

    function handlePasteImage(e) {
      const items = (e.clipboardData && e.clipboardData.items) || [];
      for (const item of items) {
        if (item.type && item.type.startsWith('image/')) {
          const f = item.getAsFile();
          if (f) handleImageFile({target: {files: [f]}});
        }
      }
    }

    function handleTextFile(e) {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      const reader = new FileReader();
      reader.onload = () => {
        attachedFileText = String(reader.result || '').slice(0, 6000);
        attachedFileName = f.name;
        renderContextChips();
      };
      reader.readAsText(f);
    }

    function promptBrowserUrl() {
      const url = window.prompt('Nhập URL công khai cần Agent truy cập và đọc:');
      if (!url || !url.trim()) return;
      const inp = document.getElementById('promptInput');
      inp.value = (inp.value ? inp.value + ', ' : '') + url.trim();
      inp.focus();
    }

    // --- Google Maps Iframe Search & Coordinate Picker ---
    function openMapPicker() {
      document.getElementById('mapModal').style.display = 'flex';
      setTimeout(() => document.getElementById('mapSearchInput').focus(), 50);
    }

    async function searchGoogleMap() {
      const q = document.getElementById('mapSearchInput').value.trim();
      if (!q) return;

      // Check if user pasted a Google Maps URL containing @lat,lng or raw "lat, lng"
      const coordMatch = q.match(/(-?\\d+\\.\\d+)\\s*,\\s*(-?\\d+\\.\\d+)/);
      if (coordMatch) {
        tempLat = parseFloat(coordMatch[1]);
        tempLng = parseFloat(coordMatch[2]);
        document.getElementById('mapCoordDisplay').value = `${tempLat.toFixed(6)}, ${tempLng.toFixed(6)}`;
      } else {
        document.getElementById('mapLabelInput').value = q;
        // Fetch coordinates from OpenStreetMap Nominatim in background
        try {
          const geoRes = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`);
          const geoList = await geoRes.json();
          if (geoList && geoList.length > 0) {
            tempLat = parseFloat(geoList[0].lat);
            tempLng = parseFloat(geoList[0].lon);
            document.getElementById('mapCoordDisplay').value = `${tempLat.toFixed(6)}, ${tempLng.toFixed(6)}`;
          }
        } catch (_) {}
      }

      document.getElementById('gmapsIframe').src = `https://maps.google.com/maps?q=${encodeURIComponent(q)}&t=&z=16&ie=UTF8&iwloc=&output=embed`;
      document.getElementById('openGmapsLink').href = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`;
    }

    function closeMapPicker() {
      document.getElementById('mapModal').style.display = 'none';
    }

    function confirmMapPoint() {
      const q = document.getElementById('mapSearchInput').value.trim();
      const label = document.getElementById('mapLabelInput').value.trim() || q || `${tempLat.toFixed(4)}, ${tempLng.toFixed(4)}`;
      const coordText = document.getElementById('mapCoordDisplay').value.trim();
      const m = coordText.match(/(-?\\d+\\.\\d+)\\s*,\\s*(-?\\d+\\.\\d+)/);
      if (m) {
        tempLat = parseFloat(m[1]);
        tempLng = parseFloat(m[2]);
      }
      attachedGeoPoint = { lat: tempLat, lng: tempLng, label };
      renderContextChips();
      closeMapPicker();
    }

    function fillPrompt(text) {
      const inp = document.getElementById('promptInput');
      inp.value = text;
      inp.focus();
    }

    function handleKey(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendPrompt();
      }
    }

    // --- Workspaces ---
    async function loadWorkspaces() {
      const res = await fetch('/api/workspaces');
      workspaces = await res.json();
      if (workspaces.length === 0) {
        await createNewSession('Điều tra mới #1');
        return;
      }
      if (!activeWorkspaceId || !workspaces.some(w => w.id === activeWorkspaceId)) {
        activeWorkspaceId = workspaces[0].id;
      }
      renderWorkspaceList();
      await Promise.all([loadChatHistory(), loadDossier()]);
    }

    function renderWorkspaceList() {
      const container = document.getElementById('wsList');
      container.innerHTML = '';
      workspaces.forEach(w => {
        const div = document.createElement('div');
        div.className = 'ws-item' + (w.id === activeWorkspaceId ? ' active' : '');
        div.onclick = () => selectWorkspace(w.id);

        const nameSpan = document.createElement('span');
        nameSpan.className = 'ws-name';
        nameSpan.textContent = w.name;
        div.appendChild(nameSpan);

        const actions = document.createElement('div');
        actions.className = 'ws-actions';

        const renameBtn = document.createElement('button');
        renameBtn.className = 'ws-icon-btn';
        renameBtn.title = 'Đổi tên project';
        renameBtn.innerHTML = '<svg class="ico" viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>';
        renameBtn.onclick = (e) => { e.stopPropagation(); renameSession(w.id, w.name); };

        const delBtn = document.createElement('button');
        delBtn.className = 'ws-icon-btn del';
        delBtn.title = 'Xóa project';
        delBtn.innerHTML = '<svg class="ico" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>';
        delBtn.onclick = (e) => { e.stopPropagation(); deleteSession(w.id, w.name); };

        actions.appendChild(renameBtn);
        actions.appendChild(delBtn);
        div.appendChild(actions);
        container.appendChild(div);
      });
      const current = workspaces.find(w => w.id === activeWorkspaceId);
      document.getElementById('activeWsTitle').textContent = current ? current.name : 'Stalker++ Agent';
    }

    async function selectWorkspace(id) {
      activeWorkspaceId = id;
      renderWorkspaceList();
      await loadDossier();
      await loadChatHistory();
      syncPinButtons();
    }

    async function createNewSession(customName) {
      const name = customName || `Điều tra #${workspaces.length + 1}`;
      const res = await fetch('/api/workspaces', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, description: 'OSINT Agent Session'})
      });
      const ws = await res.json();
      activeWorkspaceId = ws.id;
      await loadWorkspaces();
    }

    async function renameSession(id, currentName) {
      const next = window.prompt('Đổi tên project:', currentName);
      if (!next || !next.trim() || next.trim() === currentName) return;
      await fetch(`/api/workspaces/${id}`, {
        method: 'PATCH', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: next.trim()})
      });
      await loadWorkspaces();
    }

    async function deleteSession(id, name) {
      if (!window.confirm(`Xóa project "${name}"?`)) return;
      await fetch(`/api/workspaces/${id}`, { method: 'DELETE' });
      if (activeWorkspaceId === id) activeWorkspaceId = null;
      await loadWorkspaces();
    }

    // --- Verified Dossier CRUD ---
    function normalizeDossierUrl(url) {
      return String(url || '').trim().replace(/\\/+$/, '').toLowerCase();
    }

    function isSourceInDossier(url, fieldKey, fieldValue) {
      const nUrl = normalizeDossierUrl(url);
      const nKey = String(fieldKey || '').trim().toLowerCase();
      const nVal = String(fieldValue || '').trim().toLowerCase();
      return dossierItems.some(it => {
        const itUrl = normalizeDossierUrl(it.source_url);
        if (nUrl && itUrl && nUrl === itUrl) return true;
        if (nKey && nVal && (it.field_key || '').trim().toLowerCase() === nKey && (it.field_value || '').trim().toLowerCase() === nVal) return true;
        return false;
      });
    }

    function syncPinButtons() {
      document.querySelectorAll('.pin-btn[data-src-url]').forEach(btn => {
        const url = btn.getAttribute('data-src-url') || '';
        const pinned = isSourceInDossier(url, '', '');
        btn.disabled = pinned;
        btn.classList.toggle('pinned', pinned);
        btn.textContent = pinned ? '✓ Đã thêm' : '+ Lưu vào Hồ sơ';
      });
    }

    async function loadDossier() {
      if (!activeWorkspaceId) return;
      const res = await fetch(`/api/workspaces/${activeWorkspaceId}/dossier`);
      const data = await res.json();
      const items = data.items || [];
      dossierItems = items;
      document.getElementById('dossierCount').textContent = items.length;
      const list = document.getElementById('dossierList');
      if (items.length === 0) {
        list.innerHTML = '<div style="font-size:0.78rem; color:var(--ink-muted); padding:16px; text-align:center; border:1px dashed var(--border); border-radius:8px;">Chưa có thông tin nào được ghim vào Hồ sơ tổng hợp.</div>';
        syncPinButtons();
        return;
      }
      list.innerHTML = items.map(it => `
        <div class="dossier-item">
          <div class="dossier-item-top">
            <span class="dossier-key">${escapeHtml(it.field_key)}</span>
            <div style="display:flex; gap:3px;">
              <button class="ws-icon-btn" title="Sửa" onclick="editDossierItem('${it.id}', ${escapeHtml(JSON.stringify(it.field_key))}, ${escapeHtml(JSON.stringify(it.field_value))})">
                <svg class="ico" viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              </button>
              <button class="ws-icon-btn del" title="Xóa" onclick="deleteDossierItem('${it.id}')">
                <svg class="ico" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
              </button>
            </div>
          </div>
          <div class="dossier-val">${escapeHtml(it.field_value)}</div>
          ${it.source_url ? `<a class="dossier-src" href="${escapeHtml(it.source_url)}" target="_blank" rel="noopener">${escapeHtml(it.source_url)}</a>` : ''}
        </div>
      `).join('');
      syncPinButtons();
    }

    async function pinToDossier(field_key, field_value, source_url) {
      if (!activeWorkspaceId) return {already_exists: false};
      if (isSourceInDossier(source_url, field_key, field_value)) {
        syncPinButtons();
        return {already_exists: true};
      }
      const res = await fetch(`/api/workspaces/${activeWorkspaceId}/dossier`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({field_key, field_value, source_url: source_url || ''})
      });
      const saved = await res.json();
      await loadDossier();
      return saved;
    }

    async function addManualDossier() {
      const field_key = document.getElementById('dosKey').value.trim();
      const field_value = document.getElementById('dosVal').value.trim();
      const source_url = document.getElementById('dosSrc').value.trim();
      if (!field_key || !field_value) return;
      const saved = await pinToDossier(field_key, field_value, source_url);
      if (saved && saved.already_exists) {
        window.alert('Thông tin hoặc nguồn này đã có trong Hồ sơ tổng hợp rồi.');
        return;
      }
      document.getElementById('dosKey').value = '';
      document.getElementById('dosVal').value = '';
      document.getElementById('dosSrc').value = '';
    }

    async function editDossierItem(id, oldKey, oldVal) {
      const nextVal = window.prompt(`Chỉnh sửa giá trị cho "${oldKey}":`, oldVal);
      if (nextVal === null || !nextVal.trim()) return;
      await fetch(`/api/dossier/${id}`, {
        method: 'PATCH', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({field_value: nextVal.trim()})
      });
      await loadDossier();
    }

    async function deleteDossierItem(id) {
      await fetch(`/api/dossier/${id}`, { method: 'DELETE' });
      await loadDossier();
    }

    // --- Chat History & SSE Streaming ---
    async function loadChatHistory() {
      if (!activeWorkspaceId) return;
      const inner = document.getElementById('chatInner');
      const res = await fetch(`/api/workspaces/${activeWorkspaceId}/messages`);
      const data = await res.json();
      const msgs = data.messages || [];

      if (msgs.length === 0) {
        inner.innerHTML = `
          <div id="welcomeView" class="welcome">
            <h2>Bạn muốn truy vết thông tin ai hôm nay?</h2>
            <p>
              Nhập các manh mối cách nhau bằng dấu phẩy, bấm <b>+</b> để đính kèm ảnh, file hoặc chọn tọa độ bản đồ. Lưu các phát hiện chính xác vào <b>Hồ sơ tổng hợp</b> bên phải để Agent dùng cho các lượt tìm tiếp theo.
            </p>
            <div class="starter-grid">
              <div class="starter-card" onclick="fillPrompt('Nguyễn Minh Anh, THPT Demo, 15/06/2005, UEH, IELTS 7.0, 31251029999, minhanh.31251029999@st.ueh.edu.vn')">
                <div class="starter-label">Manh mối cách nhau dấu phẩy (Mẫu)</div>
                <div class="starter-text">Nguyễn Minh Anh, THPT Demo, 15/06/2005, UEH, IELTS 7.0, 31251029999, minhanh.31251029999@st.ueh.edu.vn</div>
              </div>
              <div class="starter-card" onclick="fillPrompt('Nguyễn Văn An, HCMUT, @nva_dev02, -ca sĩ')">
                <div class="starter-label">Tìm kèm Alias & Loại trừ</div>
                <div class="starter-text">Nguyễn Văn An, HCMUT, @nva_dev02, -ca sĩ</div>
              </div>
            </div>
          </div>
        `;
        return;
      }

      inner.innerHTML = '';
      msgs.forEach(m => {
        if (m.role === 'user') appendUserMessage(m.content);
        else renderAssistantResponse(m.payload && Object.keys(m.payload).length ? m.payload : {assistant_reply: m.content});
      });
      scrollToBottom();
    }

    function appendUserMessage(text) {
      const welcome = document.getElementById('welcomeView');
      if (welcome) welcome.remove();
      const wrap = document.createElement('div');
      wrap.className = 'msg user';
      wrap.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
      document.getElementById('chatInner').appendChild(wrap);
      scrollToBottom();
    }

    function createStreamStatusCard() {
      const wrap = document.createElement('div');
      wrap.className = 'msg assistant';
      wrap.id = 'streamCard';
      wrap.innerHTML = `<div class="stream-box" id="streamBox"><div class="stream-line"><span class="pulse-dot"></span><span>Đang khởi động Multi-Agent Stream...</span></div></div>`;
      document.getElementById('chatInner').appendChild(wrap);
      scrollToBottom();
    }

    function appendStreamLine(text) {
      const box = document.getElementById('streamBox');
      if (!box) return;
      const line = document.createElement('div');
      line.className = 'stream-line';
      line.innerHTML = `<span class="pulse-dot"></span><span>${escapeHtml(text)}</span>`;
      box.appendChild(line);
      scrollToBottom();
    }

    function renderAssistantResponse(data) {
      const sc = document.getElementById('streamCard');
      if (sc) sc.remove();

      const p = data.parsed_clues || {};
      const pills = [];
      if (p.target_name) pills.push(`<span class="clue-pill">Mục tiêu: ${escapeHtml(p.target_name)}</span>`);
      if (p.birth_date) pills.push(`<span class="clue-pill">Ngày sinh: ${escapeHtml(p.birth_date)}</span>`);
      (p.organizations || []).forEach(o => pills.push(`<span class="clue-pill">Tổ chức: ${escapeHtml(o)}</span>`));
      (p.locations || []).forEach(l => pills.push(`<span class="clue-pill">Địa điểm: ${escapeHtml(l)}</span>`));
      (data.learned_negative_keywords || []).forEach(n => pills.push(`<span class="clue-pill neg">Loại trừ: -${escapeHtml(n)}</span>`));

      let traceHtml = '';
      if (data.reasoning_steps && data.reasoning_steps.length > 0) {
        const rows = data.reasoning_steps.map(s =>
          `<div class="trace-row"><b>[${escapeHtml(s.agent)}] ${escapeHtml(s.action)}</b>: ${escapeHtml(s.detail)}</div>`
        ).join('');
        traceHtml = `<details class="reasoning"><summary>Quá trình suy luận Agent (${data.reasoning_steps.length} bước)</summary><div class="trace-list">${rows}</div></details>`;
      }

      let sourcesHtml = '';
      if (data.discovered_sources && data.discovered_sources.length > 0) {
        const cards = data.discovered_sources.map(s => {
          const safeTitle = escapeHtml(s.title || s.url).replace(/'/g, '&#39;');
          const safeSnip = escapeHtml(s.snippet || s.title || '').replace(/'/g, '&#39;');
          const safeUrl = escapeHtml(s.url || '').replace(/'/g, '&#39;');
          const alreadyPinned = isSourceInDossier(s.url || '', '', '');
          return `
            <div class="source-card">
              <div class="source-main">
                <a class="source-url" href="${safeUrl}" target="_blank" rel="noopener">${escapeHtml(s.title || s.url)}</a>
                <div class="source-snip">${escapeHtml(s.snippet || '')}</div>
              </div>
              <button class="pin-btn ${alreadyPinned ? 'pinned' : ''}" data-src-url="${safeUrl}" ${alreadyPinned ? 'disabled' : ''} onclick="pinToDossier('Nguồn đã xác nhận', '${safeTitle} — ${safeSnip.slice(0, 120)}', '${safeUrl}')">${alreadyPinned ? '✓ Đã thêm' : '+ Lưu vào Hồ sơ'}</button>
            </div>
          `;
        }).join('');
        sourcesHtml = `<div class="sub-heading">Nguồn công khai tìm được</div><div style="display:flex;flex-direction:column;gap:6px;">${cards}</div>`;
      }

      let dorksHtml = '';
      if (data.suggested_dorks && data.suggested_dorks.length > 0) {
        const rows = data.suggested_dorks.map(d => {
          const gUrl = 'https://www.google.com/search?q=' + encodeURIComponent(d.query);
          const gAiUrl = 'https://www.google.com/search?udm=50&q=' + encodeURIComponent(d.query);
          return `<div class="dork-row"><span class="dork-q">${escapeHtml(d.query)}</span><div style="display:flex;gap:5px;flex-shrink:0;"><a class="dork-open" href="${gAiUrl}" target="_blank" rel="noopener">Google AI</a><a class="dork-open" href="${gUrl}" target="_blank" rel="noopener">Google</a></div></div>`;
        }).join('');
        dorksHtml = `<div class="sub-heading">Truy vấn mở rộng (Google AI Mode)</div><div style="display:flex;flex-direction:column;gap:6px;">${rows}</div>`;
      }

      const wrap = document.createElement('div');
      wrap.className = 'msg assistant';
      wrap.innerHTML = `
        <div class="assistant-card">
          ${pills.length ? `<div class="clue-row">${pills.join('')}</div>` : ''}
          ${traceHtml}
          <div class="assistant-text">${formatMd(data.assistant_reply || '')}</div>
          ${sourcesHtml}
          ${dorksHtml}
        </div>
      `;
      document.getElementById('chatInner').appendChild(wrap);
      scrollToBottom();
    }

    function scrollToBottom() {
      const sc = document.getElementById('chatScroll');
      sc.scrollTop = sc.scrollHeight;
    }

    async function sendPrompt() {
      const inp = document.getElementById('promptInput');
      const btn = document.getElementById('sendBtn');
      const prompt = inp.value.trim();
      if (!prompt || !activeWorkspaceId) return;

      const modelOverride = document.getElementById('modelSelect').value;
      const imgPayload = attachedImageB64;
      const mimePayload = attachedImageMime;
      const filePayload = attachedFileText;
      const geoPayload = attachedGeoPoint;

      inp.value = '';
      attachedImageB64 = null;
      attachedFileText = null;
      attachedGeoPoint = null;
      renderContextChips();

      btn.disabled = true;
      let displayMsg = prompt;
      if (geoPayload) displayMsg += ` [Tọa độ: ${geoPayload.label} (${geoPayload.lat.toFixed(4)}, ${geoPayload.lng.toFixed(4)})]`;
      if (imgPayload) displayMsg += ' [Ảnh đính kèm]';
      if (filePayload) displayMsg += ` [File: ${attachedFileName}]`;
      appendUserMessage(displayMsg);
      createStreamStatusCard();

      try {
        const res = await fetch(`/api/workspaces/${activeWorkspaceId}/chat/stream`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            prompt,
            live_search: true,
            deep_mode: deepModeEnabled,
            model_override: modelOverride,
            image_b64: imgPayload,
            image_mime: mimePayload,
            geo_point: geoPayload,
            attached_file_text: filePayload
          })
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const blocks = buffer.split('\\n\\n');
          buffer = blocks.pop() || '';
          for (const block of blocks) {
            const evMatch = block.match(/event:\\s*(\\w+)/);
            const dataMatch = block.match(/data:\\s*(.+)/s);
            if (!evMatch || !dataMatch) continue;
            const evType = evMatch[1];
            const payload = JSON.parse(dataMatch[1]);
            if (evType === 'status') appendStreamLine(payload.step);
            else if (evType === 'step') appendStreamLine(`[${payload.agent}] ${payload.action}: ${payload.detail}`);
            else if (evType === 'done') renderAssistantResponse(payload);
          }
        }
      } catch (err) {
        renderAssistantResponse({assistant_reply: 'Lỗi kết nối stream: ' + err.message});
      } finally {
        btn.disabled = false;
        inp.focus();
      }
    }

    function exportCsv() {
      if (activeWorkspaceId) window.open(`/api/workspaces/${activeWorkspaceId}/export/csv`, '_blank');
    }

    // --- Integration Hub JS ---
    function switchHubTab(tab) {
      ['keys', 'local', 'mcp'].forEach(t => {
        document.getElementById('hubTab-' + t).classList.toggle('active', t === tab);
        document.getElementById('hubPane-' + t).style.display = t === tab ? 'flex' : 'none';
      });
    }

    async function openAiSettings() {
      document.getElementById('aiModal').style.display = 'flex';
      await Promise.all([loadKeyPool(), loadLocalHost(), loadMcpConfigs()]);
    }

    function closeAiSettings() {
      document.getElementById('aiModal').style.display = 'none';
    }

    async function loadKeyPool() {
      const res = await fetch('/api/integrations/keys');
      const data = await res.json();
      const box = document.getElementById('keyPoolList');
      const keys = data.keys || [];
      if (keys.length === 0) {
        box.innerHTML = '<div style="font-size:0.78rem; color:var(--ink-muted); padding:10px; border:1px dashed var(--border); border-radius:7px; text-align:center;">Chưa có API Key nào trong Pool.</div>';
        return;
      }
      box.innerHTML = keys.map(k => `
        <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 10px; border:1px solid var(--border); border-radius:7px; background:var(--bg-sidebar); font-size:0.78rem;">
          <div>
            <b>${escapeHtml(k.name)}</b> <span class="clue-pill">${escapeHtml(k.provider)}</span>
            <span class="clue-pill ${k.status === 'COOLDOWN' ? 'neg' : 'ok'}">${escapeHtml(k.status)}</span>
            <div style="font-family:var(--font-mono); font-size:0.7rem; color:var(--ink-muted); margin-top:3px;">
              ${escapeHtml(k.masked_key)} ${k.model ? '· ' + escapeHtml(k.model) : ''} · Dùng: ${k.usage_count} · Lỗi: ${k.error_count}
            </div>
          </div>
          <div style="display:flex; gap:5px;">
            <button class="btn" style="height:26px; font-size:0.72rem;" onclick="togglePoolKey('${k.id}', ${!k.enabled})">${k.enabled ? 'Tắt' : 'Bật'}</button>
            <button class="btn" style="height:26px; font-size:0.72rem; color:var(--neg);" onclick="deletePoolKey('${k.id}')">Xóa</button>
          </div>
        </div>
      `).join('');
    }

    async function addPoolKey() {
      const name = document.getElementById('newKeyName').value.trim();
      const provider = document.getElementById('newKeyProvider').value;
      const api_key = document.getElementById('newKeySecret').value.trim();
      const model = document.getElementById('newKeyModel').value.trim();
      if (!name || !api_key) return;
      await fetch('/api/integrations/keys', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, provider, api_key, model})
      });
      document.getElementById('newKeyName').value = '';
      document.getElementById('newKeySecret').value = '';
      document.getElementById('newKeyModel').value = '';
      await loadKeyPool();
    }

    async function togglePoolKey(id, enabled) {
      await fetch(`/api/integrations/keys/${id}`, {
        method: 'PATCH', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled})
      });
      await loadKeyPool();
    }

    async function deletePoolKey(id) {
      await fetch(`/api/integrations/keys/${id}`, { method: 'DELETE' });
      await loadKeyPool();
    }

    async function loadLocalHost() {
      const res = await fetch('/api/integrations/local');
      const cfg = await res.json();
      document.getElementById('localActiveMode').value = cfg.active_mode || 'auto';
      document.getElementById('localOllamaUrl').value = cfg.ollama_base_url || 'http://localhost:11434';
      document.getElementById('localOllamaModel').value = cfg.ollama_model || 'qwen2.5:7b';
      document.getElementById('localSearxngUrl').value = cfg.searxng_url || '';
    }

    async function saveLocalHost() {
      const payload = {
        active_mode: document.getElementById('localActiveMode').value,
        ollama_base_url: document.getElementById('localOllamaUrl').value.trim(),
        ollama_model: document.getElementById('localOllamaModel').value.trim(),
        searxng_url: document.getElementById('localSearxngUrl').value.trim()
      };
      await fetch('/api/integrations/local', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      document.getElementById('localSaveStatus').textContent = 'Đã lưu cấu hình Host Local.';
    }

    async function probeOllama() {
      const url = document.getElementById('localOllamaUrl').value.trim();
      const el = document.getElementById('ollamaProbeStatus');
      const res = await fetch('/api/integrations/ollama/models?base_url=' + encodeURIComponent(url));
      const data = await res.json();
      el.textContent = data.reachable ? ('Model local: ' + (data.models.join(', ') || 'Chưa có model')) : ('Không kết nối được Ollama tại ' + url);
    }

    async function probeSearxng() {
      const url = document.getElementById('localSearxngUrl').value.trim() || 'http://localhost:8888';
      document.getElementById('localSearxngUrl').value = url;
      const el = document.getElementById('searxngProbeStatus');
      el.textContent = 'Đang kiểm tra SearXNG JSON API...';
      const res = await fetch('/api/integrations/searxng/test?base_url=' + encodeURIComponent(url));
      const data = await res.json();
      if (data.reachable && data.json_enabled) {
        const eng = (data.engines && data.engines.length) ? (' · Engines: ' + data.engines.join(', ')) : '';
        el.innerHTML = `<span style="color:var(--ok);">SearXNG OK (${data.sample_count} kết quả mẫu${escapeHtml(eng)}) — sẵn sàng chạy song song với ddgs.</span>`;
      } else if (data.reachable && !data.json_enabled) {
        el.innerHTML = `<span style="color:var(--warn);">${escapeHtml(data.error)}</span>`;
      } else {
        el.innerHTML = `<span style="color:var(--neg);">Không kết nối được SearXNG tại ${escapeHtml(url)}. Chạy: <code style="font-family:var(--font-mono);">cd searxng &amp;&amp; docker compose up -d</code></span>`;
      }
    }

    async function loadMcpConfigs() {
      const res = await fetch('/api/integrations/mcp-config');
      const data = await res.json();
      document.getElementById('mcpAntigravity').textContent = data.antigravity_config;
      document.getElementById('mcpClaude').textContent = data.claude_code_cli;
      document.getElementById('mcpCodex').textContent = data.codex_cursor_config;
    }

    async function testMcpHandshake() {
      const res = await fetch('/api/mcp', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({jsonrpc: '2.0', id: 1, method: 'tools/list'})
      });
      const data = await res.json();
      const names = (data.result && data.result.tools || []).map(t => t.name);
      document.getElementById('mcpTestOut').textContent = `MCP OK (${names.length} tools): ` + names.join(', ');
    }

    function copyText(elId) {
      navigator.clipboard.writeText(document.getElementById(elId).textContent);
    }

    loadWorkspaces();
  </script>
</body>
</html>
"""
