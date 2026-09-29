# 更新日志

本文件记录 Ooptra 的对外变更，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [2.0.4] - 2026-09-30

### 修复

- **首次进房能正常对话，退出重进或换房间后 bot 一句话都不说**：`agora_player.html` 里 TTS 推流轨道的状态是**模块级、跨进房常驻**的，而 `agoraLeave` 只清了播放队列（`ttsNextTime` / `ttsSources` / `ttsPlaying`），**没有拆轨道**——`ttsCtx` / `ttsDest` / `ttsTrack` / `ttsPublished` 全部原样留到下一个房间。而 `AgoraRTC` 的 `CustomAudioTrack` 是**绑定在具体 client 上发布**的，退房后那个 client 已经不存在；`agoraJoin` 每次新建 client，于是重进房后第一次推流时 `ensureTtsTrack` 的两个分支同时短路（`if (!ttsCtx)` 因上下文还在而跳过重建，`if (!ttsPublished …)` 因标记仍为「已发布」而跳过重新 `publish`），模型音频全灌进一个已经离开的 client。`voice_browser` 只在 `start()` 里 `new_page()` + `goto()` 一次、`join`/`leave` 仅做 `page.evaluate`，页面是进程级复用的，所以这些变量真的会跨房间残留。现新增 `teardownTtsPipeline()`：退房时（`client` 还在，`unpublish` 需要它）摘除并 `close()` 旧轨道、关闭 `AudioContext`、清空全部标记；同时给 `ensureTtsTrack` 加**归属检查**——记录轨道发布在哪个 client 上（`ttsPublishedFor`），发现不是当前 client 就整套重建。两者各自都能单独兜住，叠起来才不会再退化。
- **语言时不时乱切换**：抢话时向服务端发送的 `realtimeInput.audioStreamEnd` **语义用反了**。该字段的含义是「用户说完了，立刻处理并回答」（官方文档：客户端 VAD 检测到句尾时发送，用于省掉服务端的静音等待），我们却在用户**刚开始**说话时发它，等于逼模型把当时缓冲区里的音频**碎片**当成一个完整回合去回答——一整段没有内容的输入，模型只能瞎猜，语言就是从这里开始飘的。本会话用的是**服务端自动 VAD**（setup 未关闭 `automaticActivityDetection`），文档明确「检测到打断时模型会取消正在进行的生成」，而远端音频本来就在持续灌入，抢话由服务端判定即可。`interrupt()` 现为**有意的客户端侧空操作**（保留方法是为接口稳定），本地静音仍由 `duplex.stop_tts()` 负责，服务端的 `interrupted` 到达后会再清一次并把回合收尾。
- **能通过「与 AI 对话」让 bot 开口，却听不见房间里其他人、谁说话都触发不了对话**：与上一条**同一类**问题，坏在另一个方向。远端采集源（`ctx` / `src`）取自**那个 client 的**远端 `audioTrack`，而 `agoraLeave` 只停了播放、**没停采集**——`remoteCaptures`（`uid → {ctx, src, processor, mute}`）原样留到下一个房间。重进房时 `agoraSetListen(true)` 会遍历房间成员重新采集，但 `startRemoteCapture` 撞上 `if (remoteCaptures.has(uid)) return;` 直接返回；而留在表里的旧采集，其源已经随上一场会话一起死掉、只会推静音。于是「同一个房间里同样那几个人」全都采集不到。现于退房时调用 `stopAllRemoteCaptures()` 拆掉全部采集（只用条目自身的资源，不依赖全局 `client`，所以异常退房路径也不会漏），并给采集条目加上归属标记 `clientRef`——`startRemoteCapture` 发现条目不属于当前 client 就先拆再重建。采集是**绑定在具体 client 上**的资源：退房不拆、重进房又被「已存在」短路，就会全部指向一个已经离开的会话。
- **语言缺少硬约束**：Live 的原生音频模型**不能**用 `speechConfig.languageCode` 锁语言（官方文档原文：*Explicitly setting a language code is not supported for native audio output models*），它按输入音频自动选语言，而我们的输入是**整个语音房间的混音**（`listen_only_uids` 默认为空即谁都吞），有人夹英文、有歌曲或噪声时就会选错。提示词是唯一可用的杠杆，故新增常量 `LANGUAGE_GUARD`，**追加在人格之后**下发（人格是用户可随时改写甚至清空的配置项，这条不会跟着丢；放最后也因为指令收尾位置权重更高）。

