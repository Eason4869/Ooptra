"""替换私钥后下一次构建必须读新文件，不能复用导入缓存。"""

from __future__ import annotations

import importlib.util
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from oopz import credentials, sdk_config


def test_private_key_replacement_ignores_import_cache(monkeypatch, tmp_path):
    old_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def pem(key):
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()

    key_path = tmp_path / "private_key.py"
    key_path.write_text(credentials._private_key_module_content(pem(old_key)), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("private_key", key_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, "private_key", module)
    monkeypatch.setattr(credentials, "PRIVATE_KEY_PATH", str(key_path))
    # Keep the persistence path real, with synthetic credentials only.
    config_path = tmp_path / "config.py"
    config_path.write_text(
        'OOPZ_CONFIG = {"device_id": "old", "person_uid": "old", '
        '"jwt_token": "old", "app_version": "old"}\n', encoding="utf-8",
    )
    monkeypatch.setattr(credentials, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(credentials, "_apply_runtime", lambda payload: None)
    credentials.save_credentials({
        "private_key_pem": pem(new_key), "device_id": "new", "person_uid": "new",
        "jwt_token": "new", "app_version": "new",
    })
    used = sdk_config._load_private_key()
    assert used.public_key().public_numbers() == new_key.public_key().public_numbers()


def test_private_key_load_reflects_same_size_replacement(monkeypatch, tmp_path):
    key_path = tmp_path / "private_key.py"
    monkeypatch.setattr(credentials, "PRIVATE_KEY_PATH", str(key_path))
    key_path.write_text('def get_private_key():\n    return "old"\n', encoding="utf-8")
    # Prime both the normal import cache and any source-file bytecode cache.
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(sys.modules, "private_key", None)
    del sys.modules["private_key"]
    import private_key

    assert private_key.get_private_key() == "old"
    assert sdk_config._load_private_key() == "old"
    key_path.write_text('def get_private_key():\n    return "new"\n', encoding="utf-8")
    assert sdk_config._load_private_key() == "new"
