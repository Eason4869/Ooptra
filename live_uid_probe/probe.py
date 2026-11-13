"""Disposable one-room Live probe. This module has no third-party dependencies."""

import asyncio
import base64
import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass, field


def normalize(text):
    return re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", text).casefold())


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def field_value(data, camel, snake):
    return data.get(camel) or data.get(snake)


class Identity:
    def __init__(self):
        self.members = set()
        self.claims = {}

    def observe(self, sender, cid, member):
        if sender and sender == cid and member:
            self.claims.setdefault(sender, set()).add(member)

    def resolve(self, sender):
        claims = self.claims.get(sender, set())
        if len(claims) != 1:
            return ""
        member = next(iter(claims))
        if member not in self.members:
            return ""
        if any(member in others for uid, others in self.claims.items() if uid != sender):
            return ""
        return member


@dataclass
class Speech:
    rtc: str
    member: str
    frames: list = field(default_factory=list)
    length: float = 0
    silence: float = 0
    last_frame_at: float = 0


class Capture:
    """Choose one track at onset and buffer one bounded utterance at a time."""

    def __init__(self, identity, offer, barge, hold_ms, is_playing, silence_ms=650):
        self.identity = identity
        self.offer = offer
        self.barge = barge
        self.hold_ms = hold_ms
        self.is_playing = is_playing
        self.silence_ms = silence_ms
        self.speech = None
        self.candidates = {}

    def frame(self, uid, pcm, rate, now=None):
        if rate != 16000 or not pcm or len(pcm) % 2:
            return
        now = time.monotonic() if now is None else now
        samples = memoryview(pcm).cast("h")
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
        duration = len(samples) / 16
        loud = rms >= 0.02
        if self.speech is None:
            if not loud:
                self.candidates.pop(uid, None)
                return
            playing = self.is_playing()
            if playing and self.hold_ms is None:
                self.candidates.clear()
                return
            last, frames, total = self.candidates.get(uid, (now, [], 0))
            if now - last > 0.4:
                frames, total = [], 0
            frames.append(pcm)
            total += duration
            threshold = max(1, self.hold_ms or 0) if playing else 1
            if total < threshold:
                self.candidates[uid] = (now, frames, total)
                return
            self.candidates.clear()
            self.speech = Speech(uid, self.identity.resolve(uid), frames, total, last_frame_at=now)
            if playing:
                self.barge(uid)
            return

        speech = self.speech
        if uid != speech.rtc:
            return
        speech.last_frame_at = now
        speech.frames.append(pcm)
        speech.length += duration
        speech.silence = 0 if loud else speech.silence + duration
        if speech.silence >= self.silence_ms or speech.length >= 12000:
            self.finish(uid)

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        if self.speech is not None and now - self.speech.last_frame_at >= self.silence_ms / 1000:
            self.finish(self.speech.rtc)

    def finish(self, uid):
        self.candidates.pop(uid, None)
        if self.speech is not None and self.speech.rtc == uid:
            speech, self.speech = self.speech, None
            self.offer(speech)


