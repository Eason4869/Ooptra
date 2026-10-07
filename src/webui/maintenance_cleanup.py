"""Explicit maintenance cleanup: only known artifacts, with live protection rechecked."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path


def read_runtime(root):
    path = root / "data/maintenance/runtime.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, ValueError) as exc:
        raise ValueError("运行环境记录无法读取，请先修复记录再清理") from exc


def linked(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def tree_snapshot(root, path):
    """Skip links/junctions rather than following them during inventory or deletion."""
    try:
        if not path.resolve().is_relative_to(root) or any(linked(p) for p in [path, *path.parents] if p.is_relative_to(root)):
            return None
        paths = [path]
        if path.is_dir():
            for folder, dirs, files in os.walk(path, followlinks=False):
                paths.extend(Path(folder) / name for name in dirs + files)
        size = 0
        digest = hashlib.sha256()
        for entry in sorted(paths):
            if linked(entry):
                return None
            info = entry.stat()
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                return None
            if entry.is_file():
                size += info.st_size
            digest.update(f"{entry.relative_to(root).as_posix()}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}".encode())
        return size, digest.hexdigest()
    except OSError:
        return None


def inventory(root, backups, job):
    runtime = read_runtime(root)
    references = [sys.executable, os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")]
    for source in [runtime, job or {}]:
        references.extend(source.get(key, "") for key in ("python", "browser_path", "old_python", "new_python", "health_python", "old_browser_path"))
    protected_paths = [Path(value).resolve() for value in references if isinstance(value, str) and value]
    protected_backups = {row["id"] for row in backups[:2]}
    protected_backups.update((job or {}).get(key) for key in ("backup_id", "safety_backup_id"))
    candidates = [(p, "environment")
                  for p in root.glob(".venv-update-*") if re.fullmatch(r"\.venv-update-[a-f0-9]{32}", p.name)]
    for folder, kind in [("browsers", "browser"), ("staging", "staging")]:
        parent = root / "data/maintenance" / folder
        if parent.exists() and not linked(parent):
            candidates.extend((path, kind) for path in parent.iterdir()
                              if path.is_dir() and (kind == "staging" or re.fullmatch(r"[a-f0-9]{32}", path.name)))
    candidates.extend((root / "data/maintenance/backups" / (row["id"] + ".zip"), "backup") for row in backups)
    totals = {"backups_count": len(backups), "backups_bytes": 0, "environments_bytes": 0, "browsers_bytes": 0, "staging_bytes": 0}
    keys = {"backup": "backups_bytes", "environment": "environments_bytes", "browser": "browsers_bytes", "staging": "staging_bytes"}
    items = []
    for path, kind in candidates:
        snapshot = tree_snapshot(root, path)
        if snapshot is None:
            continue
        size, fingerprint = snapshot
        totals[keys[kind]] += size
        if kind == "backup" and path.stem in protected_backups:
            continue
        if any(reference == path.resolve() or reference.is_relative_to(path.resolve()) for reference in protected_paths):
            continue
        items.append({"id": path.stem if kind == "backup" else path.name, "path": path.relative_to(root).as_posix(),
                      "kind": kind, "size": size, "fingerprint": fingerprint})
    totals["total_bytes"] = sum(totals[key] for key in keys.values())
    return totals, sorted(items, key=lambda item: item["path"])


def delete_items(root, items):
    # The service compares a fresh inventory before calling this; verify each path
    # once more immediately before handing a scoped path to filesystem operations.
    for item in items:
        path = root / item["path"]
        if tree_snapshot(root, path) != (item["size"], item["fingerprint"]):
            raise ValueError("清理对象已变化，请重新预览")
    for item in items:
        path = root / item["path"]
        if not path.resolve().is_relative_to(root) or linked(path):
            raise ValueError("清理路径无效")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
