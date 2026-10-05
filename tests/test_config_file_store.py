"""配置落盘的跨平台、回滚与临时文件清理。"""

from __future__ import annotations

import os

import pytest

from core import config_file_store as store


def test_atomic_write_without_fchmod(monkeypatch, tmp_path):
    monkeypatch.delattr(os, "fchmod", raising=False)
    path = tmp_path / "config.py"
    path.write_text("old = 1\n", encoding="utf-8")
    store.replace_text_files_atomically([(path, "new = 2\n")])
    assert path.read_text(encoding="utf-8") == "new = 2\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.py"]


def test_atomic_write_creates_missing_file(tmp_path):
    path = tmp_path / "private_key.py"
    store.replace_text_files_atomically([(path, "key = 'test'\n")])
    assert path.read_text(encoding="utf-8") == "key = 'test'\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["private_key.py"]


def test_second_replace_failure_restores_both_files(monkeypatch, tmp_path):
    paths = [tmp_path / "config.py", tmp_path / "private_key.py"]
    for path in paths:
        path.write_text("old\n", encoding="utf-8")
    replace = os.replace

    def fail_second(src, dst):
        if str(src).endswith(".tmp") and dst == paths[1]:
            raise OSError("simulated replace failure")
        return replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_second)
    with pytest.raises(OSError, match="simulated replace failure"):
        store.replace_text_files_atomically([(path, "new\n") for path in paths])
    assert [p.read_text(encoding="utf-8") for p in paths] == ["old\n", "old\n"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.py", "private_key.py"]
