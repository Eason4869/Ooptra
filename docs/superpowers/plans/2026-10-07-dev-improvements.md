# 261007-dev 优化与维护修复实施计划

> **For agentic workers:** Use the dispatching-parallel-agents skill for the independent maintenance, voice and frontend domains. Integrate and run one fresh whole-change review before publication.

**Goal:** 保留 beta 快照，实现已讨论的功能、代码、易用性、维护和界面改进，并修复更新／备份按钮无反应。

**Architecture:** 维护与语音保持独立服务边界，前端按页面职责提取脚本。网络图片在 OneBot 边界读取并复用 SDK 上传；所有网络操作限制时间和大小。已有进退房、概率、分域串门、关键词和回滚行为兼容。

**Tech Stack:** Python 3.10+、aiohttp、现有 SDK、原生 JavaScript／CSS、pytest、Playwright 浏览器验收。

**Spec:** 本聊天中的 beta 优化建议及用户对整轮实施、beta 快照、更新／备份按钮修复和 dev 发布的授权。

## Global Constraints

- 发布版本 `261007-dev`，目标分支 `dev`；`beta` 固定为优化前的 `a874ab950c1b051e620a82b3fe35478f5a0dd9e3`。
- 不删除现有功能；常用项直达，复杂项进入二级菜单／高级设置。
- 模糊语音退房、默认 30% 回复和 0% 时可退房保持有效；优化不得以固定词过滤取代意图判断。
- 保留凭据、数据、当前运行环境及回滚材料；清理必须先预览再由控制台使用者确认，不自动删除。
- 核心仓库与外部 AstrBot 插件保持独立，本轮只修改核心仓库。

## Review Focus

- 页面初始脚本错误不能让维护按钮静默失效；加载失败应显示可理解的状态。
- 草稿在离开页面、换配置分组、异步重新读取时不能丢失，显式放弃和保存后才能清空。
- 概率跳过／短句／错误／关键词／连续窗口均有决策记录，记录不保存原始音频、不泄露密钥。
- URL 图片超时、非图片、重定向和过大内容不能无限下载，也不能把外部 URL 当已上传附件。
- 网络暂时不可用不能误触发升级回滚；进程身份校验、版本启动失败回滚保持有效。
- 清理不得触及当前解释器、浏览器、活动任务或受保护回滚备份。

## Tasks

### 1. 分支快照与发布基线
- [x] 核对工作区干净，读取远端 dev。
- [x] 创建并推送 beta，验证 beta 与优化前 dev SHA 完全一致。

### 2. 维护按钮、统一更新与分层健康
Files: `src/webui/maintenance*.py`, `src/webui/assets/maintenance.js`, maintenance tests.
- [x] 写能重现按钮／更新链路失效的回归，定位根因后修复。
- [x] 统一更新来源、当前／目标提交、维护支持能力，保留旧 API 兼容。
- [x] 展示进程、Oopz、OneBot 的分层健康；连接离线显示降级，不按外部网络状态回滚。
- [x] 增加备份分页、存储占用、清理预览／确认接口，保护运行与回滚材料。
- [x] 验证维护、恢复、清理及真实子进程演练。

### 3. 语音决策、自检与请求优化
Files: `src/voice_agent/diagnostics.py`, backends, agent, new focused observation module, voice tests.
- [x] 有界记录回复／跳过原因和 ASR、意图、聊天、TTS 耗时，通过状态 API 提供。
- [x] 合并可合并的 MiMo 意图／聊天调用；未选中普通回复仍识别退房，失败路径保持保守。
- [x] 提供短句音频自检，分阶段验证 ASR／意图／TTS，不进入房间、不写共享记忆。
- [x] 验证两后端概率、连续窗口、强制关键词与离场语兼容。

### 4. 草稿、页面模块、手机与浏览器 CI
Files: `src/webui/assets/app.js`, new page scripts, `index.html`, `style.css`, browser tests and CI.
- [x] 回归草稿跨页／分组保留、离开确认、明确放弃与保存摘要。
- [x] 按职责提取配置和语音页面代码，既有全局接口保持兼容。
- [x] 展示语音决策与阶段耗时、维护存储／清理及分层健康，统一更新入口。
- [x] 移动端常用会话操作可达，统一按钮忙碌／错误状态，保留所有高级项。
- [x] 浏览器真实点击覆盖维护按钮、配置草稿、暗色、手机布局、试听和重启恢复，纳入 CI。

### 5. 网络图片兼容
Files: OneBot image conversion/resolution, new image-source helper, image tests.
- [x] 网络图片先有限下载、校验后上传，JSON／CQ 行为一致。
- [x] 测试正常发送、重定向、失败、超时、大小边界与已有 Base64／文件兼容。

### 6. 文档、曝光统计与发布
- [x] 版本及 README／CHANGELOG／图示统一为 `261007-dev`；曝光计数统一展示并说明 GitHub Traffic 口径。
- [x] 完整 Python 3.10／3.12 测试、Ruff、浏览器验收及独立代码审查。
- [x] 推送 dev，等待 CI 全部通过，核对 beta 快照未变。

## 本地验收记录

- Python 3.12：629 passed、1 skipped（24.55 秒）；Python 3.10：629 passed、1 skipped（26.39 秒）。跳过项需要当前 Windows 账户不具备的符号链接权限。
- Ruff 与 Git diff 空白检查通过；真实 Edge 浏览器验收通过，包含生产 ISO 时间、超时正文读取、草稿保留、维护点击／失败／重启恢复、试听停止、WAV 诊断、暗色与手机布局。
- 独立全量审查通过；发现的时间显示、detached 更新来源及 Live 自检迟到响应问题均先复现再修复。审查者独立回归 64 passed、1 skipped。
- 升级与失败回滚有真实受控子进程演练；模型和房间接口使用模拟，不代替真实 Oopz／模型账户联调。
- 优化前 beta 快照：`a874ab950c1b051e620a82b3fe35478f5a0dd9e3`；发布前远端 dev 同 SHA，main 保持 `c34d3d5618a0de95053ded680f5a9679a52ab45e`。

## 发布验收

- 功能与浏览器修订已推送 dev：`32bed0f3537dacf89bdfcbb660c2b9deeb353339`，版本 `261007-dev`。
- [GitHub CI](https://github.com/Eason4869/Ooptra/actions/runs/37589569508) 的五项检查全部成功：Ruff、Ubuntu Python 3.10／3.13、Windows Python 3.13、Linux Chromium 浏览器。
- 首轮 Linux 浏览器 CI 暴露旧 toast 干扰等待的问题；保留旧提示并延迟响应可确定性复现，改为等待当前维护页面错误后通过。
- beta 仍为原始快照 `a874ab950c1b051e620a82b3fe35478f5a0dd9e3`，main 未改动。此记录与部署指南随后同步到同一 dev 版本。
