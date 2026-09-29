"""TTS 推流必须按时间轴排队播放，不能每片都「立即开始」。

背景：Gemini Live 生成音频**快于实时**。实测一段 4.43 秒的话，13 个分片在
0.98 秒内就全部推到了浏览器。播放器此前对每一片都调 ``src.start()``（不带
``when`` = 立刻从当前时刻开始），于是这一整段话被叠成一团、压缩到 1.48 秒
播完 —— 现象就是「能听见 bot 说话，但完全听不清、断断续续、卡卡的」。

修法：维护 ``ttsNextTime``，每片接在前一片尾巴后面排期；缓冲耗尽时才重新
留一个 ``TTS_LEAD``。这个文件锁住该行为，防止改回 ``src.start()``。

浏览器端的真实时长对比（旧 1.48s / 新 4.50s）属人工验证，CI 没有 Chromium，
所以这里做的是结构断言：函数体里不允许再出现无参 ``start()``。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYER = ROOT / "src" / "oopz_sdk" / "assets" / "voice" / "agora_player.html"


def _player_source() -> str:
    return PLAYER.read_text(encoding="utf-8")


def _fn(source: str, name: str) -> str:
    """截出函数的定义体：``window.<name> = ...`` 或 ``[async] function <name>(...)``。

    结束于下一个顶层 ``window.`` 赋值、下一个 ``function`` 声明或脚本结尾。
    """
    match = re.search(rf"(?:window\.{re.escape(name)}\s*=|function\s+{re.escape(name)}\s*\()", source)
    assert match, f"播放器里找不到 {name}"
    rest = source[match.end():]
    end = len(rest)
    for stop in (
        re.search(r"\nwindow\.", rest),
        re.search(r"\n(?:async\s+)?function\s", rest),
        re.search(r"\n</script>", rest),
    ):
        if stop:
            end = min(end, stop.start())
    return rest[:end]


# ----------------------------------------------------------------------
# 排期：接在前一片后面，而不是立刻播
# ----------------------------------------------------------------------


def test_push_uses_scheduled_start_time() -> None:
    body = _fn(_player_source(), "agoraPushTtsPcm")
    assert "src.start(startAt)" in body, "推流必须带上排期时刻"


def test_push_never_starts_immediately() -> None:
    """无参 start() = 从当前时刻立刻播，正是分片重叠的根因。"""
    body = _fn(_player_source(), "agoraPushTtsPcm")
    assert not re.search(r"src\.start\(\s*\)", body), "不允许无参 start()（会与上一片重叠）"


def test_push_advances_the_timeline() -> None:
    body = _fn(_player_source(), "agoraPushTtsPcm")
    assert re.search(r"ttsNextTime\s*=\s*startAt\s*\+\s*buf\.duration", body), (
        "排期后必须把游标推进整个分片的时长"
    )


def test_push_rearms_after_underrun() -> None:
    """缓冲耗尽（游标落到当下之前）才重新起一个 lead，避免一直往后拖。"""
    body = _fn(_player_source(), "agoraPushTtsPcm")
    assert re.search(r"startAt\s*<\s*now", body), "需要有欠载判断"
    assert "TTS_LEAD" in body, "欠载后要留缓冲，吸收到达抖动"


def test_timeline_state_is_declared() -> None:
    source = _player_source()
    assert re.search(r"let\s+ttsNextTime\s*=\s*0", source)
    assert re.search(r"const\s+TTS_LEAD\s*=\s*[\d.]+", source)


def test_new_audio_context_resets_timeline() -> None:
    """换了 AudioContext，旧时间轴就失效了，必须归零。"""
    body = _fn(_player_source(), "ensureTtsTrack")
    assert re.search(r"ttsNextTime\s*=\s*0", body)


# ----------------------------------------------------------------------
# 打断：队列里的分片要真的停掉
# ----------------------------------------------------------------------


def test_stop_tts_cancels_scheduled_sources() -> None:
    body = _fn(_player_source(), "agoraStopTts")
    assert "ttsSources" in body, "要遍历未播完的分片"
    assert re.search(r"src\.stop\(\)", body), "必须真正 stop()，只调音量拦不住已排期的分片"
    assert re.search(r"ttsNextTime\s*=\s*0", body), "打断后时间轴归零，下一句重新起头"


def test_stop_tts_skips_mute_when_nothing_was_playing() -> None:
    """队列本来就空时别白等 30ms —— stop_tts 在远端音频热路径上。

    判定必须发生在 ``ttsPlaying`` 被清零**之前**，否则它永远为假、提前返回失效。
    """
    body = _fn(_player_source(), "agoraStopTts")
    assert re.search(
        r"const\s+hadAudio\s*=\s*ttsPlaying\s*\|\|\s*ttsSources\.size\s*>\s*0", body
    ), "缺少「本次是否真有音频在播」的判定"
    assert body.index("const hadAudio") < body.index("ttsPlaying = false"), (
        "判定被放在清零之后，等于恒假"
    )
    guard = re.search(r"if\s*\(!hadAudio\)\s*return", body)
    assert guard, "空队列要提前返回"
    assert guard.start() < body.index("setVolume(0)"), "提前返回要在静音窗口之前"


def test_sources_are_tracked_and_released() -> None:
    body = _fn(_player_source(), "agoraPushTtsPcm")
    assert "ttsSources.add(src)" in body
    assert "ttsSources.delete(src)" in body, "播完要移出集合，否则集合无限增长"


def test_leave_clears_the_queue() -> None:
    body = _fn(_player_source(), "agoraLeave")
    assert "ttsSources" in body and re.search(r"ttsNextTime\s*=\s*0", body)


# ----------------------------------------------------------------------
# 退房必须拆掉 TTS 轨道：不拆就是「二次进房后一句话都不说」
#
# 真实故障：agoraLeave 只清了播放队列，ttsTrack/ttsPublished 残留成「已发布」。
# 二次进房时 ensureTtsTrack 的两个分支（!ttsCtx / !ttsPublished）同时短路，模型
# 音频全灌进一个已经离开的 client —— 服务端日志一切正常（session ready、joined），
# 房间里却完全没声音。页面是进程级复用的（voice_browser 只在 start() 里 goto 一次），
# 所以这些模块级变量真的会跨房间残留。
# ----------------------------------------------------------------------


def test_leave_tears_down_the_tts_track() -> None:
    body = _fn(_player_source(), "agoraLeave")
    assert "teardownTtsPipeline()" in body, "退房没有拆 TTS 轨道"


def test_teardown_runs_while_the_client_still_exists() -> None:
    """unpublish 必须走 client，所以拆解要排在 ``client = null`` 之前。"""
    body = _fn(_player_source(), "agoraLeave")
    assert body.index("teardownTtsPipeline()") < body.index("client = null"), (
        "拆解排在 client 置空之后，unpublish 会拿到 null"
    )


def test_teardown_resets_every_publish_flag() -> None:
    body = _fn(_player_source(), "teardownTtsPipeline")
    for reset in (
        r"ttsTrack\s*=\s*null",
        r"ttsPublished\s*=\s*false",
        r"ttsPublishedFor\s*=\s*null",
        r"ttsCtx\s*=\s*null",
        r"ttsDest\s*=\s*null",
    ):
        assert re.search(reset, body), f"拆解漏了 {reset}（残留会让下次进房短路）"
    assert "unpublishTrackSafely" in body, "旧轨道要从 client 上摘掉，不能只丢引用"
    assert "closeTrackSafely" in body, "旧轨道要 close，否则 MediaStream 泄漏"


def test_ensure_tts_track_rebuilds_when_the_client_changed() -> None:
    """换了 client（重进房/换频道）就必须重建，不能复用旧轨道。"""
    body = _fn(_player_source(), "ensureTtsTrack")
    guard = re.search(r"ttsPublishedFor\s*!==\s*client", body)
    assert guard, "没有「发布目标已不是当前 client」的判定"
    assert guard.start() < body.index("if (!ttsCtx)"), "判定要在复用 AudioContext 之前"
    assert "teardownTtsPipeline()" in body, "判定命中后要真的拆掉重建"


def test_publish_records_which_client_owns_the_track() -> None:
    body = _fn(_player_source(), "ensureTtsTrack")
    assert re.search(r"ttsPublishedFor\s*=\s*client", body), (
        "publish 后没记下归属 client，重进房就检测不到轨道已经失效"
    )