### 变更

- 回合边界处新增一条 INFO 日志，记录模型听到的转写与自己的回复（被抢话时标注）：语言乱切换这类问题**只能**从这里看出来——此前 `_last_user_text` 只写进记忆、从不落日志，等于没有观测手段。记忆里本就存着这两段文本，日志不增加额外暴露。
- 控制台那张卡片**改掉有歧义的表述**：标题「快捷开口」→「**与 AI 对话**」，按钮「说一句」→「发送」，说明改为「用文字发一句话，AI 会在当前语音房用语音回答，和房间里说话是同一场对话（需已进房）。级联模式下不经过模型，直接朗读这段文字」。状态与提示同步改写，且**按模式区分**——Live 模式返回的是 `chars` 而非 `pcm_bytes`，照级联那套显示「已推送（0 bytes）」会让人以为失败了，现在显示「已发送，等 AI 开口…」。

### 测试

- `tests/test_tts_play_queue.py` 新增 5 条结构断言，锁死 TTS 轨道的生命周期：退房必须调用拆解、拆解要排在 `client = null` **之前**（`unpublish` 需要 client）、拆解必须清空全部四个标记且真的 `unpublish` + `close`、`ensureTtsTrack` 必须在**复用 `AudioContext` 之前**判定归属、`publish` 后必须记下归属 client（共 15 条）。
- 新增 `tests/test_voice_rejoin.py`（7 条），锁死**输入方向**：退房必须停掉全部远端采集、且该调用不能被关进 `if (client)` 里（异常退房路径会漏）、拆采集必须释放 processor / source / ctx 并从表里删掉、采集条目要记下归属 client、归属不符时必须先拆再重建、旧条目要在取 `audioTrack` **之前**丢掉、同一 client 内重复调用必须短路（`user-published` 与 resubscribe 会各来一次，不短路会重复上报同一条音频）。
- `tests/test_live_turn_lifecycle.py` 新增 3 条：`interrupt()` 不得再发出 `audioStreamEnd`、语言约束必须追加在人格**之后**、人格被清空时语言约束仍在（共 12 条）。
- **修正一条空转用例**：`test_concurrent_start_session_connects_once` 此前是假通过——假的 `open_live_ws` 里**一个挂起点都没有**，5 个协程被逐个同步跑完，`start_session` 的锁与复检从未被走到（在加锁之前的代码上也是绿的）。现在假 `open` 里加 `await asyncio.sleep(0)`，去掉锁即挂。
- 全量 **187 passed**；`ruff check` 干净。16 条变异（逐条回退改动，含「退房不拆轨道」「退房不停采集」「采集不记归属」「回到『表里已有该 uid 就直接返回』」「不发语言约束」「语言约束插在人格之前」「去掉 `start_session` 的锁」等）**16/16** 被对应用例抓住。
- 新增 `C:\APP\_rejoin_repro.js`：把页面脚本装进假 Agora/DOM 沙箱（`node:vm`），**两个方向一起跑**——输出方向「进房 → 推 PCM → 退房 → 重进房 → 换房间」，输入方向「进房 → 开监听 → 对方说话 → 退房 → 重进房 → 对方再说话」。对照组（`--old`，直接读 git HEAD 的旧文件）精确复现两个症状：修复前输出方向 **首次有声 / 重进房无声 / 换房无声**（`AudioContext` 只建 1 个），输入方向 **首次收得到 / 重进房与换房收不到**（`capture started` 只打印一次）；修复后两个方向三轮全通过。这个场景 CI 覆盖不到（无 Chromium），故独立成脚本保留。

