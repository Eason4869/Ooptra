# 配置与维护指南

[返回 README](../README.md) · [语音与 API 指南](voice-guide.md) · [配置模板](../config.example.py)

## 配置文件

首次使用将 `config.example.py` 复制为 `config.py`。WebUI 保存配置时只改写白名单字段，保留其他内容与注释。
常用设置位于「配置」页，心跳、重连、本地接入、域语义映射、采样率与静音判定等位于「高级选项」。

| 配置组 | 常用字段 |
| --- | --- |
| `OOPZ_CONFIG` | `login_phone` / `login_password`：登录账号；`default_area` / `default_channel`：默认目标 |
| `OOPZ_CONFIG.proxy` | 留空跟随系统代理，`direct` 直连，或填写 `http://主机:端口` |
| `ONEBOT_V11_CONFIG` | `ws_reverse_url`：对端地址；`access_token`：对端令牌；`db_path`：身份映射数据库 |
| `WEBUI_CONFIG` | `host` / `port` / `token`：控制台地址、端口与令牌，默认也供语音 API 使用 |
| `VOICE_AGENT_CONFIG` | 语音开关、后端、概率、关键词、退房控制、人格、抢话、监听范围与模型设置，见[语音指南](voice-guide.md) |
| `VOICE_AUTO_VISIT_CONFIG` | 检查间隔、每日上限、默认策略与分域覆盖；在「语音台 → 自动串门」管理 |
| `VOICE_API_CONFIG` | 默认关闭的独立语音 API 端口与令牌 |

语音模型代理 `VOICE_AGENT_CONFIG.proxy` 与 Oopz 网络代理分别设置：
`clash` 默认指向 `127.0.0.1:7890`，`direct` 直连，也支持显式 HTTP 地址；SOCKS 代理需要可选依赖。
Gemini 音色字段为 `gemini.voice`，MiMo 为 `mimo.tts_voice`，可在 WebUI 填写自定义音色。

## 环境变量

完整清单见 [`.env.example`](../.env.example)，常用项有 `BOT_WEBUI_HOST`、`BOT_WEBUI_PORT`、
`BOT_WEBUI_TOKEN`、`BOT_ONEBOT_REVERSE_URL`、`BOT_OOPZ_PROXY`。

程序**不会自动读取 `.env` 文件**，需把变量设进启动进程的环境：

- Windows PowerShell：`$env:变量名 = "值"`，仅当前会话；`setx 变量名 值` 持久保存后需重开终端。
- Linux / macOS：`export 变量名="值"`，然后在同一终端启动程序。

## 启动、访问与更新

需要 WebUI 自动更新时，在虚拟环境中使用 `python launcher.py` 启动。`python main.py` 仍可直接启动，但不能执行自动更新或恢复。Windows 可双击 `start_silent.vbs` 后台启动管理器，同样支持自动更新；
将其快捷方式放进「启动」文件夹可开机自启，快捷方式目标后加 `delay` 可延迟 30 秒启动。

WebUI 默认 `127.0.0.1:3090`，令牌留空时免登录。需要局域网访问时，设置 `host=0.0.0.0` 和非空 `token`，
从其他设备打开 `http://<部署机器的 IP>:3090/?token=<token>`，并按需放行防火墙端口。
未设置令牌的控制台仅建议在本机使用；独立语音 API 开放到其他设备时也需设置令牌。

主题选择在当前浏览器保存，切换不会刷新页面或清空未保存的配置；禁止本地存储时仅当前页面有效。

「维护」页与侧栏「检查更新」按所选分支的最新提交检查：`main` 正式版、`beta` 测试版、`dev` 预览版。默认使用当前安装分支，切换来源后需重新检查；跨分支安装前会提示可能降级或改变功能，并要求确认。

自动更新需要官方 Git 仓库、干净的工作区、虚拟环境、可写目录及足够磁盘空间，并通过 `launcher.py` 启动。维护页会先列出部署预检查结果，准备环境和备份时服务继续运行，准备完成才关闭旧会话并切换版本。新进程身份、本地启动和桥接监督检查失败时回滚；Oopz / OneBot 外部连接暂时不可用只显示降级，不因此回滚。其它部署方式先下载备份，再手动更新代码、安装依赖并重启。

版本与备份列表独立读取，部署预检查和存储统计分别加载；其中一项失败不会阻塞其他内容。检查更新总等待上限为 60 秒，失败后可直接重试；备份列表无需访问 GitHub。

### 更新代理与镜像

在「更新与备份」的网络设置中配置部署机器的更新代理和 Git 镜像，保存后下一次更新操作生效。对应配置为 `WEBUI_CONFIG.update_proxy` 和 `WEBUI_CONFIG.update_mirror`，不改变 Oopz 或语音模型的代理。

