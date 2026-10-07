"""Prepare upgrades while the current bot remains online; the launcher owns restarts."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

from core.version import __version__
from webui.maintenance_cleanup import delete_items, inventory
from webui.maintenance_storage import BackupStore, atomic_json, restored_endpoint
from webui.maintenance_worker import runtime_health

OFFICIAL_REMOTES = {
    "https://github.com/eason4869/ooptra", "https://github.com/eason4869/ooptra.git",
    "git@github.com:eason4869/ooptra.git", "ssh://git@github.com/eason4869/ooptra.git",
}
ACTIVE_PHASES = {"preparing", "awaiting_restart", "switching", "checking", "rolling_back"}
PUBLIC_JOB_FIELDS = {"id", "action", "phase", "detail", "started_at", "updated_at", "target_sha", "old_sha", "backup_id", "channel"}


def run_command(root: Path, args: list[str], timeout: int = 30, env=None) -> str:
    """Never accept shell commands or arbitrary arguments from the HTTP caller."""
    result = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        # pip/git output may contain credentials; retain only the step and return code.
        raise ValueError(f"{Path(args[0]).name} 执行失败（退出码 {result.returncode}）")
    return result.stdout.strip()


class MaintenanceService:
    def __init__(self, root, *, shutdown=None, managed=None, venv=None, port=3090, host="127.0.0.1", token="", runtime_status=None):
        self.root = Path(root).resolve()
        self.backups = BackupStore(self.root)
        self.job_file = self.root / "data/maintenance/job.json"
        self.shutdown = shutdown
        self.managed = os.environ.get("OOPTRA_MANAGED") == "1" if managed is None else managed
        self.venv = sys.prefix != sys.base_prefix if venv is None else venv
        self.port = port
        self.host = "127.0.0.1" if host in {"0.0.0.0", "localhost"} else "::1" if host in {"::", "::1"} else host
        self.token = token
        self._task = None
        self._busy = False
        self._check = None
        self._cleanup = None
        self._storage_cache = None
        self.runtime_status = runtime_status
        previous = self.read_job()
        if (previous and previous.get("phase") in ACTIVE_PHASES and previous.get("service_pid") != os.getpid()
                and os.environ.get("OOPTRA_UPDATE_ID", "") != previous.get("id")):
            previous.update(phase="failed", detail="上次维护被中断；请核对版本与数据，需要时恢复安全备份后重新操作")
            self.write_job(previous)

    def read_job(self):
        try:
            return json.loads(self.job_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write_job(self, value):
        value["updated_at"] = time.time()
        atomic_json(self.job_file, value)
        self._storage_cache = None

    def storage_status(self, backups, job):
        # Status runs in a worker thread. Repeated page polling must not walk
        # large venv/browser trees every three seconds; destructive operations
        # always call inventory afresh and never consume these cached totals.
        cached = self._storage_cache
        if cached and time.monotonic() - cached[0] < 30:
            return cached[1]
        try:
            storage, _ = inventory(self.root, backups, job)
        except ValueError as exc:
            storage = {"error": str(exc), "backups_count": len(backups), "backups_bytes": sum(row["size"] for row in backups)}
        storage["sampled_at"] = time.time()
        self._storage_cache = (time.monotonic(), storage)
        return storage

    def preflight(self):
        checks = []

        def check(name, passed, detail):
            checks.append({"id": name, "passed": bool(passed), "detail": detail})

        check("venv", self.venv, "使用 Python 虚拟环境")
        check("launcher", self.managed, "使用 python launcher.py 启动，才能安全停止、升级和回滚")
        try:
            top = run_command(self.root, ["git", "rev-parse", "--show-toplevel"])
            check("git", Path(top).resolve() == self.root, "当前目录是 Git 仓库根目录")
            remote = run_command(self.root, ["git", "remote", "get-url", "origin"])
            check("remote", remote.lower().rstrip("/") in OFFICIAL_REMOTES, "origin 指向 Eason4869/Ooptra 官方仓库")
            dirty = run_command(self.root, ["git", "status", "--porcelain"])
            check("clean", not dirty, "代码有本地改动或未跟踪文件时，先自行提交或处理；不会强制覆盖")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            check("git", False, "Git 不可用或仓库无法读取")
        check("disk", shutil.disk_usage(self.root).free >= 512 * 1024 * 1024, "至少 512 MB 可用空间；安装依赖时可能需要更多")
        try:
            with tempfile.TemporaryFile(dir=self.root):
                pass
            check("writable", True, "部署目录允许当前服务账户写入")
        except OSError:
            check("writable", False, "部署目录不可写")
        return {"supported": all(c["passed"] for c in checks), "checks": checks}

    def status(self, page=1, page_size=50):
        if isinstance(page, bool) or isinstance(page_size, bool) or not isinstance(page, int) or not isinstance(page_size, int) or page < 1 or not 1 <= page_size <= 50:
            raise ValueError("备份分页参数无效")
        job = self.read_job()
        backups = self.backups.list(limit=None)
        pages = max(1, (len(backups) + page_size - 1) // page_size)
        page = min(page, pages)
        preflight = self.preflight()
        try:
            current_sha = run_command(self.root, ["git", "rev-parse", "HEAD"])
            branch = run_command(self.root, ["git", "branch", "--show-current"])
        except (OSError, ValueError, subprocess.TimeoutExpired):
            current_sha, branch = "", ""
        channel = branch if branch in {"main", "dev"} else "dev" if re.search(r"-(?:dev|beta)$", __version__) else "main"
        if (branch not in {"main", "dev"} and isinstance(job, dict)
                and job.get("action") == "update" and job.get("phase") == "complete"
                and job.get("target_sha") == current_sha and job.get("channel") in {"main", "dev"}):
            channel = job["channel"]
        update = {"channel": channel, "current_sha": current_sha,
                  "target_sha": None, "available": False, "version": __version__, **(self._check or {}),
                  "supported": preflight["supported"]}
        storage = self.storage_status(backups, job)
        bridge = self.runtime_status() if self.runtime_status else {}
        return {
            "ok": True, "preflight": preflight, "backups": backups[(page - 1) * page_size:page * page_size],
            "backup_page": {"page": page, "page_size": page_size, "total": len(backups), "pages": pages},
            "storage": storage, "update": update,
            "health": runtime_health({"ok": True, "process": {"pid": os.getpid()}, "bridge": bridge}),
            "job": {k: v for k, v in job.items() if k in PUBLIC_JOB_FIELDS} if isinstance(job, dict) else None,
            "check": self._check, "busy": self._busy,
            "restore_supported": bool(self.managed and self.shutdown),
        }

    def preview_cleanup(self):
        if self._busy or (self.read_job() or {}).get("phase") in ACTIVE_PHASES:
            raise ValueError("维护任务进行中，暂不能清理")
        _, items = inventory(self.root, self.backups.list(limit=None), self.read_job())
        self._cleanup = {"token": uuid.uuid4().hex, "items": items, "expires_at": time.time() + 300}
        return {"ok": True, "token": self._cleanup["token"], "expires_at": self._cleanup["expires_at"],
                "items": [{k: v for k, v in item.items() if k != "fingerprint"} for item in items],
                "total_bytes": sum(item["size"] for item in items)}

    async def apply_cleanup(self, token):
        self._claim()
        try:
            preview = self._cleanup
            self._cleanup = None
            if not preview or token != preview["token"] or time.time() > preview["expires_at"]:
                raise ValueError("清理预览已失效，请重新预览并确认")
            def apply():
                _, current = inventory(self.root, self.backups.list(limit=None), self.read_job())
                if current != preview["items"]:
                    raise ValueError("清理对象或运行环境已变化，请重新预览")
                delete_items(self.root, current)
                return {"ok": True, "removed": len(current), "removed_bytes": sum(item["size"] for item in current)}
            return await asyncio.to_thread(apply)
        finally:
            self._busy = False
            self._storage_cache = None

    async def check_update(self, channel):
        if channel not in {"main", "dev"}:
            raise ValueError("仅支持 main 或 dev 更新源")
        if self._busy:
            raise ValueError("维护任务进行中")
        # Read-only remote lookup also works for unsupported installations.
        output = await asyncio.to_thread(run_command, self.root,
                                         ["git", "ls-remote", "https://github.com/Eason4869/Ooptra.git", f"refs/heads/{channel}"], 60)
        sha = output.split()[0] if output else ""
        if not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ValueError("无法读取更新版本")
        try:
            current = await asyncio.to_thread(run_command, self.root, ["git", "rev-parse", "HEAD"])
        except (OSError, ValueError):
            current = ""
        self._check = {"channel": channel, "target_sha": sha, "current_sha": current, "available": sha != current, "checked_at": time.time()}
        return {"ok": True, **self._check}

    def _claim(self):
        job = self.read_job() or {}
        if self._busy or job.get("phase") in ACTIVE_PHASES:
            raise ValueError("维护任务进行中")
        self._busy = True

    async def create_backup(self):
        self._claim()
        try:
            return await asyncio.to_thread(self.backups.create)
        finally:
            self._busy = False
            self._storage_cache = None

    async def start_update(self, channel, target_sha):
        if channel not in {"main", "dev"} or not re.fullmatch(r"[a-f0-9]{40}", str(target_sha)):
            raise ValueError("更新参数无效")
        if not (await asyncio.to_thread(self.preflight))["supported"]:
            raise ValueError("当前部署不支持自动升级，请查看预检查结果")
        if not self._check or self._check["target_sha"] != target_sha or self._check["channel"] != channel:
            raise ValueError("请先检查更新，确认要安装的提交")
        self._claim()
        job = {"id": uuid.uuid4().hex, "action": "update", "phase": "preparing", "detail": "准备独立虚拟环境，当前服务继续运行", "target_sha": target_sha, "channel": channel, "started_at": time.time(), "service_pid": os.getpid()}
        self.write_job(job)
        self._task = asyncio.create_task(self._prepare(job))
        return {k: v for k, v in job.items() if k in PUBLIC_JOB_FIELDS}

    async def start_restore(self, backup_id):
        if not self.managed or not self.shutdown:
            raise ValueError("恢复需要使用 python launcher.py 启动，确保数据库已安全关闭")
        self.backups.path(backup_id)
        self._claim()
        job = {"id": uuid.uuid4().hex, "action": "restore", "phase": "preparing", "backup_id": backup_id, "detail": "校验备份并创建恢复前备份", "started_at": time.time(), "service_pid": os.getpid()}
        self.write_job(job)
        self._task = asyncio.create_task(self._prepare_restore(job))
        return {k: v for k, v in job.items() if k in PUBLIC_JOB_FIELDS}

    def _prepare_environment(self, job):
        run_command(self.root, ["git", "fetch", "origin", job["channel"]], 120)
        fetched = run_command(self.root, ["git", "rev-parse", "FETCH_HEAD"])
        if fetched != job["target_sha"]:
            raise ValueError("远端版本已变化，请重新检查更新")
        stage_root = self.root / "data/maintenance/staging"
        stage_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=stage_root) as folder:
            stage = Path(folder)
            bundle = stage / "source.tar"
            run_command(self.root, ["git", "archive", "--format=tar", f"--output={bundle}", fetched])
            source = stage / "source"
            source.mkdir()
            with tarfile.open(bundle) as archive:
                for member in archive.getmembers():
                    dest = source / member.name
                    if not dest.resolve().is_relative_to(source) or not (member.isfile() or member.isdir()):
                        raise ValueError("目标代码归档包含不安全路径")
                filters = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
                archive.extractall(source, **filters)
            environment = self.root / f".venv-update-{job['id']}"
            server_source = source / "src/webui/server.py"
            if not server_source.is_file() or "OOPTRA_UPDATE_ID" not in server_source.read_text(encoding="utf-8"):
                raise ValueError("目标版本不支持自动升级健康检查，请按 README 手动安装")
            run_command(self.root, [sys.executable, "-m", "venv", str(environment)], 120)
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            run_command(source, [str(python), "-m", "pip", "install", "-r", "requirements.txt", "-r", "requirements-optional.txt"], 900)
            run_command(source, [str(python), "-m", "compileall", "-q", "main.py", "src"], 60)
            run_command(source, [str(python), "-c", "import aiohttp, pydantic, cryptography, PIL, aiosqlite, playwright, websockets"], 30)
            browsers = self.root / "data/maintenance/browsers" / job["id"]
            job["browser_path"] = str(browsers)
            env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(browsers))
            run_command(source, [str(python), "-m", "playwright", "install", "chromium"], 900, env)
            run_command(source, [str(python), "-c", "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); b.close(); p.stop()"], 60, env)
            return str(python)

    async def _prepare(self, job):
        try:
            job["old_sha"] = await asyncio.to_thread(run_command, self.root, ["git", "rev-parse", "HEAD"])
            job["new_python"] = await asyncio.to_thread(self._prepare_environment, job)
            if not (await asyncio.to_thread(self.preflight))["supported"]:
                raise ValueError("准备期间部署状态变化，取消切换")
            job["backup_id"] = (await asyncio.to_thread(self.backups.create))["id"]
            await self._ready(job)
        except Exception as exc:
            self._fail(job, exc)

    async def _prepare_restore(self, job):
        try:
            def validate():
                with tempfile.TemporaryDirectory(dir=self.backups.directory) as folder:
                    self.backups.validate(job["backup_id"], Path(folder))
                    job["restore_endpoint"] = restored_endpoint(Path(folder) / "config.py")
            await asyncio.to_thread(validate)
            job["safety_backup_id"] = (await asyncio.to_thread(self.backups.create))["id"]
            await self._ready(job)
        except Exception as exc:
            self._fail(job, exc)

    async def _ready(self, job):
        if not self.shutdown:
            raise ValueError("当前启动方式不支持安全重启")
        job.update({"old_python": sys.executable, "service_pid": os.getpid(), "health_port": self.port,
                    "health_token": self.token, "health_host": self.host,
                    "old_browser_path": os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""),
                    "phase": "awaiting_restart", "detail": "准备完成，正在安全关闭语音与数据库"})
        self.write_job(job)
        self.shutdown()

    def _fail(self, job, exc):
        job.update(phase="failed", detail=str(exc) if isinstance(exc, ValueError) else f"维护准备失败（{type(exc).__name__}）；当前服务继续运行")
        self.write_job(job)
        self._busy = False

    async def close(self):
        if self._task and not self._task.done():
            # Preparation runs in a worker thread; join it before exiting so it cannot
            # race the supervisor's code switch. No shutdown is requested until ready.
            with contextlib.suppress(Exception):
                await self._task


def mount_maintenance_routes(app, service):
    from urllib.parse import urlsplit

    from aiohttp import web

    async def body(request):
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            raise ValueError("跨站维护请求被拒绝")
        if request.content_type != "application/json":
            raise ValueError("维护请求必须使用 JSON")
        value = await request.json()
        if not isinstance(value, dict):
            raise ValueError("请求格式无效")
        return value

    async def status(request):
        try:
            page = int(request.query.get("page", "1"))
            page_size = int(request.query.get("page_size", "50"))
            return web.json_response(await asyncio.to_thread(service.status, page, page_size))
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def download(request):
        try:
            path = service.backups.path(request.match_info["id"])
            if not path.is_file():
                raise ValueError("备份不存在")
            return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="ooptra-{path.stem}.zip"'})
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    def handler(action):
        async def invoke(request):
            try:
                value = await body(request)
                if action == "check":
                    return web.json_response(await service.check_update(value.get("channel", "main")))
                if action == "cleanup_preview":
                    result = await asyncio.to_thread(service.preview_cleanup)
                elif action == "cleanup_apply":
                    result = await service.apply_cleanup(value.get("token", ""))
                elif action == "backup":
                    result = await service.create_backup()
                elif action == "restore":
                    result = await service.start_restore(value.get("backup_id", ""))
                else:
                    result = await service.start_update(value.get("channel"), value.get("target_sha"))
                return web.json_response({"ok": True, **result})
            except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                return web.json_response({"ok": False, "error": str(exc) if isinstance(exc, ValueError) else "维护操作失败，请检查部署环境和网络"}, status=400)
        return invoke

    app.add_routes([
        web.get("/api/maintenance", status), web.get("/api/maintenance/backups/{id}", download),
        web.post("/api/maintenance/check", handler("check")),
        web.post("/api/maintenance/backups", handler("backup")),
        web.post("/api/maintenance/restore", handler("restore")),
        web.post("/api/maintenance/update", handler("update")),
        web.post("/api/maintenance/cleanup/preview", handler("cleanup_preview")),
        web.post("/api/maintenance/cleanup/apply", handler("cleanup_apply")),
    ])
