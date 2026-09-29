"""更新检查：版本比较与载荷结构（不访问网络）。"""

from __future__ import annotations

from webui import update_check


def test_normalize_version_strips_prefix():
    assert update_check._normalize_version("v1.2.3") == "1.2.3"
    assert update_check._normalize_version("1.2.3") == "1.2.3"
    assert update_check._normalize_version("") == ""


def test_version_tuple_parses_digits():
    assert update_check._version_tuple("1.10.0") == (1, 10, 0)
    assert update_check._version_tuple("v2.0") == (2, 0)
    assert update_check._version_tuple("garbage") == (0,)


def test_is_newer_compares_versions():
    assert update_check._is_newer("1.1.0", "1.0.0") is True
    assert update_check._is_newer("1.0.0", "1.0.0") is False
    assert update_check._is_newer("v1.0.0", "1.1.0") is False
    assert update_check._is_newer("2.0.0", "1.9.9") is True


def test_payload_base_includes_repo_links():
    payload = update_check._payload_base()
    assert payload["repo_url"] == update_check.GITHUB_REPO_URL
    assert payload["default_branch"]
    assert payload["branch_url"].startswith(update_check.GITHUB_REPO_URL)
    assert "releases" in payload["releases_url"]
    assert payload["current_version"]
