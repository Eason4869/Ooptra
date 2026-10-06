# Ooptra 自动语音串门与品牌改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 实现已确认的分域自动语音串门，更新 Logo 与 WebUI，验证后以 v261006-beta 推送到 dev。

**Architecture:** 设置／持久状态、语音生命周期／AI 表达、调度策略分别负责各自概念，由 VoiceRuntime 装配。WebUI 通过受鉴权的配置和状态接口管理，不依赖页面保持打开。品牌前端、配置状态、语音表达可在明确文件边界下并行，主执行者负责调度、接口和整体验证。

**Tech Stack:** Python 3.10+、asyncio、aiohttp、现有 MiMo/Gemini、Playwright/Agora、原生 HTML/CSS/JS、SVG、pytest、Ruff。

**Spec:** `docs/superpowers/specs/2026-10-06-voice-auto-visit-design.md`（含用户后续授权的品牌与发布增补）。

## Global Constraints

- 基线 dev/941c79364cee24abbfc63790d6f580e6c4231817（2.3.0）；在隔离工作区 codex/261006-beta 实施，保留本地主目录与真实配置。
- 域开关默认关闭。删除旧 auto_join，但忽略旧配置残留，不自动迁移成开启。
- 检查全实例 10～20 分钟；默认概率20%、停留10～20分钟、全局自动冷却30～60分钟、仅退出域手动冷却120～240分钟。
- 公平选有人域，再公平选房；一轮只抽一次概率，最多尝试一个房间。
- 空房连续确认120秒后静默退出；到期等当前 bot 回复最多30秒，开场／告别总超时20秒。
- 进退意图每次由当前 AI 改写；MiMo LLM→TTS，Gemini 同会话模拟指令；不缓存语音绕过改写，不额外要求 Gemini 用户配置 MiMo。
- 北京时间每日总成功自动入房上限3次，可额外分域限额；0不限；失败／手动不计；跨日／重启保留冷却与可信计数。
- 保留旧 API、别名、鉴权、状态字段、QQ 手动控制；不新增插件指令，不改 main，不强推，不接真实账号做无人监督验收。
- 前端实用、美观、直观，不精简或删除已有功能；可用二级菜单／高级设置收纳低频项，逐项核对功能保留。
- 每个实现任务先有针对性的失败测试再修复，完成后跑对应测试。视觉调整以浏览器检查为主，不写镜像式 CSS 测试。
- 版本单一来源261006-beta，保留 RELEASE_BASE_VERSION；远端 dev 若变化先核对并整合，再普通推送。

## Review Focus

- 手动换房与晚到回调：旧自动计时器、模型音频、告别不得操作新房（Task2/4回归）。
- 真实播放尾音：finish、模型turnComplete或接口成功都不等于Agora音频播完（Task2/3测试＋Task6实房验收）。
- 配额文件损坏／崩溃在途／跨日回拨：不得静默清零、假计成功或突破上限（Task1/4回归）。
- 保存域覆盖／热更新：显式空列表不变成继承，修改一域不覆盖另一域，关闭域结束自动房间（Task1/5回归）。
- 多域低频与未知人数：不补抽概率、不把请求失败当空房、不因enter事件立即进房（Task4回归）。

## Task 0: 隔离、环境与基线

**Files:** 执行工作区与本计划，不修改真实 config.py/private_key.py。
**Interfaces:** 后续任务使用独立工作区；测试解释器可复用现有 `_fix_261001_beta/.venv/Scripts/python.exe`，不复制真实凭据。

- [x] 核对 AGENTS、Git 基线与 dev 分支；创建隔离 worktree，保存本需求和计划。
- [x] 运行 `python -m pytest -q -p no:cacheprovider --tb=short`；Expected: 全部通过，记录真实数量；测试生成的占位配置不提交。
- [x] 建立 git-ignored `.superpowers/sdd/2026-10-06-voice-auto-visit-brand-release/progress.md`，记录任务、接口、验证和偏差；不反复扫描旧会话。

## Task 1: 配置验证与可信持久状态