## [2.0.3] - 2026-09-29

### 修复

- **Live 模式下每个音频分片都把上一片掐断，语音被剁成碎片**：`_wire_live.on_audio` 在每个分片上把 `_speaking` 置 `True`，而 Live 模式下**除 `leave()` 外没有任何地方把它置回 `False`**（此前唯一的复位点就在抢话分支自身），于是 `_on_remote_pcm` 的抢话分支在**每个远端音频帧**（20 ms 一帧、房间里每个人）上各执行一次 `interrupt()` + `stop_tts()`。实测一段 4.43 秒的回复共 13 个分片，即被本地掐断 13 次：每个分片先排入播放队列，紧接着整个队列被清空（游标归零、已排期的 `AudioBufferSourceNode` 全部 `stop()`、轨道静音 30 ms），语音碎成约 340 ms 的片段，片段之间再夹 30 ms 静音。2.0.2 修复的排期逻辑本身正确，但被这条路径以「每分片一次」的频率抹掉，所以听感几乎没变。现改由后端的**回合生命周期**驱动该状态：`gemini_live` 新增 `set_turn_out` 回调，在 `turnComplete` / `interrupted`（全局唯一正确的回合边界）处通知编排层回落 `_speaking` 并计入轮次；抢话改为**边沿触发**——`_barge_in_armed` 闸门保证一次出声最多打断一次，直到该回合结束才重新武装。
- **一轮对话被记成十几轮**：`turns` 此前在每个音频分片上自增，一段 13 分片的回复记成 13 轮（实测一轮回复合计虚增 18）。现在只在回合边界 `+1`；Live 模式的 `/voice/speak` 也不再自行计数——否则 API 侧刚 `+1`、模型说完的 `turnComplete` 再 `+1`，一次说一句话被记成两轮（级联模式仍由该路径自行计数，那里没有回合边界可用）。
- **换频道后彻底不出声**：每个分片都向模型发送一次 `audioStreamEnd`（语义为「输入流已结束」），模型据此不再产生输出。
- **服务端判定抢话时本地仍把缓冲播完**（「模型停口了、喇叭还在说」）：收到 `interrupted` 时就地 `stop_tts()` 丢掉本地已排期分片。
- **Live 会话每 24~27 秒断开重连**：每个分片都要在远端音频热路径上做一次浏览器端 30 ms 等待与一次 `interrupt()` 往返，把输入路径拖住；同时非活跃窗口里 `start_session()` 被每个音频帧各调一次，而它开头即 `_reset_session()`，造成会话自持抖动。`start_session` 现以 `asyncio.Lock` + 复检 `session_active` 保证并发调用只真正建连一次。
- **断线原因被静默吞掉**：`_AiohttpWs._iter()` 在 `CLOSE` / `CLOSED` / `CLOSING` / `ERROR` 上直接 `break`，丢弃 `close_code` 与底层异常，日志里只剩一句 `Gemini Live session ended`，排查断线原因时毫无线索。现记录两者后再结束迭代（仍不抛异常，行为不变）。

### 变更

- `agoraStopTts` 在「队列为空且未在播放」时直接返回，省掉一次无谓的 30 ms 静音窗口。服务端判定抢话后本地还会再清一次，那一次通常正落在该分支里，而 `stop_tts` 在远端音频热路径上。

### 测试

