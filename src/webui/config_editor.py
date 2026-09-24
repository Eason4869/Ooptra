"""config.py 的受限读写：白名单字段 + AST 就地改写。

只在 config.py 里改写白名单分组内的字段值，文件其余部分（注释、用户自定义变量）
原样保留；写入前会先做语法与求值校验，失败则完全不落盘。
"""

from __future__ import annotations

import ast
import copy
import importlib
import json
import os
from typing import Any

from core.config_file_store import config_file_write_lock, replace_text_files_atomically
from core.logger_config import get_logger
from core.paths import PROJECT_ROOT

logger = get_logger("WebUIConfig")

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.py")

# 分组 -> config.py 中的变量名
GROUP_SOURCES: dict[str, str] = {
    "oopz": "OOPZ_CONFIG",
    "onebot": "ONEBOT_V11_CONFIG",
    "webui": "WEBUI_CONFIG",
}

# 分组 -> 展示信息：控制台标题与一句话引导（前端渲染用）。
GROUP_META: dict[str, dict[str, str]] = {
    "onebot": {
        "title": "OneBot v11 连接",
        "desc": "本程序作为客户端拨出，连到对端框架的 OneBot v11 反向 WebSocket 服务；地址与令牌要和那边一致。",
    },
    "oopz": {
        "title": "Oopz 账号与目标",
        "desc": "bot 在 Oopz 侧的身份与默认落点。登录凭据会自动维护，跑通后这里基本不用改。",
    },
    "webui": {
        "title": "Web 控制台",
        "desc": "本页面的监听地址与访问令牌；换端口后要用新地址重新打开。",
    },
}

