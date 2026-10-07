/* Real browser updater interactions against isolated local HTTP fixtures. */
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.OOPTRA_PLAYWRIGHT_MODULE || 'playwright');

const assets = path.resolve(__dirname, '../../src/webui/assets');
const requests = [];
let failed = false, slow = false, job = null;
let checked = null;
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
  if (req.method === 'POST') requests.push({endpoint, body});
  res.setHeader('Content-Type', 'application/json');
  if (slow && endpoint.startsWith('/api/maintenance')) await new Promise(resolve => setTimeout(resolve, 350));
  if (failed && endpoint.startsWith('/api/maintenance')) {
    res.statusCode = 503; return res.end(JSON.stringify({error: 'fixture offline'}));
  }
  let data = {ok: true};
  if (endpoint === '/api/status') data = {process: {version: '3.1.0'}, bridge: {runtime: {running: true, supervisor_alive: true}, oopz: {connected: true}, onebot: {connected: false}, traffic: {}, recent_events: [], recent_actions: []}};
  if (endpoint === '/api/credentials') data = {credentials: {has_password: true, has_private_key: true}};
  if (endpoint === '/api/maintenance/check') {
    checked = {channel: body.channel, current_channel: 'beta', current_sha: 'a'.repeat(40), target_sha: 'b'.repeat(40), available: true, compatible: true, action: body.channel === 'beta' ? 'update' : 'switch', requires_confirmation: body.channel !== 'beta'};
    data = checked;
  }
  if (endpoint === '/api/maintenance') data = {preflight: {supported: true, checks: []}, restore_supported: true, current_channel: 'beta', health: {checks: [{id: 'process', title: '本地进程', state: 'pass', detail: '本地启动就绪'}, {id: 'onebot', title: 'OneBot', state: 'degraded', detail: '桥接降级'}]}, update: {channel: 'beta', current_channel: 'beta', current_sha: 'a'.repeat(40), version: '3.1.0'}, check: checked, job, backups: [{id: 'a'.repeat(32), created_at: 1, size: 524}], backup_page: {page: Number(url.searchParams.get('page') || 1), pages: 2, total: 11}, storage: {total_bytes: 524, backups_count: 11}};
  if (endpoint === '/api/maintenance/cleanup/preview') data = {token: 'fixture-cleanup', items: [{kind: 'environment', path: 'old-env', size: 524}], total_bytes: 524};
  res.end(JSON.stringify(data));
});

async function main() {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true, ...(process.env.OOPTRA_BROWSER_EXECUTABLE ? {executablePath: process.env.OOPTRA_BROWSER_EXECUTABLE} : {})});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  page.setDefaultTimeout(5000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto('http://127.0.0.1:' + server.address().port);
    await page.locator('#screen-app').waitFor({state: 'visible'});
    await page.locator('[data-page="maintenance"]').first().click();
    await page.waitForFunction(() => document.querySelector('#maintenance-channel').value === 'beta');
    assert.deepEqual(await page.locator('#maintenance-channel option').evaluateAll(rows => rows.map(row => row.value)), ['main', 'beta', 'dev']);
    await page.selectOption('#maintenance-channel', 'main');
    await page.evaluate(() => window.refreshMaintenance(true));
    assert.equal(await page.locator('#maintenance-channel').inputValue(), 'main');
    assert(await page.locator('#maintenance-update').isDisabled(), 'new source requires fresh check');
    await page.locator('#maintenance-check').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-update').disabled);
    await page.locator('#maintenance-update').click();
    await page.locator('#dialog').waitFor({state: 'visible'});
    assert.match(await page.locator('#dialog').textContent(), /正式版/);
    assert.match(await page.locator('#dialog').textContent(), /降级/);
    await page.locator('#dialog-no').click();
    assert(!requests.some(row => row.endpoint === '/api/maintenance/update'));
    await page.locator('#maintenance-update').click();
    await page.locator('#dialog-yes').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-check').disabled);
    assert(requests.some(row => row.endpoint === '/api/maintenance/update' && row.body.channel === 'main' && row.body.confirm_channel_switch === true));
    slow = true;
    await page.locator('#maintenance-backup').click();
    assert(await page.locator('#maintenance-backup').isDisabled());
    assert.match(await page.locator('#maintenance-feedback').textContent(), /正在/);
    await page.waitForFunction(() => !document.querySelector('#maintenance-backup').disabled);
    assert(requests.some(row => row.endpoint === '/api/maintenance/backups'));
    failed = true;
    await page.locator('#maintenance-check').click();
    await page.waitForFunction(() => document.querySelector('#maintenance-feedback').textContent.includes('fixture offline'));
    await page.waitForFunction(() => !document.querySelector('#maintenance-check').disabled);
    assert.match(await page.locator('#maintenance-feedback').textContent(), /fixture offline/);
    failed = false; slow = false;
    job = {phase: 'checking', detail: '服务重启中'};
    await page.evaluate(() => window.refreshMaintenance(true));
    failed = true;
    await page.evaluate(() => window.refreshMaintenance(true));
    assert.match(await page.locator('#maintenance-feedback').textContent(), /重新连接|重启/);
    failed = false; job = {phase: 'complete', detail: '服务重新就绪'};
    await page.evaluate(() => window.refreshMaintenance(true));
    assert.match(await page.locator('#maintenance-detail').textContent(), /重新就绪/);
    await page.locator('#maintenance-next').click();
    await page.waitForFunction(() => document.querySelector('#maintenance-pagination').textContent.includes('第 2'));
    await page.locator('#maintenance-prev').click();
    await page.waitForFunction(() => document.querySelector('#maintenance-pagination').textContent.includes('第 1'));
    await page.locator('.rail-utilities > summary').click();
    await page.locator('#btn-check-update').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-check').disabled);
    assert.equal(requests.filter(row => row.endpoint === '/api/maintenance/check').at(-1).body.channel, 'main');
    await page.locator('.rail-utilities > summary').click();
    await page.getByText('存储与清理', {exact: true}).click();
    await page.locator('#maintenance-cleanup-preview').click();
    await page.locator('#maintenance-cleanup-apply').waitFor({state: 'visible'});
    await page.locator('#maintenance-cleanup-apply').click();
    await page.locator('#dialog-yes').click();
    await page.waitForFunction(() => !document.querySelector('#maintenance-cleanup-preview').disabled);
    assert(requests.some(row => row.endpoint === '/api/maintenance/cleanup/apply' && row.body.token === 'fixture-cleanup'));
    await page.setViewportSize({width: 390, height: 844});
    const overflow = await page.evaluate(() => [...document.querySelectorAll('*')].filter(node => node.getBoundingClientRect().right > innerWidth + 1).map(node => [node.id || node.className, node.getBoundingClientRect().right]).slice(0, 15));
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, JSON.stringify(overflow));
    // Reproduce a maintenance response covering the mobile header until it expires.
    await page.evaluate(() => {
      document.querySelector('#toasts').replaceChildren();
      toast('维护操作反馈', 'fixture offline '.repeat(20), 'err');
      toast('维护操作反馈', 'fixture offline '.repeat(20), 'err');
    });
    // Error feedback lasts six seconds; wait for its DOM removal before testing the header.
    await page.waitForFunction(() => !document.querySelector('#toasts').children.length, undefined, {timeout: 10000});
    await page.locator('#screen-app [data-theme-toggle]').first().click();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'dark');
    assert.deepEqual(errors, []);
    console.log('PASS maintenance browser: channels, confirmation, backup, failure, reconnect, pagination, shortcut, cleanup, mobile, theme');
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => {console.error(error); server.close(); process.exitCode = 1;});