**Files:** Create `src/voice_agent/auto_visit_settings.py`, `src/voice_agent/auto_visit_state.py`, `tests/test_auto_visit_settings.py`, `tests/test_auto_visit_state.py`。
**Interfaces:**
- `AutoVisitConfig` 保存 `check_interval_minutes: tuple[float,float]`、`daily_limit:int`、`defaults:dict`、`areas:dict`；配置对象为经过验证的快照。
- `parse_auto_visit_config(raw: Mapping[str,Any] | None) -> AutoVisitConfig`；`effective_area(config:AutoVisitConfig, area:str) -> dict[str,Any]` 返回 enabled、概率、时间范围、台词和域上限。
- `merge_auto_visit_patch(raw: Mapping[str,Any], patch: Mapping[str,Any]) -> dict[str,Any]` 按域／字段合并；override字段null表示删除恢复继承；缺失不改，空台词列表保留。
- `AutoVisitStateStore(path: str | Path)`；`load() -> None`；`snapshot(now:datetime) -> dict`；`can_join(area:str, now:datetime, global_limit:int, area_limit:int) -> bool`。
- `reserve(visit_id:str, area:str, now:datetime) -> None`；`confirm(visit_id:str, area:str, now:datetime) -> None`；`rollback(visit_id:str) -> None`；`set_global_cooldown(until:datetime) -> None`；`set_area_cooldown(area:str, until:datetime) -> None`。IO失败抛可读异常，未确认预留单独呈现；同visit_id确认幂等。

- [x] 先写测试：默认10/20、0.2、120/240、上限3；空台词不继承；null恢复；域隔离；非法／非有限参数拒绝。RED命令：`python -m pytest tests/test_auto_visit_settings.py tests/test_auto_visit_state.py -q`，Expected: 新模块缺失导致失败。
- [x] 写持久测试：三次确认后拒绝第四次；重复确认不增加；失败回滚不增加；UTC16:00切换北京时间日期；重启保留全局／域冷却；已有坏文件报错不清零；注入写入失败保留旧文件；pending不伪装成功。
- [x] 实现纯验证／合并、UTC+8日期、原子状态文件与幂等计数；避免未验证dict向下流动，提供明确键值文档。
- [x] GREEN：重跑上述测试全部通过；提交独立实现与测试。

## Task 2: 语音操作协调与真实播放完成

**Files:** Modify `src/voice_agent/agent.py`, `src/voice_agent/duplex.py`, `src/oopz_sdk/transport/voice_browser.py`, `src/oopz_sdk/assets/voice/agora_player.html`；Create `src/voice_agent/operations.py`, `tests/test_voice_operations.py`, `tests/test_tts_completion.py`。
**Interfaces:**
- `VoiceOperation(kind:str, source:str, area:str, channel:str, visit_id:str)`；`VoiceAgent.set_operation_callback(handler: Callable[[VoiceOperation], Awaitable[None]] | None)`，成功事件在操作锁释放后通知。
- 扩展兼容接口：`join(area='', channel='', *, source='manual', visit_id='') -> dict`；`leave(*, source='manual', expected_visit_id=None) -> dict`。旧调用默认manual；stale自动退出不操作新房。
- `is_auto_visit_current(visit_id:str) -> bool`；`wait_for_reply_end(timeout:float=30.0) -> bool`；`stop_current_reply() -> None`。追踪生成中和播放中，不能只看speaking。
- Transport／Duplex `wait_tts_complete(timeout:float) -> dict`，返回ok或error；浏览器 `agoraTtsStatus()` 返回pending sources与剩余时长。队列真正耗尽才完成。

- [x] RED：写并发join/leave、旧visit_id拒绝、手动抢占、生成未出音频仍忙、source默认manual、尾音未播完不算完成等行为测试。
- [x] 实现统一语音操作锁／代号与可取消等待，保持现有回合／节流／抢话；离开异常不能假报成功。
- [x] 删除 settings.py／agent.py 的旧 auto_join类型、加载和启动；更新相关既有测试，使旧config残留不会启用自动串门。
- [x] GREEN：`python -m pytest tests/test_voice_operations.py tests/test_tts_completion.py tests/test_tts_play_queue.py tests/test_voice_settings_reload.py -q`，Expected: 全通过；提交。

