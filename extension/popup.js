const API_BASE = 'http://127.0.0.1:8000';
let currentTabUrl = '';
let currentTabTitle = '';

function setStatus(msg, isErr = false) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.style.color = isErr ? '#ef4444' : '#22c55e';
}

async function init() {
  const wsSel = document.getElementById('wsSelect');
  try {
    const res = await fetch(`${API_BASE}/api/workspaces`);
    const list = await res.json();
    wsSel.textContent = '';
    if (!Array.isArray(list) || list.length === 0) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'Chưa có cuộc điều tra nào';
      wsSel.appendChild(opt);
    } else {
      for (const w of list) {
        const opt = document.createElement('option');
        opt.value = String(w.id || '');
        opt.textContent = String(w.name || 'Workspace');
        wsSel.appendChild(opt);
      }
    }
  } catch {
    wsSel.textContent = '';
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Không kết nối được localhost:8000';
    wsSel.appendChild(opt);
    setStatus('Hãy bật Stalker++ local trước (http://127.0.0.1:8000).', true);
  }

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.id) {
      currentTabUrl = tab.url || '';
      currentTabTitle = tab.title || currentTabUrl;
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          const sel = window.getSelection ? window.getSelection().toString().trim() : '';
          if (sel) return sel.slice(0, 2000);
          return (document.body ? document.body.innerText : '').trim().slice(0, 800);
        },
      });
      document.getElementById('clipText').value = result || '';
    }
  } catch {
    // Restricted browser pages (chrome://)
  }
}

async function sendClip(analyze) {
  const wsId = document.getElementById('wsSelect').value;
  const fieldKey = document.getElementById('fieldKey').value.trim() || 'Browser Clip';
  const text = document.getElementById('clipText').value.trim();
  if (!wsId || !text) {
    setStatus('Vui lòng chọn cuộc điều tra và nhập nội dung cần gửi.', true);
    return;
  }
  setStatus(analyze ? 'Đang gửi và phân tích bằng Agent...' : 'Đang lưu vào Hồ sơ Tổng hợp...');
  try {
    const res = await fetch(`${API_BASE}/api/workspaces/${wsId}/clip`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: currentTabTitle || 'Browser Page',
        url: currentTabUrl || 'https://browser.local/clip',
        selected_text: text,
        field_key: fieldKey,
        pin_to_dossier: true,
        analyze_with_agent: analyze,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.dossier_item && data.dossier_item.already_exists) {
      setStatus('Nguồn này đã có trong Hồ sơ Tổng hợp (không lưu trùng).');
    } else {
      const nClaims = (data.extracted_claims || []).length;
      setStatus(`Đã lưu vào Stalker++ (${nClaims} đặc trưng rút trích).`);
    }
  } catch (err) {
    setStatus(`Lỗi: ${err.message}`, true);
  }
}

document.getElementById('sendPinBtn').addEventListener('click', () => sendClip(false));
document.getElementById('sendAnalyzeBtn').addEventListener('click', () => sendClip(true));
init();
