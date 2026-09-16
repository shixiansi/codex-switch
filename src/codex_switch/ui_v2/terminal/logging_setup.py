"""AI 终端子系统日志。

写到 ``%APPDATA%/CodexSwitch/terminal.log``（非 Windows 为 ``~/.codex-switch/``）。
PTY 相关的问题（启动失败、没有输出、进程被回收）都发生在一个后台线程里，
没有日志就只能看到"界面一片空白"。这里提供统一入口，便于排查。

设计取舍：只记录关键事件（启动/退出/回收/异常），不记录逐帧输出，
避免把日志刷爆；输出内容仍可在界面上查看。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

LOGGER_NAME = "codex_switch.terminal"

_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3

_configured = False


def log_dir() -> Path:
    """终端日志所在目录，与 profiles.json 同级。"""
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) / "CodexSwitch" if appdata else Path.home() / ".codex-switch"
    return root


def log_path() -> Path:
    """终端日志文件的完整路径（供界面"打开日志"使用）。

    返回实际生效的路径：主目录不可写时会退回到临时目录。
    """
    logger = logging.getLogger(LOGGER_NAME)
    for handler in logger.handlers:
        base = getattr(handler, "baseFilename", "")
        if base:
            return Path(base)
    return log_dir() / "terminal.log"


def get_logger() -> logging.Logger:
    """返回终端子系统 logger；首次调用时装配轮转文件处理器。

    主日志目录不可写时（只读 AppData、受限环境）回退到系统临时目录，
    确保日志功能本身不会因为环境限制而整体失效。
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = _build_handler() or logging.NullHandler()
    logger.addHandler(handler)
    _configured = True
    return logger


def _build_handler() -> logging.Handler | None:
    """按可写优先级尝试创建轮转文件处理器。"""
    import tempfile

    candidates = [log_dir(), Path(tempfile.gettempdir()) / "CodexSwitch"]
    for directory in candidates:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                directory / "terminal.log",
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s")
            )
            return handler
        except OSError:
            continue
    return None


__all__ = ["LOGGER_NAME", "get_logger", "log_dir", "log_path"]
