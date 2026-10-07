/* Updater and backup UI; no framework or remote assets. */
'use strict';

(() => {
 const maintenanceApi = (path, opts = {}) => api(path, {...opts, timeout: 90000});
 function initializeMaintenance() {
  let current = null;
  let refreshing = false;
  let operating = false;
  let lastRefresh = 0;
  let feedback = '';
  let page = 1;
  let cleanup = null;
  let selectedSource = false;
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
    current = data;
    const supported = !!data.preflight?.supported;
    const busy = operating || data.busy || activePhases.has(data.job?.phase);
    const installed = currentChannel(data);
    if (!selectedSource && channels[installed]) { $('maintenance-channel').value = installed; selectedSource = true; }
    const selected = $('maintenance-channel').value;
    const check = data.check;
    text('maintenance-capability', supported ? '支持自动升级' : '查看部署预检查');
    text('maintenance-version', '当前 v' + (data.update?.version || state?.process?.version || '—'));
    busyControls(!!busy);
    $('maintenance-checks').innerHTML = checksHTML(data.preflight?.checks || []);
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
    text('maintenance-storage', storage.error || ('维护材料合计 ' + megabytes(storage.total_bytes) + ' · 备份 ' + megabytes(storage.backups_bytes) + '（' + (storage.backups_count || 0) + ' 份） · 环境 ' + megabytes(storage.environments_bytes) + ' · 浏览器 ' + megabytes(storage.browsers_bytes) + ' · 临时准备 ' + megabytes(storage.staging_bytes)));
    const pagination = data.backup_page || {page: 1, pages: 1, total: data.backups?.length || 0};
    page = pagination.page;
    text('maintenance-pagination', '第 ' + pagination.page + ' / ' + pagination.pages + ' 页 · 共 ' + pagination.total + ' 份');
    if ($('maintenance-prev')) $('maintenance-prev').disabled = !!busy || page <= 1;
    if ($('maintenance-next')) $('maintenance-next').disabled = !!busy || page >= pagination.pages;
    if (checked) {
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
    $('maintenance-backups').replaceChildren();
    for (const item of data.backups || []) {
      const li = document.createElement('li');
      li.className = 'backup-row';
      const info = document.createElement('div');
      const title = document.createElement('b');
      title.textContent = new Date(item.created_at * 1000).toLocaleString('zh-CN', {hour12: false});
      const sub = document.createElement('p');
      sub.textContent = (item.size / 1024 / 1024).toFixed(2) + ' MB';
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
      button.addEventListener('click', async () => {
        if (await confirmDialog('恢复这份备份？', '将恢复配置和数据并重启。恢复前会创建安全备份，健康检查失败时恢复当前数据。若端口或令牌改变，请用恢复后的配置重新访问。', '备份当前数据并恢复')) {
          await operation('/api/maintenance/restore', {backup_id: item.id}, '恢复准备已开始');
        }
      });
      actions.append(link, button);
      li.append(info, actions);
      $('maintenance-backups').append(li);
    }
    if (!data.backups?.length) $('maintenance-backups').innerHTML = '<li class="empty">还没有备份。更新前也会自动创建。</li>';
  }

  window.refreshMaintenance = async function(force = false) {
    if (refreshing || (!force && Date.now() - lastRefresh < 2500)) return;
    refreshing = true;
    try {
      renderMaintenance(await maintenanceApi('/api/maintenance?page=' + page + '&page_size=10'));
      lastRefresh = Date.now();
      text('maintenance-feedback', feedback);
    } catch (err) {
      text('maintenance-feedback', current?.job && activePhases.has(current.job.phase) ? '服务正在重启，页面会自动重新连接。' : err.message);
    } finally { refreshing = false; }
  };

  async function operation(path, body, message, progress = '正在准备维护操作…') {
    if (operating) return;
    operating = true;
    feedback = progress;
    text('maintenance-feedback', feedback);
    busyControls(true);
    if (current) renderMaintenance(current);
    try {
      const result = await maintenanceApi(path, {method: 'POST', body});
      feedback = message;
      toast(message, '详情会在本页持续更新。', 'ok');
      return result;
    } catch (err) { feedback = '维护操作未完成：' + err.message; toast('维护操作未完成', err.message, 'err'); }
    finally {
      operating = false;
      busyControls(false);
      await window.refreshMaintenance(true);
      text('maintenance-feedback', feedback);
    }
  }

  window.checkMaintenanceUpdate = () => operation('/api/maintenance/check', selectedSource ? {channel: $('maintenance-channel').value} : {}, '检查完成', '正在检查更新，最长等待 60 秒…');
  $('maintenance-check').addEventListener('click', window.checkMaintenanceUpdate);
  $('maintenance-channel').addEventListener('change', () => {
    selectedSource = true;
    if (current) renderMaintenance(current);
  });
  $('maintenance-backup').addEventListener('click', () => operation('/api/maintenance/backups', {}, '备份已创建', '正在创建备份，服务继续运行…'));
  if ($('maintenance-prev')) $('maintenance-prev').addEventListener('click', () => { page = Math.max(1, page - 1); window.refreshMaintenance(true); });
  if ($('maintenance-next')) $('maintenance-next').addEventListener('click', () => { page++; window.refreshMaintenance(true); });
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
      if (!cleanup?.items?.length) list.textContent = '没有可清理材料。当前环境、浏览器与回滚备份始终保留。';
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
