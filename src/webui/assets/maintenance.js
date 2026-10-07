/* Independent voice tools and maintenance UI; no framework or remote assets. */
'use strict';

(() => {
  let current = null;
  let refreshing = false;
  let operating = false;
  let lastRefresh = 0;
  const activePhases = new Set(['preparing', 'awaiting_restart', 'switching', 'checking', 'rolling_back']);
  const names = {preparing: '准备中', awaiting_restart: '正在关闭旧会话', switching: '切换中', checking: '检查新进程', rolling_back: '恢复原版本', complete: '已完成', rolled_back: '已回滚', failed: '需要处理'};

  function checksHTML(rows) {
    return rows.map(row => {
      const state = row.state || (row.passed ? 'pass' : 'fail');
      return '<li class="check-row" data-state="' + escapeHtml(state) + '"><span class="check-mark" aria-hidden="true">' + (state === 'pass' ? '✓' : state === 'fail' ? '!' : '—') + '</span><div><b>' + escapeHtml(row.title || row.id) + '</b><p>' + escapeHtml(row.detail || '') + '</p></div></li>';
    }).join('');
  }

  function renderMaintenance(data) {
    current = data;
    const supported = !!data.preflight?.supported;
    const busy = operating || data.busy || activePhases.has(data.job?.phase);
    const selected = $('maintenance-channel').value;
    const check = data.check;
    text('maintenance-capability', supported ? '支持自动升级' : '查看部署预检查');
    text('maintenance-version', '当前 v' + (state?.process?.version || '—'));
    $('maintenance-checks').innerHTML = checksHTML(data.preflight?.checks || []);
    $('maintenance-update').disabled = busy || !supported || !check?.available || check.channel !== selected;
    $('maintenance-backup').disabled = !!busy;
    $('maintenance-check').disabled = !!busy;
    $('maintenance-channel').disabled = !!busy;
    if (check?.channel === selected) text('maintenance-check-detail', check.available ? '目标提交 ' + check.target_sha.slice(0, 12) + '，确认后准备并安装。' : '已是所选分支的最新提交。');
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
      renderMaintenance(await api('/api/maintenance'));
      lastRefresh = Date.now();
      $('maintenance-feedback').textContent = '';
    } catch (err) {
      text('maintenance-feedback', current?.job && activePhases.has(current.job.phase) ? '服务正在重启，页面会自动重新连接。' : err.message);
    } finally { refreshing = false; }
  };

  async function operation(path, body, message) {
    operating = true;
    if (current) renderMaintenance(current);
    try {
      await api(path, {method: 'POST', body});
      toast(message, '详情会在本页持续更新。', 'ok');
    } catch (err) { toast('维护操作未完成', err.message, 'err'); }
    finally {
      operating = false;
      await window.refreshMaintenance(true);
    }
  }

  $('maintenance-check').addEventListener('click', () => operation('/api/maintenance/check', {channel: $('maintenance-channel').value}, '检查完成'));
  $('maintenance-channel').addEventListener('change', () => {
    text('maintenance-check-detail', '更新来源已切换，请重新检查。');
    if (current) renderMaintenance(current);
  });
  $('maintenance-backup').addEventListener('click', () => operation('/api/maintenance/backups', {}, '备份已创建'));
  $('maintenance-update').addEventListener('click', async () => {
    const check = current?.check;
    if (!check || $('maintenance-update').disabled) return;
    if (await confirmDialog('升级 Ooptra？', '安装 ' + check.channel + ' 分支提交 ' + check.target_sha.slice(0, 12) + '。先创建备份和独立虚拟环境，再重启服务；健康检查失败会尝试恢复原版本。', '备份并升级')) {
      await operation('/api/maintenance/update', {channel: check.channel, target_sha: check.target_sha}, '升级准备已开始');
    }
  });

  $('diagnostic-run').addEventListener('click', async () => {
    const button = $('diagnostic-run');
    button.disabled = true;
    button.textContent = '检查中…';
    try {
      const result = await api('/api/voice/diagnostics', {method: 'POST', body: {network: $('diagnostic-network').checked}});
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
})();
