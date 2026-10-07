/* Real browser acceptance: isolated local fixtures, no Oopz/model credentials. */
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.OOPTRA_PLAYWRIGHT_MODULE || 'playwright');

const assets = path.resolve(__dirname, '../../src/webui/assets');
const requests = [];
let failures = new Set();
let job = null;
let slowMaintenance = false;
let stallMaintenanceStatus = false;
let configReadDelay = 0;
let stallCheckBody = false;
let installedChannel = 'beta';
let deletableBackup = true;
let updateCheck = {channel: 'beta', current_channel: 'beta', target_sha: 'b'.repeat(40), available: true, action: 'update', requires_confirmation: false, compatible: true};
let schema = {oopz: {fields: {default_area: {type: 'str', value: 'original', label: '默认域'}}}, voice: {fields: {backend: {type: 'select', value: 'mimo_cascade', label: '后端', options: ['mimo_cascade', 'gemini_live']}}}, webui: {fields: {port: {type: 'int', value: 8080, label: '端口'}, update_proxy: {type: 'str', value: null, is_set: true, sensitive: true, label: '更新代理', adv: true}, update_mirror: {type: 'str', value: '', label: '更新镜像', adv: true}}}};
const wav = Buffer.alloc(524);
wav.write('RIFF'); wav.writeUInt32LE(516, 4); wav.write('WAVEfmt ', 8); wav.writeUInt32LE(16, 16);
wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22); wav.writeUInt32LE(24000, 24);
wav.writeUInt32LE(48000, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(480, 40);
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const endpoint = url.pathname;
  if (endpoint === '/' || endpoint.startsWith('/assets/')) {
    const file = path.join(assets, endpoint === '/' ? 'index.html' : path.basename(endpoint));
    res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.svg') ? 'image/svg+xml' : 'text/html');
    return res.end(fs.readFileSync(file));
  }
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = chunks.length ? JSON.parse(Buffer.concat(chunks)) : {};
  if (['POST', 'DELETE'].includes(req.method)) requests.push({endpoint, body, method: req.method});
  res.setHeader('Content-Type', 'application/json');
  if (stallCheckBody && endpoint === '/api/maintenance/check') {
    res.write('{"ok":');
    await new Promise(resolve => setTimeout(resolve, 500));
    return res.end('true}');
  }
  if (endpoint === '/api/config' && req.method === 'GET' && configReadDelay) await new Promise(resolve => setTimeout(resolve, configReadDelay));
  if (stallMaintenanceStatus && endpoint === '/api/maintenance') await new Promise(resolve => setTimeout(resolve, 2000));
  if (slowMaintenance && ['/api/maintenance/check', '/api/maintenance/backups'].includes(endpoint)) await new Promise(resolve => setTimeout(resolve, 500));
  if (failures.has(endpoint)) { res.statusCode = 503; return res.end(JSON.stringify({error: 'fixture offline'})); }
  let data = {ok: true};
  if (endpoint === '/api/status') data = {process: {version: '261007-dev'}, bridge: {runtime: {running: true}, oopz: {connected: true}, onebot: {connected: false}, traffic: {}, recent_events: [], recent_actions: []}};
  if (endpoint === '/api/credentials') data = {credentials: {has_password: true, has_private_key: true}};
  if (endpoint === '/api/config') {
    if (req.method === 'POST') {
      const changed = {};
      for (const [group, fields] of Object.entries(body.updates)) {
        changed[group] = Object.keys(fields);
        for (const [field, value] of Object.entries(fields)) {
          const meta = schema[group].fields[field];
          meta.value = meta.sensitive ? null : value;
          if (meta.sensitive) meta.is_set = !!value;
        }
      }
      data = {changed};
    } else data = {groups: schema, path: 'fixture/config.py'};
  }
  if (endpoint === '/api/oopz/areas') data = {areas: [{id: 'qa', name: '验收域'}], default_area: 'qa', default_channel: 'room'};
  if (endpoint === '/api/oopz/channels') data = {channels: [{id: 'room', name: '语音房'}]};
  if (endpoint === '/api/voice/status') data = {status: {enabled: true, joined: true, backend: 'mimo_cascade', voice_observation: {recent_decisions: [{timestamp: '2026-10-07T08:30:45+00:00', outcome: 'skipped', reason: 'probability', elapsed_ms: 19, timings_ms: {asr: 12, intent: 7}}]}}, auto_visit: {empty_room: {state: 'occupied'}}};
  if (endpoint === '/api/voice/preview/prompts') data = {prompts: ['保存的台词一', '保存的台词二']};
  if (endpoint === '/api/voice/preview') data = {text: body.text, wav_base64: wav.toString('base64')};
  if (endpoint === '/api/voice/diagnostics') data = {checks: [{id: 'asr', title: '音频识别', state: 'pass', detail: '样本识别完成', elapsed_ms: 12}]};
  if (endpoint === '/api/maintenance/check') {
    updateCheck = {channel: body.channel, current_channel: installedChannel, target_sha: 'b'.repeat(40), available: true, action: body.channel === installedChannel ? 'update' : 'switch', requires_confirmation: body.channel !== installedChannel, compatible: true};
    data = updateCheck;
  }
  if (endpoint === '/api/maintenance/backups/' + 'a'.repeat(32) && req.method === 'DELETE') deletableBackup = false;
  if (endpoint === '/api/maintenance/network/test') data = {ok: true, elapsed_ms: 42, detail: 'Git 分支读取成功'};
  if (endpoint === '/api/maintenance') data = {preflight: {supported: true, checks: []}, restore_supported: true, health: {checks: [{id: 'process', title: '进程', state: 'pass', detail: '控制台在线'}, {id: 'onebot', title: 'OneBot', state: 'warn', detail: '未接入，桥接降级'}]}, backups: [...(deletableBackup ? [{id: 'a'.repeat(32), created_at: 1, size: 524, can_delete: true}] : []), {id: 'c'.repeat(32), created_at: 2, size: 100, can_delete: false, delete_reason: '回滚任务引用'}], backup_page: {page: Number(url.searchParams.get('page') || 1), pages: 2, total: 11, page_size: 10}, storage: {total_bytes: 524, backups_count: 11, backups_bytes: 524}, update: {channel: 'dev', current_channel: installedChannel, current_sha: 'a'.repeat(40), target_sha: 'b'.repeat(40)}, check: updateCheck, job};
  if (endpoint === '/api/maintenance/preflight') data = {ok: true, preflight: {supported: true, checks: [], pending: false}};
  if (endpoint === '/api/maintenance/storage') data = {ok: true, storage: {total_bytes: 524, backups_count: 11, backups_bytes: 524, pending: false}};
  if (endpoint === '/api/maintenance/cleanup/preview') data = {token: 'fixture-cleanup', items: [{id: 'old-env', path: 'old-env', kind: 'environment', size: 524}], total_bytes: 524};
  res.end(JSON.stringify(data));
});