- 新增 `tests/test_live_turn_lifecycle.py`（9 条）：锁死「分片与音频帧交替时一轮只打断一次」（实测 13 → 1）、「轮次只在回合边界 +1」、「回合结束后 `_speaking` 回落」、「下一回合重新武装」、「服务端 `interrupted` 清理本地播放」、「Live 的 `/voice/speak` 由回合边界计数」、「级联模式行为不变」、「并发 `start_session` 只建连一次」、「`CLOSE` 时日志带 `close_code` 与底层异常」。逐条回退改动做变异验证，8/8 均被对应用例抓住。
- 涉及音频帧的两条用例显式写死 `enabled=True`，并前置断言 `pushed_frames` 必须等于送进去的帧数：CI 的 `config.py` 由 `config.example.py` 生成（`VOICE_AGENT_CONFIG.enabled` 为 `False`），否则帧会在 `_on_remote_pcm` 第一道门被丢弃——断言「1 次调用」的用例误挂、断言「0 次调用」的用例**假通过**（首次 CI 即踩到，本地因真实配置为 `True` 而全绿）。
- `tests/test_tts_play_queue.py` 新增 1 条（共 10 条）锁死「空队列不空等 30 ms」。
- 全量 **172 passed**。

## [2.0.2] - 2026-09-29

### 修复

- **推流语音分片相互重叠，人声无法辨识**：Gemini Live 生成音频**快于实时**——实测一段 4.43 秒的语音，13 个分片在 0.98 秒内即全部推送完毕。播放器对每个分片调用无参 `AudioBufferSourceNode.start()`（语义为「自当前时刻立即播放」而非接续上一分片），于是整段语音被叠合播放并压缩至 1.48 秒，叠加削波后完全听不清，表现为「能听见 bot 说话，但断断续续、听不懂」。现维护 `ttsNextTime` 游标按时间轴顺序排期，仅在缓冲耗尽（欠载）时以 `TTS_LEAD`（80 ms）重新起头以吸收到达抖动。
- **抢话打断失效**：`agoraStopTts` 仅将轨道音量压低 30 ms 再恢复，在无队列时尚可勉强中断，队列引入后已排期的分片会在音量恢复后继续播完。现改为真正 `stop()` 全部已排期分片并归零游标；退房时一并清空队列。

- **控制台的「复制域 ID / 复制频道 ID / 复制绑定指令」点击无反应**：`navigator.clipboard` **只在安全上下文**（https 或 localhost）存在，用局域网 IP（`http://192.168.x.x:3090`）打开时它是 `undefined`，旧代码直接 `navigator.clipboard.writeText(...).then(...)`——属性访问本身就抛 `TypeError`，`.then` 与失败分支都不会执行，所以既不复制也不报错。现改为：安全上下文优先用 Clipboard API，否则退回隐藏 `<textarea>` + `execCommand('copy')`，两条路都不通时弹 `prompt`（默认值为选中态，`Ctrl+C` 即可）并明确告知原因。
- **房间成员列表的麦克风/扬声器状态始终为「未知」**：`GET /voice/members` 不带 `channel` 时是**整个域汇总**，而静音状态只有同一个 Agora 房间内的人会广播（实测：每人进房/改状态时发一条 `{"m","uid","cid","hm"}`，一次一人、无整房快照），因此列出的别房成员状态永远无法得知，整张表看起来就是「没修好」。现前端先读 `/api/voice/status` 取得 bot 当前所在频道，只查询该频道；未在房时不臆造频道、按域查询并在状态行说明原因。
- **成员页把「没收到广播」显示成「未知」**：`未知` 无法区分「我们没收到」与「对方没广播」。现该列显示「未广播」（悬浮提示说明成因），状态行由累计广播条数改为已解析人数 `M/N`（新增 `live_members` 字段），不再出现「收到 7 条」被误读为 7 个人的情况。

### 测试

- 新增 `tests/test_tts_play_queue.py`（9 条），锁死「推流不得出现无参 `start()`」。
- 新增 `tests/test_webui_clipboard.py`（6 条）锁死复制须在非安全上下文下可用；新增 `tests/test_webui_members.py`（6 条）与 `tests/test_voice_api_routes.py` 的成员范围用例（4 条）锁死「成员查询必须带上 bot 所在频道」。
- 全量 **162 passed**。

