# 更新日志

本文件记录 Ooptra 的对外变更，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [2.0.1] - 2026-09-29

### 修复

- **Gemini Live 端点 URL 重复拼接 `key`**：`start_session` 无条件追加 `?key=`，当 `gemini.base_url` 已包含 key（Google 文档给出的 `...BidiGenerateContent?key=API_KEY` 形式）时会生成 `...?key=<k>?key=<k>`，服务端解析出的 key 长度翻倍并直接关闭连接，且不返回错误帧。表现为进入语音频道后无任何语音输出，日志中亦不出现 `Gemini Live session ready`。新增 `build_live_url()` 幂等拼接：显式 `api_key` 优先，为空时保留 URL 自带的 key，其余查询参数原样保留，key 做 percent-encode；未配置 key 时在建连前报错。
- **WebUI 与独立 VOICE_API 同端口时抢占本机回环流量**：Windows 下 aiohttp 默认启用 `SO_REUSEADDR`，`0.0.0.0:3090` 与 `127.0.0.1:3090` 可同时绑定，更具体的回环 socket 优先接收本机请求，导致 WebUI 页面与 `/api/*` 在 `127.0.0.1` 上返回 404，而局域网地址正常。`VoiceApiServer.start()` 现检测到与 WebUI 监听地址相同时跳过启动并记录 WARNING。
- **`GET /api/update` 恒返回 HTTP 500**：`str(getattr(...)).get(...)` 对字符串调用 `.get()`，必然抛出 `AttributeError`。
- **房间成员页无法获取麦克风/扬声器状态**：Oopz 的 REST（`membersByChannels`）与网关事件均不提供静音状态，唯一来源是各客户端经 Agora `sendStreamMessage` 广播的 `{m, uid, cid, hm}`，而播放器此前仅发送不接收。现播放器监听 `stream-message` 事件并将状态回传 Python；`/voice/members` 新增 `live_state_received` 计数，为 `0` 表示本房未收到任何广播，此时静音列保持 `null`（未知）。
- **推流语音分片重叠，人声无法辨识**：Gemini Live 生成音频**快于实时**——实测一段 4.43 秒的语音，13 个分片在 0.98 秒内即全部推送完毕。播放器对每个分片调用无参 `AudioBufferSourceNode.start()`（自当前时刻立即播放，而非接续上一分片），导致全部分片叠合播放并被压缩至 1.48 秒，叠加削波后完全听不清。现维护 `ttsNextTime` 游标按时间轴顺序排期，缓冲耗尽（欠载）时以 `TTS_LEAD`（80 ms）重新起头。同时 `agoraStopTts` 改为真正 `stop()` 已排期分片——原先仅以静音 30 ms 模拟中断，队列中的分片会在音量恢复后继续播放，抢话打断失效；退房时一并清空队列。

### 变更

- **WebUI 左侧导航精简**：`房间成员`、`人格与记忆` 为语音台页内的子标签，侧栏重复列出会与页内标签栏重叠。侧栏「语音」组仅保留 `语音台`（点击进入「会话控制」）。
- **`.gitignore` 补充**：新增 `/config.py.bak*` 与 `/private_key.py.bak*`。原规则仅覆盖 `/config.py` 与原子替换产生的 `/.config.py.*.bak`，手工备份存在被 `git add -A` 一并提交的风险（含 Oopz 账密与 JWT）。

### 测试

- 新增 `tests/test_gemini_live_url.py`（15 条）、`tests/test_voice_member_live_state.py`（32 条）与 `tests/test_tts_play_queue.py`（9 条）；全量 **145 passed**。

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

[2.0.1]: https://github.com/Eason4869/Ooptra/releases/tag/v2.0.1
[2.0.0]: https://github.com/Eason4869/Ooptra/releases/tag/v2.0.0
[1.0.0]: https://github.com/Eason4869/Ooptra/releases/tag/v1.0.0
