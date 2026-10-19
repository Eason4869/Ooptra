/* Responsive, keyboard and error feedback acceptance against the offline demo. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.OOPTRA_PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '../..');
const artifacts = process.env.OOPTRA_BROWSER_ARTIFACTS;
const baseline = process.env.OOPTRA_UI_BASELINE === '1';
let html = fs.readFileSync(path.join(root, 'webui_preview.html'), 'utf8');
// Optional local source overlay leaves the generated preview untouched during review.
if (process.env.OOPTRA_UI_SOURCES === '1') {
  html = html.replace(/<style>\n[\s\S]*?\n<\/style>/, () => '<style>\n' + fs.readFileSync(path.join(root, 'src/webui/assets/style.css'), 'utf8') + '\n</style>');
  for (const name of ['app.js', 'config.js']) {
    const source = fs.readFileSync(path.join(root, 'src/webui/assets', name), 'utf8').replaceAll('oopz.webui.', 'ooptra.preview.');
    const start = html.indexOf('<script>\n' + source.split(/\r?\n/)[0]);
    assert(start >= 0, 'Cannot locate inline ' + name);
    const end = html.indexOf('\n</script>', start);
    html = html.slice(0, start) + '<script>\n' + source.replaceAll('</script', '<\\/script') + html.slice(end);
  }
}
const server = http.createServer((req, res) => {res.setHeader('Content-Type', 'text/html'); res.end(html);});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true, executablePath: process.env.OOPTRA_BROWSER_EXECUTABLE || undefined});
  const report = {layouts: [], findings: [], errors: [], remote: []};
  if (artifacts) fs.mkdirSync(artifacts, {recursive: true});
  try {
    const page = await browser.newPage();
    page.on('pageerror', error => report.errors.push(error.message));
    page.on('request', request => {if (/^https?:/.test(request.url()) && !request.url().startsWith('http://127.0.0.1:')) report.remote.push(request.url());});
    const origin = 'http://127.0.0.1:' + server.address().port;
    await page.goto(origin + '/voice');
    await page.locator('#login-token').fill('demo');
    await page.locator('#login-form').evaluate(form => form.requestSubmit());
    await page.locator('#screen-login').waitFor({state: 'hidden'});
    await page.evaluate(() => stopPolling());
    if (!baseline) {
      await page.locator('#page-voice').waitFor({state: 'visible'});
      await page.locator('.nav-item[data-page="config"]').click();
      assert.equal(new URL(page.url()).pathname, '/config');
      await page.goBack(); await page.locator('#page-voice').waitFor({state: 'visible'});
      await page.goForward(); await page.locator('#page-config').waitFor({state: 'visible'});
      await page.reload();
      await page.locator('#screen-login').waitFor({state: 'visible'});
      await page.locator('#login-token').fill('demo');
      await page.locator('#login-form').evaluate(form => form.requestSubmit());
      await page.locator('#page-config').waitFor({state: 'visible'});
      await page.evaluate(() => stopPolling());
      await page.waitForFunction(() => document.querySelectorAll('.cfg-field').length > 0);
      await page.locator('[data-group="oopz"][data-field="default_area"] input').fill('audit-draft');
      await page.goBack();
      await page.locator('#dialog').waitFor({state: 'visible'});
      await page.keyboard.press('Escape');
      await page.waitForFunction(() => location.pathname === '/config');
      await page.locator('#page-config').waitFor({state: 'visible'});
      await page.goBack(); await page.locator('#dialog-yes').click();
      await page.locator('#page-voice').waitFor({state: 'visible'});
      await page.goForward(); await page.locator('#page-config').waitFor({state: 'visible'});
      assert.equal(await page.locator('[data-group="oopz"][data-field="default_area"] input').inputValue(), 'audit-draft');
      await page.evaluate(() => {dirty = {}; renderConfig(); updateSavebar();});
    }
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({width, height: 900});
      for (const theme of ['light', 'dark']) {
        if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('[data-theme-toggle]:visible').click();
        for (const name of ['overview', 'logs', 'voice', 'config', 'account', 'maintenance']) {
          await page.locator('.nav-item[data-page="' + name + '"]').click();
          await page.locator('#page-' + name).waitFor({state: 'visible'});
          if (name === 'config') await page.waitForFunction(() => document.querySelectorAll('.cfg-group').length > 0);
          if (name === 'voice') await page.waitForFunction(() => document.querySelectorAll('.channel-card').length > 0);
          const views = name === 'voice' ? ['session', 'auto-visit', 'members', 'persona', 'tools'] : name === 'config' ? ['connection', 'voice', 'system', 'connection-advanced', 'voice-advanced', 'system-advanced'] : name === 'maintenance' ? ['', 'advanced'] : [''];
          for (const tab of views) {
            if (name === 'maintenance') await page.locator('.maintenance-advanced').evaluate((el, open) => {el.open = open;}, tab === 'advanced');
            if (name === 'config') {
              const advanced = tab.endsWith('-advanced');
              if (await page.evaluate(() => showAdvanced) !== advanced) await page.locator('#tool-adv').click();
            }
            if (tab && name !== 'maintenance') {
              const selection = name === 'config' ? tab.replace('-advanced', '') : tab;
              await page.locator('#' + (name === 'voice' ? 'voice-tabs' : 'config-tabs') + ' [data-tab="' + selection + '"]').click();
              await page.waitForTimeout(80);
            }
            if (!baseline && name === 'voice' && tab === 'session') {
              assert(await page.locator('.voice-output-card').isVisible(), 'Microphone and volume controls must appear in the session');
              assert(await page.locator('#voice-output-volume').isVisible());
            }
            const layout = await page.evaluate(() => ({width: window.innerWidth, scroll: document.documentElement.scrollWidth, overflowing: [...document.querySelectorAll('.page.is-active *')].filter(el => {const rect = el.getBoundingClientRect(); return rect.width && rect.right > window.innerWidth + 1 && getComputedStyle(el).position !== 'fixed';}).slice(0, 10).map(el => ({tag: el.tagName, id: el.id, cls: el.className}))}));
            report.layouts.push({name, tab, theme, ...layout});
            if (layout.scroll > width) report.findings.push({name, tab, theme, width, overflow: layout.scroll - width, elements: layout.overflowing});
            if (artifacts) await page.screenshot({path: path.join(artifacts, `${width}-${theme}-${name}${tab ? '-' + tab : ''}.png`), fullPage: true, animations: 'disabled'});
          }
        }
      }
    }
    await page.setViewportSize({width: 390, height: 844});
    await page.locator('.nav-item[data-page="overview"]').click();
    const originalFetch = await page.evaluate(() => {window.auditFetch = window.fetch; return true;});
    assert(originalFetch);
    await page.evaluate(() => {window.fetch = async () => new Response(JSON.stringify({error: '审查：连接中断'}), {status: 503});});
    await page.locator('#tool-refresh').click();
    await page.waitForTimeout(100);
    const failedRefresh = await page.locator('#toasts').textContent();
    report.findings.push({case: 'failedRefreshFeedback', text: failedRefresh});
    if (!baseline) {assert(!failedRefresh.includes('已刷新')); assert.match(failedRefresh, /刷新失败/);}
    if (!baseline) {
      await page.evaluate(() => {window.fetch = async (...args) => {await new Promise(resolve => setTimeout(resolve, 400)); return window.auditFetch(...args);};});
      await page.locator('#tool-refresh').click();
      assert(await page.locator('#tool-refresh').isDisabled());
      assert.equal(await page.locator('#tool-refresh').getAttribute('aria-busy'), 'true');
      await page.waitForFunction(() => !document.querySelector('#tool-refresh').disabled);
    }
    await page.evaluate(() => {window.fetch = window.auditFetch; document.querySelector('#toasts').replaceChildren(); for (let i = 0; i < 8; i++) toast('审查通知 ' + i, '长地址：' + 'very-long-host.example/'.repeat(12), 'err');});
    const toastState = await page.evaluate(() => ({count: document.querySelectorAll('.toast').length, scroll: document.documentElement.scrollWidth, bottom: document.querySelector('#toasts').getBoundingClientRect().bottom, newestBottom: document.querySelector('.toast:last-child').getBoundingClientRect().bottom}));
    report.findings.push({case: 'toastBurst', ...toastState});
    if (artifacts) await page.screenshot({path: path.join(artifacts, 'toast-burst.png'), fullPage: true, animations: 'disabled'});
    if (!baseline) {assert(toastState.count <= 3); assert(toastState.scroll <= 390); assert(toastState.bottom <= 844); assert(toastState.newestBottom <= toastState.bottom + 1); await page.locator('.toast-close').first().click(); assert.equal(await page.locator('.toast').count(), 2);}
    await page.evaluate(() => document.querySelector('#toasts').replaceChildren());
    if (!baseline) {
      await page.locator('.nav-item[data-page="config"]').click();
      await page.waitForFunction(() => document.querySelectorAll('.cfg-field').length > 0);
      await page.evaluate(() => {window.fetch = async () => new Response(JSON.stringify({error: '审查：配置中断'}), {status: 503});});
      await page.locator('#tool-reload').click();
      await page.waitForFunction(() => !document.querySelector('#tool-reload').disabled);
      const feedback = await page.locator('#toasts').textContent();
      assert.match(feedback, /配置读取失败/); assert(!feedback.includes('已重新读取'));
      await page.evaluate(() => {window.fetch = window.auditFetch; document.querySelector('#toasts').replaceChildren();});
      await page.setViewportSize({width: 1440, height: 900});
      await page.locator('#tool-reload').click();
      await page.waitForFunction(() => !document.querySelector('#tool-reload').disabled);
      await page.locator('#tool-reload').click({timeout: 2000});
      await page.waitForFunction(() => !document.querySelector('#tool-reload').disabled);
      await page.locator('#config-tabs [data-tab="connection"]').click();
      await page.locator('[data-group="oopz"][data-field="default_area"] input').fill('toast-draft');
      await page.locator('#savebar').scrollIntoViewIfNeeded();
      await page.evaluate(() => toast('保存条审查', '提示应避让可见的保存条', 'warn'));
      assert(await page.evaluate(() => document.querySelector('#toasts').getBoundingClientRect().bottom <= document.querySelector('#savebar').getBoundingClientRect().top - 10));
      await page.evaluate(() => {dirty = {}; renderConfig(); updateSavebar(); document.querySelector('#toasts').replaceChildren();});
      await page.locator('#config-tabs [data-tab="voice"]').click();
      assert.equal(await page.evaluate(() => document.activeElement.dataset.tab), 'voice');
      assert.equal(await page.locator('#config-tabs [data-tab="voice"]').getAttribute('aria-pressed'), 'true');
      const volumeField = page.locator('[data-field="output_volume"] input');
      await volumeField.focus();
      const fieldFocus = await volumeField.evaluate(el => ({outlineStyle: getComputedStyle(el).outlineStyle, outlineWidth: parseFloat(getComputedStyle(el).outlineWidth)}));
      assert.equal(fieldFocus.outlineStyle, 'solid'); assert(fieldFocus.outlineWidth >= 2);
      await page.evaluate(() => {window.fetch = (input, options = {}) => String(input) === '/api/config' && options.method === 'POST' ? Promise.resolve(new Response(JSON.stringify({changed: {voice: ['output_volume']}, notes: ['语音配置应用失败：审查fixture'], hot_reload_failed: true}), {status: 200})) : window.auditFetch(input, options);});
      await page.locator('[data-field="output_volume"] input').fill('61');
      await page.locator('#config-save').click();
      await page.waitForFunction(() => !document.querySelector('#config-save').disabled);
      const applyWarning = await page.locator('#toasts').textContent();
      assert.match(applyWarning, /配置已保存，部分未生效/); assert(!applyWarning.includes('已保存并热生效'));
      assert.equal(await page.locator('.toast.warn').count(), 1);
      await page.evaluate(() => {window.fetch = window.auditFetch; document.querySelector('#toasts').replaceChildren();});
      await page.locator('.nav-item[data-page="voice"]').click();
      await page.locator('#voice-tabs [data-tab="session"]').click();
      await page.evaluate(() => {document.querySelector('.ch-name').textContent = 'VeryLongVoiceChannel'.repeat(14); document.querySelector('.chip-tab').textContent = 'VeryLongAreaName'.repeat(14);});
      for (const width of [390, 320]) {
        await page.setViewportSize({width, height: 844});
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Long room and area names must fit mobile');
        if (artifacts) await page.screenshot({path: path.join(artifacts, width + '-long-room-name.png'), fullPage: true, animations: 'disabled'});
      }
      await page.locator('.nav-item[data-page="logs"]').click();
      await page.evaluate(() => {stopLogStream(); const view = document.querySelector('#log-view'); view.replaceChildren(logNode('2026-10-11 12:00:00 [Voice] INFO: 手机日志正文应该使用整行宽度，保证排查问题时可读。'), logNode('普通未解析日志正文也应使用整行宽度。'));});
      const logWidths = await page.locator('.ln-body').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().width));
      assert(logWidths.every(width => width >= 250), '320px mobile log bodies must use the available line width');
      if (artifacts) await page.screenshot({path: path.join(artifacts, '320-structured-and-plain-logs.png'), fullPage: true, animations: 'disabled'});
      await page.locator('.nav-item[data-page="overview"]').click();
    }
    await page.locator('#tool-refresh').focus();
    await page.evaluate(() => {window.auditDialog = confirmDialog('键盘确认', '按 Esc 取消，Tab 应留在对话框内');});
    const modal = await page.evaluate(() => ({focused: document.activeElement.id, role: document.querySelector('#dialog .dialog').getAttribute('role'), modal: document.querySelector('#dialog .dialog').getAttribute('aria-modal')}));
    report.findings.push({case: 'dialogKeyboard', ...modal});
    if (!baseline) {
      assert.equal(modal.focused, 'dialog-no'); assert.equal(modal.role, 'dialog'); assert.equal(modal.modal, 'true');
      await page.keyboard.press('Shift+Tab'); assert.equal(await page.evaluate(() => document.activeElement.id), 'dialog-yes');
      await page.keyboard.press('Tab'); assert.equal(await page.evaluate(() => document.activeElement.id), 'dialog-no');
      await page.keyboard.press('Escape'); assert.equal(await page.evaluate(() => window.auditDialog), false);
      assert.equal(await page.evaluate(() => document.activeElement.id), 'tool-refresh');
      await page.evaluate(async () => {
        window.auditDialog = confirmDialog('会话过期审查', '会话失效时应关闭弹窗并恢复登录框可用状态');
        window.fetch = async () => new Response('{}', {status: 401});
        await refreshStatus();
        window.fetch = window.auditFetch;
      });
      assert.equal(await page.evaluate(() => window.auditDialog), false);
      assert(await page.locator('#dialog').isHidden());
      assert(await page.locator('#screen-login').isVisible());
      assert.equal(await page.locator('#screen-login').evaluate(el => el.inert), false);
      await page.locator('#login-token').fill('demo');
      await page.locator('#login-form').evaluate(form => form.requestSubmit());
      await page.locator('#screen-login').waitFor({state: 'hidden'});
    } else await page.locator('#dialog-no').click();
    if (!baseline) {
      const offlineDirectory = artifacts || path.join(root, '.venv/ui-audit');
      fs.mkdirSync(offlineDirectory, {recursive: true});
      const offlinePath = path.join(offlineDirectory, 'offline-test.html');
      fs.writeFileSync(offlinePath, html);
      const offline = await browser.newPage();
      offline.on('pageerror', error => report.errors.push(error.message));
      await offline.goto(pathToFileURL(offlinePath).href + '#/voice');
      await offline.locator('#login-token').fill('demo');
      await offline.locator('#login-form').evaluate(form => form.requestSubmit());
      await offline.locator('#page-voice').waitFor({state: 'visible'});
      await offline.locator('.nav-item[data-page="config"]').click();
      assert.equal(new URL(offline.url()).hash, '#/config');
      await offline.goBack(); await offline.locator('#page-voice').waitFor({state: 'visible'});
      await offline.goForward(); await offline.locator('#page-config').waitFor({state: 'visible'});
      await offline.reload();
      await offline.locator('#login-token').fill('demo');
      await offline.locator('#login-form').evaluate(form => form.requestSubmit());
      await offline.locator('#page-config').waitFor({state: 'visible'});
      await offline.close();
      assert.deepEqual(report.findings.filter(item => item.overflow), []); assert.deepEqual(report.errors, []); assert.deepEqual(report.remote, []);
    }
    if (artifacts) fs.writeFileSync(path.join(artifacts, 'audit.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({layouts: report.layouts.length, findings: report.findings, errors: report.errors, remote: report.remote}, null, 2));
  } finally {await browser.close(); await new Promise(resolve => server.close(resolve));}
})().catch(error => {console.error(error); server.close(); process.exitCode = 1;});
