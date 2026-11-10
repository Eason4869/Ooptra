"""Run the probe beside an Ooptra 4.0.0 checkout with its own configured bot."""

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path

from probe import Capture, Identity, LiveProbe, emit

# Install before joining so that the first identity broadcast is observable.
# Existing SDK functions remain in charge of subscribing, decoding and playing audio.
BROWSER_HOOK = """() => {
  const original = ensureVoiceStateHook;
  ensureVoiceStateHook = function () {
    original();
    client.on('stream-message', (sender, payload) => {
      const state = decodeStreamMessage(payload);
      if (state?.uid && state.cid != null && (state.m != null || state.hm != null)) {
        window.uidProbeIdentity(String(sender), String(state.cid), String(state.uid));
      }
    });
    client.on('user-unpublished', (user, kind) => {
      if (kind === 'audio') window.uidProbeTrackEnd(String(user.uid));
    });
    client.on('user-left', user => window.uidProbeTrackEnd(String(user.uid)));
  };
  selectSpeaker = () => true;
}"""


async def attach_browser(transport, identity_callback, track_end_callback):
    await transport.start()

    async def install():
        page = transport._page
        await page.expose_function("uidProbeIdentity", identity_callback)
        await page.expose_function("uidProbeTrackEnd", track_end_callback)
        await page.evaluate(BROWSER_HOOK)

    future = asyncio.run_coroutine_threadsafe(install(), transport._thread_loop)
    await asyncio.wrap_future(future)


