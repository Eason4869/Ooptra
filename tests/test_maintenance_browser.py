import asyncio
import io
import tarfile

from webui import maintenance


def test_browser_preparation_failure_does_not_stop_current_service(tmp_path, monkeypatch):
    stopped = []
    commands = []
    def run(root, args, timeout=30, env=None):
        commands.append((args, env))
        if args[:2] == ["git", "archive"]:
            output = next(value.removeprefix("--output=") for value in args if value.startswith("--output="))
            with tarfile.open(output, "w") as archive:
                for name, content in {"src/webui/server.py": "OOPTRA_UPDATE_ID", "main.py": "pass"}.items():
                    value = content.encode()
                    info = tarfile.TarInfo(name)
                    info.size = len(value)
                    archive.addfile(info, io.BytesIO(value))
        if "playwright" in args and "install" in args:
            assert env["PLAYWRIGHT_BROWSERS_PATH"].startswith(str(tmp_path))
            raise ValueError("browser download unavailable")
        return "a" * 40
    monkeypatch.setattr(maintenance, "run_command", run)
    service = maintenance.MaintenanceService(tmp_path, shutdown=lambda: stopped.append(True))
    job = {"id": "b" * 32, "action": "update", "channel": "dev", "target_sha": "a" * 40, "phase": "preparing"}
    asyncio.run(service._prepare(job))
    assert not stopped
    assert service.status()["job"]["phase"] == "failed"
    assert any("playwright" in args and "install" in args for args, env in commands)