# 分组 -> 字段 -> 规范。type 决定保存时的类型转换，sensitive 字段不会回传明文。
# tier: basic=常显；adv=收在「高级选项」里；hidden=不给前端（自动维护/只读）。
# adv 字段可用 section 在「高级选项」内再分小节；缺省 section 归入「其他」。
FIELD_SPECS: dict[str, dict[str, dict[str, Any]]] = {
    "oopz": {
        "default_area": {
            "type": "str",
            "label": "默认域 ID",
            "tier": "basic",
            "hint": "OneBot 调用没带目标域时用它兜底",
        },
        "default_channel": {
            "type": "str",
            "label": "默认频道 ID",
            "tier": "basic",
            "hint": "同上，频道兜底",
        },
        "proxy": {
            "type": "str",
            "label": "网络出口",
            "tier": "basic",
            "hint": "留空=跟随系统代理，direct=直连，也可填 http://主机:端口",
        },
        "login_phone": {"type": "str", "label": "登录手机号", "tier": "adv", "section": "账号"},
        "login_password": {
            "type": "str",
            "label": "登录密码",
            "sensitive": True,
            "tier": "adv",
            "section": "账号",
        },
        "use_announcement_style": {
            "type": "bool",
            "label": "公告样式",
            "tier": "adv",
            "section": "行为",
            "hint": "bot 不是域主时保持关闭",
        },
        "app_version": {"type": "str", "label": "app_version", "readonly": True, "tier": "hidden"},
        "device_id": {"type": "str", "label": "device_id", "readonly": True, "tier": "hidden"},
        "person_uid": {"type": "str", "label": "person_uid", "readonly": True, "tier": "hidden"},
        "jwt_token": {"type": "str", "label": "jwt_token", "readonly": True, "tier": "hidden"},
    },
    "onebot": {
        "ws_reverse_url": {
            "type": "str",
            "label": "反向 WS 地址",
            "tier": "basic",
            "prefix": ("ws://", "wss://"),
            "hint": "对端反向 WS 的监听地址，路径由对端决定，如 ws://127.0.0.1:6200/ws",
        },
        "access_token": {
            "type": "str",
            "label": "access_token",
            "sensitive": True,
            "tier": "basic",
            "hint": "要和 OneBot 实现里的 token 相同；两边都留空即不校验",
        },
        "enabled": {"type": "bool", "label": "启用 OneBot v11", "tier": "adv", "section": "连接"},
        "enable_ws_reverse": {
            "type": "bool",
            "label": "启用反向 WebSocket",
            "tier": "adv",
            "section": "连接",
        },
        "ws_reverse_api_url": {
            "type": "str",
            "label": "反向 WS API 地址",
            "tier": "adv",
            "section": "连接",
            "prefix": ("ws://", "wss://"),
            "hint": "仅当对端区分 API/Event 时填写",
        },
        "ws_reverse_event_url": {
            "type": "str",
            "label": "反向 WS Event 地址",
            "tier": "adv",
            "section": "连接",
            "prefix": ("ws://", "wss://"),
        },
        "secret": {
            "type": "str",
            "label": "secret",
            "sensitive": True,
            "tier": "adv",
            "section": "连接",
            "hint": "仅在需要签名校验时填写，一般留空",
        },
        "ws_reverse_reconnect_interval": {
            "type": "float",
            "label": "重连间隔(秒)",
            "tier": "adv",
            "section": "连接",
            "min": 0.5,
            "max": 300,
        },
        "enable_http": {"type": "bool", "label": "本地 HTTP action", "tier": "adv", "section": "本地接入"},
        "enable_ws": {
            "type": "bool",
            "label": "本地正向 WebSocket",
            "tier": "adv",
            "section": "本地接入",
            "hint": "反向桥接不需要，留给主动连过来的 OneBot 客户端",
        },
        "host": {"type": "str", "label": "本地监听地址", "tier": "adv", "section": "本地接入"},
        "port": {
            "type": "int",
            "label": "本地监听端口",
            "tier": "adv",
            "section": "本地接入",
            "min": 1,
            "max": 65535,
        },
        "enable_http_post": {
            "type": "bool",
            "label": "HTTP POST 上报",
            "tier": "adv",
            "section": "本地接入",
        },
        "http_post_urls": {"type": "list", "label": "上报地址列表", "tier": "adv", "section": "本地接入"},
        "send_connect_event": {
            "type": "bool",
            "label": "发送 connect 事件",
            "tier": "adv",
            "section": "推送与心跳",
        },
        "heartbeat_enabled": {"type": "bool", "label": "发送心跳", "tier": "adv", "section": "推送与心跳"},
        "heartbeat_interval": {
            "type": "float",
            "label": "心跳间隔(秒)",
            "tier": "adv",
            "section": "推送与心跳",
            "min": 1,
            "max": 3600,
        },
        "member_list_max": {
            "type": "int",
            "label": "成员列表上限",
            "tier": "adv",
            "section": "推送与心跳",
            "min": 0,
            "max": 100000,
        },
        "enable_area_scoped_group_ban": {
            "type": "bool",
            "label": "禁言作用于整个域",
            "tier": "adv",
            "section": "域语义映射",
        },
        "enable_set_group_kick_as_area_kick": {
            "type": "bool",
            "label": "踢人=移出域",
            "tier": "adv",
            "section": "域语义映射",
        },
        "enable_set_group_leave_as_area_leave": {
            "type": "bool",
            "label": "退群=退出域",
            "tier": "adv",
            "section": "域语义映射",
        },
        "enable_set_group_admin_as_area_role": {
            "type": "bool",
            "label": "设置管理员=域身份组",
            "tier": "adv",
            "section": "域语义映射",
        },
        "group_admin_role_id": {
            "type": "int",
            "label": "管理员身份组 ID",
            "tier": "adv",
            "section": "域语义映射",
            "min": 0,
            "max": 999999,
        },
        "db_path": {
            "type": "str",
            "label": "映射数据库路径",
            "tier": "adv",
            "section": "数据",
            "hint": "存 group_id/self_id 映射，删除会导致对端看到的群号全部变化",
        },
    },
    "webui": {
        "host": {
            "type": "str",
            "label": "监听地址",
            "tier": "basic",
            "nonempty": True,
            "hint": "127.0.0.1 仅本机；0.0.0.0 允许局域网访问",
        },
        "port": {"type": "int", "label": "监听端口", "tier": "basic", "min": 1, "max": 65535},
        "token": {
            "type": "str",
            "label": "访问令牌",
            "sensitive": True,
            "tier": "basic",
            "hint": "留空=不校验；填入后访问需带 ?token=...",
        },
        "enabled": {"type": "bool", "label": "启用 Web 控制台", "tier": "adv", "section": "其他"},
        "log_lines": {
            "type": "int",
            "label": "日志默认行数",
            "tier": "adv",
            "section": "其他",
            "min": 50,
            "max": 5000,
        },
    },
}

_RESTART_FREE_FIELDS = {("webui", "log_lines")}


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------