## [2.0.1] - 2026-09-29

### 修复

- **Gemini Live 端点 URL 重复拼接 `key`**：`start_session` 无条件追加 `?key=`，当 `gemini.base_url` 已包含 key（Google 文档给出的 `...BidiGenerateContent?key=API_KEY` 形式）时会生成 `...?key=<k>?key=<k>`，服务端解析出的 key 长度翻倍并直接关闭连接，且不返回错误帧。表现为进入语音频道后无任何语音输出，日志中亦不出现 `Gemini Live session ready`。新增 `build_live_url()` 幂等拼接：显式 `api_key` 优先，为空时保留 URL 自带的 key，其余查询参数原样保留，key 做 percent-encode；未配置 key 时在建连前报错。
- **WebUI 与独立 VOICE_API 同端口时抢占本机回环流量**：Windows 下 aiohttp 默认启用 `SO_REUSEADDR`，`0.0.0.0:3090` 与 `127.0.0.1:3090` 可同时绑定，更具体的回环 socket 优先接收本机请求，导致 WebUI 页面与 `/api/*` 在 `127.0.0.1` 上返回 404，而局域网地址正常。`VoiceApiServer.start()` 现检测到与 WebUI 监听地址相同时跳过启动并记录 WARNING。
- **`GET /api/update` 恒返回 HTTP 500**：`str(getattr(...)).get(...)` 对字符串调用 `.get()`，必然抛出 `AttributeError`。
- **房间成员页无法获取麦克风/扬声器状态**：Oopz 的 REST（`membersByChannels`）与网关事件均不提供静音状态，唯一来源是各客户端经 Agora `sendStreamMessage` 广播的 `{m, uid, cid, hm}`，而播放器此前仅发送不接收。现播放器监听 `stream-message` 事件并将状态回传 Python；`/voice/members` 新增 `live_state_received` 计数，为 `0` 表示本房未收到任何广播，此时静音列保持 `null`（未知）。

### 变更

- **WebUI 左侧导航精简**：`房间成员`、`人格与记忆` 为语音台页内的子标签，侧栏重复列出会与页内标签栏重叠。侧栏「语音」组仅保留 `语音台`（点击进入「会话控制」）。
- **`.gitignore` 补充**：新增 `/config.py.bak*` 与 `/private_key.py.bak*`。原规则仅覆盖 `/config.py` 与原子替换产生的 `/.config.py.*.bak`，手工备份存在被 `git add -A` 一并提交的风险（含 Oopz 账密与 JWT）。

### 测试

- 新增 `tests/test_gemini_live_url.py`（15 条）与 `tests/test_voice_member_live_state.py`（32 条）；全量 **136 passed**。

## [2.0.0] - 2026-09-29

### 修复

