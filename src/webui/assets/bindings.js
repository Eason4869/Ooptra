/* Mount the same UMO session manager used by the AstrBot workbench. */
'use strict';
let voiceSessionManager = null;
let sessionLoadVersion = 0;
async function loadBindings() {
  const root = $('session-manager'), version = ++sessionLoadVersion;
  if (!root) return;
  try {
    const [data, areas] = await Promise.all([api('/api/voice/astrbot/bindings'), api('/api/oopz/areas')]);
    if (version !== sessionLoadVersion) return;
    if (!data.source_management) throw new Error('请先更新 astrbot_plugin_ooptra dev，当前插件不支持完整 UMO 与多会话记忆。');
    if (!voiceSessionManager) voiceSessionManager = window.OoptraSessionManager.mount(root, {
      rpc: body => api('/api/voice/astrbot/bindings', {method: 'POST', body}),
      channels: area => api('/api/oopz/channels?area=' + encodeURIComponent(area)),
    });
    voiceSessionManager.update(data, areas.areas || []);
    await voiceSessionManager.loadChannels();
  } catch (error) {
    if (version !== sessionLoadVersion) return;
    voiceSessionManager = null; root.textContent = error.message;
  }
}
