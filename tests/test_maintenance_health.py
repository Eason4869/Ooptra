import pytest

from webui import maintenance_worker as worker


def test_detached_updated_install_retains_its_verified_source(tmp_path, monkeypatch):
    from webui.maintenance import MaintenanceService

    current = "a" * 40
    branch = ""
    def git_output(root, args, *extra, **kwargs):
        return current if args == ["git", "rev-parse", "HEAD"] else branch if args == ["git", "branch", "--show-current"] else ""
    monkeypatch.setattr("webui.maintenance.run_command", git_output)
    service = MaintenanceService(tmp_path)
    service.write_job({"action": "update", "phase": "complete", "channel": "main", "target_sha": current})
    assert service.status()["update"]["channel"] == "main"
    branch = "dev"
    assert service.status()["update"]["channel"] == "dev"
    branch = ""
    service.write_job({"action": "update", "phase": "complete", "channel": "main", "target_sha": "b" * 40})
    assert service.status()["update"]["channel"] == "dev"


def payload(**process):
    return {"ok": True, "process": {"pid": 123, "update_id": "candidate", "executable": "/venv/bin/python", **process},
            "bridge": {"oopz": {"connected": False}, "onebot": {"connected": False}}}


def test_disconnected_network_is_degraded_but_process_remains_healthy():
    health = worker.runtime_health(payload(), expected_pid=123, update_id="candidate", expected_python="/venv/bin/python")
    assert health["process_ok"] is True
    assert health["state"] == "degraded"
    assert [row["state"] for row in health["checks"]] == ["pass", "degraded", "degraded"]


@pytest.mark.parametrize("override", [{"pid": 456}, {"update_id": "other"}, {"executable": "/other/bin/python"}])
def test_process_identity_mismatch_is_unhealthy(override):
    health = worker.runtime_health(payload(**override), expected_pid=123, update_id="candidate", expected_python="/venv/bin/python")
    assert health["process_ok"] is False
    assert health["state"] == "failed"


def test_two_interpreters_linked_to_same_base_do_not_share_runtime_identity(tmp_path):
    base = tmp_path / "base-python"
    base.write_bytes(b"python")
    intended, other = tmp_path / "intended-python", tmp_path / "other-python"
    try:
        intended.symlink_to(base)
        other.symlink_to(base)
    except OSError:
        pytest.skip("Symbolic links unavailable on this Windows account")
    health = worker.runtime_health(payload(executable=str(other)), expected_pid=123, update_id="candidate", expected_python=str(intended))
    assert health["process_ok"] is False


@pytest.mark.parametrize("malformed", [None, [], {"ok": True, "process": []}])
def test_malformed_health_payload_is_failed_instead_of_raising(malformed):
    assert worker.runtime_health(malformed, expected_pid=123)["process_ok"] is False