def _runtime_config():
    return importlib.import_module("config")


def _live_group(group: str) -> dict[str, Any]:
    module = _runtime_config()
    value = getattr(module, GROUP_SOURCES[group], None)
    return value if isinstance(value, dict) else {}


def schema_payload() -> dict[str, Any]:
    """下发给前端：分组规范 + 当前值。敏感字段不回传明文，自动维护项不下发。"""
    groups: dict[str, Any] = {}
    for group, fields in FIELD_SPECS.items():
        current = _live_group(group)
        entries: dict[str, Any] = {}
        for field, meta in fields.items():
            tier = str(meta.get("tier", "adv"))
            if tier == "hidden":
                continue
            entry = {
                "type": meta["type"],
                "label": meta.get("label", field),
                "readonly": bool(meta.get("readonly")),
                "sensitive": bool(meta.get("sensitive")),
                "hint": meta.get("hint", ""),
                "tier": tier,
                "section": meta.get("section", ""),
            }
            for bound in ("min", "max"):
                if bound in meta:
                    entry[bound] = meta[bound]
            if meta.get("readonly"):
                entry["value"] = current.get(field)
            elif meta.get("sensitive"):
                entry["value"] = None
                entry["is_set"] = bool(current.get(field))
            else:
                value = current.get(field)
                entry["value"] = list(value) if isinstance(value, (list, tuple)) else value
            entries[field] = entry
        groups[group] = {
            "source": GROUP_SOURCES[group],
            "title": GROUP_META.get(group, {}).get("title", group),
            "desc": GROUP_META.get(group, {}).get("desc", ""),
            "fields": entries,
        }
    return groups


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------


def _coerce(meta: dict[str, Any], value: Any, field: str) -> Any:
    kind = meta["type"]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError(f"{field} 需要布尔值")
    if kind == "int":
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} 需要整数") from exc
        _check_bounds(meta, parsed, field)
        return parsed
    if kind == "float":
        try:
            parsed = float(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} 需要数字") from exc
        _check_bounds(meta, parsed, field)
        return parsed
    if kind == "list":
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]
    text = str(value).strip()
    if text and meta.get("prefix") and not text.lower().startswith(tuple(meta["prefix"])):
        raise ValueError(f"{field} 必须以 {' 或 '.join(meta['prefix'])} 开头")
    if not text and meta.get("nonempty"):
        raise ValueError(f"{field} 不能为空")
    return text


def _check_bounds(meta: dict[str, Any], value: float, field: str) -> None:
    if "min" in meta and value < meta["min"]:
        raise ValueError(f"{field} 不能小于 {meta['min']}")
    if "max" in meta and value > meta["max"]:
        raise ValueError(f"{field} 不能大于 {meta['max']}")


