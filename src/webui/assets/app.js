/* Ooptra · Oopz ⇄ OneBot v11 桥接控制台 —— 前端逻辑（无外部依赖） */
'use strict';

const TOKEN_KEY = 'oopz.webui.token';
const SIGNED_OUT_KEY = 'oopz.webui.signedout';
const ADV_KEY = 'oopz.webui.advanced';
const POLL_MS = 3000;

const PAGE_META = {
  overview: ['概览', '一眼看清两条链路、流量与最近动态'],
  logs: ['日志', '实时跟随日志文件，可过滤、换行、下载'],
  config: ['配置', '常用项直接改；其余默认值适用于绝大多数情况，收在「高级选项」里'],
  account: ['账号', '查看凭据状态，或重新登录 Oopz'],
};
const GROUP_TITLE = { oopz: 'Oopz 账号与事件', onebot: 'OneBot v11 桥接', webui: 'Web 控制台' };

let token = '';
let pollTimer = null;
let logStream = null;
let loginPollTimer = null;
let configSchema = null;
let dirty = {};
let logBuffer = [];
let eventFilter = 'msg';
let showAdvanced = localStorage.getItem(ADV_KEY) === '1';

const $ = (id) => document.getElementById(id);
const show = (el, on) => { el.hidden = !on; };

/* ───────── 基础设施 ───────── */

class AuthError extends Error {}

function withToken(path) {
  if (!token) return path;
  return path + (path.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token);
}

