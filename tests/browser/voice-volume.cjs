/* Measure the production TTS signal with Web Audio; Agora publication is stubbed. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.OOPTRA_PLAYWRIGHT_MODULE || 'playwright');
const player = fs.readFileSync(path.resolve(__dirname, '../../src/oopz_sdk/assets/voice/agora_player.html'), 'utf8');

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.OOPTRA_BROWSER_EXECUTABLE || undefined});
  try {
    for (const volume of [undefined, 0, 25, 50, 100]) {
      const page = await browser.newPage();
      await page.setContent(player);
      const peak = await page.evaluate(async requested => {
        // OfflineAudioContext renders the same graph into inspectable samples.
        window.AudioContext = function({sampleRate}) {
          const ctx = new OfflineAudioContext(1, 6000, sampleRate);
          ctx.createMediaStreamDestination = () => {
            const dest = ctx.createGain();
            dest.stream = {getAudioTracks: () => [{}]};
            dest.connect(ctx.destination);
            return dest;
          };
          return ctx;
        };
        window.AgoraRTC = {createCustomAudioTrack: () => ({setVolume() {}, close() {}})};
        client = {publish: async () => {}, unpublish: async () => {}};
        // A 0.5-amplitude PCM signal is buffered before the live volume change.
        const pcm = new Int16Array(2400).fill(16384);
        const b64 = btoa(String.fromCharCode(...new Uint8Array(pcm.buffer)));
        const result = await window.agoraPushTtsPcm(b64, 24000, false);
        if (!result.ok) throw new Error(result.error);
        if (requested !== null) {
          const updated = window.agoraSetTtsVolume(requested);
          if (!updated.ok) throw new Error(updated.error);
        }
        const rendered = await ttsCtx.startRendering();
        return Math.max(...rendered.getChannelData(0));
      }, volume === undefined ? null : volume);
      const expected = 0.5 * (volume === undefined ? 50 : volume) / 100;
      assert(Math.abs(peak - expected) < 1e-6, `volume ${volume}: expected ${expected}, measured ${peak}`);
      await page.close();
    }

    const page = await browser.newPage();
    await page.setContent(player);
    const state = await page.evaluate(async () => {
      window.AgoraRTC = {createCustomAudioTrack: () => ({setVolume() {}, close() {}})};
      client = {publish: async () => {}, unpublish: async () => {}};
      const pending = window.agoraSetTtsVolume(25);
      await ensureTtsTrack(24000);
      const first = ttsGain.gain.value;
      await teardownTtsPipeline();
      await ensureTtsTrack(24000);
      const rejoined = ttsGain.gain.value;
      const invalid = window.agoraSetTtsVolume('bad');
      window.agoraSetVolume(80);
      return {pending: pending.ok, first, rejoined, invalid: invalid.ok, voice: ttsGain.gain.value, music: _currentVolume};
    });
    assert.deepEqual(state, {pending: true, first: 0.25, rejoined: 0.25, invalid: false, voice: 0.25, music: 80});
    console.log('Voice volume: measured default 50%, mute, 25/50/100%, buffered audio, rejoin and independent music volume passed.');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