- 代理留空时使用部署进程的网络环境；可填写 `http://127.0.0.1:7890` 等实际可用地址。这里的 `127.0.0.1` 指部署机器，局域网浏览器所在设备无需安装代理。
- 镜像填写支持 Git 传输的完整 HTTPS 仓库地址，可使用自行维护的国内同步仓库或 GitHub Git 加速地址。普通网页、Release 或压缩包下载镜像不一定支持 Git。默认保留官方源，不内置第三方地址。
- 官方 Git 查询失败后尝试官方 GitHub API；配置了镜像时，代码拉取失败可通过镜像重试。安装前必须与官方查询到的目标提交一致，镜像同步滞后或无法验证官方提交时停止更新。

Git 镜像仅加速代码传输，Python 依赖与 Chromium 下载仍取决于部署机器的网络。更新保留官方 `origin`、全局 Git 设置和证书校验。


## 数据文件与备份

| 路径 | 内容与注意事项 |
| --- | --- |
| `config.py` | 配置与登录凭据，已忽略，不要提交 |
| `private_key.py` | 自动生成的 RSA 私钥，已忽略，不要提交 |
| `data/onebot_v11.sqlite3` | 群与成员 ID 映射；删除或换路径会改变对端编号 |
| `data/names.json` | 昵称缓存，可删除后重新拉取 |
| `data/voice_memory.jsonl` | 语音共享记忆，删除会清空上下文 |
| `data/voice_auto_visit.json` | 自动加入次数、冷却和未确认记录，重启保留；不要删除以重置额度 |
| `logs/oopz_bot.log` | WebUI 读取的运行日志，保留 7 天 |

升级或迁移前，停止程序并备份 `config.py`、`private_key.py` 与 `data/`。
自动串门状态异常时先暂停并核对实际房间，恢复步骤见[语音指南](voice-guide.md#状态异常与恢复)。

## 故障排查

| 现象 | 检查方向 |
| --- | --- |
| 反向 WS 未连接 | 对端需提供反向 WS 服务端；核对地址、路径、令牌及跨机端口 |
| 对端收不到频道消息 | 频道消息以 `message_type=group` 上报，检查对端群消息设置 |
| 群或成员编号变化 | 核对身份映射数据库是否被删除或更换路径 |
| 凭据无效 | 有账号密码时尝试自动续期；只导入 JWT 时在「账号」页重新登录 |
| 需要本地 HTTP / 正向 WS | 开启 `enable_http` / `enable_ws`，默认地址 `127.0.0.1:6700` |
| 语音无反应 | 依次检查语音开关、Playwright / Chromium、API Key、模型代理、会话就绪日志和回复概率 |
| 退房、重进或换频道后异常 | 先核对部署版本、实际房间和日志；重试后仍异常，请附日志提交问题 |
| 语音回复切换语言 | 检查 `Live 回合：` 转写与回复，限定监听成员或调整人格，详见[语音指南](voice-guide.md#后端与手动开口) |
| 麦克风状态「未知／未广播」 | 仅同一 Agora 房间内客户端广播此状态，跨频道或未广播时无法得知 |
| Windows 中文乱码 | 入口会切换 UTF-8；自定义启动脚本请保证终端编码，可使用 `chcp 65001` |
| 浏览器内核加载失败 | 检查可选依赖与 Chromium 是否安装；同时排查安装路径，优先尝试英文路径 |

## 开发说明

```text
Ooptra/
├─ main.py                  桥接与 WebUI 入口
├─ config.example.py        配置模板
├─ private_key.example.py   RSA 私钥模板
├─ start_silent.vbs         Windows 后台启动
├─ assets/readme/           README 插图
├─ docs/                    使用指南与设计记录
├─ src/
│  ├─ bridge/               桥接内核与运行状态
│  ├─ core/                 配置、日志、路径、代理与版本
│  ├─ onebot_v11/           OneBot v11 协议与映射
│  ├─ oopz/                 Oopz 业务层
│  ├─ oopz_sdk/             内置 SDK
│  ├─ voice_agent/          语音编排、记忆与模型后端
│  └─ webui/                控制台与 HTTP API
└─ tests/                   pytest 用例
```

检查命令见 [README](../README.md#开发与测试)，CI 配置见 [ci.yml](../.github/workflows/ci.yml)。
内置 SDK 包含语音生命周期与播放完成检测的适配修复，不参与 Ruff 与类型检查。
本地测试会写运行日志；CI 从示例生成 `config.py`，语音默认关闭，语音用例需显式设置相关字段，不依赖本机配置。
