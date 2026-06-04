"""Compatibility loader for the split test suite."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import unittest


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

SPLIT_TEST_MODULES = (
    "test_storage",
    "test_skills",
    "test_ui_logic",
    "test_project_template",
    "test_proxy",
    "test_chat",
)


def _import_split_module(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return importlib.import_module(f"tests.{name}")


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    if pattern is not None:
        return unittest.TestSuite()
    suite = unittest.TestSuite()
    for module_name in SPLIT_TEST_MODULES:
        suite.addTests(loader.loadTestsFromModule(_import_split_module(module_name)))
    return suite
