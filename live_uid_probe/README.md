# Ooptra Live 音轨归属探针

这份独立原型以 Ooptra `main` 的 `079b2b7`（4.0.0）为基线。它用部署机上的 Oopz 账号和 Gemini 配置进入一个测试房，全程只建立一个 Gemini Live WebSocket。每句先在本机从一条 Agora 音轨切出，再用 `activityStart → PCM → activityEnd` 送入会话。探针等待回合完成和输入转写，再决定是否播放。这个缓冲策略用于观察协议行为，延迟不代表最终实现。

## 运行

把整个 `live_uid_probe` 目录复制到部署机。使用已经安装 Ooptra 语音依赖和 Chromium 的 Python 环境。为避免同一个机器人账号的两个客户端争抢房间，请使用专用测试机器人，或在测试窗口停掉该账号的常驻实例。测试房由机器人和 A、B 两个真人账号组成，命令里的成员 ID 填 **Oopz UID**。

```powershell
python -B live_uid_probe/run_room.py --checkout 'D:\Ooptra' --area '域ID' --channel '频道ID' --member-a 'A的OopzUID' --member-b 'B的OopzUID' --seconds 240 --show-text
```

`--show-text` 会输出转写，联调时可用它核对独特短句。默认省略文本，日志仍含成员 ID。探针复用 Ooptra 的启动配置和账号刷新流程，在测试房推送音频回复。关键词默认为“小欧”，普通回复概率固定为 `0%`，追问窗口为 30 秒。抢话沿用部署配置中的 `barge_in` 开关，`--hold-ms` 默认 300。`--settle` 默认在收到转写和 `turnComplete` 后额外等 0.8 秒，便于观察迟到事件。

## 双账号验收

| 操作 | 要核对的日志和听感 |
| --- | --- |
| 探针 `room_ready` 后 A、B 依次进房。若已经在房内，各切换一次麦克风状态，再重复离房、进房。 | `identity_broadcast` 的 `sender` 与 `cid` 一致，`mapping` 分别命中 A、B 的 Oopz UID。两人交替开口至少三轮，每轮 `activity_start` 的 `rtc` 与实际账号一致。没有广播、冲突或 `member` 为空都记为未通过，保留日志。 |
| A 说“小欧，记一下测试词是红伞”，等机器人答完。B 说“我的测试词是蓝船”，随后 A 在 30 秒内问“我的测试词是什么”。 | A、B、A 的 `decision` 依次为 `keyword`、`skipped`、`follow_up`。B 的“蓝船”不能被当成 A 的话；即便本地归属正确，若共享模型历史仍让回答串人，也单独记为未通过。 |
| A 说“小欧，请从一数到二十，慢一点”，在 bot 播报时 B 持续说“蓝船，小欧，告诉我今天是星期几”。 | 先看到旧轮的 `barge`、`playback_stopped`，再看到 B 的 `activity_start`。听不到旧回复恢复，B 句首“蓝船”仍在自己的转写里。另测短咳或短于门限的“嗯”，应继续播原回复。 |
| A、B 紧接着轮流说出不同短句，其中一次有短暂重叠。 | 每个手动输入回合只有一条音轨。记录每个 `transcript` 与 `turn_complete` 的顺序；`after_complete_ms` 为数字表示转写在完成事件之后。超过探针收尾时间才到的片段可能记为 `unassigned_transcript`。任何文本被挂到错误 UID 都判失败。若未遇到迟到转写，记为本次未观测到。 |

`setup_complete` 说明当前部署的模型与端点接受了探针配置。每次实际发言都出现 `activity_end`、`turn_complete` 和对应转写，才算确认这套手动边界能跑通。Gemini 的输入转写事件没有本地回合 ID。超过收尾等待、且恰好落进下一轮接收阶段的迟到片段仍可能无法区分，因此必须用不同测试词核对原始转写和发言人，不能把模拟结果或有限次实测当作协议保证。

本地模拟命令如下。

```powershell
python -B -m unittest discover -s live_uid_probe -v
```
