import asyncio
import base64
import json
import struct
import unittest

from probe import Capture, Identity, LiveProbe, Speech


def frame(amplitude):
    return struct.pack("<h", amplitude) * 1600


class Socket:
    def __init__(self):
        self.sent = []
        self.probe = None
        self.phrases = iter(["小欧，请讲一个故事", "我也想听", "然后呢"])

    async def send(self, raw):
        data = json.loads(raw)["realtimeInput"]
        self.sent.append(data)
        if "activityEnd" in data:
            self.probe.receive({"serverContent": {"modelTurn": {"parts": [{"inlineData": {
                "data": base64.b64encode(frame(123)).decode(), "mimeType": "audio/pcm;rate=24000"}}]},
                "turnComplete": True}})
            asyncio.get_running_loop().call_later(0.001, self.probe.receive, {
                "serverContent": {"inputTranscription": {"text": next(self.phrases)}}})


class Transport:
    def __init__(self):
        self.played = asyncio.Event()
        self.released = asyncio.Event()
        self.stops = 0

    async def push_tts_pcm(self, pcm, rate, finish=False):
        self.played.set()
        return {"ok": True}

    async def wait_tts_complete(self, timeout):
        await self.released.wait()
        return {"ok": True}

    async def stop_tts(self):
        self.stops += 1
        return {"ok": True}


def identity():
    result = Identity()
    result.members = {"A", "B"}
    result.observe("7", "7", "A")
    result.observe("8", "8", "B")
    return result


class IdentityTests(unittest.TestCase):
    def test_sender_payload_and_roster_must_agree(self):
        value = identity()
        value.observe("9", "10", "B")
        self.assertEqual(value.resolve("9"), "")
        self.assertEqual(value.resolve("8"), "B")
        value.members.remove("B")
        self.assertEqual(value.resolve("8"), "")

    def test_conflicting_claims_are_unattributed(self):
        value = identity()
        value.observe("9", "9", "A")
        self.assertEqual(value.resolve("7"), "")
        self.assertEqual(value.resolve("9"), "")
        value.observe("8", "8", "A")
        self.assertEqual(value.resolve("8"), "")


class CaptureTests(unittest.TestCase):
    def test_interleaved_tracks_never_mix_and_missing_frames_finish(self):
        utterances = []
        capture = Capture(identity(), utterances.append, self.fail, 300, lambda: False)
        a, b = frame(2000), frame(5000)
        capture.frame("7", a, 16000, 0)
        capture.frame("8", b, 16000, 0.02)
        capture.frame("7", a, 16000, 0.1)
        capture.tick(0.8)
        self.assertEqual([(u.member, u.frames) for u in utterances], [("A", [a, a])])

    def test_barge_in_counts_contiguous_frames_of_one_uid(self):
        barges = []
        capture = Capture(identity(), self.fail, barges.append, 300, lambda: True)
        a, b = frame(2000), frame(5000)
        capture.frame("7", a, 16000, 0)
        capture.frame("7", a, 16000, 0.1)
        capture.frame("8", b, 16000, 0.1)
        capture.frame("7", a, 16000, 0.8)
        self.assertEqual(barges, [])
        capture.frame("8", b, 16000, 0.8)
        capture.frame("8", b, 16000, 0.9)
        capture.frame("8", b, 16000, 1.0)
        self.assertEqual(barges, ["8"])
        self.assertEqual(capture.speech.frames, [b, b, b])

    def test_barge_disabled_does_not_start_an_utterance(self):
        capture = Capture(identity(), self.fail, self.fail, None, lambda: True)
        capture.frame("7", frame(5000), 16000)
        self.assertIsNone(capture.speech)


class LiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_boundaries_late_transcription_barge_and_followup(self):
        events = []
        ws, transport = Socket(), Transport()
        probe = LiveProbe(ws, transport, identity(), ["小欧"], settle=0.01,
                          report=lambda name, **data: events.append((name, data)))
        ws.probe = probe
        task = asyncio.create_task(probe.run_turn(Speech("7", "A", [frame(2000)])))
        await asyncio.wait_for(transport.played.wait(), 1)
        probe.barge("8")
        probe.receive({"serverContent": {"inputTranscription": {"text": "小欧，旧的片段"}}})
        await asyncio.wait_for(task, 1)
        self.assertEqual(transport.stops, 1)
        self.assertEqual(len(ws.sent), 3)
        await probe.run_turn(Speech("8", "B", [frame(5000)]))
        transport.released.set()
        await probe.run_turn(Speech("7", "A", [frame(2000)]))
        decisions = [(data["member"], data["reason"]) for name, data in events if name == "decision"]
        self.assertEqual(decisions, [("A", "keyword"), ("B", "skipped"), ("A", "follow_up")])
        self.assertEqual([next(iter(data)) for data in ws.sent],
                         ["activityStart", "audio", "activityEnd"] * 3)
        self.assertEqual(base64.b64decode(ws.sent[4]["audio"]["data"]), frame(5000))
        self.assertTrue(any(name == "unassigned_transcript" for name, data in events))
        self.assertTrue(all(data["after_complete_ms"] is not None
                            for name, data in events if name == "transcript"))

    async def test_unknown_source_does_not_open_personal_window(self):
        probe = LiveProbe(Socket(), Transport(), identity(), ["小欧"])
        self.assertEqual(probe.decision("", "小欧"), "keyword")
        self.assertEqual(probe.decision("", "然后呢"), "skipped")
        self.assertEqual(probe.windows, {})


if __name__ == "__main__":
    unittest.main()
