<p align="center">
  <img src="./src/webui/assets/logo.svg" width="80" alt="Ooptra 双对话桥 Logo" />
</p>

<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="Ooptra 把 Oopz 频道会话桥接到 OneBot v11" />
</p>

<p align="center">
  <a href="CHANGELOG.md"><img alt="当前版本 3.0.1" src="https://img.shields.io/badge/version-3.0.1-315DDC?style=flat-square"></a>
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

当前版本：**3.0.1**。WebUI 支持亮色／暗色切换，主题选择在当前浏览器保存。完整变更见[更新日志](CHANGELOG.md)。

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
| Web 控制台 | 状态总览、实时日志、配置编辑、账号与凭据管理；适配桌面和手机，支持暗色模式，前端不依赖外部框架或 CDN |
| 语音对话 | 可选模块：进 Oopz 语音房做 **Live 端到端语音**（类似 Gemini Live，语音进语音出），支持抢话打断 |
| 语音 API | 与控制台同端口的 `/voice/*`、`/persona`、`/memory` 及其 `/api` 别名，供外部插件调用 |
| 自动串门 | 分域独立启用，低频概率进房、限时告别退出、每日上限与持久化冷却；MiMo / Gemini 每次改写进退房语音 |
| 项目边界 | 单进程运行，不含内置命令、插件系统与消息存储，只做桥接与运维 |

## 运行链路

<p align="center">
  <img src="./assets/readme/runtime-map.svg" width="100%" alt="Oopz 与会话经过 Ooptra 的事件标准化和身份映射后，以 OneBot v11 反向 WebSocket 交给对端框架" />
</p>

事件标准化、身份映射、凭据维护与网络适配彼此独立；桥接内核与 Web 控制台在同一个进程内运行。

## 快速开始

