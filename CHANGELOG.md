# 更新日志

本文件记录 Ooptra 的对外变更，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

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

[1.0.0]: https://github.com/Eason4869/Ooptra/releases/tag/v1.0.0