def _normalize_updates(updates: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(updates, dict):
        raise ValueError("updates 必须是对象")
    normalized: dict[str, dict[str, Any]] = {}
    for group, values in updates.items():
        if group not in FIELD_SPECS:
            raise ValueError(f"未知配置分组: {group}")
        if not isinstance(values, dict):
            raise ValueError(f"{group} 的值必须是对象")
        specs = FIELD_SPECS[group]
        target: dict[str, Any] = {}
        for field, value in values.items():
            meta = specs.get(field)
            if meta is None:
                raise ValueError(f"未知配置项: {group}.{field}")
            if meta.get("readonly"):
                raise ValueError(f"{group}.{field} 是只读项，请通过「Oopz 登录」修改")
            if value is None and meta.get("sensitive"):
                continue
            target[field] = _coerce(meta, value, f"{group}.{field}")
        if target:
            normalized[group] = target
    if not normalized:
        raise ValueError("没有需要保存的改动")
    return normalized


def _python_literal(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_python_literal(item) for item in value) + "]"
    if isinstance(value, dict):
        parts = [
            f"{_python_literal(str(key))}: {_python_literal(item)}"
            for key, item in value.items()
        ]
        return "{" + ", ".join(parts) + "}"
    return json.dumps(str(value), ensure_ascii=False)


def _line_offsets(lines: list[str]) -> list[int]:
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    return offsets


def _byte_col_to_char_index(line: str, byte_col: int) -> int:
    total = 0
    for index, char in enumerate(line):
        total += len(char.encode("utf-8"))
        if total > byte_col:
            return index
        if total == byte_col:
            return index + 1
    return len(line)


def _node_span(lines: list[str], offsets: list[int], node: ast.expr) -> tuple[int, int]:
    end_lineno = node.end_lineno
    end_col_offset = node.end_col_offset
    if end_lineno is None or end_col_offset is None:
        raise RuntimeError("配置语法节点缺少结束位置")
    start_col = _byte_col_to_char_index(lines[node.lineno - 1], node.col_offset)
    end_col = _byte_col_to_char_index(lines[end_lineno - 1], end_col_offset)
    return offsets[node.lineno - 1] + start_col, offsets[end_lineno - 1] + end_col


def _dict_assignments(tree: ast.AST) -> dict[str, ast.Dict]:
    assignments: dict[str, ast.Dict] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                assignments[target.id] = node.value
    return assignments


def _patched_text(text: str, updates: dict[str, dict[str, Any]]) -> str:
    try:
        tree = ast.parse(text, filename=CONFIG_PATH)
    except SyntaxError as exc:
        raise RuntimeError(f"config.py 存在语法错误，无法保存: {exc}") from exc

    lines = text.splitlines(keepends=True)
    offsets = _line_offsets(lines)
    assignments = _dict_assignments(tree)
    replacements: list[tuple[int, int, str]] = []
    insertions: dict[int, list[str]] = {}

    for group, values in updates.items():
        source_name = GROUP_SOURCES[group]
        dict_node = assignments.get(source_name)
        if dict_node is None:
            raise RuntimeError(f"config.py 找不到 {source_name}，无法写入")

        existing: dict[str, ast.expr] = {}
        for key_node, value_node in zip(dict_node.keys, dict_node.values, strict=True):
            if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                existing[key_node.value] = value_node

        for field, value in values.items():
            literal = _python_literal(value)
            value_node = existing.get(field)
            if value_node is not None:
                start, end = _node_span(lines, offsets, value_node)
                replacements.append((start, end, literal))
                continue
            end_lineno = dict_node.end_lineno
            if end_lineno is None:
                raise RuntimeError(f"{source_name} 缺少结束行信息")
            closing_line = lines[end_lineno - 1]
            closing_indent = closing_line[: len(closing_line) - len(closing_line.lstrip())]
            insertions.setdefault(offsets[end_lineno - 1], []).append(
                f"{closing_indent}    {_python_literal(field)}: {literal},\n"
            )

    edits: list[tuple[int, int, str]] = list(replacements)
    for position, chunks in insertions.items():
        edits.append((position, position, "".join(chunks)))
    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def _validate_text(text: str) -> None:
    namespace: dict[str, Any] = {}
    try:
        # config.py 是纯字面量数据，且本函数就是它的写入方，求值等同于 import 该文件。
        exec(compile(text, CONFIG_PATH, "exec"), namespace)
    except Exception as exc:
        raise RuntimeError(f"新配置无法求值，已取消保存: {exc}") from exc


def _sync_runtime(namespace: dict[str, Any]) -> None:
    module = _runtime_config()
    for source_name in GROUP_SOURCES.values():
        target = getattr(module, source_name, None)
        fresh = namespace.get(source_name)
        if isinstance(target, dict) and isinstance(fresh, dict):
            target.clear()
            target.update(copy.deepcopy(fresh))


def apply_updates(updates: Any) -> dict[str, Any]:
    """校验并写回 config.py，随后就地更新运行中的字典。"""
    normalized = _normalize_updates(updates)
    with config_file_write_lock():
        with open(CONFIG_PATH, encoding="utf-8", newline="") as handle:
            text = handle.read()
        patched = _patched_text(text, normalized)
        _validate_text(patched)

        namespace: dict[str, Any] = {}
        exec(compile(patched, CONFIG_PATH, "exec"), namespace)
        replace_text_files_atomically(((CONFIG_PATH, patched),))

    _sync_runtime(namespace)
    changed = {group: sorted(values) for group, values in normalized.items()}
    restart_required = any(
        (group, field) not in _RESTART_FREE_FIELDS
        for group, fields in normalized.items()
        for field in fields
    )
    logger.info("配置已保存: %s", changed)
    return {"changed": changed, "restart_required": restart_required}


__all__ = ["CONFIG_PATH", "FIELD_SPECS", "GROUP_SOURCES", "apply_updates", "schema_payload"]