async def run(args):
    root = args.checkout.resolve()
    sys.path[:0] = [str(root), str(root / "src")]
    os.chdir(root)

    from bridge.runtime import apply_runtime_overrides
    from oopz.proxy_transport import install_proxy_transports
    from oopz.sdk_config import build_sdk_config
    from oopz_sdk import OopzBot
    from voice_agent.backends.gemini_live import build_live_url, live_url_has_key
    from voice_agent.settings import load_voice_agent_settings, resolve_agent_proxy_url
    from voice_agent.ws_transport import open_live_ws
    from webui.voice_routes import _channel_member_map, _field

    apply_runtime_overrides()
    settings, _ = load_voice_agent_settings()
    url = build_live_url(settings.gemini_base_url, settings.gemini_api_key)
    if not live_url_has_key(url):
        raise SystemExit("Gemini Live key is missing in the deployment settings")
    if args.member_a == args.member_b:
        raise SystemExit("The two test members must have distinct Oopz UIDs")
    known = {args.member_a: "A", args.member_b: "B"}
    identity = Identity()
    loop = asyncio.get_running_loop()
    config, proxy, _ = await build_sdk_config()
    config.onebot_v11 = None
    bot_ready = asyncio.Event()

    async def on_ready(_context):
        bot_ready.set()

    bot = OopzBot(config, on_ready=on_ready)
    install_proxy_transports(bot, proxy)
    transport = bot.voice.backend
    ws = None
    joined = False
    tasks = []
    last_map = None

    def report_mapping():
        nonlocal last_map
        mapping = {rtc: identity.resolve(rtc) for rtc in sorted(identity.claims)}
        if mapping != last_map:
            emit("mapping", tracks=[{"rtc": rtc, "member": uid, "label": known.get(uid, "")}
                                    for rtc, uid in mapping.items()])
            last_map = mapping

    def observe(sender, cid, member):
        if member in known:
            emit("identity_broadcast", sender=sender, cid=cid, member=member,
                 sender_matches=sender == cid)
        identity.observe(sender, cid, member)
        report_mapping()

    async def poll_members():
        while True:
            raw = await bot.channels.get_voice_channel_members(area=args.area)
            rows = _channel_member_map(raw).get(args.channel, [])
            identity.members = {str(_field(row, "uid", "person_uid", "user_id", default="") or "")
                                for row in rows} & known.keys()
            report_mapping()
            await asyncio.sleep(3)

    try:
        # Fail before entering the room if the configured model rejects manual VAD.
        ws = await open_live_ws(url, proxy=resolve_agent_proxy_url(settings.proxy))
        probe = LiveProbe(ws, transport, identity, [args.keyword], settle=args.settle,
                          show_text=args.show_text)
        tasks.append(asyncio.create_task(probe.read()))
        emit("live_setup", model=settings.gemini_model, manual_vad=True, connections=1)
        await probe.send({"setup": {
            "model": f"models/{settings.gemini_model.removeprefix('models/')}",
            "generation_config": {"response_modalities": ["AUDIO"]},
            "system_instruction": {"parts": [{"text": "用普通话回答测试房的问题，按问题要求控制回答长度。"}]},
            "input_audio_transcription": {},
            "realtime_input_config": {"automatic_activity_detection": {"disabled": True},
                                      "activity_handling": "NO_INTERRUPTION"},
        }})
        ready = asyncio.create_task(probe.ready.wait())
        tasks.append(ready)
        done, _ = await asyncio.wait({tasks[0], ready}, timeout=15, return_when=asyncio.FIRST_COMPLETED)
        if tasks[0] in done:
            tasks[0].result()
        if ready not in done:
            raise TimeoutError("Gemini did not acknowledge the manual VAD setup")

        gateway = asyncio.create_task(bot.start())
        tasks.append(gateway)
        gateway_ready = asyncio.create_task(bot_ready.wait())
        tasks.append(gateway_ready)
        done, _ = await asyncio.wait({gateway, gateway_ready}, timeout=30,
                                     return_when=asyncio.FIRST_COMPLETED)
        if gateway in done:
            gateway.result()
        await asyncio.wait_for(asyncio.shield(gateway_ready), timeout=10)
        capture = Capture(identity, probe.offer, probe.barge,
                          args.hold_ms if settings.barge_in else None, lambda: probe.playing)

        async def finish_idle_tracks():
            while True:
                await asyncio.sleep(0.05)
                capture.tick()

        await attach_browser(transport,
                             lambda *claim: loop.call_soon_threadsafe(observe, *claim),
                             lambda uid: loop.call_soon_threadsafe(capture.finish, uid))
        await bot.voice.join(area=args.area, channel=args.channel)
        joined = True
        tasks.append(asyncio.create_task(poll_members()))
        tasks.append(asyncio.create_task(probe.run()))
        tasks.append(asyncio.create_task(finish_idle_tracks()))
        transport.set_remote_pcm_callback(
            lambda uid, pcm, rate: loop.call_soon_threadsafe(capture.frame, uid, pcm, rate))
        listening = await transport.enable_listen(True)
        if not listening.get("ok"):
            raise RuntimeError("Could not enable the Agora track observer")
        emit("room_ready", area=args.area, channel=args.channel, keyword=args.keyword,
             barge_in=settings.barge_in, hold_ms=args.hold_ms)
        watched = {tasks[0], *tasks[-3:]}
        if not gateway.done():
            watched.add(gateway)
        done, _ = await asyncio.wait(watched, timeout=args.seconds,
                                     return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        emit("room_done", turns=probe.turn, connections=1)
    finally:
        transport.set_remote_pcm_callback(None)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if joined:
            with contextlib.suppress(Exception):
                await bot.voice.leave()
        with contextlib.suppress(Exception):
            await bot.stop()
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    for name in ("area", "channel", "member-a", "member-b"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--keyword", default="小欧")
    parser.add_argument("--hold-ms", type=int, default=300)
    parser.add_argument("--settle", type=float, default=0.8)
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--show-text", action="store_true")
    args = parser.parse_args()
    if args.hold_ms < 0 or args.settle < 0 or args.seconds <= 0:
        parser.error("invalid time limits")
    if not (args.checkout / "src" / "voice_agent" / "backends" / "gemini_live.py").is_file():
        parser.error("--checkout must point to an Ooptra 4.0.0 checkout")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        emit("stopped")
    except Exception as exc:
        # Model handshake exceptions can include the authenticated URL.
        emit("probe_failed", kind=type(exc).__name__, close_code=getattr(exc, "code", None))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
