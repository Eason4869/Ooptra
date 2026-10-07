/* Independent voice tools and maintenance UI; no framework or remote assets. */
'use strict';

(() => {
 function initializeMaintenance() {
  let current = null;
  let refreshing = false;
  let refreshAgain = false;
  let operating = false;
  let lastRefresh = 0;
  let feedback = '';
  let page = 1;
  let cleanup = null;
  let selectedSource = false;
  const sections = {preflight: {loading: false, readAt: 0, value: null, error: ''}, storage: {loading: false, readAt: 0, value: null, error: ''}};
  let networkLoading = false;
  let networkLoaded = false;
  let networkDirty = false;
  let proxyDirty = false;
  let networkSaving = false;
  let networkReadAt = 0;
  let discardCheck = false;
  let checkingUpdate = false;
  let backupSignature = '';
  let testingNetwork = false;
  const acceleratorSuffix = '/https://github.com/Eason4869/Ooptra.git';
  const acceleratorPresets = ['https://edgeone.gh-proxy.com', 'https://hk.gh-proxy.com', 'https://gh-proxy.com', 'https://gh.dpik.top'];
  const safeError = err => String(err?.message || err || '读取失败').replace(/([a-z][a-z0-9+.-]*:\/\/)[^\s/@]+@/gi, '$1[隐藏凭据]@').replace(/([?&](?:token|key|password|api_key)=)[^\s&]+/gi, '$1[隐藏]');
  const channels = {main: '正式版', beta: '测试版', dev: '预览版'};
  const channelName = channel => channels[channel] ? channels[channel] + '（' + channel + '）' : channel || '未知';
  const currentChannel = data => data?.current_channel || data?.update?.current_channel || data?.update?.channel;
  const switchingChannel = check => !!check?.requires_confirmation || check?.action === 'switch' || !!(check?.current_channel && check.current_channel !== check.channel);
  const activePhases = new Set(['preparing', 'awaiting_restart', 'switching', 'checking', 'rolling_back']);
  const names = {preparing: '准备中', awaiting_restart: '正在关闭旧会话', switching: '切换中', checking: '检查新进程', rolling_back: '恢复原版本', complete: '已完成', rolled_back: '已回滚', failed: '需要处理'};
  const megabytes = value => (Number(value || 0) / 1024 / 1024).toFixed(2) + ' MB';

  function busyControls(busy) {
    for (const id of ['maintenance-check', 'maintenance-backup', 'maintenance-channel', 'maintenance-cleanup-preview', 'maintenance-prev', 'maintenance-next']) {
      if ($(id)) $(id).disabled = busy;
    }
    if ($('maintenance-cleanup-apply')) {
      $('maintenance-cleanup-apply').disabled = busy || !cleanup?.items?.length;
      show($('maintenance-cleanup-apply'), !!cleanup?.items?.length);
    }
    if (busy) $('maintenance-update').disabled = true;
  }

  function checksHTML(rows) {
    return rows.map(row => {
      const state = row.state || (row.passed ? 'pass' : 'fail');
      return '<li class="check-row" data-state="' + escapeHtml(state) + '"><span class="check-mark" aria-hidden="true">' + (state === 'pass' ? '✓' : state === 'fail' ? '!' : '—') + '</span><div><b>' + escapeHtml(row.title || row.id) + '</b><p>' + escapeHtml(row.detail || '') + (row.elapsed_ms != null ? ' · ' + Number(row.elapsed_ms).toFixed(0) + ' ms' : '') + '</p></div></li>';
    }).join('');
  }

  function renderMaintenance(data) {
    data = {...data, preflight: sections.preflight.value || data.preflight, storage: sections.storage.value || data.storage};
    if (discardCheck) data.check = null;
    current = data;
    const supported = !!data.preflight?.supported && !data.preflight?.pending && !sections.preflight.error;
    const busy = operating || data.busy || activePhases.has(data.job?.phase);
    const installed = currentChannel(data);
    if (!selectedSource && channels[installed]) { $('maintenance-channel').value = installed; selectedSource = true; }
    const selected = $('maintenance-channel').value;
    const check = data.check;
    text('maintenance-capability', supported ? '支持自动升级' : data.preflight?.pending ? '部署预检查待完成' : '查看部署预检查');
    text('maintenance-version', '当前 v' + (data.update?.version || state?.process?.version || '—'));
    busyControls(!!busy);
    $('maintenance-checks').innerHTML = checksHTML(data.preflight?.checks || []);
    text('maintenance-preflight-status', sections.preflight.error || data.preflight?.error || (data.preflight?.pending ? data.preflight.detail || '部署预检查尚未完成；可先检查更新和查看备份。' : data.preflight?.detail || ''));
    const checked = check?.channel === selected;
    const compatible = check?.compatible !== false && check?.compatibility?.supported !== false;
    const switching = switchingChannel(check) || !!(installed && installed !== check?.channel);
    $('maintenance-update').disabled = busy || !supported || !checked || !check?.available || check?.action === 'current' || !compatible;
    text('maintenance-update', checked && switching ? '备份并切换频道' : '备份并更新');
    $('maintenance-backup').disabled = !!busy;
    $('maintenance-check').disabled = !!busy;
    $('maintenance-channel').disabled = !!busy;
    const update = data.update || check || {};
    text('maintenance-update-metadata', '当前频道 ' + channelName(installed) + ' · 目标 ' + channelName(selected) + ' · 当前提交 ' + (update.current_sha?.slice(0, 12) || '未知') + ' · 目标提交 ' + (checked ? check.target_sha?.slice(0, 12) || '待检查' : '待检查') + (checked && check.target_version ? ' · 目标 v' + check.target_version : '') + ' · ' + (supported && compatible ? '可自动更新' : '需手动更新'));
    if ($('maintenance-health')) $('maintenance-health').innerHTML = checksHTML(data.health?.checks || []);
    const storage = data.storage || {};
    text('maintenance-storage', sections.storage.error || storage.error || (storage.pending ? (storage.detail || '完整空间统计尚未完成') + ' · 备份 ' + megabytes(storage.backups_bytes) + '（' + (storage.backups_count || 0) + ' 份）；可稍后重试。' : '维护材料合计 ' + megabytes(storage.total_bytes) + ' · 备份 ' + megabytes(storage.backups_bytes) + '（' + (storage.backups_count || 0) + ' 份） · 环境 ' + megabytes(storage.environments_bytes) + ' · 浏览器 ' + megabytes(storage.browsers_bytes) + ' · 临时准备 ' + megabytes(storage.staging_bytes)));
    const pagination = data.backup_page || {page: 1, pages: 1, total: data.backups?.length || 0};
    const displayedPage = pagination.page;
    text('maintenance-pagination', '第 ' + pagination.page + ' / ' + pagination.pages + ' 页 · 共 ' + pagination.total + ' 份');
    if ($('maintenance-pagination-row')) show($('maintenance-pagination-row'), pagination.pages > 1);
    text('maintenance-backup-count', '共 ' + pagination.total + ' 份');
    if ($('maintenance-prev')) $('maintenance-prev').disabled = !!busy || displayedPage <= 1;
    if ($('maintenance-next')) $('maintenance-next').disabled = !!busy || displayedPage >= pagination.pages;
    if (checkingUpdate && data.check_stage) text('maintenance-check-detail', safeError(data.check_stage));
    else if (checked) {
      if (!compatible) text('maintenance-check-detail', '目标不支持自动更新，请手动安装。' + (check.compatibility_detail || check.compatibility?.detail || ''));
      else if (!check.available || check.action === 'current') text('maintenance-check-detail', '已是' + channelName(selected) + '的最新提交，无需更新。');
      else text('maintenance-check-detail', (switching ? '将切换到' + channelName(selected) + '，可能降级或改变功能。' : '发现' + channelName(selected) + '更新。') + '目标提交 ' + (check.target_sha?.slice(0, 12) || '未知') + '，确认后准备并安装。');
    } else text('maintenance-check-detail', '请检查' + channelName(selected) + '，再确认安装。');
    show($('maintenance-job'), !!data.job);
    if (data.job) {
      $('maintenance-job').dataset.phase = data.job.phase;
      text('maintenance-phase', names[data.job.phase] || data.job.phase);
      text('maintenance-detail', data.job.detail);
    }
    const signature = JSON.stringify([data.backups || [], !!busy, !!data.restore_supported]);
    if (backupSignature === signature) return;
    backupSignature = signature;
    $('maintenance-backups').replaceChildren();
    for (const item of data.backups || []) {
      const li = document.createElement('li');
      li.className = 'backup-row';
      const info = document.createElement('div');
      const title = document.createElement('b');
      title.textContent = new Date(item.created_at * 1000).toLocaleString('zh-CN', {hour12: false});
      const sub = document.createElement('p');
      sub.textContent = megabytes(item.size) + (item.delete_reason ? ' · ' + item.delete_reason : '');
      info.append(title, sub);
      const actions = document.createElement('div');
      actions.className = 'btn-row';
      const link = document.createElement('a');
      link.className = 'btn ghost sm';
      link.textContent = '下载';
      link.href = withToken('/api/maintenance/backups/' + encodeURIComponent(item.id));
      link.download = 'ooptra-' + item.id + '.zip';
      const button = document.createElement('button');
      button.className = 'btn subtle sm';
      button.textContent = '恢复';
      button.disabled = !!busy || !data.restore_supported;
      button.title = data.restore_supported ? '恢复配置与数据并重启服务' : '恢复需要通过 python launcher.py 启动';
      button.addEventListener('click', async () => {
        if (await confirmDialog('恢复这份备份？', '将恢复配置和数据并重启。恢复前会创建安全备份，健康检查失败时恢复当前数据。若端口或令牌改变，请用恢复后的配置重新访问。', '备份当前数据并恢复')) {
          await operation('/api/maintenance/restore', {backup_id: item.id}, '恢复准备已开始');
        }
      });
      const remove = document.createElement('button');
      remove.className = 'btn subtle sm backup-delete';
      remove.textContent = '删除';
      remove.disabled = !!busy || item.can_delete !== true;
      remove.title = item.delete_reason || '永久删除这份本地备份';
      remove.addEventListener('click', async () => {
        if (remove.disabled || operating) return;
        if (!await confirmDialog('删除这份备份？', title.textContent + '，' + megabytes(item.size) + '。永久删除本地备份文件，无法撤销；当前配置和数据不受影响。', '确认删除')) return;
        const result = await operation('/api/maintenance/backups/' + encodeURIComponent(item.id), {}, '备份已删除', '正在删除已确认的备份…', 'DELETE');
        if (result) {
          cleanup = null;
          if ($('maintenance-cleanup-result')) $('maintenance-cleanup-result').textContent = '备份已变化，请重新预览后再清理。';
          if (current) renderMaintenance(current);
        }
      });
      actions.append(link, button, remove);
      li.append(info, actions);
      $('maintenance-backups').append(li);
    }
    if (!data.backups?.length) $('maintenance-backups').innerHTML = '<li class="empty">还没有备份。更新前也会自动创建。</li>';
  }

  async function loadSection(name, force = false) {
    const section = sections[name];
    if (section.loading || (!force && Date.now() - section.readAt < 30000)) return;
    section.loading = true;
    const retry = $('maintenance-' + name + '-retry');
    if (retry) retry.disabled = true;
    try {
      const result = await api('/api/maintenance/' + name, {timeout: 20000});
      if (result[name]) section.value = result[name];
      section.error = '';
    } catch (err) { section.error = '读取失败：' + safeError(err) + '。可重试此项。'; }
    finally {
      section.loading = false;
      section.readAt = Date.now();
      if (retry) retry.disabled = false;
      if (current) renderMaintenance(current);
      else if (section.error) text(name === 'preflight' ? 'maintenance-preflight-status' : 'maintenance-storage', section.error);
    }
  }

  async function loadNetwork() {
    if (networkLoading || networkLoaded || networkDirty || Date.now() - networkReadAt < 30000 || !$('maintenance-network-save')) return;
    networkLoading = true;
    $('maintenance-network-save').disabled = true;
    try {
      const result = await api('/api/config', {timeout: 15000});
      const fields = result.groups?.webui?.fields;
      if (!fields?.update_proxy || !fields?.update_mirror) throw new Error('当前服务未提供更新网络配置，请刷新服务后重试');
      if (!networkDirty) {
        $('maintenance-network-proxy').value = '';
        proxyDirty = false;
        if ($('maintenance-proxy-mode')) $('maintenance-proxy-mode').value = 'keep';
        $('maintenance-network-proxy').placeholder = fields.update_proxy.is_set ? '已配置，留空保留原代理' : '留空使用部署机器的环境代理；direct 表示直连';
        $('maintenance-network-mirror').value = fields.update_mirror.value || '';
        syncAccelerator(fields.update_mirror.value || '');
        $('maintenance-network-clear-proxy').checked = false;
      }
      networkLoaded = true;
      text('maintenance-network-status', '官方 GitHub 优先；失败时自动尝试直连和已配置的镜像。');
    } catch (err) { text('maintenance-network-status', '更新网络配置读取失败：' + safeError(err)); }
    finally { networkLoading = false; networkReadAt = Date.now(); $('maintenance-network-save').disabled = !networkLoaded; renderAccelerator(); }
  }
  function syncAccelerator(mirror) {
    if (!$('maintenance-accelerator-mode')) return;
    const prefix = mirror.endsWith(acceleratorSuffix) ? mirror.slice(0, -acceleratorSuffix.length) : '';
    $('maintenance-accelerator-mode').value = !mirror ? 'off' : prefix ? 'on' : 'repository';
    $('maintenance-accelerator-node').value = !mirror ? 'https://gh-proxy.com' : acceleratorPresets.includes(prefix) ? prefix : 'custom';
    $('maintenance-accelerator-custom').value = prefix;
    renderAccelerator();
  }
  function renderAccelerator() {
    if (!$('maintenance-accelerator-mode')) return;
    const mode = $('maintenance-accelerator-mode').value;
    show($('maintenance-accelerator-options'), mode === 'on');
    show($('maintenance-accelerator-custom-field'), mode === 'on' && $('maintenance-accelerator-node').value === 'custom');
    show($('maintenance-mirror-field'), mode === 'repository');
    $('maintenance-network-test').disabled = testingNetwork || networkSaving || !networkLoaded;
  }
  function proxyDraft() {
    const mode = $('maintenance-proxy-mode')?.value;
    if (mode === 'direct') return 'direct';
    if ($('maintenance-network-clear-proxy').checked || mode === 'environment') return '';
    const proxy = $('maintenance-network-proxy').value.trim();
    if (mode === 'manual') return proxy || 'direct';
    return proxy || (proxyDirty ? 'direct' : undefined);
  }
  function renderProxy() {
    const mode = $('maintenance-proxy-mode')?.value;
    $('maintenance-network-proxy').disabled = networkSaving || $('maintenance-network-clear-proxy').checked || mode === 'direct' || mode === 'environment';
  }
  function acceleratorMirror() {
    if (!$('maintenance-accelerator-mode')) return $('maintenance-network-mirror').value.trim();
    const mode = $('maintenance-accelerator-mode').value;
    if (mode === 'off') return '';
    if (mode === 'repository') return $('maintenance-network-mirror').value.trim();
    const node = $('maintenance-accelerator-node').value;
    const prefix = (node === 'custom' ? $('maintenance-accelerator-custom').value.trim() : node).replace(/\/+$/, '');
    if (!prefix) throw new Error('请填写自定义 GitHub 加速地址');
    return prefix + acceleratorSuffix;
  }
  for (const id of ['maintenance-accelerator-mode', 'maintenance-accelerator-node', 'maintenance-accelerator-custom']) if ($(id)) $(id).addEventListener(id.endsWith('custom') ? 'input' : 'change', () => { networkDirty = true; renderAccelerator(); });
  if ($('maintenance-network-test')) $('maintenance-network-test').addEventListener('click', async () => {
    if (testingNetwork || !networkLoaded) return;
    testingNetwork = true;
    renderAccelerator();
    text('maintenance-network-test-status', '部署机器正在测试 Git 分支读取，最长 15 秒…');
    try {
      const body = {mirror: acceleratorMirror(), channel: $('maintenance-channel').value};
      const proxy = proxyDraft();
      if (proxy !== undefined) body.proxy = proxy;
      const result = await api('/api/maintenance/network/test', {method: 'POST', body, timeout: 20000});
      text('maintenance-network-test-status', '测试通过（' + result.elapsed_ms + ' ms）：' + result.detail);
    } catch (err) { text('maintenance-network-test-status', '测试未通过：' + safeError(err)); }
    finally { testingNetwork = false; renderAccelerator(); }
  });
  for (const id of ['maintenance-network-proxy', 'maintenance-network-mirror']) if ($(id)) $(id).addEventListener('input', () => { networkDirty = true; if (id === 'maintenance-network-proxy') proxyDirty = true; });
  if ($('maintenance-proxy-mode')) $('maintenance-proxy-mode').addEventListener('change', () => {
    networkDirty = true;
    proxyDirty = false;
    const mode = $('maintenance-proxy-mode').value;
    $('maintenance-network-proxy').value = mode === 'manual' ? 'http://127.0.0.1:7890' : '';
    $('maintenance-network-clear-proxy').checked = mode === 'environment';
    renderProxy();
  });
  if ($('maintenance-network-clear-proxy')) $('maintenance-network-clear-proxy').addEventListener('change', () => {
    networkDirty = true;
    renderProxy();
  });
  if ($('maintenance-network-retry')) $('maintenance-network-retry').addEventListener('click', () => {
    if (networkDirty) {
      text('maintenance-network-status', '有未保存修改，请先保存更新网络设置，再重新读取。');
      return;
    }
    networkLoaded = false;
    networkReadAt = 0;
    void loadNetwork();
  });
  if ($('maintenance-network-save')) $('maintenance-network-save').addEventListener('click', async () => {
    if (!networkLoaded || networkSaving) return;
    let mirror;
    try { mirror = acceleratorMirror(); } catch (err) { text('maintenance-network-status', safeError(err)); return; }
    const updates = {update_mirror: mirror};
    const proxy = proxyDraft();
    if (proxy !== undefined) updates.update_proxy = proxy;
    networkSaving = true;
    $('maintenance-network-save').disabled = true;
    for (const id of ['maintenance-network-proxy', 'maintenance-network-mirror', 'maintenance-network-clear-proxy', 'maintenance-network-retry', 'maintenance-accelerator-mode', 'maintenance-accelerator-node', 'maintenance-accelerator-custom', 'maintenance-proxy-mode']) if ($(id)) $(id).disabled = true;
    renderAccelerator();
    text('maintenance-network-status', '正在保存更新网络配置…');
    try {
      await api('/api/config', {method: 'POST', body: {updates: {webui: updates}}, timeout: 15000});
      networkDirty = false;
      proxyDirty = false;
      $('maintenance-network-mirror').value = mirror;
      syncAccelerator(mirror);
      $('maintenance-network-proxy').value = '';
      if ('update_proxy' in updates) $('maintenance-network-proxy').placeholder = updates.update_proxy ? '已配置，留空保留原代理' : '留空使用部署机器的环境代理；direct 表示直连';
      $('maintenance-network-clear-proxy').checked = false;
      if ($('maintenance-proxy-mode')) $('maintenance-proxy-mode').value = 'keep';
      $('maintenance-network-proxy').disabled = false;
      text('maintenance-network-status', '更新网络配置已保存，下次检查更新生效。');
    } catch (err) { text('maintenance-network-status', '保存失败：' + safeError(err)); }
    finally {
      networkSaving = false;
      $('maintenance-network-save').disabled = false;
      for (const id of ['maintenance-network-mirror', 'maintenance-network-clear-proxy', 'maintenance-network-retry', 'maintenance-accelerator-mode', 'maintenance-accelerator-node', 'maintenance-accelerator-custom', 'maintenance-proxy-mode']) if ($(id)) $(id).disabled = false;
      renderProxy();
      renderAccelerator();
    }
  });

  window.refreshMaintenance = async function(force = false) {
    void loadSection('preflight');
    void loadSection('storage');
    void loadNetwork();
    if (refreshing) { if (force) refreshAgain = true; return; }
    if (!force && Date.now() - lastRefresh < 2500) return;
    refreshing = true;
    const requestedPage = page;
    if ($('maintenance-status-retry')) $('maintenance-status-retry').disabled = true;
    try {
      const result = await api('/api/maintenance?page=' + requestedPage + '&page_size=10', {timeout: 15000});
      if (page !== requestedPage) { refreshAgain = true; return; }
      page = result.backup_page?.page || requestedPage;
      renderMaintenance(result);
      lastRefresh = Date.now();
      text('maintenance-status', '');
      show($('maintenance-status'), false);
      text('maintenance-feedback', feedback);
      show($('maintenance-feedback'), !!feedback);
    } catch (err) {
      show($('maintenance-status'), true);
      text('maintenance-status', current?.job && activePhases.has(current.job.phase) ? '服务正在重启，页面会自动重新连接。' : '版本与备份读取失败：' + safeError(err) + '。请重试。');
      if (!current) {
        text('maintenance-capability', '部署状态尚未读取');
        text('maintenance-version', state?.process?.version ? '当前 v' + state.process.version : '版本暂不可用');
        $('maintenance-backups').innerHTML = '<li class="empty">备份读取失败，请点击重试版本与备份。</li>';
      }
    } finally {
      refreshing = false;
      if ($('maintenance-status-retry')) $('maintenance-status-retry').disabled = false;
      if (refreshAgain) { refreshAgain = false; void window.refreshMaintenance(true); }
    }
  };

  async function operation(path, body, message, progress = '正在准备维护操作…', method = 'POST') {
    if (operating) return;
    operating = true;
    if (path === '/api/maintenance/check') { checkingUpdate = true; discardCheck = true; if (current) current = {...current, check: null}; }
    feedback = progress;
    text('maintenance-feedback', feedback);
    show($('maintenance-feedback'), true);
    busyControls(true);
    if (current) renderMaintenance(current);
    try {
      const result = await api(path, {method, body, timeout: path === '/api/maintenance/check' ? 65000 : 90000});
      if (path === '/api/maintenance/check') {
        discardCheck = false;
        if (result?.channel && result?.target_sha && current) current = {...current, check: result};
      }
      if (method === 'DELETE' || ['/api/maintenance/backups', '/api/maintenance/cleanup/apply'].includes(path)) {
        sections.storage.value = null;
        sections.storage.readAt = 0;
      }
      feedback = message;
      toast(message, '详情会在本页持续更新。', 'ok');
      return result;
    } catch (err) { feedback = '维护操作未完成：' + safeError(err); toast('维护操作未完成', safeError(err), 'err'); }
    finally {
      operating = false;
      checkingUpdate = false;
      busyControls(false);
      if (current) renderMaintenance(current);
      else $('maintenance-update').disabled = true;
      text('maintenance-feedback', feedback);
      void window.refreshMaintenance(true);
    }
  }

  window.checkMaintenanceUpdate = () => operation('/api/maintenance/check', selectedSource ? {channel: $('maintenance-channel').value} : {}, '检查完成', '正在由部署机器检查更新，最长等待 65 秒…');
  if ($('maintenance-status-retry')) $('maintenance-status-retry').addEventListener('click', () => window.refreshMaintenance(true));
  for (const name of ['preflight', 'storage']) if ($('maintenance-' + name + '-retry')) $('maintenance-' + name + '-retry').addEventListener('click', () => { void loadSection(name, true); });
  $('maintenance-check').addEventListener('click', window.checkMaintenanceUpdate);
  $('maintenance-channel').addEventListener('change', () => {
    selectedSource = true;
    if (current) renderMaintenance(current);
  });
  $('maintenance-backup').addEventListener('click', () => operation('/api/maintenance/backups', {}, '备份已创建', '正在创建备份，服务继续运行…'));
  if ($('maintenance-prev')) $('maintenance-prev').addEventListener('click', () => { page = Math.max(1, page - 1); window.refreshMaintenance(true); });
  if ($('maintenance-next')) $('maintenance-next').addEventListener('click', () => { page = Math.min(current?.backup_page?.pages || page + 1, page + 1); window.refreshMaintenance(true); });
  if ($('maintenance-cleanup-preview')) $('maintenance-cleanup-preview').addEventListener('click', async () => {
    cleanup = null;
    const result = await operation('/api/maintenance/cleanup/preview', {}, '清理预览已生成', '正在检查可清理的维护材料…');
    cleanup = result || null;
    const list = $('maintenance-cleanup-result');
    if (list) {
      list.replaceChildren();
      for (const item of cleanup?.items || []) {
        const row = document.createElement('li'); row.textContent = item.path + ' · ' + megabytes(item.size); list.append(row);
      }
      if (!result) list.textContent = '清理预览失败，请重试；未删除任何文件。';
      else if (!cleanup?.items?.length) list.textContent = '没有可清理材料。当前环境、浏览器与回滚备份始终保留。';
    }
    if (current) renderMaintenance(current);
  });
  if ($('maintenance-cleanup-apply')) $('maintenance-cleanup-apply').addEventListener('click', async () => {
    if (!cleanup?.items?.length || operating) return;
    if (!await confirmDialog('清理预览中的维护材料？', '删除 ' + cleanup.items.length + ' 项，共 ' + megabytes(cleanup.total_bytes) + '。此操作不可撤销，仅删除刚才预览的非活动材料；保留当前运行与回滚材料。', '确认清理')) return;
    const token = cleanup.token;
    cleanup = null;
    await operation('/api/maintenance/cleanup/apply', {token}, '维护材料已清理', '正在清理已确认的维护材料…');
    if ($('maintenance-cleanup-result')) $('maintenance-cleanup-result').textContent = '请重新预览后再清理。';
  });
  $('maintenance-update').addEventListener('click', async () => {
    const check = current?.check;
    if (!check || check.channel !== $('maintenance-channel').value || $('maintenance-update').disabled) return;
    const installed = check.current_channel || currentChannel(current);
    const switching = switchingChannel(check) || !!(installed && installed !== check.channel);
    const detail = (switching ? '从' + channelName(installed) + '切换到' + channelName(check.channel) + '，可能降级或改变功能。' : '更新' + channelName(check.channel) + '。') + '安装提交 ' + check.target_sha.slice(0, 12) + '。先创建备份和独立虚拟环境，再重启服务；健康检查失败会尝试恢复原版本。';
    if (await confirmDialog(switching ? '确认切换更新频道？' : '更新 Ooptra？', detail, switching ? '确认切换并安装' : '备份并更新')) {
      const body = {channel: check.channel, target_sha: check.target_sha};
      if (switching) body.confirm_channel_switch = true;
      await operation('/api/maintenance/update', body, switching ? '频道切换准备已开始' : '更新准备已开始');
    }
  });

  $('diagnostic-run').addEventListener('click', async () => {
    const button = $('diagnostic-run');
    button.disabled = true;
    button.textContent = '检查中…';
    try {
      const body = {network: $('diagnostic-network').checked};
      const file = $('diagnostic-audio')?.files?.[0];
      if (file) {
        if (file.size > 2 * 1024 * 1024) throw new Error('自检 WAV 不能超过 2 MiB。');
        body.audio_wav_base64 = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(',')[1]);
          reader.onerror = () => reject(new Error('无法读取自检音频。'));
          reader.readAsDataURL(file);
        });
      }
      const result = await api('/api/voice/diagnostics', {method: 'POST', body});
      $('diagnostic-results').innerHTML = checksHTML(result.checks || []);
    } catch (err) {
      $('diagnostic-results').innerHTML = checksHTML([{title: '自检未完成', state: 'fail', detail: err.message}]);
    } finally { button.disabled = false; button.textContent = '开始自检'; }
  });

  const audio = $('preview-audio');
  const defaults = {voice: '你好，我是 Ooptra，很高兴听到你的声音。', enter: '在玩什么游戏？', leave: '拜拜，我下了'};
  let saved = [];
  let promptRequest = 0;
  window.loadPreviewPrompts = async () => {
    const kind = $('preview-kind').value;
    const request = ++promptRequest;
    show($('preview-saved'), kind !== 'voice');
    if (kind === 'voice') return;
    const area = $('preview-area').value;
    $('preview-area').replaceChildren(new Option('全局默认', ''));
    for (const [id, name] of Object.entries(voiceAreaNames)) $('preview-area').add(new Option(name, id));
    $('preview-area').value = area;
    try {
      const result = await api('/api/voice/preview/prompts?kind=' + kind + '&area=' + encodeURIComponent(area));
      if (request !== promptRequest) return;
      saved = result.prompts || [];
      $('preview-prompt').replaceChildren();
      saved.forEach((value, index) => $('preview-prompt').add(new Option(value, String(index))));
      if (!saved.length) $('preview-prompt').add(new Option('未保存台词；可输入临时试听内容', ''));
      $('preview-random').disabled = !saved.length;
      if (saved.length) $('preview-text').value = saved[0];
    } catch (err) { if (request === promptRequest) text('preview-status', err.message); }
  };
  $('preview-kind').addEventListener('change', () => { $('preview-text').value = defaults[$('preview-kind').value]; window.loadPreviewPrompts(); });
  $('preview-area').addEventListener('change', () => window.loadPreviewPrompts());
  $('preview-prompt').addEventListener('change', () => { const value = saved[Number($('preview-prompt').value)]; if (value) $('preview-text').value = value; });
  $('preview-random').addEventListener('click', () => { if (saved.length) { const index = Math.floor(Math.random() * saved.length); $('preview-prompt').value = String(index); $('preview-text').value = saved[index]; } });
  $('preview-stop').addEventListener('click', () => { audio.pause(); audio.currentTime = 0; });
  $('preview-run').addEventListener('click', async () => {
    const button = $('preview-run');
    const content = $('preview-text').value.trim();
    if (!content) { text('preview-status', '请输入试听内容。'); return; }
    audio.pause();
    audio.removeAttribute('src');
    show(audio, false);
    button.disabled = true;
    $('preview-stop').disabled = true;
    text('preview-status', '正在生成独立试听，最长等待 30 秒…');
    try {
      const result = await api('/api/voice/preview', {method: 'POST', body: {kind: $('preview-kind').value, text: content, voice: $('preview-voice').value.trim()}});
      audio.src = 'data:audio/wav;base64,' + result.wav_base64;
      show(audio, true);
      $('preview-stop').disabled = false;
      text('preview-status', '试听文本：' + result.text);
      try { await audio.play(); } catch (_) { text('preview-status', '音频已生成，请点击播放器播放。文本：' + result.text); }
    } catch (err) { text('preview-status', err.message); }
    finally { button.disabled = false; }
  });
 }
 function start() {
   try { initializeMaintenance(); }
   catch (err) {
     const node = document.getElementById('maintenance-feedback');
     if (node) node.textContent = '维护页面加载失败，请刷新页面重试：' + err.message;
     console.error('Maintenance initialization failed', err);
   }
 }
 if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
 else start();
})();
