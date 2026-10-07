"""
Ooptra —— Oopz -> OneBot v11 反向 WebSocket 桥接配置示例

复制为 config.py 后填写。唯一必填项是 OOPZ_CONFIG 里的账号密码（或已登录的
device_id / person_uid / jwt_token + private_key.py）。
Web 控制台（默认 http://127.0.0.1:3090）保存配置会写回本文件，并就地更新当前进程。
"""

# Oopz 平台配置
OOPZ_CONFIG = {
    "app_version": "73817",
    "channel": "Web",
    "platform": "windows",
    "web": True,
    "base_url": "https://gateway.oopz.cn",
    "ws_url": "wss://ws.oopz.cn",   # 事件推送的 WebSocket 地址，一般不改

    # === 账号密码登录是主要方式 ===
    "login_phone": "",                   # OOPZ 登录手机号 / 账号
    "login_password": "",                # OOPZ 登录密码
    "device_id": "",                     # 设备 ID（登录成功后自动写入）
    "person_uid": "",                    # 用户 UID（登录成功后自动写入）
    "jwt_token": "",                     # JWT Token（登录成功后自动写入）

    "default_area": "",                  # 默认域 ID
    "default_channel": "",               # 默认频道 ID
    "use_announcement_style": False,     # bot 不是域主时保持 False

    # 代理：不设或 "" = 系统代理；False/"direct" = 直连；"clash" = http://127.0.0.1:7890
    # 注意：socks5 代理需要额外安装 aiohttp-socks。
    "proxy": "",
}

# 本地代理客户端别名端口：proxy 填 "clash"/"mihomo" 等别名时使用。
PROXY_ALIAS_CONFIG = {
    "host": "127.0.0.1",
    "http_port": 7890,
    "socks_port": 7891,
}

# HTTP 请求头模板
DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Content-Type": "application/json;charset=utf-8",
    "Origin": "https://web.oopz.cn",
    "Pragma": "no-cache",
    "Priority": "u=1, i",
    "Sec-Ch-Ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
}

# OneBot v11 桥接配置
ONEBOT_V11_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 6700,
    "access_token": "",
    "secret": "",
    "db_path": "data/onebot_v11.sqlite3",

    # === 反向 WebSocket（本程序作为客户端主动连到对端框架）===
    "enable_ws_reverse": True,
    "ws_reverse_url": "ws://127.0.0.1:6200/ws",
    "ws_reverse_api_url": "",
    "ws_reverse_event_url": "",
    "ws_reverse_reconnect_interval": 3.0,

    # === 本地 OneBot 服务（正向 WS / HTTP action），纯桥接不需要 ===
    "enable_http": False,
    "enable_ws": False,

    "enable_http_post": False,
    "http_post_urls": [],
    "http_post_timeout": 0.0,

    "send_connect_event": True,
    "heartbeat_enabled": True,
    "heartbeat_interval": 15.0,
    "member_list_max": 5000,

    "enable_area_scoped_group_ban": False,
    "enable_set_group_kick_as_area_kick": False,
    "enable_set_group_leave_as_area_leave": False,
    "enable_set_group_admin_as_area_role": False,
    "group_admin_role_id": 0,
}

# 本地 Web 控制台
WEBUI_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",   # 监听地址：127.0.0.1 仅本机；0.0.0.0 允许局域网访问
    "port": 3090,
    # 访问令牌：留空表示不校验；填入后需用 ?token=... 访问。
    # 语音 HTTP API 默认挂在此端口，外部插件（如 astrbot_plugin_ooptra）的令牌也填这一项。
    "token": "",
    "log_lines": 300,
}