async function api(path, opts = {}) {
  const res = await fetch(withToken(path), {
    method: opts.method || 'GET',
    headers: opts.body ? { 'Content-Type': 'application/json' } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let payload = null;
  try { payload = await res.json(); } catch (err) { payload = null; }
  if (res.status === 401) throw new AuthError('需要访问令牌');
  if (!res.ok) throw new Error((payload && payload.error) || ('HTTP ' + res.status));
  return payload || {};
}

function toast(title, text, kind) {
  const box = document.createElement('div');
  box.className = 'toast ' + (kind || '');
  box.innerHTML = '<b></b><span></span>';
  box.querySelector('b').textContent = title;
  box.querySelector('span').textContent = text || '';
  $('toasts').appendChild(box);
  setTimeout(() => box.remove(), kind === 'err' ? 6000 : 3600);
}

function fmtDuration(seconds) {
  if (!seconds || seconds <= 0) return '—';
  const t = Math.floor(seconds);
  const d = Math.floor(t / 86400), h = Math.floor((t % 86400) / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  if (d) return d + ' 天 ' + h + ' 小时';
  if (h) return h + ' 小时 ' + m + ' 分';
  if (m) return m + ' 分 ' + s + ' 秒';
  return s + ' 秒';
}

function fmtClock(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('zh-CN', { hour12: false });
}

function fmtAgo(ts) {
  if (!ts) return '从未';
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (diff < 60) return diff + ' 秒前';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false });
}

function text(id, value) {
  const node = $(id);
  if (node) node.textContent = value === undefined || value === null || value === '' ? '—' : String(value);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function copyText(value) {
  return navigator.clipboard.writeText(value).then(
    () => toast('已复制', String(value).slice(0, 40), 'ok'),
    () => toast('复制失败', '浏览器拒绝了剪贴板访问', 'err'),
  );
}

function confirmDialog(title, message, yesLabel) {
  return new Promise((resolve) => {
    $('dialog-title').textContent = title;
    $('dialog-text').textContent = message;
    $('dialog-yes').textContent = yesLabel || '确定';
    show($('dialog'), true);
    const done = (ok) => {
      show($('dialog'), false);
      $('dialog-yes').onclick = $('dialog-no').onclick = null;
      resolve(ok);
    };
    $('dialog-yes').onclick = () => done(true);
    $('dialog-no').onclick = () => done(false);
  });
}

function credsUsable(creds) {
  if (!creds) return false;
  return Boolean(String(creds.jwt_token || '').trim() || creds.has_password);
}

/* ───────── 登录闸门 ───────── */

async function tryStatus() {
  try {
    return { kind: 'ok', data: await api('/api/status') };
  } catch (err) {
    if (err instanceof AuthError) return { kind: 'auth' };
    return { kind: 'error', message: err.message };
  }
}

async function guard() {
  const probe = await tryStatus();
  if (probe.kind === 'auth') return { gate: 'token' };
  if (probe.kind === 'error') return { gate: 'offline', message: probe.message };
  state = probe.data;
  try {
    const cred = await api('/api/credentials');
    state.creds = cred.credentials || {};
  } catch (err) {
    state.creds = {};
  }
  if (!credsUsable(state.creds)) return { gate: 'oopz' };
  if (sessionStorage.getItem(SIGNED_OUT_KEY) === '1') return { gate: 'signedout' };
  return { gate: null };
}

let state = {};
let loginGate = 'token';

function showLogin(result) {
  loginGate = result.gate;
  show($('screen-app'), false);
  show($('screen-login'), true);

  const titles = {
    token: ['输入访问令牌', 'config.py 的 WEBUI_CONFIG.token。令牌只存在这台机器的浏览器里。'],
    oopz: ['登录 Oopz', '桥接需要一份可用的 Oopz 凭据；登录成功后会写入 config.py 与 private_key.py 并自动重连。'],
    signedout: ['已退出控制台', '点击下方按钮重新进入。'],
    offline: ['连不上控制台后端', result.message || '请确认进程仍在运行。'],
  };
  const buttons = { token: '进入控制台', oopz: '登录并进入', signedout: '进入控制台', offline: '重试' };
  const t = titles[loginGate] || titles.token;
  $('login-title').textContent = t[0];
  $('login-sub').className = loginGate === 'offline' ? 'hint err' : 'hint';
  $('login-sub').textContent = t[1];
  show($('login-token-field'), loginGate === 'token');
  show($('login-oopz-field'), loginGate === 'oopz');
  show($('login-alt'), loginGate === 'oopz');
  $('login-submit').textContent = buttons[loginGate] || '进入';
  $('login-msg').textContent = '';
  $('login-msg').className = 'login-msg';
  const focus = loginGate === 'token' ? $('login-token') : (loginGate === 'oopz' ? $('login-phone') : $('login-submit'));
  if (focus) setTimeout(() => focus.focus(), 60);
}

function loginMsg(message, kind) {
  $('login-msg').textContent = message || '';
  $('login-msg').className = 'login-msg ' + (kind || '');
}

async function onLoginSubmit(event) {
  event.preventDefault();
  const button = $('login-submit');
  if (loginGate === 'signedout') return enterApp();
  if (loginGate === 'offline') { const g = await guard(); return g.gate ? showLogin(g) : enterApp(); }
  if (loginGate === 'token') {
    const value = $('login-token').value.trim();
    if (!value) return loginMsg('请填写访问令牌', 'err');
    token = value;
    const probe = await tryStatus();
    if (probe.kind === 'auth') { token = ''; return loginMsg('令牌不正确', 'err'); }
    if (probe.kind === 'error') return loginMsg(probe.message, 'err');
    localStorage.setItem(TOKEN_KEY, token);
    loginMsg('令牌有效，正在继续…', 'ok');
    const g = await guard();
    return g.gate ? showLogin(g) : enterApp();
  }
  if (loginGate === 'oopz') {
    button.disabled = true;
    loginMsg('正在登录 Oopz…');
    try {
      await api('/api/login/api', {
        method: 'POST',
        body: { phone: $('login-phone').value, password: $('login-password').value, timeout: 60 },
      });
      loginMsg('登录成功，正在进入…', 'ok');
      $('login-password').value = '';
      const g = await guard();
      return g.gate ? showLogin(g) : enterApp();
    } catch (err) {
      loginMsg(err.message, 'err');
    } finally {
      button.disabled = false;
    }
  }
}

function enterApp() {
  sessionStorage.removeItem(SIGNED_OUT_KEY);
  show($('screen-login'), false);
  show($('screen-app'), true);
  setupNav();
  refreshCredentials();
  loadLogFiles();
  switchPage('overview');
  startPolling();
}

function logout() {
  sessionStorage.setItem(SIGNED_OUT_KEY, '1');
  localStorage.removeItem(TOKEN_KEY);
  stopLogStream();
  stopPolling();
  token = '';
  location.reload();
}

/* ───────── 导航 ───────── */

let navReady = false;

function setupNav() {
  if (navReady) return;
  navReady = true;
  document.querySelectorAll('.nav-item[data-page]').forEach((item) => {
    item.addEventListener('click', () => switchPage(item.dataset.page));
  });
  $('ev-filter').addEventListener('click', (event) => {
    const button = event.target.closest('.seg-btn');
    if (!button) return;
    eventFilter = button.dataset.mode;
    document.querySelectorAll('#ev-filter .seg-btn').forEach((item) => item.classList.toggle('is-active', item === button));
    renderOverview();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopPolling(); else startPolling();
  });
}

function switchPage(name) {
  const meta = PAGE_META[name] || PAGE_META.overview;
  document.querySelectorAll('.nav-item[data-page]').forEach((item) => {
    item.classList.toggle('is-active', item.dataset.page === name);
  });
  document.querySelectorAll('.page').forEach((page) => {
    page.classList.toggle('is-active', page.id === 'page-' + name);
  });
  text('page-title', meta[0]);
  text('page-sub', meta[1]);
  renderPageTools(name);
  if (name === 'logs') startLogStream();
  else stopLogStream();
  if (name === 'config') loadConfig();
  if (name === 'account') refreshCredentials();
}

function renderPageTools(name) {
  const tools = $('page-tools');
  if (name === 'overview') {
    tools.innerHTML = '<span class="chip" id="updated-at">—</span><button class="btn ghost sm" id="tool-refresh">立即刷新</button>';
    $('tool-refresh').addEventListener('click', () => { refreshStatus(); toast('已刷新', '状态已重新读取', 'ok'); });
  } else if (name === 'account') {
    tools.innerHTML = '<button class="btn ghost sm" id="tool-cred">刷新凭据</button>';
    $('tool-cred').addEventListener('click', refreshCredentials);
  } else if (name === 'config') {
    tools.innerHTML = '<button class="btn ghost sm" id="tool-adv">高级选项</button>' +
      '<button class="btn ghost sm" id="tool-reload">重新读取</button>';
    const adv = $('tool-adv');
    adv.classList.toggle('toggle-on', showAdvanced);
    adv.addEventListener('click', () => {
      showAdvanced = !showAdvanced;
      localStorage.setItem(ADV_KEY, showAdvanced ? '1' : '0');
      adv.classList.toggle('toggle-on', showAdvanced);
      renderConfig();
    });
    $('tool-reload').addEventListener('click', () => { toast('已重新读取', 'config.py 的当前值', 'ok'); loadConfig(); });
  } else {
    tools.innerHTML = '';
  }
}

/* ───────── 概览 ───────── */

function renderOverview() {
  const bridge = (state && state.bridge) || {};
  const rt = bridge.runtime || {};
  const oopz = bridge.oopz || {};
  const onebot = bridge.onebot || {};
  const traffic = bridge.traffic || {};
  const proc = (state && state.process) || {};

  let tone = 'ok';
  let title = '链路正常';
  let detail = 'Oopz 与 OneBot 端双向可用，事件和指令都在流动。';
  let action = false;

  if (!rt.running) {
    tone = 'err'; action = true;
    title = '桥接未运行';
    detail = rt.last_error ? '上一次错误：' + rt.last_error : 'SDK 会话没有起来，点右侧按钮重试。';
  } else if (!oopz.connected) {
    tone = 'err'; action = true;
    title = 'Oopz 未连接';
    detail = (oopz.last_error ? '最近错误：' + oopz.last_error + '。' : '') + '检查账号凭据与网络，或在账号页重新登录。';
  } else if (!onebot.connected) {
    tone = 'warn'; action = true;
    title = '等待 OneBot 端接入';
    detail = 'Oopz 侧正常，反向 WS 尚未连上 ' + (onebot.target || '目标地址') + '。确认对端已启用 OneBot v11 反向 WS。';
  }

  const verdict = $('verdict');
  verdict.dataset.tone = tone;
  text('verdict-title', title);
  text('verdict-detail', detail);
  show($('verdict-action'), action);

  setDot('tile-oopz', oopz.connected ? 'ok' : 'err');
  text('t-oopz-state', oopz.connected ? '已连接' : '未连接');
  text('t-oopz-sub', (oopz.target || '—') + ' · 持续 ' + fmtDuration(oopz.uptime_seconds) + (oopz.joined_areas ? ' · 已加入 ' + oopz.joined_areas + ' 个域' : ''));

  setDot('tile-onebot', onebot.connected ? 'ok' : (rt.running && oopz.connected ? 'warn' : 'err'));
  text('t-onebot-state', onebot.connected ? '已接入' : '等待中');
  text('t-onebot-sub', (onebot.target || '—') + ' · 重连 ' + (onebot.attempts ?? 0) + ' 次 / 断开 ' + (onebot.drops ?? 0) + ' 次');

  setDot('tile-traffic', traffic.events_total ? 'ok' : 'warn');
  text('t-total', traffic.events_total ?? 0);
  const byType = traffic.events_by_type || {};
  const countOf = (prefix) => Object.entries(byType).filter(([key]) => key.startsWith(prefix))
    .reduce((sum, [, value]) => sum + value, 0);
  text('t-types', '消息 ' + countOf('message') + ' · 通知 ' + countOf('notice') + ' · 心跳 ' + countOf('meta_event'));

  setDot('tile-process', rt.running ? 'ok' : 'err');
  text('t-uptime', fmtDuration(rt.uptime_seconds));
  text('t-process-sub', 'PID ' + (proc.pid ?? '—') + ' · Python ' + (proc.python ?? '—') + ' · 桥接重启 ' + (rt.restarts ?? 0) + ' 次');

  const account = (oopz.nickname || '') + (oopz.self_uid ? ' · ' + oopz.self_uid.slice(0, 8) : '');
  if (account) text('t-oopz-sub', account + ' · ' + (oopz.target || '—') + ' · 持续 ' + fmtDuration(oopz.uptime_seconds));

  const allEvents = bridge.recent_events || [];
  const shownEvents = allEvents.filter((item) => eventFilter === 'all' || !String(item.kind || '').startsWith('meta_event'));
  renderFeed('feed-events', 'ev-count', shownEvents, 'event',
    eventFilter === 'msg' ? '最近只有心跳，切到「全部」可以看' : '还没有事件推送给对端');
  text('ev-count', shownEvents.length === allEvents.length ? allEvents.length + ' 条' : shownEvents.length + ' / ' + allEvents.length + ' 条');
  renderFeed('feed-actions', 'ac-count', bridge.recent_actions || [], 'action', '对端还没有下发过 action');

  const last = traffic.last_event_at;
  text('updated-at', last ? '最近事件 ' + fmtAgo(last) : '更新于 ' + new Date().toLocaleTimeString('zh-CN', { hour12: false }));
  renderRailMeta(tone, title);
}

function setDot(tileId, tone) {
  const tile = $(tileId);
  if (!tile) return;
  const dot = tile.querySelector('.dot');
  if (dot) dot.className = 'dot ' + tone;
}

function renderRailMeta(tone, title) {
  $('rail-meta').innerHTML = '<span class="dot ' + tone + '" style="display:inline-block;margin-right:6px"></span>' + escapeHtml(title);
}

function renderFeed(listId, countId, items, kind, emptyText) {
  const list = $(listId);
  text(countId, items.length + ' 条');
  if (!items.length) {
    list.innerHTML = '<li class="empty">' + escapeHtml(emptyText || '暂无数据') + '</li>';
    return;
  }
  list.innerHTML = items.slice(0, 24).map((item) => {
    if (kind === 'action') {
      const meta = [item.group_id ? '群 ' + item.group_id : '', item.user_id ? '用户 ' + item.user_id : ''].filter(Boolean).join(' · ');
      return '<li class="feed-item"><i class="kind-dot k-action"></i><div class="feed-main">' +
        '<div class="feed-top"><b>' + escapeHtml(item.action || '—') + '</b><span class="meta">' + escapeHtml(meta) + '</span></div>' +
        '<p class="feed-text">来自对端的调用</p></div><time>' + fmtClock(item.time) + '</time></li>';
    }
    const key = String(item.kind || '');
    const cls = key.startsWith('message') ? 'k-message' : (key.startsWith('notice') ? 'k-notice' : 'k-meta');
    const meta = [item.group_id ? '群 ' + item.group_id : '', item.user_id ? '用户 ' + item.user_id : ''].filter(Boolean).join(' · ');
    return '<li class="feed-item"><i class="kind-dot ' + cls + '"></i><div class="feed-main">' +
      '<div class="feed-top"><b>' + escapeHtml(key || '—') + '</b><span class="meta">' + escapeHtml(meta) + '</span></div>' +
      '<p class="feed-text">' + (escapeHtml(item.preview || '') || '<span class="muted">（无文本内容）</span>') + '</p></div><time>' + fmtClock(item.time) + '</time></li>';
  }).join('');
}

async function refreshStatus() {
  try {
    state = { ...state, ...(await api('/api/status')) };
  } catch (err) {
    if (err instanceof AuthError) { stopPolling(); return showLogin({ gate: 'token' }); }
    text('verdict-title', '读取状态失败');
    text('verdict-detail', err.message);
    return;
  }
  renderPageToolsIfNeeded();
  renderVersion();
  if (isPage('overview')) renderOverview();
  else {
    const b = state.bridge || {};
    const rt = b.runtime || {};
    const healthy = rt.running && (b.oopz || {}).connected && (b.onebot || {}).connected;
    renderRailMeta(healthy ? 'ok' : (rt.running ? 'warn' : 'err'), healthy ? '链路正常' : (rt.running ? '部分异常' : '桥接未运行'));
    syncConfigChips();
  }
}

const isPage = (name) => document.querySelector('.page.is-active')?.id === 'page-' + name;

function renderVersion() {
  const version = (state && state.process && state.process.version) || '';
  const el = $('rail-ver');
  if (el && version && el.textContent !== 'v' + version) el.textContent = 'v' + version;
}

function renderPageToolsIfNeeded() {
  if (isPage('overview') && !$('updated-at')) renderPageTools('overview');
}

function startPolling() {
  stopPolling();
  refreshStatus();
  pollTimer = setInterval(() => { if (!document.hidden) refreshStatus(); }, POLL_MS);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function restartBridge() {
  const ok = await confirmDialog('重新连接桥接', '会断开当前 Oopz 与 OneBot 端的连接并立即重连（通常几秒）。', '重连');
  if (!ok) return;
  try {
    const result = await api('/api/bridge/restart', { method: 'POST', body: {} });
    toast('已请求重连', result.message || '桥接正在重建连接', 'ok');
    setTimeout(refreshStatus, 1500);
  } catch (err) {
    toast('重连失败', err.message, 'err');
  }
}

/* ───────── 日志 ───────── */

const LINE_RE = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[([^\]]+)\]\s+([A-Z]+):\s?([\s\S]*)$/;
const MAX_NODES = 4000;
let logTerms = [];
let logLevel = '';

function levelTone(level) {
  if (level === 'ERROR' || level === 'CRITICAL') return 'lv-err';
  if (level === 'WARNING' || level === 'WARN') return 'lv-warn';
  if (level === 'DEBUG' || level === 'TRACE') return 'lv-debug';
  return 'lv-info';
}

function passesFilter(raw) {
  if (logLevel === 'WARN' && !/(WARNING|WARN|ERROR|CRITICAL)/.test(raw)) return false;
  if (logLevel === 'ERROR' && !/(ERROR|CRITICAL)/.test(raw)) return false;
  if (!logTerms.length) return true;
  const lower = raw.toLowerCase();
  return logTerms.every((term) => lower.includes(term));
}

function highlight(escaped, terms) {
  if (!terms.length) return escaped;
  return terms.reduce((acc, term) => {
    if (!term) return acc;
    const safe = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return acc.replace(new RegExp('(' + safe + ')', 'gi'), '<mark class="hit">$1</mark>');
  }, escaped);
}

function logNode(raw) {
  const match = LINE_RE.exec(raw);
  let time = '', level = '', body = raw;
  if (match) { time = match[1].slice(11); level = match[3]; body = '[' + match[2] + '] ' + match[4]; }
  const node = document.createElement('div');
  node.className = 'ln ' + levelTone(level);
  node.innerHTML = '<span class="ln-time">' + escapeHtml(time) + '</span>' +
    '<span class="ln-level">' + escapeHtml(level || '·') + '</span>' +
    '<span class="ln-body">' + highlight(escapeHtml(body), logTerms) + '</span>';
  return node;
}

async function loadLogFiles() {
  try {
    const data = await api('/api/logs');
    const select = $('log-file');
    select.innerHTML = (data.files || []).map((item) =>
      '<option value="' + escapeHtml(item.name) + '">' + escapeHtml(item.name) + ' · ' + (item.size / 1024).toFixed(0) + ' KB</option>').join('');
    if (!select.value && data.default) select.value = data.default;
  } catch (err) {
    text('log-status', err.message);
  }
}

function stopLogStream() {
  if (logStream) { logStream.close(); logStream = null; }
}

function appendLog(raw) {
  logBuffer.push(raw);
  if (logBuffer.length > MAX_NODES * 1.5) logBuffer = logBuffer.slice(-MAX_NODES);
  if (!passesFilter(raw)) return;
  const view = $('log-view');
  const stick = view.scrollTop + view.clientHeight >= view.scrollHeight - 60;
  view.appendChild(logNode(raw));
  while (view.childElementCount > MAX_NODES) view.removeChild(view.firstChild);
  if (stick) view.scrollTop = view.scrollHeight;
  else show($('log-jump'), true);
}

function rerenderLogs() {
  const view = $('log-view');
  view.innerHTML = '';
  const matched = logBuffer.filter(passesFilter).slice(-MAX_NODES);
  const fragment = document.createDocumentFragment();
  matched.forEach((raw) => fragment.appendChild(logNode(raw)));
  view.appendChild(fragment);
  view.scrollTop = view.scrollHeight;
  show($('log-jump'), false);
}

async function loadLogTail() {
  try {
    const data = await api('/api/logs/tail?lines=' + encodeURIComponent($('log-lines').value) +
      '&file=' + encodeURIComponent($('log-file').value));
    $('log-view').innerHTML = '';
    logBuffer = [];
    (data.lines || []).forEach(appendLog);
    $('log-view').scrollTop = $('log-view').scrollHeight;
    text('log-status', '已加载 ' + (data.lines || []).length + ' 行（未跟随）');
  } catch (err) {
    text('log-status', err.message);
  }
}

function startLogStream() {
  stopLogStream();
  if (!isPage('logs')) return;
  if (!$('log-follow').checked) {
    text('log-status', '读取中…');
    loadLogTail();
    return;
  }
  const file = $('log-file').value;
  text('log-status', '实时跟随中…');
  logStream = new EventSource(withToken('/api/logs/stream?lines=' + encodeURIComponent($('log-lines').value) +
    '&file=' + encodeURIComponent(file)));
  logStream.addEventListener('reset', () => { logBuffer = []; $('log-view').innerHTML = ''; });
  logStream.addEventListener('line', (event) => {
    try { appendLog(JSON.parse(event.data).line); } catch (err) { /* 忽略坏帧 */ }
  });
  logStream.onerror = () => text('log-status', '日志流已断开，正在重试…');
}

function wireLogs() {
  $('log-file').addEventListener('change', startLogStream);
  $('log-lines').addEventListener('change', startLogStream);
  $('log-follow').addEventListener('change', startLogStream);
  $('log-wrap').addEventListener('change', () => $('log-view').classList.toggle('wrap', $('log-wrap').checked));
  $('log-search').addEventListener('input', () => {
    logTerms = $('log-search').value.toLowerCase().split(/\s+/).filter(Boolean);
    rerenderLogs();
  });
  $('log-level').addEventListener('change', () => {
    logLevel = $('log-level').value;
    rerenderLogs();
  });
  $('log-clear').addEventListener('click', () => {
    logBuffer = [];
    $('log-view').innerHTML = '';
    toast('已清屏', '只影响当前页面，不会动日志文件', 'ok');
  });
  $('log-download').addEventListener('click', () => {
    window.open(withToken('/api/logs/tail?lines=20000&file=' + encodeURIComponent($('log-file').value)), '_blank');
  });
  $('log-jump').addEventListener('click', () => {
    $('log-view').scrollTop = $('log-view').scrollHeight;
    show($('log-jump'), false);
  });
  $('log-view').addEventListener('scroll', () => {
    const view = $('log-view');
    if (view.scrollTop + view.clientHeight >= view.scrollHeight - 60) show($('log-jump'), false);
  });
}

/* ───────── 配置 ───────── */

async function loadConfig() {
  try {
    const data = await api('/api/config');
    configSchema = data.groups || {};
    dirty = {};
    text('config-status', data.path);
    renderConfig();
    updateSavebar();
  } catch (err) {
    text('config-status', err.message);
    toast('配置读取失败', err.message, 'err');
  }
}

function renderConfig() {
  const host = $('config-groups');
  host.innerHTML = '';
  Object.entries(configSchema || {}).forEach(([group, spec]) => {
    const card = document.createElement('article');
    card.className = 'cfg-group';
    const live = (group === 'onebot' || group === 'oopz')
      ? '<span class="cfg-state" data-group="' + escapeHtml(group) + '"></span>' : '';
    card.innerHTML = '<header><h3>' + escapeHtml(spec.title || GROUP_TITLE[group] || group) + '</h3>' + live +
      '<span class="chip">' + escapeHtml(spec.source || group) + '</span></header>' +
      (spec.desc ? '<p class="cfg-desc">' + escapeHtml(spec.desc) + '</p>' : '') +
      '<div class="cfg-body"></div><div class="cfg-extra" hidden></div>';
    const body = card.querySelector('.cfg-body');
    const extra = card.querySelector('.cfg-extra');
    const sections = new Map();
    Object.entries(spec.fields || {}).forEach(([field, meta]) => {
      const row = fieldRow(group, field, meta);
      if (meta.tier !== 'adv') { body.appendChild(row); return; }
      const name = meta.section || '其他';
      if (!sections.has(name)) {
        const box = document.createElement('section');
        box.className = 'cfg-sec';
        box.innerHTML = '<h4>' + escapeHtml(name) + '</h4><div class="cfg-body"></div>';
        sections.set(name, box);
        extra.appendChild(box);
      }
      sections.get(name).querySelector('.cfg-body').appendChild(row);
    });
    if (!body.childElementCount) body.remove();
    if (sections.size) extra.hidden = !showAdvanced;
    else extra.remove();
    host.appendChild(card);
  });
  syncConfigChips();
}

function syncConfigChips() {
  const bridge = (state && state.bridge) || {};
  document.querySelectorAll('.cfg-state').forEach((el) => {
    const onebot = el.dataset.group === 'onebot';
    const connected = !!(onebot ? (bridge.onebot || {}).connected : (bridge.oopz || {}).connected);
    const tone = connected ? 'ok' : 'err';
    el.className = 'cfg-state ' + tone;
    el.innerHTML = '<i class="dot ' + tone + '"></i>' + (onebot ? 'OneBot ' : 'Oopz ') +
      (connected ? (onebot ? '已接入' : '已连接') : (onebot ? '未接入' : '未连接'));
  });
}

function fieldRow(group, field, meta) {
  const wrap = document.createElement('div');
  wrap.className = 'cfg-field';

  if (meta.type === 'bool') {
    wrap.innerHTML = '<label class="cfg-switch"><input type="checkbox"><span>' + escapeHtml(meta.label || field) + '</span></label>';
    const box = wrap.querySelector('input');
    box.checked = !!meta.value;
    box.addEventListener('change', () => markDirty(group, field, meta, box.checked, wrap));
    if (meta.hint) wrap.insertAdjacentHTML('beforeend', '<p class="hint">' + escapeHtml(meta.hint) + '</p>');
    return wrap;
  }

  const type = meta.sensitive ? 'password' : (meta.type === 'int' || meta.type === 'float' ? 'number' : 'text');
  const value = meta.type === 'list' ? (meta.value || []).join(', ') : (meta.value ?? '');
  const placeholder = meta.sensitive ? (meta.is_set ? '已设置（留空不改）' : '未设置') : '';
  wrap.innerHTML = '<label><span>' + escapeHtml(meta.label || field) + '</span><input type="' + type + '"' +
    (type === 'number' ? ' step="any"' : '') + ' autocomplete="off" placeholder="' + escapeHtml(placeholder) + '"></label>';
  const input = wrap.querySelector('input');
  input.value = value;
  input.addEventListener('change', () => {
    const next = meta.type === 'list' ? input.value.split(',').map((s) => s.trim()).filter(Boolean) : input.value;
    markDirty(group, field, meta, next, wrap);
  });
  if (meta.hint) wrap.insertAdjacentHTML('beforeend', '<p class="hint">' + escapeHtml(meta.hint) + '</p>');
  return wrap;
}

function markDirty(group, field, meta, value, wrap) {
  dirty[group] = dirty[group] || {};
  const blank = meta.sensitive && typeof value === 'string' && !value.trim();
  if (blank) delete dirty[group][field];
  else dirty[group][field] = value;
  if (Object.keys(dirty[group]).length === 0) delete dirty[group];
  wrap.classList.toggle('is-dirty', !blank);
  updateSavebar();
}

function updateSavebar() {
  const count = Object.values(dirty).reduce((sum, fields) => sum + Object.keys(fields).length, 0);
  show($('savebar'), count > 0);
  if (count) text('savebar-text', '有 ' + count + ' 项改动待保存');
}

async function saveConfig(restartAfter) {
  const count = Object.values(dirty).reduce((sum, fields) => sum + Object.keys(fields).length, 0);
  if (!count) return;
  $('config-save').disabled = $('config-save-restart').disabled = true;
  try {
    const result = await api('/api/config', { method: 'POST', body: { updates: dirty } });
    toast('配置已保存', Object.entries(result.changed || {}).map(([g, f]) => g + ': ' + f.join('/')).join('；'), 'ok');
    await loadConfig();
    if (restartAfter) {
      await api('/api/bridge/restart', { method: 'POST', body: {} });
      toast('正在重新连接', '桥接会按新配置重建连接', 'ok');
      setTimeout(refreshStatus, 1500);
    } else if (result.restart_required) {
      toast('需要重新连接才生效', '这些字段在下次启动桥接时读取', 'warn');
    }
  } catch (err) {
    toast('保存失败', err.message, 'err');
    text('config-status', err.message);
  } finally {
    $('config-save').disabled = $('config-save-restart').disabled = false;
  }
}

function wireConfig() {
  $('config-save').addEventListener('click', () => saveConfig(false));
  $('config-save-restart').addEventListener('click', () => saveConfig(true));
  $('config-discard').addEventListener('click', () => { toast('已放弃改动', '重新读取 config.py', 'ok'); loadConfig(); });
}

/* ───────── 账号 ───────── */

async function refreshCredentials() {
  try {
    const data = await api('/api/credentials');
    state.creds = data.credentials || {};
  } catch (err) {
    if (err instanceof AuthError) return showLogin({ gate: 'token' });
    toast('凭据读取失败', err.message, 'err');
    return;
  }
  renderCredentials();
}

function renderCredentials() {
  const c = state.creds || {};
  const remain = c.expires_in_seconds;
  const chip = $('cred-expiry-chip');
  if (remain === null || remain === undefined) {
    chip.className = 'chip'; chip.textContent = '到期未知';
  } else if (remain <= 0) {
    chip.className = 'chip err'; chip.textContent = 'JWT 已过期';
  } else if (remain < 21600) {
    chip.className = 'chip warn'; chip.textContent = '剩余 ' + fmtDuration(remain);
  } else {
    chip.className = 'chip ok'; chip.textContent = '剩余 ' + fmtDuration(remain);
  }

  const rows = [
    ['手机号', c.login_phone],
    ['UID', c.person_uid, true],
    ['device_id', c.device_id, true],
    ['JWT', c.jwt_token, true],
    ['登录密码', c.has_password ? '已保存' : '未保存', false, c.has_password ? 'good' : 'bad'],
    ['RSA 私钥', c.has_private_key ? '已保存' : '未保存', false, c.has_private_key ? 'good' : 'bad'],
    ['到期时间', c.expires_at ? new Date(c.expires_at * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'],
  ];
  $('cred-list').innerHTML = rows.map(([label, value, copy, tone]) => {
    const v = (value === undefined || value === null || value === '') ? '—' : String(value);
    return '<div class="kv"><dt>' + escapeHtml(label) + '</dt><dd class="' + (tone || '') + '" title="' + escapeHtml(v) + '">' +
      escapeHtml(v) + '</dd>' + (copy && v !== '—' ? '<button class="btn subtle sm" data-copy="' + escapeHtml(v) + '">复制</button>' : '') + '</div>';
  }).join('');
  $('cred-list').querySelectorAll('[data-copy]').forEach((btn) => {
    btn.addEventListener('click', () => copyText(btn.dataset.copy));
  });
}

async function doApiLogin(phoneId, passwordId, statusId, onSuccess) {
  const status = $(statusId);
  status.className = 'login-msg';
  status.textContent = '正在登录 Oopz…';
  try {
    await api('/api/login/api', {
      method: 'POST',
      body: { phone: $(phoneId)?.value || '', password: $(passwordId)?.value || '', timeout: 60 },
    });
    status.className = 'login-msg ok';
    status.textContent = '登录成功，凭据已写入 config.py';
    if ($(passwordId)) $(passwordId).value = '';
    toast('Oopz 登录成功', '凭据已保存并触发重连', 'ok');
    await refreshCredentials();
    if (onSuccess) await onSuccess();
  } catch (err) {
    status.className = 'login-msg err';
    status.textContent = err.message;
  }
}

async function doBrowserLogin(phone, password, headless, statusEl, onSuccess) {
  const status = $(statusEl);
  status.className = 'login-msg';
  status.textContent = '正在启动浏览器…';
  try {
    await api('/api/login/browser', { method: 'POST', body: { phone, password, headless } });
    status.textContent = '已启动，请在弹出的浏览器里完成验证（滑块 / 短信）';
    watchBrowserLogin(statusEl, onSuccess);
  } catch (err) {
    status.className = 'login-msg err';
    status.textContent = err.message;
  }
}

function watchBrowserLogin(statusEl, onSuccess) {
  clearTimeout(loginPollTimer);
  api('/api/login/browser').then(async (data) => {
    const task = data.task || {};
    const status = $(statusEl);
    if (task.state === 'running') {
      status.className = 'login-msg';
      status.textContent = task.message || '浏览器登录进行中…';
      loginPollTimer = setTimeout(() => watchBrowserLogin(statusEl, onSuccess), 2000);
    } else if (task.state === 'ok') {
      status.className = 'login-msg ok';
      status.textContent = '网页版登录成功，凭据已保存';
      toast('网页版登录成功', '凭据已写入 config.py', 'ok');
      await refreshCredentials();
      if (onSuccess) await onSuccess();
    } else if (task.state === 'failed') {
      status.className = 'login-msg err';
      status.textContent = task.message || '登录失败';
    } else if (task.state === 'cancelled') {
      status.className = 'login-msg';
      status.textContent = '已取消';
    }
  }).catch(() => { loginPollTimer = setTimeout(() => watchBrowserLogin(statusEl, onSuccess), 4000); });
}

async function cancelBrowserLogin(statusEl) {
  clearTimeout(loginPollTimer);
  try {
    const result = await api('/api/login/browser/cancel', { method: 'POST', body: {} });
    if (statusEl) $(statusEl).textContent = result.message || '已取消';
  } catch (err) {
    toast('取消失败', err.message, 'err');
  }
}

/* ───────── 装配 ───────── */

function readToken() {
  const fromQuery = new URLSearchParams(location.search).get('token');
  if (fromQuery) {
    localStorage.setItem(TOKEN_KEY, fromQuery);
    const url = new URL(location.href);
    url.searchParams.delete('token');
    history.replaceState(null, '', url.pathname + url.search);
    return fromQuery;
  }
  return localStorage.getItem(TOKEN_KEY) || '';
}

function wireLogin() {
  $('login-form').addEventListener('submit', onLoginSubmit);
  $('login-browser').addEventListener('click', () => {
    show($('login-cancel'), true);
    doBrowserLogin($('login-phone').value, $('login-password').value, false, 'login-msg', async () => {
      const g = await guard();
      return g.gate ? showLogin(g) : enterApp();
    });
  });
  $('login-cancel').addEventListener('click', async () => {
    await cancelBrowserLogin('login-msg');
    show($('login-cancel'), false);
  });
}

function wireAccount() {
  $('api-login').addEventListener('click', () => doApiLogin('api-phone', 'api-password', 'api-login-status'));
  $('browser-login').addEventListener('click', () => {
    doBrowserLogin($('api-phone').value, $('api-password').value, $('browser-headless').checked, 'browser-login-status');
  });
  $('browser-cancel').addEventListener('click', () => cancelBrowserLogin('browser-login-status'));
}

function wireRail() {
  $('btn-restart').addEventListener('click', restartBridge);
  $('verdict-action').addEventListener('click', restartBridge);
  $('btn-logout').addEventListener('click', async () => {
    const ok = await confirmDialog('退出登录', '会清除本机浏览器里保存的访问令牌。服务器端配置不受影响。', '退出');
    if (ok) logout();
  });
}

async function boot() {
  token = readToken();
  wireLogin();
  wireLogs();
  wireConfig();
  wireAccount();
  wireRail();
  const result = await guard();
  if (result.gate) showLogin(result);
  else enterApp();
}

document.addEventListener('DOMContentLoaded', boot);
window.addEventListener('beforeunload', () => { stopPolling(); stopLogStream(); });
