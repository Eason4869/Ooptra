"""The checked-in standalone UI must follow production assets without running config.py."""

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "preview_builder", ROOT / "scripts/build_webui_preview.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preview_matches_sources():
    builder = load_builder()
    assert (ROOT / "webui_preview.html").read_text(encoding="utf-8") == builder.build(ROOT)


def test_preview_is_self_contained_and_uses_current_controls():
    html = load_builder().build(ROOT)
    assert 'src="/assets/' not in html
    assert 'href="/assets/' not in html
    assert 'id="maintenance-progress"' in html
    assert 'id="login-token"' in html
    assert 'id="log-wrap"' in html
    assert 'data:image/svg+xml;base64,' in html


def test_preview_reads_example_only_and_redacts_sensitive_fields(tmp_path):
    builder = load_builder()
    (tmp_path / "src/webui").mkdir(parents=True)
    shutil.copyfile(ROOT / "config.example.py", tmp_path / "config.example.py")
    shutil.copyfile(ROOT / "src/webui/config_editor.py", tmp_path / "src/webui/config_editor.py")
    (tmp_path / "config.py").write_text("raise RuntimeError('never execute')", encoding="utf-8")
    schema = builder.demo_schema(tmp_path)
    for group in schema.values():
        for field in group["fields"].values():
            if field.get("sensitive"):
                assert field["value"] is None
    assert "persona" not in schema["voice"]["fields"]
    assert schema["webui"]["fields"]["token"]["is_set"]


def test_generated_preview_is_identical_for_lf_and_crlf_assets(tmp_path):
    builder = load_builder()
    shutil.copytree(ROOT / "src/webui/assets", tmp_path / "src/webui/assets")
    for name in ("config.example.py", "src/webui/config_editor.py", "src/core/version.py",
                 "scripts/webui_preview.js"):
        output = tmp_path / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, output)
    paths = list((tmp_path / "src/webui/assets").iterdir())
    for path in paths:
        path.write_bytes(path.read_text(encoding="utf-8").encode("utf-8"))
    lf = builder.build(tmp_path)
    for path in paths:
        path.write_bytes(path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    assert builder.build(tmp_path) == lf