- **独立 VOICE_API 端口（3091）与 WebUI（3090）路由分叉**：3091 曾经自带一份手写路由表，缺 `GET /voice/channels`（插件 v0.3.0 依赖，直接 404）、缺 `/oopz/*` 与 `/api/*` 别名。现在两个端口共用 `webui/voice_routes.build_voice_routes` 的**唯一实现**，并在测试中断言两者路由集合完全一致。
- **`GET /voice/members` 在 3091 上返回 500**：旧实现把 pydantic 的 `VoiceChannelMembersResult` 当 dict/list 处理，又把模型对象原样塞进响应体，触发 `TypeError: Object of type VoiceChannelMembersResult is not JSON serializable`。
- **成员昵称永远为空**：`VoiceChannelMemberInfo` 根本没有 `name` 字段（旧代码 `getattr(row, "name", "")` 恒为空串）。改为经 `NameResolver.ensure_users()` 批量补全，未解析到则回退短 ID。
- **WebUI 房间成员表永远显示「开麦 / 正常」**：接口只返回 `mic`/`speaker`/`m`/`hm`，而前端读的是 `mic_muted`/`speaker_muted`。现在两套字段一起返回；Oopz 的 `membersByChannels` 不返回静音状态时统一为 `null`（未知），不再伪造「开麦」。同时给 `VoiceChannelMemberInfo` 增加静音字段透传，服务端哪天带上即可直接生效。
- **Gemini Live 会话断开后无法恢复**：`_session_loop` 退出时只 `_ready.set()`，不回收 `_ws`/`_session_task`，导致 `session_active` 对已死 socket 恒为 `True`，`start_session` 变成空操作、`push_audio` 把错误吞成 debug 日志（音频进黑洞），`speak_text` 直接 500。现在退出即回收、`session_active` 以循环存活为准、`speak_text` 会真重连一次再发、音频热路径断线后后台重连并打 WARNING。
- **退出语音不关闭 Live 会话**：`VoiceAgent.leave()` 从不调用 `backend.aclose()`，Gemini 会话一直挂着（计费 + 占并发），且是上一条「重新进房后没反应」的直接诱因。
- **配置保存后不生效、必须重启**：WebUI 保存只改了 `config` 模块的字典，`VoiceRuntime` 里启动时构造的 dataclass 快照永不刷新。现在 `VoiceRuntime.reload_settings()` 就地写回（`runtime.agent_settings` / `agent.settings` / `backend.settings` 本就是同一对象）并按需重建 VAD、记忆、后端与已建立的模型会话；`restart_required` 只对真正无法热应用的字段置位。
- 未进房时调用 `/voice/speak`、`/voice/join` 返回裸 500：改为带原因的 JSON 错误。
- 独立 VOICE_API 端口未配置 token 时现在会打 WARNING（此前静默无鉴权）。

### 新增

- `GET /health` 现在回传 `version`。

- **语音对话 Agent**（`VOICE_AGENT_CONFIG`）：进入 Oopz 语音房，**Live 端到端语音**（语音进、语音出，默认 `gemini_live` / BidiGenerateContent）；支持抢话打断。可选 `mimo_cascade` 级联兜底（ASR→LLM→TTS）。
- **语音 HTTP API** 挂载在 Web 控制台同端口（默认 `3090`，复用 `WEBUI_CONFIG.token`）：`/api/voice/*`、`/api/oopz/areas|channels`、`/api/persona`、`/api/memory`，便于 AstrBot 等外部插件查询语音状态与同步人格记忆。
- **Web 控制台语音台**：侧栏二级导航；域标签 + 频道卡片选择目标；会话控制 / 房间成员 / 人格与记忆三个子页；配置页按「连接 / 语音模型 / 系统」分组。
- Agora 浏览器后端支持 `agoraSetListen` / `agoraPushTtsPcm`，实现远端 PCM 采集与 TTS 流式推流。
- 共享记忆 JSONL（`data/voice_memory.jsonl`），供多端人格一致。
- `tests/test_voice_agent_smoke.py` 冒烟测试。
- **模型配置页厂商预设与音色下拉**：`VOICE_AGENT_CONFIG` 的 `gemini.*` / `mimo.*` / `openai.*` 进入「语音模型」配置页；按所选 Live 厂商显示对应字段。可配置 **接口地址（base_url）、API Key、模型名、音色**；音色与模型名支持下拉预设（Gemini Live：Puck / Charon / Kore…；MiMo TTS：冰糖 / 茉莉 / 苏打 / 白桦…；OpenAI：alloy / echo…）并可自定义输入。
- **模型 API 可选代理**（`VOICE_AGENT_CONFIG.proxy`，选填）：默认不启用；可一键启用 `127.0.0.1:7890`（Clash/Mihomo 别名 `clash`），也可填自定义 `http://主机:端口`。Gemini Live WebSocket 与 MiMo HTTP、更新检查均走该出口。
- **Web 控制台检查更新**：`GET /api/update` 查询 GitHub 最新 release/tag 并与本地 `core.version` 比较；侧栏新增「检查更新」「GitHub」按钮，可直接打开仓库（默认分支）。
- **语音台「设为默认」**：在「会话控制」选中域/频道后一键写入 `OOPZ_CONFIG.default_area` / `default_channel`，作为插件 `/进语音` 不带参数时的默认目标；一群绑多个域时也按默认域查询。
- **`GET /voice/channels`**：列出域内语音频道与在线人数（含 `default_area` / `default_channel`），供插件按域汇总、按频道名找频道；`/voice/status` 亦回传默认目标。