async function main() {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true, ...(process.env.OOPTRA_BROWSER_EXECUTABLE ? {executablePath: process.env.OOPTRA_BROWSER_EXECUTABLE} : {})});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const nav = name => page.locator('.nav-item[data-page="' + name + '"]').first().click();
  try {
    await page.goto('http://127.0.0.1:' + server.address().port);
    await page.locator('#screen-app').waitFor({state: 'visible'});
    await nav('maintenance');
    await page.waitForFunction(() => document.querySelector('#maintenance-channel').value === 'beta');
    await page.locator('#maintenance-advanced > summary').click();
    await page.getByText('更新网络设置', {exact: true}).click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-network-save').disabled);
    assert.equal(await page.locator('#maintenance-network-proxy').inputValue(), '', 'saved proxy credentials are never echoed');
    await page.selectOption('#maintenance-accelerator-mode', 'repository');
    await page.locator('#maintenance-network-mirror').fill('https://mirror.example/ooptra.git');
    await page.locator('#maintenance-network-save').click();
    await page.waitForFunction(() => document.querySelector('#maintenance-network-status').textContent.includes('已保存'));
    const networkSave = requests.find(item => item.endpoint === '/api/config' && item.body.updates.webui?.update_mirror);
    assert.equal(networkSave.body.updates.webui.update_mirror, 'https://mirror.example/ooptra.git');
    assert(!Object.hasOwn(networkSave.body.updates.webui, 'update_proxy'), 'blank untouched proxy preserves stored credentials');
    await page.selectOption('#maintenance-accelerator-mode', 'on');
    await page.selectOption('#maintenance-accelerator-node', 'https://gh-proxy.com');
    await page.locator('#maintenance-network-test').click();
    await page.waitForFunction(() => document.querySelector('#maintenance-network-test-status').textContent.includes('测试通过'));
    assert.equal(requests.filter(row => row.endpoint === '/api/maintenance/network/test').at(-1).body.mirror, 'https://gh-proxy.com/https://github.com/Eason4869/Ooptra.git');
    await page.getByText('部署机器代理', {exact: true}).click();
    await page.selectOption('#maintenance-accelerator-mode', 'off');
    await page.selectOption('#maintenance-proxy-mode', 'manual');
    assert.equal(await page.locator('#maintenance-network-proxy').inputValue(), 'http://127.0.0.1:7890');
    await page.locator('#maintenance-network-save').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-network-save').disabled);
    assert.deepEqual(requests.filter(row => row.endpoint === '/api/config').at(-1).body.updates.webui, {update_mirror: '', update_proxy: 'http://127.0.0.1:7890'});
    await page.selectOption('#maintenance-proxy-mode', 'manual');
    await page.locator('#maintenance-network-proxy').fill('');
    await page.locator('#maintenance-network-test').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-network-test').disabled);
    assert.equal(requests.filter(row => row.endpoint === '/api/maintenance/network/test').at(-1).body.proxy, 'direct');
    await page.locator('#maintenance-network-save').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-network-save').disabled);
    assert.equal(requests.filter(row => row.endpoint === '/api/config').at(-1).body.updates.webui.update_proxy, 'direct');
    await page.getByText('更新网络设置', {exact: true}).click();
    assert.deepEqual(await page.locator('#maintenance-channel option').evaluateAll(options => options.map(option => [option.value, option.textContent])), [['main', 'main · 正式版'], ['beta', 'beta · 测试版'], ['dev', 'dev · 预览版']]);
    await page.selectOption('#maintenance-channel', 'main');
    await page.evaluate(() => window.refreshMaintenance(true));
    assert.equal(await page.locator('#maintenance-channel').inputValue(), 'main', 'status polling preserves manual channel selection');
    assert(await page.locator('#maintenance-update').isDisabled(), 'changing channel requires a fresh check');
    await page.locator('#maintenance-check').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-update').disabled);
    assert.match(await page.locator('#maintenance-update').textContent(), /切换/);
    await page.locator('#maintenance-update').click();
    await page.locator('#dialog').waitFor({state: 'visible'});
    assert.match(await page.locator('#dialog').textContent(), /正式版/);
    assert.match(await page.locator('#dialog').textContent(), /降级/);
    await page.locator('#dialog-no').click();
    assert(!requests.some(item => item.endpoint === '/api/maintenance/update'), 'cancel must leave installation untouched');
    await page.locator('#maintenance-update').click();
    await page.locator('#dialog-yes').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-check').disabled);
    assert(requests.some(item => item.endpoint === '/api/maintenance/update' && item.body.channel === 'main' && item.body.confirm_channel_switch === true));
    updateCheck = {...updateCheck, channel: 'main', available: false, action: 'current', requires_confirmation: false};
    await page.evaluate(() => window.refreshMaintenance(true));
    assert(await page.locator('#maintenance-update').isDisabled(), 'current target must not offer an install');
    assert.match(await page.locator('#maintenance-check-detail').textContent(), /无需更新|最新/);
    installedChannel = 'dev';
    updateCheck = {...updateCheck, channel: 'dev', current_channel: 'dev', available: true, action: 'update'};
    await page.reload();
    await page.locator('#screen-app').waitFor({state: 'visible'});
    await nav('config');
    await page.locator('#config-groups input[type="text"]').fill('draft-area');
    await page.locator('#config-tabs [data-tab="voice"]').click();
    await page.locator('#config-tabs [data-tab="connection"]').click();
    assert.equal(await page.locator('#config-groups input[type="text"]').inputValue(), 'draft-area', 'changing groups must preserve typed draft');
    await nav('overview');
    await page.locator('#dialog').waitFor({state: 'visible'});
    await page.locator('#dialog-no').click();
    assert(await page.locator('#page-config').evaluate(node => node.classList.contains('is-active')));
    await nav('overview');
    await page.locator('#dialog-yes').click();
    await nav('config');
    await page.waitForFunction(() => document.querySelector('#config-groups input').value === 'draft-area');
    await page.locator('#tool-reload').click();
    await page.waitForFunction(() => document.querySelector('#config-groups input').value === 'draft-area');
    configReadDelay = 250;
    await page.locator('#tool-reload').click();
    await page.locator('#config-groups input').fill('draft-during-load');
    await page.waitForTimeout(300);
    assert.equal(await page.locator('#config-groups input').inputValue(), 'draft-during-load');
    configReadDelay = 0;
    await page.locator('#config-groups input').fill('draft-area');
    const unloadPrompt = page.waitForEvent('dialog');
    const refresh = page.evaluate(() => location.reload());
    const unloadDialog = await unloadPrompt;
    assert.equal(unloadDialog.type(), 'beforeunload', 'refresh must prompt before dropping an unsaved draft');
    await unloadDialog.dismiss();
    await refresh;
    assert.equal(await page.locator('#config-groups input').inputValue(), 'draft-area');
    failures.add('/api/config');
    await page.locator('#config-save').click();
    await page.waitForFunction(() => !document.querySelector('#config-save').disabled);
    assert.match(await page.locator('#config-status').textContent(), /fixture offline/);
    assert(await page.locator('#savebar').isVisible(), 'failed save must retain draft');
    failures.clear();
    await page.locator('#config-save').click();
    await page.locator('#savebar').waitFor({state: 'hidden'});
    await page.locator('#config-groups input').fill('discarded-area');
    await page.locator('#config-discard').click();
    await page.locator('#dialog-yes').click();
    await page.waitForFunction(() => document.querySelector('#config-groups input').value === 'draft-area');
    await nav('maintenance');
    const remove = page.locator('.backup-delete').first();
    await remove.waitFor();
    assert(await page.locator('.backup-delete').last().isDisabled(), 'referenced backup must be protected');
    await remove.focus();
    await page.evaluate(() => window.refreshMaintenance(true));
    assert(await remove.evaluate(node => node === document.activeElement), 'polling must retain keyboard focus');
    await remove.click();
    await page.locator('#dialog-no').click();
    assert(!requests.some(row => row.method === 'DELETE'), 'cancelled deletion must not call API');
    failures.add('/api/maintenance/backups/' + 'a'.repeat(32));
    await remove.click();
    await page.locator('#dialog-yes').click();
    await page.waitForFunction(() => document.querySelector('#maintenance-feedback').textContent.includes('fixture offline'));
    assert.equal(await page.locator('.backup-delete').count(), 2, 'failed delete must keep the backup row');
    failures.clear();
    await remove.click();
    await page.locator('#dialog-yes').click();
    await page.waitForFunction(() => document.querySelectorAll('.backup-delete').length === 1);
    assert(requests.some(row => row.method === 'DELETE' && row.endpoint.endsWith('a'.repeat(32))));
    await page.locator('#maintenance-advanced > summary').click();
    slowMaintenance = true;
    await page.locator('#maintenance-check').click();
    assert.match(await page.locator('#maintenance-feedback').textContent(), /正在.*检查更新/);
    assert(await page.locator('#maintenance-check').isDisabled());
    await page.waitForFunction(() => !document.querySelector('#maintenance-check').disabled);
    await page.locator('#maintenance-backup').click();
    assert.match(await page.locator('#maintenance-feedback').textContent(), /正在创建备份/);
    assert(await page.locator('#maintenance-backup').isDisabled());
    await page.waitForFunction(() => !document.querySelector('#maintenance-backup').disabled);
    slowMaintenance = false;
    assert(requests.some(item => item.endpoint === '/api/maintenance/check' && item.body.channel === 'dev'));
    assert(requests.some(item => item.endpoint === '/api/maintenance/backups'));
    stallCheckBody = true;
    await page.evaluate(() => {
      window.browserTestTimeout = window.setTimeout;
      window.setTimeout = (callback, delay, ...args) => window.browserTestTimeout(callback, delay === 65000 ? 100 : delay, ...args);
    });
    await page.locator('#maintenance-check').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-check').disabled);
    assert.match(await page.locator('#maintenance-feedback').textContent(), /请求超过 65 秒/, 'a timeout while reading the response must report failure');
    await page.evaluate(() => { window.setTimeout = window.browserTestTimeout; delete window.browserTestTimeout; });
    stallCheckBody = false;
    stallMaintenanceStatus = true;
    failures.add('/api/maintenance/check');
    await page.locator('#maintenance-check').click();
    await page.waitForFunction(() => document.querySelector('#maintenance-feedback').textContent.includes('fixture offline'), null, {timeout: 1000});
    assert(await page.locator('#maintenance-check').isEnabled(), 'check failure restores controls before slow status finishes');
    assert(await page.locator('#maintenance-update').isDisabled(), 'failed recheck must invalidate the previous install target');
    stallMaintenanceStatus = false;
    failures.clear();
    await page.waitForTimeout(2100);
    assert.match(await page.locator('#maintenance-feedback').textContent(), /fixture offline/, 'later polling retains operation error');
    assert.match(await page.locator('#maintenance-health').textContent(), /桥接降级/);
    await page.locator('#maintenance-next').click();
    await page.waitForFunction(() => document.querySelector('#maintenance-pagination').textContent.includes('第 2'));
    await page.locator('#maintenance-prev').click();
    await page.waitForFunction(() => document.querySelector('#maintenance-pagination').textContent.includes('第 1'));
    await page.selectOption('#maintenance-channel', 'main');
    await page.locator('.rail-utilities > summary').click();
    await page.locator('#btn-check-update').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-check').disabled);
    assert(requests.some(item => item.endpoint === '/api/maintenance/check' && item.body.channel === 'main'), 'sidebar and maintenance page must check the same selected source');
    await page.locator('.rail-utilities > summary').click();
    await page.selectOption('#maintenance-channel', 'dev');
    await page.getByText('存储与清理', {exact: true}).click();
    await page.locator('#maintenance-cleanup-preview').click();
    await page.locator('#maintenance-cleanup-apply').waitFor({state: 'visible'});
    await page.locator('#maintenance-cleanup-apply').click();
    await page.locator('#dialog-yes').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-cleanup-preview').disabled);
    assert(requests.some(item => item.endpoint === '/api/maintenance/cleanup/apply' && item.body.token === 'fixture-cleanup'));
    slowMaintenance = true;
    await page.evaluate(() => toast('旧错误提示', 'fixture offline', 'err'));
    failures.add('/api/maintenance/check');
    await page.locator('#maintenance-check').click();
    await page.waitForFunction(() => document.querySelector('#maintenance-feedback').textContent.includes('fixture offline'));
    assert.match(await page.locator('#maintenance-feedback').textContent(), /fixture offline/);
    slowMaintenance = false;
    failures.clear();
    job = {phase: 'checking', detail: '重启中'};
    await page.evaluate(() => window.refreshMaintenance(true));
    failures.add('/api/maintenance');
    await page.evaluate(() => window.refreshMaintenance(true));
    assert.match(await page.locator('#maintenance-status').textContent(), /重新连接|重启/);
    assert.match(await page.locator('#maintenance-feedback').textContent(), /fixture offline/, 'reconnection status must not erase the operation failure');
    failures.clear(); job = {phase: 'complete', detail: '恢复连接'};
    await page.evaluate(() => window.refreshMaintenance(true));
    assert.match(await page.locator('#maintenance-detail').textContent(), /恢复连接/);
    await nav('voice');
    await page.getByText('回复决策与耗时', {exact: true}).click();
    await page.locator('#voice-decision-list').waitFor({state: 'visible'});
    assert.match(await page.locator('#voice-decision-list').textContent(), /概率/);
    const expectedDecisionTime = await page.evaluate(() => new Date('2026-10-07T08:30:45+00:00').toLocaleTimeString('zh-CN', {hour12: false}));
    assert((await page.locator('#voice-decision-list').textContent()).includes(expectedDecisionTime), 'production ISO timestamps must render the local time');
    await page.locator('#voice-tabs [data-tab="tools"]').click();
    await page.selectOption('#preview-kind', 'enter');
    await page.waitForFunction(() => document.querySelector('#preview-text').value === '保存的台词一');
    await page.selectOption('#preview-prompt', '1');
    await page.locator('#preview-run').click();
    await page.locator('#preview-audio').waitFor({state: 'visible'});
    await page.locator('#preview-stop').click();
    assert(await page.locator('#preview-audio').evaluate(audio => audio.paused));
    await page.locator('#diagnostic-audio').setInputFiles({name: 'sample.wav', mimeType: 'audio/wav', buffer: wav});
    await page.locator('#diagnostic-run').click();
    await page.locator('#diagnostic-results .check-row').waitFor();
    assert(requests.some(item => item.endpoint === '/api/voice/diagnostics' && item.body.audio_wav_base64 === wav.toString('base64')));
    const theme = page.locator('#screen-app [data-theme-toggle]').first();
    await theme.click();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'dark');
    await page.reload();
    await page.locator('#screen-app').waitFor({state: 'visible'});
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'dark');
    await page.setViewportSize({width: 390, height: 844});
    await nav('voice');
    await page.locator('#voice-tabs [data-tab="session"]').click();
    for (const selector of ['#voice-join', '#voice-stop', '#voice-leave']) {
      await page.locator(selector).click();
      await page.waitForFunction(selector => !document.querySelector(selector).disabled, selector);
    }
    await page.locator('#voice-tabs [data-tab="tools"]').click();
    await page.locator('#preview-run').click();
    await page.locator('#preview-audio').waitFor({state: 'visible'});
    await page.locator('#preview-stop').click();
    for (const name of ['voice', 'maintenance', 'config']) {
      await nav(name);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'mobile overflow on ' + name);
      if (process.env.OOPTRA_BROWSER_ARTIFACTS) {
        fs.mkdirSync(process.env.OOPTRA_BROWSER_ARTIFACTS, {recursive: true});
        await page.waitForFunction(() => !document.querySelector('#toasts').children.length);
        await page.screenshot({path: path.join(process.env.OOPTRA_BROWSER_ARTIFACTS, 'mobile-' + name + '.png'), fullPage: true});
      }
    }
    if (process.env.OOPTRA_BROWSER_ARTIFACTS) {
      await page.setViewportSize({width: 1440, height: 1000});
      for (const desired of ['light', 'dark']) {
        if (await page.evaluate(() => document.documentElement.dataset.theme) !== desired) await page.locator('#screen-app [data-theme-toggle]').first().click();
        for (const name of ['maintenance', 'config']) {
          await nav(name);
          await page.waitForFunction(() => !document.querySelector('#toasts').children.length);
          await page.screenshot({path: path.join(process.env.OOPTRA_BROWSER_ARTIFACTS, 'desktop-' + name + '-' + desired + '.png'), fullPage: true});
        }
      }
    }
    assert.deepEqual(errors, [], 'page scripts must load without errors');
    console.log('PASS webui browser acceptance: drafts, maintenance clicks/errors/reconnect, decisions, WAV diagnostics, preview, theme, mobile');
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
}
main().catch(error => {console.error(error); server.close(); process.exitCode = 1;});
