/* Configuration editor: in-memory drafts, groups and explicit save/discard. */
'use strict';

/* ───────── 配置 ───────── */

let configRequest = 0;
let configSaving = false;

function draftCount() {
  return Object.values(dirty).reduce((sum, fields) => sum + Object.keys(fields).length, 0);
}

function draftValue(group, field, meta) {
  return Object.prototype.hasOwnProperty.call(dirty[group] || {}, field) ? dirty[group][field] : meta.value;
}

async function loadConfig() {
  const request = ++configRequest;
  try {
    const data = await api('/api/config');
    if (request !== configRequest) return;
    configSchema = data.groups || {};
    text('config-status', data.path);
    renderConfig();
    updateSavebar();
  } catch (err) {
    text('config-status', err.message);
    toast('配置读取失败', err.message, 'err');
  }
}

const CONFIG_TAB_MAP = {
  connection: ['oopz', 'onebot'],
  voice: ['voice', 'voice_api'],
  system: ['webui'],
};

function activeConfigTab() {
  return localStorage.getItem('oopz.webui.cfgtab') || 'connection';
}

function renderConfigTabs() {
  const host = $('config-groups');
  if (!host) return;
  let bar = document.getElementById('config-tabs');
  if (!bar) {
    bar = document.createElement('div');
    bar.className = 'subtabs';
    bar.id = 'config-tabs';
    host.parentNode.insertBefore(bar, host);
    bar.addEventListener('click', (event) => {
      const btn = event.target.closest('.subtab');
      if (!btn) return;
      localStorage.setItem('oopz.webui.cfgtab', btn.dataset.tab);
      renderConfig();
    });
  }
  const current = activeConfigTab();
  bar.innerHTML = [
    ['connection', '连接'],
    ['voice', '语音模型'],
    ['system', '系统'],
  ].map(([id, label]) =>
    '<button type="button" class="subtab' + (current === id ? ' is-active' : '') +
    '" data-tab="' + id + '">' + label + '</button>'
  ).join('');
}

