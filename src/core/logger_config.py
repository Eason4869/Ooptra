import contextlib
import glob
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

from core.paths import LOG_FILE
from core.paths import LOGS_DIR as LOG_DIR

LOG_RETENTION_DAYS = 7

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

def _env_level(env_key: str, default: int) -> int:
    raw = os.environ.get(env_key, "").upper().strip()
    return _LEVEL_MAP.get(raw, default)

_initialized = False


def _ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def _cleanup_old_logs():
    """删除超过 LOG_RETENTION_DAYS 天的日志文件。"""
    if not os.path.isdir(LOG_DIR):
        return
    cutoff = time.time() - LOG_RETENTION_DAYS * 86400
    removed = 0
    for path in glob.glob(os.path.join(LOG_DIR, "*.log*")):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    if removed:
        logging.getLogger("LogCleanup").info(
            f"已清理 {removed} 个超过 {LOG_RETENTION_DAYS} 天的日志文件"
        )


def setup_logger(name: str, level=logging.DEBUG) -> logging.Logger:
    """
    创建并返回一个配置好的 logger。
    首次调用时初始化文件 handler，后续调用复用同一 handler。
    """
    global _initialized

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not _initialized:
        _ensure_log_dir()
        _cleanup_old_logs()

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_level = _env_level("BOT_LOG_FILE_LEVEL", logging.DEBUG)
        console_level = _env_level("BOT_LOG_CONSOLE_LEVEL", logging.INFO)

        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)

        _force_utf8_streams()

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)

        root = logging.getLogger()
        root.setLevel(min(file_level, console_level))
        root.addHandler(file_handler)
        root.addHandler(console_handler)

        _attach_sdk_logger(file_handler, console_handler)
        _initialized = True

    return logger


def _force_utf8_streams() -> None:
    """把 stdout / stderr 切到 UTF-8。

    Windows 下控制台与重定向文件的默认编码是 GBK，中文日志会变成乱码；
    main.py 里的 ``chcp`` 只管控制台显示，对管道和重定向无效，因此这里直接
    改写流本身的编码。流被替换成不支持 reconfigure 的对象时静默跳过。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")


def _attach_sdk_logger(*handlers: logging.Handler) -> None:
    sdk_logger = logging.getLogger("oopz_sdk")
    sdk_logger.setLevel(_env_level("BOT_SDK_LOG_LEVEL", logging.INFO))
    existing = set(sdk_logger.handlers)
    for handler in handlers:
        if handler not in existing:
            sdk_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """获取已配置的 logger（简写）"""
    return setup_logger(name)
