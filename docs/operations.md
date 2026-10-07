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

推荐在虚拟环境中运行 `python launcher.py`，以支持自动升级与回滚。`python main.py` 仍可直接运行桥接，但不能自动重启维护。Windows 可双击 `start_silent.vbs` 后台启动；
将其快捷方式放进「启动」文件夹可开机自启，快捷方式目标后加 `delay` 可延迟 30 秒启动。

WebUI 默认 `127.0.0.1:3090`，令牌留空时免登录。需要局域网访问时，设置 `host=0.0.0.0` 和非空 `token`，
从其他设备打开 `http://<部署机器的 IP>:3090/?token=<token>`，并按需放行防火墙端口。
未设置令牌的控制台仅建议在本机使用；独立语音 API 开放到其他设备时也需设置令牌。

主题选择在当前浏览器保存，切换不会刷新页面或清空未保存的配置；禁止本地存储时仅当前页面有效。

侧栏「检查更新」统一打开「更新与备份」，默认检查当前安装渠道；支持 main 正式版、beta 测试版及 dev 预览版，旧 Release / 标签 API 保留兼容。

### 自动升级与恢复

1. 使用官方 Git 仓库、Python 虚拟环境和 `python launcher.py` 启动；需保持代码干净，部署目录、维护目录和 Git 元数据可写，并预留至少 512 MB 空间（安装依赖可能需要更多）。Docker、压缩包和其他托管方式先手动更新。
2. 默认跟随当前安装渠道，也可在「更新与备份」选择其他渠道；跨渠道安装可能降级或改变功能，需明确确认目标提交。依赖在独立虚拟环境中准备，失败时当前服务继续运行；准备成功后关闭语音与数据库，创建最终备份并切换代码。
3. 启动新进程并检查 WebUI，失败时尝试恢复旧提交、数据及解释器。回滚仍失败时显示明确状态，请查看部署机器日志，用原环境手动启动。

升级在部署机器执行，与浏览器是否运行在局域网另一台机器无关；服务账户必须具备写入权限和 Git/pip 网络访问。远程维护必须配置 WebUI token。不覆盖本地代码改动，不提权，不执行浏览器传入的任意命令。

备份可下载，也可在 launcher 启动下恢复并重启。备份包含凭据与密钥；仅处理 `config.py`、`private_key.py` 和用户 `data/`，排除维护文件、缓存和日志，限制 1024 个文件、256 MB 原始内容；SQLite 使用在线备份。
恢复会先校验路径、大小与哈希，并创建恢复前备份；未列入备份的其他文件保留。恢复配置可能改变控制台端口或令牌，请用恢复后的配置重新访问。

维护文件保存在 `data/maintenance/`；成功升级选择的解释器保存在其中的 `runtime.json`，以后 launcher 会继续使用它。旧虚拟环境与备份保留供恢复，确认新版本稳定后再自行清理。

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
| AstrBot 图片发送失败 | 升级到包含图片适配修复的版本；支持 AstrBot 的 `base64://` 图片、图片 data URL 和部署机器本地文件。两端分机部署时请使用 Base64，另一台机器的本地路径无法直接读取 |
| `/helps` 等指令后多出 AI 回复 | 先检查指令结果是否发送失败。部分 AstrBot 版本会在图片发送失败后继续进入 LLM；图片发送恢复后仍出现，请检查对应插件是否结束事件 |
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
