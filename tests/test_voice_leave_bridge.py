"""Execute the real player and feed its leave results through the Python SDK."""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from oopz_sdk.services.voice import Voice
from oopz_sdk.transport.voice_browser import BrowserVoiceTransport


@pytest.mark.parametrize("fail_first", [False, True])
def test_real_player_leave_results_complete_membership_cleanup(tmp_path, fail_first):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to execute the actual player")
    player = Path(__file__).resolve().parents[1] / "src/oopz_sdk/assets/voice/agora_player.html"
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*)<\/script>/)[1];
let failFirst = process.argv[3] === 'true';
const sandbox = {
  console: {log() {}, warn() {}, error() {}},
  setTimeout, clearTimeout, performance, Date, Map, Set,
  WebSocket: Object.assign(class {}, {CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3}),
  AgoraRTC: {createClient() {return {
    on() {}, async setClientRole() {}, remoteUsers: [],
    async join(app, room, token, uid) {return uid;},
    async leave() {
      if (failFirst) {failFirst = false; throw new Error('RTC leave rejected');}
    },
  };}},
};
sandbox.window = sandbox;
vm.runInNewContext(source, sandbox);
(async () => {
  const joined = await sandbox.agoraJoin('app', 'token', 'room', 123);
  if (!joined.ok) throw new Error(JSON.stringify(joined));
  const results = [];
  for (let i = 0; i < 2; i++) {
    const result = await sandbox.agoraLeave();
    results.push({result: result ?? null, state: sandbox.agoraGetStatus()});
  }
  process.stdout.write(JSON.stringify(results));
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    script_path = tmp_path / "voice_leave.cjs"
    script_path.write_text(script, encoding="utf-8")
    output = subprocess.run(
        [node, str(script_path), str(player), str(fail_first).lower()],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    assert output.returncode == 0, output.stderr
    attempts = json.loads(output.stdout)

    async def run():
        results = iter(attempts)
        transport = BrowserVoiceTransport.__new__(BrowserVoiceTransport)
        transport._started = True
        transport._oopz_uid = None
        transport._agora_uid = "123"
        transport._joined_uid = "123"
        transport._joined_room = "room"
        transport._voice_states = {"human": {"mic_muted": False}}

        async def browser(method):
            assert method == "agoraLeave"
            return next(results)["result"]

        transport._run_on_browser = browser
        membership_calls = []

        async def membership_leave(**kwargs):
            membership_calls.append(kwargs)
            return SimpleNamespace(ok=True)

        config = SimpleNamespace(person_uid="self")
        owner = SimpleNamespace(channels=SimpleNamespace(leave_voice_channel=membership_leave))
        voice = Voice(owner, config, None, None, None)
        voice.backend = transport
        voice._current_area, voice._current_channel = "a", "c"
        voice._current_sign, voice._current_uid = object(), "123"

        if fail_first:
            with pytest.raises(RuntimeError, match="RTC leave rejected"):
                await voice.leave()
            assert attempts[0]["state"]["hasClient"]
            assert not membership_calls
            assert voice._current_channel == "c" and transport._joined_room == "room"
        else:
            await voice.leave()
            assert attempts[0]["state"]["state"] == "idle"
        await voice.leave()  # Retry a failure, or idempotently leave the idle player.
        assert len(membership_calls) == 1
        assert membership_calls[0] == {"area": "a", "channel": "c", "target": "self"}
        assert attempts[1]["state"]["state"] == "idle"
        assert not attempts[1]["state"]["hasClient"]
        assert voice.current_sign is None and voice._current_area is None
        assert voice._current_channel is None and transport._joined_room is None
        assert not transport._voice_states

    asyncio.run(run())