## Task 3: 每次 AI 改写的进退房表达

**Files:** Create `src/voice_agent/announcements.py`, `tests/test_voice_announcements.py`；Modify `src/voice_agent/agent.py`, `src/voice_agent/backends/mimo_cascade.py`, `src/voice_agent/backends/gemini_live.py`。
**Interfaces:** `VoiceAgent.speak_announcement(kind:str, template:str, *, expected_visit_id:str, timeout:float=20.0) -> dict`，返回ok/text/error；kind只允许enter/leave。

- [x] RED：MiMo调用改写再TTS；Gemini只用当前Live；模板不变成真人记忆；无MiMo密钥也能走Gemini；每次请求AI；空结果／无音频／超时退出；尾音完成才返回。
- [x] 实现事件意图包装和persona复用，目标1～2句／35字，复用净化；不注入跨房历史。不改普通speak_text契约。
- [x] 开场／告别期间暂停新输入；完成、失败、取消后恢复；手动抢占立即使旧表达失效。Gemini旧回合无法真正取消时，超时路径有界重建会话后告别，不能混播旧回合。
- [x] GREEN：`python -m pytest tests/test_voice_announcements.py tests/test_gemini_session_lifecycle.py tests/test_voice_agent_live_bargein.py -q`，Expected: 全通过；提交。

## Task 4: 低频调度、日额度与差异冷却

**Files:** Create `src/voice_agent/auto_visit.py`, `tests/test_auto_visit_controller.py`, `tests/auto_visit_fakes.py`。
**Interfaces:** `AutoVisitController(agent, config:AutoVisitConfig, store:AutoVisitStateStore, *, clock=None, rng=None)`；`start()/stop()/reload(config)/pause()/resume()` 为async；`set_bot_ready(ready:bool)` 与 `notify_presence(area:str, channel:str)`不阻塞事件流；`on_operation(event:VoiceOperation)` 为async；`status() -> dict`。
- 时钟注入 `utcnow()->datetime`、`monotonic()->float`、`sleep(seconds)->Awaitable[None]`；随机源提供choice/uniform/random，默认标准库。
- status使用phase/paused/pause_reason/next_check_at/leave_at/global_cooldown_until/day/daily_count/daily_limit/areas/last_action/last_error；时间是UTC ISO字符串，空时间为null。

- [x] RED：可推进的假时钟／随机源测试首轮等600～1200秒；候选两域不因房间数加权；一次概率不命中不补抽；请求失败不当空房；并发请求≤4。
- [x] RED：成功三次封顶；午夜、持久恢复、损坏状态暂停；自动冷却1800～3600秒阻止所有域；manual7200～14400秒只阻止退出域；manual不受quota影响。
- [x] RED：停留600～1200秒；最多等回复30秒；空房120秒且退出前复查；未知结果打断空房确认；关闭域告别；手动抢占不被旧退出任务影响；每个失败回合最多一次加入。
- [x] 实现Spec算法、代号取消、事件／60秒补查、失败退房三次重试、计数预留／确认；退出失败与持久状态不可信时暂停并保留真实房间信息。
- [x] GREEN：`python -m pytest tests/test_auto_visit_controller.py -q`，Expected: 全通过、不真实等待分钟；提交。

## Task 5: Runtime、API 与原子热配置

**Files:** Modify `src/voice_agent/runtime.py`, `src/bridge/app.py`, `src/webui/config_editor.py`, `src/webui/server.py`, `src/webui/voice_routes.py`, `config.example.py`；Create `tests/test_auto_visit_api.py`, `tests/test_auto_visit_runtime.py`。
**Interfaces:** 下列路由同时有/voice与/api/voice别名，成功保持原ok结构：
- GET `/voice/auto-visit` 返回 `config`（原始完整设置）与 `status`（Task4）。
- POST `/voice/auto-visit/config` body `{"updates": {...}}`：只写提交字段，返回config/status；原子落盘后在主事件循环reload。
- POST `/voice/auto-visit/pause`、`/resume` 返回status；恢复不清额度／冷却。
- 旧status追加auto_visit，不更改旧state；旧join/leave默认manual，根路径与API别名及独立端口共享一个控制器。

