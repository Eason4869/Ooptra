<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="Ooptra 把 Oopz 频道会话桥接到 OneBot v11" />
</p>

<p align="center">
  <a href="https://github.com/Eason4869/Ooptra/releases"><img alt="最新版本" src="https://img.shields.io/github/v/release/Eason4869/Ooptra?label=release&style=flat-square"></a>
  <a href="https://github.com/Eason4869/Ooptra/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/Eason4869/Ooptra?style=flat-square"></a>
  <a href="https://github.com/Eason4869/Ooptra/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Eason4869/Ooptra/ci.yml?style=flat-square&label=CI"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square&logo=python&logoColor=white">
  <a href="LICENSE"><img alt="许可" src="https://img.shields.io/badge/license-MIT-3ddc97?style=flat-square"></a>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#对端对接">对端对接</a> ·
  <a href="#web-控制台">Web 控制台</a> ·
  <a href="#语音对话">语音对话</a> ·
  <a href="#关键配置">关键配置</a> ·
  <a href="#目录结构">目录结构</a> ·
  <a href="#开发与测试">开发与测试</a> ·
  <a href="#常见问题">常见问题</a> ·
  <a href="CHANGELOG.md">更新日志</a>
</p>

Ooptra 把 Oopz 的频道会话转换为 [OneBot v11](https://github.com/botuniverse/onebot-11) 事件与动作，以
**反向 WebSocket** 接入任意 OneBot v11 实现——机器人框架、平台适配器或自研服务都可以，
两端只约定 OneBot v11 协议，不绑定任何具体框架。项目自带本地 Web 控制台，用来查看状态、跟踪日志、编辑配置和登录 Oopz；
另有一个可选的语音模块，让 bot 进入 Oopz 语音频道与人实时对话。

> [!CAUTION]
> Ooptra 是独立的第三方项目，与 Oopz 官方没有隶属或授权关系。请仅用于你自己的账号与你负责管理的社群，
> 并遵守 Oopz 的用户协议与当地法律；软件按“现状”提供，不作任何担保。

## 核心能力

| 场景 | 能力 |
| --- | --- |
| 接入方式 | OneBot v11 反向 WebSocket，本程序作为客户端主动拨出，默认 `universal` 角色，支持 `access_token` |
| 上行事件 | `message`（群 / 私聊）、`notice`（撤回）、`meta_event`（心跳、生命周期） |
| 下行动作 | 发送、撤回、消息查询、群与成员查询、禁言、踢人、退群、设置管理员等 OneBot v11 动作 |
| 身份映射 | `group_id` / `user_id` 与 Oopz 域、频道、成员双向映射，持久化在 SQLite，重启后编号稳定 |
| 凭据维护 | 账号密码或网页版登录；`device_id` / `person_uid` / `jwt_token` / RSA 私钥自动写回配置并自动重连 |
| Web 控制台 | 状态总览、实时日志、配置编辑、账号与凭据管理；前端单文件无外部依赖 |
| 语音对话 | 可选模块：进 Oopz 语音房做 **Live 端到端语音**（类似 Gemini Live，语音进语音出），支持抢话打断 |
| 语音 API | 与控制台同端口的 `/api/voice/*`、`/api/persona`、`/api/memory`，供外部插件调用 |
| 项目边界 | 单进程运行，不含内置命令、插件系统与消息存储，只做桥接与运维 |

## 运行链路

<p align="center">
  <img src="./assets/readme/runtime-map.svg" width="100%" alt="Oopz 与会话经过 Ooptra 的事件标准化和身份映射后，以 OneBot v11 反向 WebSocket 交给对端框架" />
</p>

事件标准化、身份映射、凭据维护与网络适配彼此独立；桥接内核与 Web 控制台在同一个进程内运行。

## 快速开始

需要 Python 3.10 或更高版本。

1. 获取代码并安装依赖：

   ```bash
   git clone https://github.com/Eason4869/Ooptra.git
   cd Ooptra
   python -m venv .venv
   # Windows: .venv\Scripts\activate    Linux / macOS: source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. 生成配置并填入 Oopz 账号：

   ```bash
   # Windows: copy config.example.py config.py    Linux / macOS: cp config.example.py config.py
   ```

   至少要填 `OOPZ_CONFIG["login_phone"]` 与 `OOPZ_CONFIG["login_password"]`，其余凭据字段会在首次登录成功后自动写入。

3. 启动：

   ```bash
   python main.py
   ```

4. 打开 `http://127.0.0.1:3090`，在「配置」页把**反向 WS 地址**改成对端的监听地址（示例默认 `ws://127.0.0.1:6200/ws`），
   保存并重新连接。概览页的「OneBot v11 反向 WS」显示已接入，就说明两端握手成功。

Windows 下可以双击 `start_silent.vbs` 静默后台启动；把它放进「启动」文件夹即可开机自启，
带参数启动（快捷方式目标后加 `delay`）会先等待 30 秒再拉起。

## 对端对接

反向 WebSocket 的方向是**本程序主动拨出、对端监听**。因此对端只需要提供一个 OneBot v11 反向 WS 服务端：

| 项目 | 说明 |
| --- | --- |
| 地址 | `ONEBOT_V11_CONFIG["ws_reverse_url"]`，例如 `ws://127.0.0.1:6200/ws`；路径由对端决定 |
| 令牌 | 对端要求校验时，把相同的值填进 `access_token`；两边都留空则跳过校验 |
| 分离端点 | 对端区分 API / Event 两个端点时，另外填 `ws_reverse_api_url` 与 `ws_reverse_event_url` |
| 连接角色 | 只填 `ws_reverse_url` 时以 `universal` 角色连接，事件与动作走同一条连接 |

如果对端反而是「等待客户端连入」的形态（本地 HTTP 或正向 WebSocket），打开 `enable_http` / `enable_ws`，
再让对端连到 `host:port`（默认 `127.0.0.1:6700`）；纯反向桥接场景不需要打开。

> `data/onebot_v11.sqlite3` 保存 `group_id` / `user_id` 映射，**请勿删除**，否则对端看到的群号与成员编号会全部变化。

## Web 控制台

默认只监听 `127.0.0.1:3090`。访问令牌留空即免登录，仅建议在本机使用时这样做。

| 页面 | 内容 |
| --- | --- |
| 概览 | 两条链路的连接状态、事件与动作吞吐、最近推送与最近指令；异常时直接给出重连入口 |
| 日志 | 实时跟随日志文件（SSE），支持关键字与级别过滤、清屏、下载、回到底部 |
| 配置 | 常用项直接改，其余默认值收在「高级选项」；保存即写回 `config.py` 并就地生效 |
| 账号 | 凭据状态与有效期、账号密码登录、网页版登录（可手动过验证） |
| 语音 | 语音台：会话控制、房间成员、人格与记忆三个子页；另有「语音模型」配置页 |

侧栏的「检查更新」会查询 GitHub 最新版本并与本地版本比较，可直接打开仓库。

### 绑定到局域网

把 `WEBUI_CONFIG["host"]` 改成 `0.0.0.0` 可以让同网段的设备访问，但**务必同时设置 `token`**，否则任何人都能打开控制台。
设置令牌后访问需带上它：`http://<你的 IP>:3090/?token=<token>`。

## 语音对话

语音模块默认关闭。启用 `VOICE_AGENT_CONFIG.enabled` 后，bot 可以进入 Oopz 语音频道参与实时语音：

- **听**：订阅 Agora 远端音轨，PCM **持续**灌入模型会话（不是先转文字）
- **想**：模型在语音域直接推理，或走「语音转文字 → 语言模型 → 文字转语音」的级联链路
- **说**：模型音频分片**流式**推回语音房，按时间轴排期播放，支持抢话打断（`barge_in`）
- **记**：人格提示词与共享记忆（`data/voice_memory.jsonl`）持久化，多端保持一致

### 两种后端

| 后端 | 取值 | 特点 |
| --- | --- | --- |
| Live 端到端语音 | `gemini_live`（默认） | 语音进、语音出，延迟低、语气自然；需要 Live 模型的配额与网络可达 |
| 级联 | `mimo_cascade` | ASR → LLM → TTS 三段式，延迟更高，适合没有 Live 配额时兜底 |

Live 模式下，**抢话打断由服务端自动 VAD 判定**：检测到有人插话时模型会取消当前生成，客户端随即清空本地已排期的音频。
客户端不会向服务端发送「说完了」之类的信号，以免把缓冲区里的音频碎片误当成一个完整回合。

Live 的原生音频模型**不支持指定输出语言**（官方文档：*Explicitly setting a language code is not supported for native audio output models*），
它依据输入音频自动选择；而输入是整个语音房间的混音。因此人格提示词之后会追加一条固定约束，要求一律用中文普通话作答——
这是当前可用的唯一杠杆，**属于提示词层面的约束而非强制**，房间里长时间出现外语或纯音乐时仍可能失准。
`VOICE_AGENT_CONFIG.listen_only_uids` 可以限定只监听指定成员，减少无关声音的干扰。

### 控制台入口

在「语音 → 会话控制」选择域与频道后进房/退房，可查看房间成员、编辑人格与共享记忆。
「与 AI 对话」卡片用于**用文字发起一次对话**：AI 会在当前语音房用语音回答，和房间里说话属于同一场对话（需已进房）；
级联模式下不经过模型，直接朗读这段文字。

### HTTP API

Web 控制台同时挂载 JSON API（与控制台同端口，默认 `3090`，复用 `WEBUI_CONFIG.token`）。**外部插件一律用这个入口**——它路由完整、契约是扁平的：

```http
GET  /health
GET  /voice/status
GET  /voice/members?area=&channel=
GET  /voice/channels?area=
POST /voice/join     {"area":"","channel":""}
POST /voice/leave
POST /voice/speak    {"text":"..."}
GET  /oopz/areas
GET  /oopz/channels?area=
GET  /persona        PUT /persona
GET  /memory         POST /memory   DELETE /memory
```

以上每个路径都另有 `/api` 前缀的等价别名（如 `/api/voice/status`），供控制台自身使用，两者由同一份实现生成，行为完全一致。

`VOICE_API_CONFIG`（默认 `3091`，默认关闭）只是给「不想走 WebUI 端口」的场景准备的**等价副本**：它挂载同一套 handler，
路由与响应结构完全一致（有测试断言两者路由集合相同），鉴权用 `VOICE_API_CONFIG.token`；开启时记得配 token，否则该端口无鉴权。

外部插件（如 [astrbot_plugin_ooptra](https://github.com/Eason4869/astrbot_plugin_ooptra)）调用这些接口时，令牌填 **`WEBUI_CONFIG.token`**（默认同端口）；
只有单独启用 `VOICE_API_CONFIG` 独立端口时才改用 `VOICE_API_CONFIG.token`。两边都留空则不校验。
域 ID / 频道 ID 可在「语音 → 会话控制」页查看并一键复制，用于群绑定；选中目标后点**「设为默认」**可写入
`OOPZ_CONFIG.default_area` / `default_channel`，作为插件进房的默认目标。

### 语音依赖

除运行时依赖外还需要 `playwright` 与 Chromium：

```bash
pip install -r requirements-optional.txt
python -m playwright install chromium
```

未启用语音时行为与纯桥接一致，不会加载浏览器。语音模型 API 若需走代理，见下文 `VOICE_AGENT_CONFIG.proxy`。

## 关键配置

配置文件是 `config.py`，四个分组分别对应 `OOPZ_CONFIG`、`ONEBOT_V11_CONFIG`、`WEBUI_CONFIG`、`VOICE_AGENT_CONFIG`。
控制台只改写白名单字段，其余内容与注释保持原样。

| 字段 | 说明 |
| --- | --- |
| `OOPZ_CONFIG.login_phone` / `login_password` | Oopz 账号；登录成功后自动写入并维护凭据 |
| `OOPZ_CONFIG.default_area` / `default_channel` | OneBot 调用没有指定目标时的兜底域 / 频道 |
| `OOPZ_CONFIG.proxy` | 网络出口：留空跟随系统代理，`direct` 直连，也可填 `http://主机:端口` |
| `ONEBOT_V11_CONFIG.ws_reverse_url` | 对端的反向 WS 地址，最常修改的一项 |
| `ONEBOT_V11_CONFIG.access_token` | 与对端一致的令牌 |
| `ONEBOT_V11_CONFIG.db_path` | 身份映射数据库路径 |
| `WEBUI_CONFIG.host` / `port` / `token` | 控制台监听地址、端口与访问令牌；语音 API 与外部插件默认也用这个 token |
| `VOICE_AGENT_CONFIG.enabled` | 是否启用语音模块，默认 `False` |
| `VOICE_AGENT_CONFIG.backend` | `gemini_live`（默认）或 `mimo_cascade` |
| `VOICE_AGENT_CONFIG.proxy` | 模型 API 代理（选填）：`clash` = `127.0.0.1:7890`，`direct` 直连，或显式 `http://主机:端口` |
| `VOICE_AGENT_CONFIG.barge_in` | 是否允许抢话打断，默认 `True` |
| `VOICE_AGENT_CONFIG.listen_only_uids` | 只监听这些成员的音频；留空表示整个房间 |
| `VOICE_AGENT_CONFIG.auto_join` | 启动后自动进入 `area` / `channel` |
| `VOICE_AGENT_CONFIG.gemini.voice` | Gemini Live 音色（Puck / Charon / Kore…，可自定义） |
| `VOICE_AGENT_CONFIG.mimo.tts_voice` | MiMo TTS 音色（冰糖 / 茉莉 / 苏打 / 白桦…，可自定义） |

更细的开关（心跳间隔、重连间隔、本地接入、域语义映射、采样率、静音判定时长等）都在控制台「配置」页的「高级选项」里，
默认值适用于绝大多数情况。「语音模型」配置页按所选 Live 厂商（Gemini / MiMo / OpenAI）展示对应的 API Key、模型名与音色下拉。

## 环境变量

除 `config.py` 外还支持环境变量覆盖，完整清单见 [`.env.example`](.env.example)，常用的有
`BOT_WEBUI_HOST`、`BOT_WEBUI_PORT`、`BOT_WEBUI_TOKEN`、`BOT_ONEBOT_REVERSE_URL`、`BOT_OOPZ_PROXY`。

> [!NOTE]
> 程序**不会**自动读取 `.env` 文件，`.env.example` 只是变量名的参照表。请把变量设进进程环境：
> Windows 用 `setx 变量名 值`（需重开终端）或 `$env:变量名 = "值"`（仅当前会话），Linux / macOS 用 `export`。

## 数据文件

| 路径 | 内容 |
| --- | --- |
| `config.py` | 你的配置与凭据，已在 `.gitignore` 中，**请勿提交** |
| `private_key.py` | 登录用的 RSA 私钥，自动生成，同样不入库 |
| `data/onebot_v11.sqlite3` | `group_id` / `user_id` 映射，删除会导致对端群号全部变化 |
| `data/names.json` | 成员与频道昵称缓存，可安全删除（会重新拉取） |
| `data/voice_memory.jsonl` | 语音共享记忆，删除即清空上下文 |
| `logs/oopz_bot.log` | 运行日志，控制台「日志」页读取的就是它；保留 7 天 |

## 目录结构

```
Ooptra/
├─ main.py                  入口：装配桥接内核与 Web 控制台
├─ config.example.py        配置模板（复制为 config.py）
├─ private_key.example.py   RSA 私钥模板
├─ start_silent.vbs         Windows 静默后台启动
├─ assets/readme/           README 插图
├─ src/
│  ├─ bridge/               桥接内核：控制器、反向 WS 服务、运行时状态
│  ├─ core/                 日志、路径、代理、配置读写、版本号
│  ├─ onebot_v11/           OneBot v11 协议模型与 SDK 接入、数据迁移
│  ├─ oopz/                 Oopz 业务层：凭据、昵称解析、代理传输
│  ├─ oopz_sdk/             随项目附带的 Oopz SDK 源码（不参与 lint）
│  ├─ voice_agent/          语音 Agent：编排、VAD、记忆、双工与模型后端
│  └─ webui/                Web 控制台、配置编辑、日志跟随、语音 HTTP API
└─ tests/                   pytest 用例
```

## 开发与测试

```bash
pip install -r requirements-dev.txt   # 运行时依赖 + ruff / pytest / pyright
ruff check .                          # 代码检查
pytest -q                             # 单元测试
pyright                               # 可选：类型检查
```

CI（`.github/workflows/ci.yml`）在每次 PR 上运行 ruff 与 pytest，测试矩阵为 Ubuntu（Python 3.10 / 3.13）与 Windows（Python 3.13）。
`src/oopz_sdk/` 是内置的上游 SDK 源码，保持与上游一致，不参与 lint 与类型检查。

> 本地跑测试会写入 `logs/oopz_bot.log`；CI 上的 `config.py` 由 `config.example.py` 生成，语音模块为关闭状态，
> 因此涉及语音的用例需要自己显式打开相关字段，不能依赖本机配置。

## 常见问题

**桥接**

- **反向 WS 一直未连接**：确认对端已启动反向 WS 服务端，地址、路径、`access_token` 三者与对端一致；跨机部署还要放行端口。
- **对端收不到消息内容**：Oopz 的频道消息以 `message_type=group` 上报，检查对端是否放行了群消息。
- **群号或成员编号变了**：`data/onebot_v11.sqlite3` 被删除或路径被改动，映射需要重新积累。
- **提示凭据无效**：JWT 过期时程序会尝试用账号密码自动续期；如果当初只导入了 JWT 而没有密码，请在「账号」页重新登录。
- **想让对端连进来**：打开 `enable_http` / `enable_ws`，让对端连到 `127.0.0.1:6700`。

**语音**

- **进房后完全没有反应**：按顺序检查——`VOICE_AGENT_CONFIG.enabled` 是否为 `True`、是否已安装 Playwright 与 Chromium、
  API Key 是否填对、日志里是否出现会话就绪。模型 API 在国内通常需要走代理，确认 `VOICE_AGENT_CONFIG.proxy` 可用。
- **退出重进或换频道后听不到它说话 / 听不到别人说话**：2.1.0 已修复此类资源残留问题，请先升级到最新版本。
- **回复偶发切成英文或其他语言**：Live 模型按输入音频自动选语言，而输入是整房混音。可开启 `listen_only_uids` 只监听指定成员，
  或在人格里进一步强调语言要求。日志中 `Live 回合：` 一行会同时打印模型听到的转写与它的回复，可据此判断是听错还是答错。
- **成员列表的麦克风状态是「未知」或「未广播」**：该状态只由**同一 Agora 房间内**的客户端广播，跨频道或对方客户端未广播时无法得知，属正常现象。
- **想让它只管当前频道**：默认会吞下整个房间的音频，用 `listen_only_uids` 收窄监听范围。

**Windows**

- **控制台中文乱码**：`main.py` 启动时会执行 `chcp 65001` 切到 UTF-8；若在自定义脚本里启动，请自行保证终端为 UTF-8 编码。
- **路径含空格或中文**：安装目录建议使用纯英文路径，避免 Playwright 与浏览器内核加载异常。

## 使用边界与许可

> [!IMPORTANT]
> 本项目采用 [MIT 许可](LICENSE)，是独立的第三方工具，与 Oopz 官方无隶属关系，也不对 Oopz 服务的可用性作任何保证。

- 请只在自己的账号与有权管理的社群中使用，不要用于骚扰、刷屏或对他人社群做批量自动化。
- `src/oopz_sdk/` 是随项目附带的 Oopz SDK 源码，版权归其原作者所有；如权利人提出异议，我们会移除或替换。
- 项目最初派生自社区项目 `Oopzbot`，当前仓库是围绕「纯 OneBot v11 反向桥接 + Web 控制台」重写后的版本。

## 社区与鸣谢

- [提交问题](https://github.com/Eason4869/Ooptra/issues)
- 协议参考：[OneBot v11](https://github.com/botuniverse/onebot-11)
- 文档组织与产品形态参考了 [SnowLuma](https://github.com/SnowLuma/SnowLuma)（无隶属关系）