function renderConfig() {
  renderConfigTabs();
  const host = $('config-groups');
  host.innerHTML = '';
  const allow = CONFIG_TAB_MAP[activeConfigTab()] || null;
  Object.entries(configSchema || {}).forEach(([group, spec]) => {
    if (allow && !allow.includes(group)) return;
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
  applyVendorVisibility();
  syncConfigChips();
  lockConfigEditor(configSaving);
}

function lockConfigEditor(locked) {
  document.querySelectorAll('#config-groups input, #config-groups select, #config-tabs button, #tool-adv, #tool-reload').forEach(control => { control.disabled = locked; });
}

function currentBackend() {
  const dirtyBackend = dirty.voice && dirty.voice.backend;
  if (dirtyBackend != null) return String(dirtyBackend);
  const meta = configSchema && configSchema.voice && configSchema.voice.fields && configSchema.voice.fields.backend;
  return meta ? String(meta.value || 'gemini_live') : 'gemini_live';
}

function applyVendorVisibility() {
  const backend = currentBackend();
  document.querySelectorAll('.cfg-field[data-vendor]').forEach((el) => {
    el.hidden = el.dataset.vendor !== backend;
  });
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
  wrap.dataset.group = group;
  wrap.dataset.field = field;
  wrap.classList.toggle('is-dirty', Object.prototype.hasOwnProperty.call(dirty[group] || {}, field));
  if (meta.vendor) wrap.dataset.vendor = meta.vendor;

  if (meta.type === 'bool') {
    wrap.innerHTML = '<label class="cfg-switch"><input type="checkbox"><span>' + escapeHtml(meta.label || field) + '</span></label>';
    const box = wrap.querySelector('input');
    box.checked = !!draftValue(group, field, meta);
    box.addEventListener('change', () => markDirty(group, field, meta, box.checked, wrap));
    if (meta.hint) wrap.insertAdjacentHTML('beforeend', '<p class="hint">' + escapeHtml(meta.hint) + '</p>');
    return wrap;
  }

  if (meta.type === 'select') {
    return selectFieldRow(group, field, meta, wrap);
  }

  const type = meta.sensitive ? 'password' : (meta.type === 'int' || meta.type === 'float' ? 'number' : 'text');
  const current = draftValue(group, field, meta);
  const value = meta.type === 'list' ? (current || []).join(', ') : (current ?? '');
  const placeholder = meta.sensitive ? (meta.is_set ? '已设置（留空不改）' : (meta.placeholder || '未设置')) : (meta.placeholder || '');
  wrap.innerHTML = '<label><span>' + escapeHtml(meta.label || field) + '</span><input type="' + type + '"' +
    (type === 'number' ? ' step="any"' : '') + ' autocomplete="off" placeholder="' + escapeHtml(placeholder) + '"></label>';
  const input = wrap.querySelector('input');
  input.value = value;
  input.addEventListener('input', () => {
    const next = meta.type === 'list' ? input.value.split(',').map((s) => s.trim()).filter(Boolean) : input.value;
    markDirty(group, field, meta, next, wrap);
  });
  if (meta.hint) wrap.insertAdjacentHTML('beforeend', '<p class="hint">' + escapeHtml(meta.hint) + '</p>');
  return wrap;
}

function selectFieldRow(group, field, meta, wrap) {
  const options = (meta.options || []).map((opt) =>
    typeof opt === 'object' && opt
      ? { value: String(opt.value ?? ''), label: String(opt.label ?? opt.value ?? '') }
      : { value: String(opt), label: String(opt) }
  );
  const allowCustom = !!meta.allow_custom;
  const current = String(draftValue(group, field, meta) ?? '');
  const inPreset = options.some((opt) => opt.value === current);
  const CUSTOM = '__custom__';

  let html = '<label><span>' + escapeHtml(meta.label || field) + '</span><select class="cfg-select">';
  options.forEach((opt) => {
    html += '<option value="' + escapeHtml(opt.value) + '">' + escapeHtml(opt.label) + '</option>';
  });
  if (allowCustom) {
    html += '<option value="' + CUSTOM + '">' + (inPreset && current ? '自定义…' : '自定义…') + '</option>';
  }
  html += '</select></label>';
  if (allowCustom) {
    html += '<input class="cfg-custom" type="text" autocomplete="off" placeholder="输入自定义值"' +
      (inPreset || !current ? ' hidden' : '') + '>';
  }
  wrap.innerHTML = html;

  const select = wrap.querySelector('select');
  const custom = wrap.querySelector('.cfg-custom');

  if (inPreset) {
    select.value = current;
    if (custom) custom.hidden = true;
  } else if (allowCustom && current) {
    select.value = CUSTOM;
    if (custom) {
      custom.hidden = false;
      custom.value = current;
    }
  } else {
    select.value = options.length ? options[0].value : '';
    if (custom) {
      custom.hidden = true;
      custom.value = '';
    }
  }

  const emit = () => {
    if (select.value === CUSTOM) {
      const raw = custom ? custom.value.trim() : '';
      markDirty(group, field, meta, raw, wrap);
    } else {
      if (custom) {
        custom.hidden = true;
        custom.value = '';
      }
      markDirty(group, field, meta, select.value, wrap);
    }
  };

  select.addEventListener('change', () => {
    if (select.value === CUSTOM) {
      if (custom) {
        custom.hidden = false;
        custom.focus();
      }
    }
    emit();
  });
  if (custom) custom.addEventListener('input', emit);

  if (meta.hint) wrap.insertAdjacentHTML('beforeend', '<p class="hint">' + escapeHtml(meta.hint) + '</p>');
  return wrap;
}

function markDirty(group, field, meta, value, wrap) {
  dirty[group] = dirty[group] || {};
  const blank = meta.sensitive && typeof value === 'string' && !value.trim();
  const unchanged = !meta.sensitive && (Array.isArray(value) ? JSON.stringify(value) === JSON.stringify(meta.value) : String(value) === String(meta.value ?? ''));
  if (blank || unchanged) delete dirty[group][field];
  else dirty[group][field] = value;
  if (Object.keys(dirty[group]).length === 0) delete dirty[group];
  wrap.classList.toggle('is-dirty', !blank && !unchanged);
  if (group === 'voice' && field === 'backend') applyVendorVisibility();
  updateSavebar();
}

function updateSavebar() {
  const count = draftCount();
  show($('savebar'), count > 0);
  if (count) text('savebar-text', '有 ' + count + ' 项改动待保存');
  const labels = Object.entries(dirty).flatMap(([group, fields]) => Object.keys(fields).map(field => configSchema?.[group]?.fields?.[field]?.label || field));
  text('config-summary', count ? '待保存：' + labels.join('、') : '');
  show($('config-summary'), count > 0);
}

async function saveConfig(restartAfter) {
  const count = draftCount();
  if (!count || configSaving) return;
  configSaving = true;
  lockConfigEditor(true);
  const updates = JSON.parse(JSON.stringify(dirty));
  $('config-save').disabled = $('config-save-restart').disabled = true;
  $('config-discard').disabled = true;
  $('savebar').setAttribute('aria-busy', 'true');
  try {
    const result = await api('/api/config', { method: 'POST', body: { updates } });
    for (const [group, fields] of Object.entries(updates)) {
      for (const [field, value] of Object.entries(fields)) {
        if (JSON.stringify(dirty[group]?.[field]) === JSON.stringify(value)) delete dirty[group][field];
      }
      if (dirty[group] && !Object.keys(dirty[group]).length) delete dirty[group];
    }
    updateSavebar();
    const fields = Object.entries(result.changed || {}).map(([g, f]) => g + ': ' + f.join('/')).join('；');
    const notes = result.notes || [];
    if (notes.length) {
      // 语音配置会真正热应用，把后端回传的结果如实告诉用户
      toast('已保存并热生效', notes.join('；'), 'ok');
    } else {
      toast('配置已保存', fields, 'ok');
    }
    await loadConfig();
    if (restartAfter) {
      await api('/api/bridge/restart', { method: 'POST', body: {} });
      toast('正在重新连接', '桥接会按新配置重建连接', 'ok');
      setTimeout(refreshStatus, 1500);
    } else if (result.restart_required) {
      toast('部分字段需重启才生效', fields, 'warn');
    }
  } catch (err) {
    toast('保存失败', err.message, 'err');
    text('config-status', err.message);
  } finally {
    configSaving = false;
    lockConfigEditor(false);
    $('config-save').disabled = $('config-save-restart').disabled = false;
    $('config-discard').disabled = false;
    $('savebar').removeAttribute('aria-busy');
  }
}

function wireConfig() {
  $('config-save').addEventListener('click', () => saveConfig(false));
  $('config-save-restart').addEventListener('click', () => saveConfig(true));
  $('config-discard').addEventListener('click', async () => {
    if (!draftCount() || configSaving) return;
    if (!await confirmDialog('放弃未保存的改动？', '将清除当前配置草稿并重新读取已保存的配置。', '放弃改动')) return;
    dirty = {};
    renderConfig();
    updateSavebar();
    await loadConfig();
    toast('已放弃改动', '已重新读取保存的配置', 'ok');
  });
  window.addEventListener('beforeunload', event => {
    if (!draftCount()) return;
    event.preventDefault();
    event.returnValue = '';
  });
}
