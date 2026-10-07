"""把 Oopz-SDK 登录凭据原子写回本项目现有配置格式。"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from core.config_file_store import config_file_write_lock, replace_text_files_atomically
from core.paths import PROJECT_ROOT
from oopz_sdk.auth import OopzLoginCredentials
from oopz_sdk.exceptions import OopzPasswordLoginError

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.py")
CONFIG_EXAMPLE_PATH = os.path.join(PROJECT_ROOT, "config.example.py")
PRIVATE_KEY_PATH = os.path.join(PROJECT_ROOT, "private_key.py")
OOPZ_CONFIG_CREDENTIAL_FIELDS = ("app_version", "device_id", "person_uid", "jwt_token")


def credentials_payload(credentials: OopzLoginCredentials | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(credentials, OopzLoginCredentials):
        return {
            "device_id": credentials.device_id,
            "person_uid": credentials.person_uid,
            "jwt_token": credentials.jwt_token,
            "private_key_pem": credentials.private_key_pem,
            "app_version": credentials.app_version,
        }
    return dict(credentials)


def _read_config_template() -> str:
    for path in (CONFIG_PATH, CONFIG_EXAMPLE_PATH):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as file:
                return file.read()
    raise OopzPasswordLoginError("config.py 不存在，且未找到 config.example.py")


def _has_additional_config_binding(tree: ast.AST) -> bool:
    """Recognize bindings stored as strings rather than ast.Name nodes."""
    for node in ast.walk(tree):
        if isinstance(node, ast.alias):
            # A dotted import binds its first component unless it has an alias.
            if node.name == "*" or (node.asname or node.name.split(".")[0]) == "OOPZ_CONFIG":
                return True
        elif isinstance(node, ast.arg):
            if node.arg == "OOPZ_CONFIG":
                return True
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            if "OOPZ_CONFIG" in node.names:
                return True
        elif any(getattr(node, field, None) == "OOPZ_CONFIG" for field in ("name", "rest")):
            # Function/class, exception handler, match captures (including **rest)
            # and generic type parameters all carry their binding as a string.
            return True
    return False


def _updated_config_content(credentials: Mapping[str, Any]) -> str:
    content = _read_config_template()
    try:
        tree = ast.parse(content)
        definitions = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(isinstance(target, ast.Name) and target.id == "OOPZ_CONFIG"
                    for target in (node.targets if isinstance(node, ast.Assign) else [node.target]))
        ]
        if len(definitions) != 1 or definitions[0] not in tree.body:
            raise ValueError("OOPZ_CONFIG 必须是唯一顶层定义")
        definition = definitions[0]
        targets = definition.targets if isinstance(definition, ast.Assign) else [definition.target]
        references = [
            name for name in ast.walk(tree)
            if isinstance(name, ast.Name) and name.id == "OOPZ_CONFIG"
        ]
        # Only a standalone static definition is supported. Further references
        # can mutate the dictionary directly or pass an alias to arbitrary code;
        # reject them rather than attempt to evaluate/control user code.
        if (
            len(targets) != 1 or len(references) != 1 or references[0] is not targets[0]
            or _has_additional_config_binding(tree)
        ):
            raise ValueError("OOPZ_CONFIG 包含无法安全更新的动态引用或绑定")
        node = definitions[0].value
        if not isinstance(node, ast.Dict):
            raise ValueError("OOPZ_CONFIG 必须是字典字面量")
        # Never execute user configuration, including calls and dictionary unpacking.
        ast.literal_eval(node)
        fields = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str) or key.value in fields:
                raise ValueError("OOPZ_CONFIG 包含不安全或重复的键")
            fields[key.value] = value
        lines = content.splitlines(keepends=True)
        encoded = content.encode("utf-8")
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line.encode("utf-8")))
        edits = []
        for key in OOPZ_CONFIG_CREDENTIAL_FIELDS:
            value = credentials.get(key)
            if key not in fields or value is None or str(value) == "":
                raise ValueError(f"缺少凭据字段 {key}")
            old = fields[key]
            start = offsets[old.lineno - 1] + old.col_offset
            end = offsets[old.end_lineno - 1] + old.end_col_offset
            replacement = json.dumps(str(value), ensure_ascii=False).encode("utf-8")
            edits.append((start, end, replacement))
        for start, end, replacement in sorted(edits, reverse=True):
            encoded = encoded[:start] + replacement + encoded[end:]
        return encoded.decode("utf-8")
    except (SyntaxError, ValueError, TypeError) as exc:
        raise OopzPasswordLoginError("无法安全更新 OOPZ_CONFIG 凭据字段") from exc


def _private_key_module_content(pem: str) -> str:
    normalized = pem.strip().replace("\r\n", "\n")
    return (
        '"""RSA 私钥（由 Oopz-SDK 登录自动生成）"""\n\n'
        "from cryptography.hazmat.primitives import serialization\n"
        "from cryptography.hazmat.backends import default_backend\n\n"
        f'PRIVATE_KEY_PEM = b"""{normalized}"""\n\n\n'
        "def get_private_key():\n"
        '    """加载并返回 RSA 私钥对象。"""\n'
        "    return serialization.load_pem_private_key(\n"
        "        PRIVATE_KEY_PEM, password=None, backend=default_backend()\n"
        "    )\n"
    )


def _apply_runtime(credentials: Mapping[str, Any]) -> None:
    updates = {
        key: credentials.get(key)
        for key in OOPZ_CONFIG_CREDENTIAL_FIELDS
        if credentials.get(key)
    }
    try:
        module = sys.modules.get("config")
        target = getattr(module, "OOPZ_CONFIG", None)
        if isinstance(target, dict):
            target.update(updates)
    except Exception:
        pass


def save_credentials(credentials: OopzLoginCredentials | Mapping[str, Any]) -> list[str]:
    payload = credentials_payload(credentials)
    pem = str(payload.get("private_key_pem") or payload.get("private_key") or "").strip()
    if not pem:
        raise OopzPasswordLoginError("缺少 RSA 私钥，无法写入 private_key.py")
    with config_file_write_lock():
        replace_text_files_atomically(
            (
                (CONFIG_PATH, _updated_config_content(payload)),
                (PRIVATE_KEY_PATH, _private_key_module_content(pem)),
            )
        )
    _apply_runtime(payload)
    return ["config.py", "private_key.py"]


async def persist_credentials(
    credentials: OopzLoginCredentials | Mapping[str, Any],
) -> list[str]:
    return await asyncio.to_thread(save_credentials, credentials)


def load_private_key_from_pem(pem: str):
    return serialization.load_pem_private_key(
        pem.encode("utf-8"),
        password=None,
        backend=default_backend(),
    )


__all__ = [
    "credentials_payload",
    "load_private_key_from_pem",
    "persist_credentials",
    "save_credentials",
]