- [x] RED：鉴权、非法域／配置400、原子合并两域、空列表、null继承、写盘失败不部分生效、旧API默认manual、旧插件状态字段、两个端口共用状态。
- [x] Runtime装配controller/store，绑定operation callback与ready／presence；teardown及时取消；语音开关／桥接重建不重复启动。增加受限auto_visit配置分组，映射对象不走字符串coerce。
- [x] GREEN：`python -m pytest tests/test_auto_visit_api.py tests/test_auto_visit_runtime.py tests/test_voice_api_routes.py tests/test_config_editor.py -q`，Expected: 全通过；提交。

## Task 6: 原创 Logo 与 WebUI 改版

**Files:** Create `src/webui/assets/logo.svg`, `src/webui/assets/favicon.svg`（必要的readme品牌资源）；Modify `src/webui/assets/index.html`, `app.js`, `style.css` 与静态资产路由；不改后端控制器文件。
**Interfaces:** 使用Task5已定API；保留现有DOM id／功能绑定。未完成API时用本地固定响应做视觉验收，不把假数据提交成实际运行行为。

- [x] 先记录设计tokens与布局：冷白#F5F8FC、浅蓝灰#E7EEF7、深海蓝#173451、钴蓝#315DDC、青绿#167F7A、警示琥珀#B66B17；中文系统字体；导航／运行区／配置区／日志明确层级。
- [x] 设计原创双对话环／桥接SVG，保证16px和32px辨认、无外部字体／资源；用于导航、favicon、README品牌展示。
- [x] 优化所有现有页面响应式和交互层级；新增自动串门状态与配置界面，区分全局设置、继承覆盖、两种冷却与额度。
- [x] 使用真实本地后端或专用可识别fixture做1440px／390px截图；检查控制台错误、横向溢出、键盘焦点、减少动态效果、复制／保存／切域功能；修复布局问题。
- [x] JS语法检查与现有WebUI回归通过后提交；不为纯视觉写镜像测试。

## Task 7: 集成审查、版本与推送

**Files:** Modify `src/core/version.py`, `README.md`, `CHANGELOG.md`、按需版本相关测试；保存验收证据，不提交凭据／日志／运行状态文件。

- [x] 全量 `python -m pytest -q -p no:cacheprovider --tb=short`、`python -m ruff check .`、`git diff --check`；Expected: 全通过。
- [x] 独立审查完整差异与Spec，覆盖正确性、架构、权限、资源、UI；重要发现补失败测试后修复，再跑受影响测试／全量检查。
- [x] WebUI用本地匿名fixture验证；真实Oopz/MiMo/Gemini验收如无授权账号条件则明确未验证，不把fixture当实房。给出真实验收步骤和恢复默认方法。
- [x] 设置单一版本 `261006-beta` 和正式比较基线；CHANGELOG标题 `v261006-beta`。更新迁移：旧auto_join移除、域默认关闭、默认参数、意图列表、quota与冷却持久。
- [ ] 完成最终全量检查；git状态只含预期文件；敏感路径不进入提交；提交后核对最新远端dev，若变化整合并验证。
- [ ] 普通推送 `HEAD:refs/heads/dev`，创建并推送 `v261006-beta` 标记（已有同名标记则先核对，禁止覆盖）；核对远端分支／标记哈希。用户未要求main合并，不操作main。

## 执行与发布证据

账本记录每任务RED／GREEN命令、提交、偏差与审查结果。最终说明分别报告自动化测试、浏览器视觉验证、真实语音验证、dev提交和版本标记，不能将未做的实房验收写成通过。

实施状态（2026-10-06）：Task0—Task6已完成并集成；最终pytest410passed6.27s，Ruff/JS语法/diff检查通过。独立审查APPROVE；4个P1与2个P2全部修复并重放。各依赖任务统一以整体验证后的release提交交付，替代中间任务提交。详见2026-10-06-voice-auto-visit-validation.md。Task7提交和远端核验见最终交付。
