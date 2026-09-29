"""重进房 / 换房间后必须重建的浏览器侧资源。

一句话：**绑定在具体 Agora client 上的东西，退房时不拆，重进房时就会被
「已存在」的判断短路，全部指向一个已经离开的会话。**两个方向各踩过一次：

* **输出方向**（AI 的语音推给房间）：`ttsTrack` 是 `client.publish()` 出去的，
  退房只清了播放队列、没拆轨道 → 「首次进房能对话，退出重进/换房后一句话都不说」。
  用例在 `test_tts_play_queue.py`，本文件只做交叉引用。
* **输入方向**（别人的麦克风进来）：采集源 `ctx`/`src` 取自**那个 client 的**
  远端 `audioTrack`，退房只停了播放、没停采集 → `remoteCaptures` 留着旧 uid，
  重进房时 `startRemoteCapture` 撞上 `remoteCaptures.has(uid)` 直接返回，
  旧采集的源又已经随上一场会话死掉（只会推静音）→「能通过快捷开口让 bot 说话，
  但听不见房间里其他人，谁说话都触发不了对话」。

CI 里没有 Chromium，真跑场景在 `C:\\APP\\_rejoin_repro.js`（假 Agora/DOM 沙箱里
装真实页面脚本，`--old` 读 git HEAD 当对照）。这里做的是结构断言：锁住那两个
「必须先拆 / 必须判定归属」的不变量，防止改回去。
"""

from __future__ import annotations

import re

from test_tts_play_queue import _fn, _player_source

# ----------------------------------------------------------------------
# 退房必须停掉别人的麦克风采集
# ----------------------------------------------------------------------


def test_leave_stops_remote_captures() -> None:
    """不调用它，旧 uid 会留在 remoteCaptures 里，把重进房的采集短路掉。"""
    body = _fn(_player_source(), "agoraLeave")
    assert "stopAllRemoteCaptures()" in body, "退房没有停掉远端采集"


def test_leave_stops_captures_regardless_of_client() -> None:
    """stopAllRemoteCaptures 要排在任何「client 已置空」之后的逻辑之外。

    采集的拆卸只用条目自身的 ctx/src/processor，不依赖全局 client —— 所以放在
    ``client = null`` 之后也正确。这里只是防止有人把它挪进 ``if (client)`` 里，
    那样 client 为 null 时（异常退房路径）采集就漏掉了。
    """
    body = _fn(_player_source(), "agoraLeave")
    guard = re.search(r"if\s*\(client\)\s*\{[^}]*stopAllRemoteCaptures", body)
    assert not guard, "stopAllRemoteCaptures 被放进了 if (client) 里，异常路径会漏"


def test_stop_capture_releases_every_resource() -> None:
    body = _fn(_player_source(), "stopRemoteCapture")
    for release in (r"cap\.processor\.disconnect\(\)", r"cap\.source\.disconnect\(\)",
                    r"cap\.ctx\.close\(\)"):
        assert re.search(release, body), f"拆采集漏了 {release}"
    assert re.search(r"remoteCaptures\.delete\(uid\)", body), "拆完没从表里删掉"


# ----------------------------------------------------------------------
# 采集必须绑定 client，并在换了 client 时重建
# ----------------------------------------------------------------------


def test_capture_records_the_owning_client() -> None:
    body = _fn(_player_source(), "startRemoteCapture")
    assert re.search(r"clientRef\s*:\s*client", body), (
        "采集条目没记下归属 client，重进房就判断不出它是死的"
    )


def test_capture_rebuilds_when_the_client_changed() -> None:
    """同一个 uid 在新 client 上必须重新建采集，不能因为「表里已有」就跳过。"""
    body = _fn(_player_source(), "startRemoteCapture")
    guard = re.search(r"existing\.clientRef\s*===\s*client", body)
    assert guard, "没有「采集仍属于当前 client」的判定"
    assert re.search(r"stopRemoteCapture\(uid\)", body), "归属不符时要先拆掉旧的再重建"


def test_stale_capture_is_dropped_before_the_audio_track_check() -> None:
    """先拆再判：``user.audioTrack`` 缺失时也必须把旧条目清掉，不能留在表里。"""
    body = _fn(_player_source(), "startRemoteCapture")
    drop = body.index("stopRemoteCapture(uid)")
    assert drop < body.index("if (!user.audioTrack)"), (
        "旧条目要在取 audioTrack 之前就丢掉"
    )


def test_capture_is_idempotent_within_one_client() -> None:
    """同一个 client 上重复调用不该重建（user-published 与 resubscribe 会各来一次）。"""
    body = _fn(_player_source(), "startRemoteCapture")
    assert re.search(r"if\s*\(existing\.clientRef\s*===\s*client\)\s*return", body), (
        "同一 client 内不再短路的话，会重复建采集、重复上报同一条音频"
    )