### 变更

- Web 控制台侧栏改为分组导航；原登录、账号、连接配置、日志等功能保留。
- 语音相关配置进入 `config.py` 的 `VOICE_AGENT_CONFIG` / `VOICE_API_CONFIG`，可在控制台编辑。
- 配置编辑器支持 `select` 字段类型与嵌套字段路径（如 `gemini.voice`），写回 `config.py` 时保留注释与未改字段。

## [1.0.0] - 2026-09-24

首个公开版本：项目更名为 **Ooptra**，并重建为「Oopz → OneBot v11 反向 WebSocket」的纯桥接工具。

### 新增

- **Web 控制台**（默认 `127.0.0.1:3090`）：状态总览、实时日志（SSE）、配置编辑、账号与凭据管理；前端单文件、无外部依赖。
- 独立登录屏：需要访问令牌或 Oopz 凭据时先登录，通过后再进入面板。
- 配置页分层：常用项直接可见，其余默认值收进「高级选项」；每张卡片带一句话说明与实时链路状态。
- 账号密码登录与网页版登录（可手动过验证）；登录成功后 `device_id` / `person_uid` / `jwt_token` 与 RSA 私钥自动写回配置并自动重连。
- 身份映射持久化到 SQLite，保证对端看到的群号与成员编号稳定。
- `start_silent.vbs`：Windows 静默后台启动脚本，可放入「启动」文件夹实现开机自启。
- 版本号单一来源 `src/core/version.py`，并随状态接口与界面展示。
- 单元测试（`tests/`）与 GitHub Actions CI：ruff 检查 + 多平台多版本 pytest。

### 变更

- 项目更名为 **Ooptra**。
- 桥接对端从绑定某一具体框架改为**任意 OneBot v11 实现**，界面与文档不再依赖特定框架的命名。
- 反向 WebSocket 心跳默认间隔调整为 15 秒，并对对端事件循环阻塞更宽容，避免 PONG 超时反复重连。
- 静态资源响应附带 `Cache-Control: no-cache`，界面更新后刷新即可生效。
- 配置页提示与文案重写为「按连接顺序引导」，降低首次配置的理解成本。

### 移除

- 全部内置命令、插件与业务功能，项目只保留桥接与运维能力。
- 本地 HTTP / 正向 WebSocket 服务默认关闭（纯反向桥接不需要）。
- 不再上报 `group_increase` / `group_decrease` 通知（底层 SDK 未对这两类事件建模）。
- 配置页不再展示 `app_version` / `device_id` / `person_uid` / `jwt_token` 等自动维护字段，避免误改，也不再经配置接口明文回传。

### 修复

- 登录屏流程图连线不渲染：渐变改为 `userSpaceOnUse`（水平线包围盒高度为 0，按 SVG 规范 objectBoundingBox 渐变不会被绘制）。
- 配置页只读行溢出卡片，导致「复制」按钮被挤出可视区域。
- 配置页高级字段在隐藏状态下仍参与表单布局，造成列宽不一致。

[2.0.2]: https://github.com/Eason4869/Ooptra/releases/tag/v2.0.2
[2.0.1]: https://github.com/Eason4869/Ooptra/releases/tag/v2.0.1
[2.0.0]: https://github.com/Eason4869/Ooptra/releases/tag/v2.0.0
[1.0.0]: https://github.com/Eason4869/Ooptra/releases/tag/v1.0.0
