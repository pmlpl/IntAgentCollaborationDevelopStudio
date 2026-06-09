# core/logging.py — Studio 结构化日志系统
"""统一日志工厂，输出到 .studio/logs/studio.log（按天轮转）。

用法：
    from core.logging import get_logger
    logger = get_logger(__name__)
    logger.info("task created: %s", task_id)
    logger.debug("spawn resolve: %s -> %s", shim_path, exe_path)
    logger.warning("parse failed: %s", error_msg)
    logger.error("agent crash: %s", exc, exc_info=True)
"""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_LOG_DIR: Path | None = None
_INITIALIZED = False


def init_logging(log_dir: Path) -> Path:
    """初始化日志系统，返回日志目录路径。只需调用一次。"""
    global _LOG_DIR, _INITIALIZED
    if _INITIALIZED:
        return _LOG_DIR or log_dir
    _LOG_DIR = log_dir
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    handler = TimedRotatingFileHandler(
        str(_LOG_DIR / "studio.log"),
        when="midnight",
        backupCount=7,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)-5s] %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger("studio")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    # 同时输出到 stderr（方便开发调试）
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(name)s %(message)s"))
    root.addHandler(console)

    _INITIALIZED = True
    return _LOG_DIR


def get_logger(name: str) -> logging.Logger:
    """获取 studio 命名空间下的 logger。自动完成初始化。"""
    if not _INITIALIZED:
        # 自动初始化到默认路径（CWD 下的 .studio/logs/）
        init_logging(Path(".studio") / "logs")
    return logging.getLogger(f"studio.{name}")