class LiveProbe:
    def __init__(self, ws, transport, identity, keywords, *, settle=0.8, report=emit, show_text=False):
        self.ws = ws
        self.transport = transport
        self.identity = identity
        self.keywords = [normalize(word) for word in keywords if normalize(word)]
        self.settle = settle
        self.report = report
        self.show_text = show_text
        self.pending = asyncio.Queue(maxsize=1)
        self.ready = asyncio.Event()
        self.changed = asyncio.Event()
        self.interrupt = asyncio.Event()
        self.windows = {}
        self.turn = 0
        self.phase = "idle"
        self.member = ""
        self.text = []
        self.audio = []
        self.completed_at = None
        self.transcript_at = None

    @property
    def playing(self):
        return self.phase == "playing" and not self.interrupt.is_set()

    def barge(self, uid):
        self.report("barge", turn=self.turn, next_rtc=uid)
        self.interrupt.set()

    def offer(self, speech):
        if self.pending.full():
            old = self.pending.get_nowait()
            self.report("pending_dropped", rtc=old.rtc)
        self.pending.put_nowait(speech)

    async def send(self, message):
        await self.ws.send(json.dumps(message))

    async def read(self):
        async for raw in self.ws:
            self.receive(json.loads(raw))
        raise RuntimeError("Live connection closed")

    def receive(self, message):
        if "setupComplete" in message or "setup_complete" in message:
            self.ready.set()
            self.report("setup_complete")
        server = field_value(message, "serverContent", "server_content") or {}
        transcript = field_value(server, "inputTranscription", "input_transcription") or {}
        text = transcript.get("text", "")
        if self.phase != "receiving":
            if text:
                self.report("unassigned_transcript", phase=self.phase)
            return
        if text:
            self.transcript_at = time.monotonic()
            self.text.append(text)
            late_ms = (None if self.completed_at is None else
                       round((self.transcript_at - self.completed_at) * 1000))
            extra = {"text": text} if self.show_text else {}
            self.report("transcript", turn=self.turn, after_complete_ms=late_ms, **extra)
        model = field_value(server, "modelTurn", "model_turn") or {}
        for part in model.get("parts", []):
            inline = field_value(part, "inlineData", "inline_data") or {}
            if inline.get("data"):
                mime = field_value(inline, "mimeType", "mime_type") or ""
                rate = re.search(r"rate=(\d+)", mime)
                self.audio.append((base64.b64decode(inline["data"]), int(rate[1]) if rate else 24000))
        if field_value(server, "turnComplete", "turn_complete"):
            self.completed_at = time.monotonic()
            self.report("turn_complete", turn=self.turn)
        self.changed.set()

    async def wait_response(self):
        deadline = time.monotonic() + 25
        while True:
            now = time.monotonic()
            if self.completed_at is not None and self.transcript_at is not None:
                quiet = max(self.completed_at, self.transcript_at) + self.settle - now
                if quiet <= 0:
                    return
            else:
                quiet = deadline - now
            if now >= deadline:
                raise TimeoutError("Live response missing turnComplete or input transcription")
            self.changed.clear()
            try:
                await asyncio.wait_for(self.changed.wait(), min(quiet, deadline - now))
            except asyncio.TimeoutError:
                continue

    def decision(self, member, text):
        now = time.monotonic()
        spoken = normalize(text)
        if any(word in spoken for word in self.keywords):
            reason = "keyword"
        elif member and self.windows.get(member, 0) > now:
            reason = "follow_up"
        else:
            return "skipped"
        if member:
            self.windows[member] = now + 30
        return reason

    async def play(self):
        self.interrupt.clear()
        self.phase = "playing"
        try:
            for pcm, rate in self.audio:
                step = int(rate * 0.08) * 2
                for start in range(0, len(pcm), step):
                    if self.interrupt.is_set():
                        return
                    result = await self.transport.push_tts_pcm(pcm[start:start + step], rate)
                    if not result.get("ok"):
                        raise RuntimeError("Agora playback failed")
            result = await self.transport.push_tts_pcm(b"", self.audio[-1][1], finish=True)
            if not result.get("ok"):
                raise RuntimeError("Agora playback finish failed")
            playback = asyncio.create_task(self.transport.wait_tts_complete(timeout=30))
            interrupt = asyncio.create_task(self.interrupt.wait())
            try:
                done, _ = await asyncio.wait({playback, interrupt}, return_when=asyncio.FIRST_COMPLETED)
                if playback in done and not playback.result().get("ok"):
                    raise RuntimeError("Agora playback did not complete")
            finally:
                for task in (playback, interrupt):
                    task.cancel()
                await asyncio.gather(playback, interrupt, return_exceptions=True)
        finally:
            if self.interrupt.is_set():
                stopped = await self.transport.stop_tts()
                if not stopped.get("ok"):
                    raise RuntimeError("Agora stop_tts failed")
                self.report("playback_stopped", turn=self.turn)
            self.phase = "idle"

    async def run_turn(self, speech):
        self.turn += 1
        self.phase = "receiving"
        self.text, self.audio = [], []
        self.completed_at = self.transcript_at = None
        self.member = speech.member if self.identity.resolve(speech.rtc) == speech.member else ""
        self.report("activity_start", turn=self.turn, rtc=speech.rtc, member=self.member)
        await self.send({"realtimeInput": {"activityStart": {}}})
        for pcm in speech.frames:
            await self.send({"realtimeInput": {"audio": {
                "mime_type": "audio/pcm;rate=16000", "data": base64.b64encode(pcm).decode("ascii")}}})
        await self.send({"realtimeInput": {"activityEnd": {}}})
        self.report("activity_end", turn=self.turn)
        await self.wait_response()
        member = self.member if self.identity.resolve(speech.rtc) == self.member else ""
        reason = self.decision(member, "".join(self.text))
        self.report("decision", turn=self.turn, rtc=speech.rtc, member=member, reason=reason,
                    audio_parts=len(self.audio))
        if reason != "skipped" and self.audio:
            await self.play()
        self.phase = "idle"

    async def run(self):
        while True:
            await self.run_turn(await self.pending.get())
