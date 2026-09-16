"""AI 终端日志测试。

日志是排查"界面一片空白"的唯一线索，必须保证：即使主日志目录不可写，
也能退回临时目录并且路径可被界面读到。
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT, _ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("CODEX_SWITCH_DISABLE_OPEN_URL", "1")

from codex_switch.ui_v2.terminal import logging_setup  # noqa: E402


class LoggingSetupTests(unittest.TestCase):
    def test_logger_writes_messages(self) -> None:
        logger = logging_setup.get_logger()
        logger.info("单元测试日志标记 UNIQUE_LOG_MARKER")
        for handler in logger.handlers:
            handler.flush()
        path = logging_setup.log_path()
        self.assertTrue(path.exists(), f"日志文件应存在：{path}")
        self.assertIn("UNIQUE_LOG_MARKER", path.read_text(encoding="utf-8"))

    def test_log_path_is_readable_and_points_at_real_file(self) -> None:
        logging_setup.get_logger()
        path = logging_setup.log_path()
        # 界面"打开日志"依赖这个路径真实存在。
        self.assertEqual(path.name, "terminal.log")
        self.assertTrue(path.exists())

    def test_falls_back_to_temp_when_primary_unwritable(self) -> None:
        """主目录不可写时必须回退，而不是整个日志功能失效。"""
        original_handlers = logging.getLogger(logging_setup.LOGGER_NAME).handlers
        original_configured = logging_setup._configured
        logging.getLogger(logging_setup.LOGGER_NAME).handlers = []
        logging_setup._configured = False
        try:
            with patch.object(logging_setup, "log_dir", return_value=Path("/nonexistent/readonly/dir")):
                logger = logging_setup.get_logger()
            has_file_handler = any(
                isinstance(h, logging.FileHandler) for h in logger.handlers
            )
            self.assertTrue(has_file_handler, "主目录不可写时应回退到临时目录")
            logger.info("fallback marker")
            for h in logger.handlers:
                h.flush()
            self.assertTrue(logging_setup.log_path().exists())
        finally:
            for h in logging.getLogger(logging_setup.LOGGER_NAME).handlers:
                h.close()
            logging.getLogger(logging_setup.LOGGER_NAME).handlers = original_handlers
            logging_setup._configured = original_configured


if __name__ == "__main__":
    unittest.main()
