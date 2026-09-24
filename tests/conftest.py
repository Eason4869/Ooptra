"""让测试可以直接 import src/ 下的模块，与 main.py 的 sys.path 约定保持一致。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

# 全新检出（例如 CI）没有 config.py：从 config.example.py 生成一份占位配置，
# 使依赖运行期配置的模块也能被导入。已存在的 config.py 不会被覆盖。
if not (ROOT / "config.py").exists() and (ROOT / "config.example.py").exists():
    shutil.copyfile(ROOT / "config.example.py", ROOT / "config.py")
