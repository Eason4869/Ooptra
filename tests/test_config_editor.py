"""config.py 就地改写的纯逻辑测试：不启动服务，也不需要 config.py 真的存在。"""

from __future__ import annotations

import ast

import pytest

from webui import config_editor as editor

SAMPLE = '''\
"""示例配置：这行模块 docstring 与下面的注释都必须原样保留"""
OOPZ_CONFIG = {
    # 这是一条必须保留的注释
    "login_phone": "",
    "proxy": "",
}
ONEBOT_V11_CONFIG = {
    "ws_reverse_url": "ws://127.0.0.1:6200/ws",
    "http_post_urls": [],
}
'''


def test_normalize_rejects_unknown_group():
    with pytest.raises(ValueError):
        editor._normalize_updates({"nope": {"a": 1}})


def test_normalize_rejects_unknown_field():
    with pytest.raises(ValueError):
        editor._normalize_updates({"webui": {"nope": 1}})


def test_normalize_rejects_readonly_field():
    """凭据字段只能由登录流程写回，配置接口不许改。"""
    with pytest.raises(ValueError):
        editor._normalize_updates({"oopz": {"app_version": "1"}})


def test_normalize_drops_blank_sensitive_value():
    """敏感项留空表示「不修改」，只应用其它的真实改动。"""
    normalized = editor._normalize_updates({"webui": {"token": None, "log_lines": 400}})
    assert normalized == {"webui": {"log_lines": 400}}


def test_normalize_keeps_sensitive_value_when_present():
    assert editor._normalize_updates({"webui": {"token": "abc"}}) == {"webui": {"token": "abc"}}


def test_normalize_enforces_prefix():
    with pytest.raises(ValueError):
        editor._normalize_updates({"onebot": {"ws_reverse_url": "http://127.0.0.1/ws"}})


def test_normalize_enforces_bounds():
    with pytest.raises(ValueError):
        editor._normalize_updates({"webui": {"log_lines": 10}})


def test_normalize_splits_list_field():
    normalized = editor._normalize_updates({"onebot": {"http_post_urls": "a, b ,c"}})
    assert normalized["onebot"]["http_post_urls"] == ["a", "b", "c"]


def test_normalize_rejects_empty_change_set():
    with pytest.raises(ValueError):
        editor._normalize_updates({"webui": {"token": None}})


def test_patched_text_preserves_comments_and_untouched_keys():
    patched = editor._patched_text(SAMPLE, {"oopz": {"proxy": "direct"}})
    assert "这是一条必须保留的注释" in patched
    assert '"ws_reverse_url": "ws://127.0.0.1:6200/ws"' in patched
    ast.parse(patched)
    namespace: dict[str, object] = {}
    exec(compile(patched, "<patched>", "exec"), namespace)
    oopz = namespace["OOPZ_CONFIG"]
    assert isinstance(oopz, dict)
    assert oopz["proxy"] == "direct"
    assert oopz["login_phone"] == ""


def test_patched_text_only_touches_target():
    patched = editor._patched_text(SAMPLE, {"onebot": {"ws_reverse_url": "ws://x/ws"}})
    assert '"ws_reverse_url": "ws://x/ws"' in patched
    assert '"proxy": ""' in patched


def test_patched_text_inserts_missing_field():
    patched = editor._patched_text(SAMPLE, {"oopz": {"default_area": "A1"}})
    namespace: dict[str, object] = {}
    exec(compile(patched, "<patched>", "exec"), namespace)
    oopz = namespace["OOPZ_CONFIG"]
    assert isinstance(oopz, dict)
    assert oopz["default_area"] == "A1"
    assert oopz["proxy"] == ""


def test_validate_text_rejects_broken_syntax():
    with pytest.raises(RuntimeError):
        editor._validate_text("OOPZ_CONFIG = {")


def test_validate_text_accepts_good_syntax():
    editor._validate_text(SAMPLE)


def test_field_specs_are_well_formed():
    """元数据自洽：tier 合法、高级项有分组、隐藏项只放自动维护的凭据字段。"""
    hidden = set()
    for group, fields in editor.FIELD_SPECS.items():
        assert group in editor.GROUP_SOURCES
        for field, meta in fields.items():
            tier = meta.get("tier", "adv")
            assert tier in {"basic", "adv", "hidden"}, (group, field)
            if tier == "adv":
                assert meta.get("section"), (group, field)
            if tier == "hidden":
                hidden.add(field)
    assert hidden == {"app_version", "device_id", "person_uid", "jwt_token"}
    for group in editor.FIELD_SPECS:
        assert editor.GROUP_META[group]["title"]
        assert editor.GROUP_META[group]["desc"]