需要 Git、Python 3.10 或更高版本。纯文字桥接只需运行时依赖；语音和网页版登录另需[可选依赖](#语音依赖)。

1. 获取代码并安装依赖：

   ```bash
   git clone https://github.com/Eason4869/Ooptra.git
   cd Ooptra
   python -m venv .venv
   ```

2. 激活虚拟环境、安装依赖并生成配置。Windows PowerShell：

   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   Copy-Item config.example.py config.py
   ```

   Linux / macOS：

   ```bash
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   cp config.example.py config.py
   ```

   使用账号密码登录时，填入 `OOPZ_CONFIG["login_phone"]` 与 `OOPZ_CONFIG["login_password"]`；
   也可启动后在「账号」页登录。其余凭据字段会在登录成功后自动写入。

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
| 配置 | 分为「连接」「语音模型」「系统」三个子页；不常用项收在右上角「高级选项」，保存写回 `config.py` |
| 账号 | 凭据状态与有效期、账号密码登录、网页版登录（可手动过验证） |
| 语音台 | 分为「会话控制」「自动串门」「房间成员」「人格与记忆」；模型、密钥和音色在「配置 → 语音模型」中设置 |

右上角的「暗色模式」开关可即时切换主题，登录页也可切换。默认亮色，刷新或重新打开后沿用当前浏览器的选择；
切换主题不会重新加载页面，也不会清空尚未保存的配置。浏览器禁止本地存储时，主题选择仅在当前页面有效。

侧栏「维护与账号」中提供「重新连接」「检查更新」「GitHub」和「退出登录」；手机端展开同名菜单即可访问。
「检查更新」会查询 GitHub 最新版本并与本地版本比较。连接设置变更后，可点击「保存并重新连接」重新建立桥接。

### 绑定到局域网

把 `WEBUI_CONFIG["host"]` 改成 `0.0.0.0` 可以让同网段的设备访问，但**务必同时设置 `token`**，否则任何人都能打开控制台。
设置令牌后访问需带上它：`http://<你的 IP>:3090/?token=<token>`。

## 语音对话

语音模块默认关闭。启用 `VOICE_AGENT_CONFIG.enabled` 后，bot 可以进入 Oopz 语音频道参与实时语音：

- **听**：订阅 Agora 远端音轨，按电平选择当前主讲人的音频；Live 持续输入 PCM，级联先经 VAD 切句再识别文字
- **想**：模型在语音域直接推理，或走「语音转文字 → 语言模型 → 文字转语音」的级联链路
- **说**：模型音频分片**流式**推回语音房，按时间轴排期播放，支持抢话打断（`barge_in`）
- **记**：人格提示词与共享记忆（`data/voice_memory.jsonl`）持久化，多端保持一致

### 两种后端

| 后端 | 取值 | 特点 |
| --- | --- | --- |
| Live 端到端语音 | `gemini_live`（默认） | 语音进、语音出，延迟低、语气自然；需要 Live 模型的配额与网络可达 |
| 级联 | `mimo_cascade` | ASR → LLM → TTS 三段式，延迟更高，适合没有 Live 配额时兜底 |
| OpenAI Realtime | `openai_realtime` | **骨架，协议尚未接入**，暂不可用 |

Live 模式下，**抢话打断由客户端判定**：某位成员连续说话达到 `barge_in_hold_ms`（默认 300 毫秒）后，
客户端清空当前播放并丢弃本回合剩余音频。服务端设置 `NO_INTERRUPTION`，避免背景人声持续打断生成。
客户端不会向服务端发送「说完了」之类的信号，以免把缓冲区里的音频碎片误当成一个完整回合。

Live 的原生音频模型**不支持指定输出语言**（官方文档：*Explicitly setting a language code is not supported for native audio output models*），
它依据输入音频自动选择。输入采用主讲人选择，而非把多人音轨按到达顺序拼接；人格提示词之后还会追加约束，要求用中文普通话作答。
这是提示词层面的约束，房间里长时间出现外语或纯音乐时仍可能失准。
`VOICE_AGENT_CONFIG.listen_only_uids` 可以限定只监听指定成员，减少无关声音的干扰。

### 控制台入口

先在「配置 → 语音模型」开启语音模块并设置后端、密钥、模型和音色，再在「语音台 → 会话控制」选择域与频道后进房／退房。
成员状态在「房间成员」子页查看，人格与共享记忆在「人格与记忆」子页管理。
「与 AI 对话」卡片用于**用文字发起一次对话**：AI 会在当前语音房用语音回答，和房间里说话属于同一场对话（需已进房）；
级联模式下不经过模型，直接朗读这段文字。

### 自动串门

先配置可用的语音后端并开启语音总开关，再打开「语音台 → 自动串门」，选择已加入的域，
勾选「允许在这个域自动串门」并保存。域开关默认全部关闭；旧版 `auto_join` 已移除，残留字段忽略且不会开启任何域。

| 默认规则 | 行为 |
| --- | --- |
| 检查间隔 | 全实例共用，每 10～20 分钟随机检查一次，不会看到有人立即进房 |
| 选择与概率 | 先在符合条件且有真人的域中等概率选域，再随机选房间，按该域概率决定是否加入；默认 20% |
| 停留 | 10～20 分钟；到期最多等 bot 当前回复 30 秒，告别语音生成及播放最多 20 秒，之后退出 |
| 自动退房冷却 | 全实例休息 30～60 分钟，期间仍可手动进房 |
| 手动退房冷却 | 刚退出的域休息 2～4 小时，其他开启域仍可串门 |
| 每日上限 | 北京时间自然日全实例默认 3 次；可另设域上限，0 为不限；手动进房及已确认失败不计数 |
| 空房 | 真人全部离开且连续确认 2 分钟后复查并静默退房；查询失败按未知处理 |

检查间隔只支持全局设置，其余策略可按域覆盖；取消覆盖恢复继承。每行一条进房／告别表达意图，随机选取后由当前 AI
每次改写：MiMo 使用文字生成与 TTS，Gemini 使用当前 Live 会话生成语音，无需额外 MiMo 密钥。
清空列表即静默，合成失败也会按正常停留／退出规则继续。台词不写作用户记忆，不会携带其他房间的聊天历史。

暂停只停止新的自动加入；已开始的自动停留仍会按规则退出。恢复不清空次数和冷却；关闭域开关会告别退出该域的自动房间。
手动房间始终由用户控制，不受自动换房、限时退出或域开关影响。退出失败会保留实际房间状态并暂停后续自动加入。

运行状态损坏、磁盘写入失败或中断进房留下未确认记录时，自动加入会暂停，文字桥接与手动操作仍可使用。
先检查控制台与日志，确认账号实际所在房间并手动退出，停止程序并备份 `data/voice_auto_visit.json`；
对未确认记录，应保守核对并补记当天成功次数及对应域次数，保持 `confirmed` 与计数一致，再清理对应 `pending`。
恢复文件后重启或点击恢复。不要直接删除状态文件绕过当日额度；尚未核清的记录应保持暂停。

详细设计与实施验收见 [需求说明](docs/superpowers/specs/2026-10-06-voice-auto-visit-design.md) 和
[实施计划](docs/superpowers/plans/2026-10-06-voice-auto-visit-brand-release.md)。本次自动化与匿名界面验证的范围见更新日志；
真实联调时分别检查 MiMo/Gemini 进房问候、到期尾音播完再退出、手动接管、空房退出及重启后额度仍在。

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
GET  /voice/auto-visit
POST /voice/auto-visit/config  {"updates":{...}}
POST /voice/auto-visit/pause
POST /voice/auto-visit/resume
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
域 ID / 频道 ID 可在「语音台 → 会话控制」页查看并一键复制，用于群绑定；选中目标后点**「设为默认」**可写入
`OOPZ_CONFIG.default_area` / `default_channel`，作为插件进房的默认目标。

### 语音依赖

语音对话与 WebUI 的「网页版登录」都需要 Playwright 和 Chromium。在已激活的虚拟环境中执行：

```bash
python -m pip install -r requirements-optional.txt
python -m playwright install chromium
```

未启用语音时行为与纯桥接一致，不会加载浏览器。语音模型 API 若需走代理，见下文 `VOICE_AGENT_CONFIG.proxy`。

## 关键配置

配置文件是 `config.py`：`OOPZ_CONFIG`、`ONEBOT_V11_CONFIG`、`WEBUI_CONFIG` 是桥接与控制台的主体，
`VOICE_AGENT_CONFIG`、`VOICE_API_CONFIG` 对应语音模块（默认关闭），`VOICE_AUTO_VISIT_CONFIG` 管理自动串门。
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
| `VOICE_AGENT_CONFIG.barge_in_hold_ms` | 连续说话达到此时长才打断 bot，默认 300 毫秒；人多时可适当调高 |
| `VOICE_AGENT_CONFIG.listen_only_uids` | 只监听这些成员的音频；留空表示整个房间 |
| `VOICE_AUTO_VISIT_CONFIG` | 自动串门全局规则、默认策略与分域覆盖；使用「语音台 → 自动串门」管理 |
| `VOICE_AGENT_CONFIG.gemini.voice` | Gemini Live 音色（Puck / Charon / Kore…，可自定义） |
| `VOICE_AGENT_CONFIG.mimo.tts_voice` | MiMo TTS 音色（冰糖 / 茉莉 / 苏打 / 白桦…，可自定义） |

更细的开关（心跳间隔、重连间隔、本地接入、域语义映射、采样率、静音判定时长等）都在控制台「配置」页的「高级选项」里，
默认值适用于绝大多数情况。「配置 → 语音模型」按后端和厂商展示 API Key、模型名与音色；
当前可用后端为 Gemini Live 和 MiMo 级联，OpenAI Realtime 仅为预留骨架，暂不可用。

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
| `data/voice_auto_visit.json` | 北京时间每日自动加入次数、两种冷却与未确认记录；重启保留，不应删除以重置上限 |
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

CI（`.github/workflows/ci.yml`）在每次 PR，以及 `main` / `dev` 推送时运行 Ruff 与 pytest，测试矩阵为 Ubuntu（Python 3.10 / 3.13）与 Windows（Python 3.13）。
`src/oopz_sdk/` 是内置 SDK，包含语音生命周期和播放完成检测的适配修复，不参与 lint 与类型检查。

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
- **回复偶发切成英文或其他语言**：Live 模型按输入音频自动选语言。可设置 `listen_only_uids` 只监听指定成员，
  或在人格里进一步强调语言要求。日志中 `Live 回合：` 一行会同时打印模型听到的转写与它的回复，可据此判断是听错还是答错。
- **成员列表的麦克风状态是「未知」或「未广播」**：该状态只由**同一 Agora 房间内**的客户端广播，跨频道或对方客户端未广播时无法得知，属正常现象。
- **想只听指定成员**：bot 只监听当前加入的语音频道，用 `listen_only_uids` 进一步限定成员；留空时按主讲人选择接收房间音频。

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
