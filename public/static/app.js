/* ===========================================================
   net·console — vanilla JS frontend
   Comunica con backend FastAPI (paramiko) via REST:
     GET  {base}/api/health
     POST {base}/api/run
   Storage locale: rubrica device, script, storico sessioni, URL backend.
   =========================================================== */

(() => {
  'use strict';

  // ─────────── localStorage helpers ───────────
  const KEYS = {
    backend: 'rcfg.backend',
    devices: 'rcfg.devices',
    scripts: 'rcfg.scripts',
    history: 'rcfg.history',
  };
  const read = (k, fb) => {
    try { const r = localStorage.getItem(k); return r ? JSON.parse(r) : fb; }
    catch { return fb; }
  };
  const write = (k, v) => localStorage.setItem(k, JSON.stringify(v));
  const uid = () => Math.random().toString(36).slice(2, 10);

  const Store = {
    getBackend: () => localStorage.getItem(KEYS.backend) || 'http://localhost:8000',
    setBackend: (u) => localStorage.setItem(KEYS.backend, u.replace(/\/$/, '')),

    listDevices: () => read(KEYS.devices, []),
    saveDevice: (d) => {
      const all = Store.listDevices().filter(x => x.id !== d.id);
      all.unshift(d); write(KEYS.devices, all);
    },
    deleteDevice: (id) => write(KEYS.devices, Store.listDevices().filter(d => d.id !== id)),

    listScripts: () => read(KEYS.scripts, []),
    saveScript: (s) => {
      const all = Store.listScripts().filter(x => x.id !== s.id);
      all.unshift(s); write(KEYS.scripts, all);
    },
    deleteScript: (id) => write(KEYS.scripts, Store.listScripts().filter(s => s.id !== id)),

    listHistory: () => read(KEYS.history, []),
    pushHistory: (rec) => write(KEYS.history, [rec, ...Store.listHistory()].slice(0, 100)),
    clearHistory: () => write(KEYS.history, []),
  };

  // ─────────── DOM helpers ───────────
  const $  = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));
  const escapeHtml = (s) => String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  // ─────────── toast ───────────
  function toast(msg, type = 'info') {
    const c = $('#toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    c.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .25s'; }, 2600);
    setTimeout(() => el.remove(), 3000);
  }

  // ─────────── form state ───────────
  const F = {
    name:    $('#f-name'),
    host:    $('#f-host'),
    port:    $('#f-port'),
    user:    $('#f-user'),
    password:$('#f-password'),
    device:  $('#f-device'),
    nohostkey: $('#f-nohostkey'),
    savepwd:   $('#f-savepwd'),
    cmds:    $('#f-commands'),
  };
  const getForm = () => ({
    name: F.name.value.trim(),
    host: F.host.value.trim(),
    port: parseInt(F.port.value) || 22,
    user: F.user.value.trim(),
    password: F.password.value,
    device: F.device.value,
    noHostKey: F.nohostkey.checked,
    savePassword: F.savepwd.checked,
  });
  const setForm = (v) => {
    F.name.value = v.name ?? '';
    F.host.value = v.host ?? '';
    F.port.value = v.port ?? 22;
    F.user.value = v.user ?? '';
    F.password.value = v.password ?? '';
    F.device.value = v.device ?? 'generic';
    F.nohostkey.checked = v.noHostKey ?? true;
    F.savepwd.checked   = v.savePassword ?? false;
  };

  // ─────────── backend ───────────
  const dot = $('#backend-dot');
  const setDot = (s) => { dot.className = 'dot ' + (s === 'ok' ? 'dot-ok' : s === 'down' ? 'dot-down' : 'dot-idle'); };

  async function pingBackend() {
    setDot('idle');
    try {
      const r = await fetch(Store.getBackend() + '/api/health', { method: 'GET' });
      setDot(r.ok ? 'ok' : 'down');
      return r.ok;
    } catch { setDot('down'); return false; }
  }
  async function runSSH(payload) {
    const r = await fetch(Store.getBackend() + '/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const t = await r.text().catch(() => r.statusText);
      throw new Error(`Backend ${r.status}: ${t}`);
    }
    return r.json();
  }

  // ─────────── terminal render ───────────
  const term = $('#terminal');
  let currentSession = null;
  let isRunning = false;

  function renderTerminal() {
    if (!currentSession && !isRunning) {
      term.innerHTML = '<div class="terminal-empty">— nessun output — esegui un comando per iniziare</div>';
      return;
    }
    let html = '';
    const s = currentSession;
    if (s) {
      html += `<div class="t-prompt">╭─ ${escapeHtml(s.user)}@${escapeHtml(s.host)} [${escapeHtml(s.device)}]</div>`;
      if (s.banner) html += `<div class="t-banner">${escapeHtml(s.banner)}</div>`;
      if (s.error)  html += `<div class="t-error">✗ ${escapeHtml(s.error)}</div>`;
      for (const r of (s.results || [])) {
        html += `<div class="t-block">`;
        html += `<div><span class="t-prompt">❯ </span><span class="t-cmd">${escapeHtml(r.command)}</span><span class="t-meta">(${r.duration_ms}ms)</span></div>`;
        if (r.error) html += `<div class="t-error">${escapeHtml(r.error)}</div>`;
        else html += `<div>${escapeHtml(r.output) || '<span class="t-meta">(nessun output)</span>'}</div>`;
        html += `</div>`;
      }
      if (!isRunning) {
        const ts = new Date(s.timestamp).toLocaleTimeString();
        html += `<div class="t-prompt" style="opacity:.7">╰─ session ended at ${ts}</div>`;
      }
    }
    if (isRunning) {
      const host = getForm().host || '…';
      html += `<div class="t-running"><span class="spinner"></span> esecuzione su ${escapeHtml(host)}…</div>`;
    }
    term.innerHTML = html;
    term.scrollTop = term.scrollHeight;
  }

  // ─────────── exec ───────────
  async function execute() {
    const f = getForm();
    if (!f.host || !f.user) { toast('Host e user obbligatori', 'error'); return; }
    const cmds = F.cmds.value.split('\n').map(x => x.trim()).filter(Boolean);
    if (cmds.length === 0) { toast('Inserisci almeno un comando', 'error'); return; }

    isRunning = true;
    currentSession = null;
    $('#btn-run').disabled = true;
    renderTerminal();

    try {
      const res = await runSSH({
        host: f.host, user: f.user,
        password: f.password || undefined,
        port: f.port, device: f.device,
        commands: cmds,
        no_host_key_check: f.noHostKey,
      });
      currentSession = {
        id: uid(), timestamp: Date.now(),
        host: res.host, device: res.device, user: f.user,
        success: res.success, banner: res.banner ?? null, error: res.error ?? null,
        results: res.results || [],
      };
      Store.pushHistory(currentSession);
      renderHistory();
      if (res.success) toast(`Eseguiti ${(res.results||[]).length} comandi`, 'success');
      else toast(res.error || 'Errore SSH', 'error');
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      currentSession = {
        id: uid(), timestamp: Date.now(),
        host: f.host, device: f.device, user: f.user,
        success: false, error: `Backend irraggiungibile — ${msg}`, results: [],
      };
      Store.pushHistory(currentSession);
      renderHistory();
      toast("Backend irraggiungibile. Controlla l'URL in alto a destra.", 'error');
    } finally {
      isRunning = false;
      $('#btn-run').disabled = false;
      renderTerminal();
    }
  }

  // ─────────── side panel rendering ───────────
  function renderDevices() {
    const list = Store.listDevices();
    const c = $('#list-devices');
    if (!list.length) { c.innerHTML = '<div class="list-empty">nessun device salvato</div>'; return; }
    c.innerHTML = list.map(d => `
      <div class="list-item" data-id="${d.id}" data-action="load-device">
        <div class="li-row">
          <span class="li-title">${escapeHtml(d.name)}</span>
          <button class="li-del" data-action="del-device" data-id="${d.id}" title="elimina">×</button>
        </div>
        <span class="li-sub">${escapeHtml(d.user)}@${escapeHtml(d.host)}:${d.port} · ${escapeHtml(d.device)}</span>
      </div>`).join('');
  }
  function renderScripts() {
    const list = Store.listScripts();
    const c = $('#list-scripts');
    if (!list.length) { c.innerHTML = '<div class="list-empty">nessuno script salvato</div>'; return; }
    c.innerHTML = list.map(s => `
      <div class="list-item" data-id="${s.id}" data-action="load-script">
        <div class="li-row">
          <span class="li-title">${escapeHtml(s.name)}</span>
          <button class="li-del" data-action="del-script" data-id="${s.id}" title="elimina">×</button>
        </div>
        <span class="li-sub">${s.commands.length} comandi · ${escapeHtml(s.device)}</span>
      </div>`).join('');
  }
  function renderHistory() {
    const list = Store.listHistory();
    const c = $('#list-history');
    if (!list.length) { c.innerHTML = '<div class="list-empty">nessuna sessione</div>'; return; }
    c.innerHTML = list.map(h => {
      const ts = new Date(h.timestamp).toLocaleString();
      const cls = h.success ? 'li-status-ok' : 'li-status-err';
      const sym = h.success ? '✓' : '✗';
      return `
        <div class="list-item" data-id="${h.id}" data-action="load-history">
          <div class="li-row">
            <span class="li-title"><span class="${cls}">${sym}</span> ${escapeHtml(h.user)}@${escapeHtml(h.host)}</span>
            <span class="li-sub">${(h.results||[]).length} cmd</span>
          </div>
          <span class="li-sub">${ts} · ${escapeHtml(h.device)}</span>
        </div>`;
    }).join('');
  }
  function renderAll() { renderDevices(); renderScripts(); renderHistory(); }

  // ─────────── event wiring ───────────
  function init() {
    // backend url input
    $('#backend-url').value = Store.getBackend();
    $('#backend-test').addEventListener('click', pingBackend);
    $('#backend-save').addEventListener('click', () => {
      const v = $('#backend-url').value.trim();
      if (!v) return toast('URL vuoto', 'error');
      Store.setBackend(v);
      $('#backend-url').value = Store.getBackend();
      toast('Backend salvato', 'success');
      pingBackend();
    });

    // password toggle
    $('#pwd-toggle').addEventListener('click', () => {
      F.password.type = F.password.type === 'password' ? 'text' : 'password';
    });

    // run
    $('#btn-run').addEventListener('click', execute);

    // save device
    $('#btn-save-device').addEventListener('click', () => {
      const f = getForm();
      if (!f.host || !f.user) { toast('Host e user obbligatori', 'error'); return; }
      Store.saveDevice({
        id: uid(),
        name: f.name || `${f.user}@${f.host}`,
        host: f.host, port: f.port, user: f.user, device: f.device,
        savePassword: f.savePassword,
        password: f.savePassword ? f.password : undefined,
      });
      renderDevices();
      toast('Device salvato', 'success');
    });

    // save script
    $('#btn-save-script').addEventListener('click', () => {
      const cmds = F.cmds.value.split('\n').map(x => x.trim()).filter(Boolean);
      if (!cmds.length) { toast('Nessun comando da salvare', 'error'); return; }
      const name = window.prompt('Nome dello script:');
      if (!name) return;
      Store.saveScript({ id: uid(), name, device: getForm().device, commands: cmds });
      renderScripts();
      toast('Script salvato', 'success');
    });

    // tabs
    $$('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
        const t = btn.dataset.tab;
        $$('.tab-panel').forEach(p => p.classList.toggle('active', p.dataset.panel === t));
      });
    });

    // delegated clicks: load/delete from lists
    document.addEventListener('click', (e) => {
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;
      const action = t.dataset.action;
      const id = t.dataset.id;

      if (action === 'del-device') {
        e.stopPropagation();
        Store.deleteDevice(id); renderDevices(); toast('Device eliminato'); return;
      }
      if (action === 'del-script') {
        e.stopPropagation();
        Store.deleteScript(id); renderScripts(); toast('Script eliminato'); return;
      }

      const item = t.closest('.list-item');
      if (!item) return;
      const itemAction = item.dataset.action;
      const itemId = item.dataset.id;

      if (itemAction === 'load-device') {
        const d = Store.listDevices().find(x => x.id === itemId);
        if (d) {
          setForm({
            name: d.name, host: d.host, port: d.port, user: d.user,
            password: d.password ?? '', device: d.device,
            noHostKey: true, savePassword: !!d.savePassword,
          });
          toast(`Caricato ${d.name}`, 'success');
        }
      } else if (itemAction === 'load-script') {
        const s = Store.listScripts().find(x => x.id === itemId);
        if (s) {
          F.cmds.value = s.commands.join('\n');
          F.device.value = s.device;
          toast(`Script "${s.name}" caricato`, 'success');
        }
      } else if (itemAction === 'load-history') {
        const h = Store.listHistory().find(x => x.id === itemId);
        if (h) {
          currentSession = h;
          F.host.value = h.host; F.user.value = h.user; F.device.value = h.device;
          F.cmds.value = (h.results || []).map(r => r.command).join('\n');
          renderTerminal();
        }
      }
    });

    $('#btn-clear-history').addEventListener('click', () => {
      if (!confirm('Svuotare lo storico?')) return;
      Store.clearHistory(); renderHistory(); toast('Storico svuotato');
    });

    renderAll();
    renderTerminal();
    pingBackend();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