# 语音实时对话（Voice Agent）—— Web 控制台「配置」页可改
VOICE_AGENT_CONFIG = {
    "enabled": False,                 # 总开关；不影响纯 OneBot 桥接
    "area": "",                       # 留空用 OOPZ_CONFIG["default_area"]
    "channel": "",                    # 留空用 OOPZ_CONFIG["default_channel"]

    # 语音对话架构：Live 端到端（推荐）| 级联兜底
    #   gemini_live   —— 语音进语音出（Live，类似电话）
    #   mimo_cascade  —— ASR→LLM→TTS（延迟更高，可离线/国内节点）
    #   openai_realtime —— 骨架，协议待接
    "backend": "gemini_live",
    "persona": "你是 Oopz 语音频道助手，说话简洁友好，像在语音房里自然聊天。",
    "barge_in": True,
    # 某人要**连续**说话满这么多毫秒才算抢话（房间越吵调越大，600~800 适合人多时）。
    # 0 = 关掉门限：一出声就打断，房间一热闹 bot 就说不完整句话。
    "barge_in_hold_ms": 300,
    "vad_mode": "local",
    "listen_only_uids": [],
    "reply_text_to_channel": False,

    "sample_rate_in": 16000,
    "sample_rate_out": 24000,
    # 说完多久算一句。700ms 对中文太短 —— 想词、换气的自然停顿就会被当成
    # 「说完了」，一句话被切成好几段，bot 于是逐段回（表现为「我每句话必回」）。
    "silence_ms": 1200,
    "max_utterance_ms": 15000,
    # 短于这么多毫秒的音频不送 ASR：「对。」0.1s、「哦。」0.4s 这类一个字的气声，
    # 回了也只是噪音。0 = 不过滤。
    "min_utterance_ms": 500,
    # 回合节流：bot 完整说完一条后，至少隔这么多毫秒才开下一轮。
    # 不设的话它一直在出声，你说下一句时它还没说完，越说越迟。
    # 被抢话打断的回合不计冷却。0 = 不冷却。
    "reply_cooldown_ms": 2500,
    # 自动语音回复概率：默认30%；0=仅命中强制关键词时接话，100=每次均允许回复。
    # 快捷开口与进退房台词、语音退房控制不受限制；Gemini 仍会产生模型用量。
    "reply_probability_percent": 30,
    # 包含任一关键词时强制回复，绕过概率。忽略大小写、全半角、空格与标点。
    # 例如 ["Ooptra", "机器人", "小欧"]；同音识别别名可直接补到列表。默认不启用。
    "force_reply_keywords": [],
    # 命中关键词后，同一成员可连续追问；换房/退房清除窗口。
    "conversation_window_enabled": True,
    "conversation_window_seconds": 30,
    # AI 识别真人让 bot 退出语音的意图，先说离场语再真正退房；默认开启。
    # 所有当前监听成员均可触发。复用自动串门分域 leave_prompts，空列表时使用默认告别。
    # MiMo 开启时每句都需 ASR 与额外意图判断；关闭且无关键词时才在ASR前按概率跳过。
    "voice_leave_enabled": True,

    # 模型 API 网络代理（选填）：""=不启用；"clash"=http://127.0.0.1:7890；
    # "direct"=强制直连；也可填显式地址 "http://主机:端口"
    "proxy": "",

    "mimo": {
        "api_key": "",                # 或环境变量 MIMO_API_KEY
        "base_url": "https://api.xiaomimimo.com/v1",
        "asr_model": "mimo-v2.5-asr",
        "llm_model": "mimo-v2.6-flash",
        "tts_model": "mimo-v2.5-tts",
        "tts_voice": "冰糖",
    },
    "gemini": {
        "api_key": "",                # 或 GEMINI_API_KEY
        "base_url": "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent",
        "model": "gemini-2.0-flash-live-001",
        "voice": "Puck",
    },
    "openai": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "realtime_model": "gpt-4o-mini-realtime-preview",
        "voice": "alloy",
    },

    "memory_path": "data/voice_memory.jsonl",
    "memory_max_turns": 30,
}

# 分域自动语音串门：所有域默认关闭，通过语音台逐域启用。
# 分域覆盖仅支持 defaults 字段；删除覆盖恢复继承，空台词列表表示静默。
# daily_limit=0 表示不限；分域上限和全局上限同时约束成功自动进房次数。
VOICE_AUTO_VISIT_CONFIG = {
    "check_interval_minutes": [10, 20],  # 仅实例级，不支持分域覆盖
    "daily_limit": 3,                   # 北京时间自然日，重启保留计数
    "defaults": {
        "join_probability": 0.2,
        "stay_minutes": [10, 20],
        "auto_cooldown_minutes": [30, 60],
        "manual_cooldown_minutes": [120, 240],
        "enter_prompts": ["在玩什么游戏？"],
        "leave_prompts": ["拜拜，我下了"],
    },
    "areas": {},
}

# 语音 HTTP API —— 已合并到 WebUI（http://127.0.0.1:3090/voice/* 与 /api/voice/*）。
# 外部插件（astrbot_plugin_ooptra）请直接用 3090，令牌填 WEBUI_CONFIG.token。
# 下面这个独立端口是与 3090 **完全等价**的副本（同一套路由），一般无需开启；
# 只在「不想把语音 API 暴露在 WebUI 端口上」时才打开，并务必填 token——
# token 留空时该端口不做任何校验。
VOICE_API_CONFIG = {
    "enabled": False,
    "host": "127.0.0.1",
    "port": 3091,
    "token": "",
}

# 名称映射表（手工补充 ID -> 名称；运行时会自动发现新 ID 并写入 data/names.json）
NAME_MAP = {
    "users": {},
    "channels": {},
    "areas": {},
}
