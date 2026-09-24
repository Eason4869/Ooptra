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
    "token": "",
    "log_lines": 300,
}

# 名称映射表（手工补充 ID -> 名称；运行时会自动发现新 ID 并写入 data/names.json）
NAME_MAP = {
    "users": {},
    "channels": {},
    "areas": {},
}
