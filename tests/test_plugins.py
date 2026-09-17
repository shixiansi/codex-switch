from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codex_switch.plugins import (  # noqa: E402
    API_VERSION,
    ManifestError,
    PermissionDenied,
    PluginActionError,
    PluginApi,
    PluginLoadError,
    load_manifest_file,
    load_plugin,
    parse_manifest,
)
from codex_switch.plugins.registry import (  # noqa: E402
    STATUS_DISABLED,
    STATUS_ERROR,
    STATUS_READY,
    PluginRegistry,
    scan_plugins,
)


TEST_TMP_ROOT = PROJECT_ROOT / ".tmp" / "test-plugins"


def make_temp_dir(case: unittest.TestCase) -> Path:
    """工作区内的临时目录。

    不用 ``tempfile.TemporaryDirectory``：受限环境下系统临时目录会被拒绝写入。
    """
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"{case._testMethodName}-", dir=str(TEST_TMP_ROOT)))
    case.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
    return root


def manifest_payload(**overrides) -> dict:
    payload = {
        "id": "demo-plugin",
        "name": "示例插件",
        "version": "1.0.0",
        "apiVersion": API_VERSION,
        "entry": "entry.py",
    }
    payload.update(overrides)
    return payload


def write_plugin(directory: Path, *, entry_code: str = "", **manifest_overrides) -> Path:
    """在目录里放一个最小可用插件。"""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plugin.json").write_text(
        json.dumps(manifest_payload(**manifest_overrides), ensure_ascii=False),
        encoding="utf-8",
    )
    if entry_code:
        (directory / manifest_overrides.get("entry", "entry.py")).write_text(
            entry_code, encoding="utf-8",
        )
    return directory


# ---------------------------------------------------------------------------
# 清单校验
# ---------------------------------------------------------------------------

class ManifestTests(unittest.TestCase):
    def test_accepts_minimal_manifest(self) -> None:
        manifest = parse_manifest(manifest_payload())
        self.assertEqual(manifest.id, "demo-plugin")
        self.assertEqual(manifest.api_version, API_VERSION)
        self.assertEqual(manifest.permissions, frozenset())
        self.assertFalse(manifest.has_page)

    def test_rejects_non_object(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(["not", "an", "object"])

    def test_rejects_missing_required_fields(self) -> None:
        for field in ("id", "name", "version", "apiVersion", "entry"):
            with self.subTest(field=field):
                payload = manifest_payload()
                del payload[field]
                with self.assertRaises(ManifestError):
                    parse_manifest(payload)

    def test_rejects_bad_plugin_id(self) -> None:
        for bad in ("Demo", "de", "demo_plugin", "demo plugin", "-demo", "demo-" * 20):
            with self.subTest(bad=bad):
                with self.assertRaises(ManifestError):
                    parse_manifest(manifest_payload(id=bad))

    def test_rejects_mismatched_api_version(self) -> None:
        """apiVersion 不匹配必须拒绝：按旧契约写的插件行为不可预期。"""
        with self.assertRaises(ManifestError) as caught:
            parse_manifest(manifest_payload(apiVersion=API_VERSION + 1))
        self.assertIn("apiVersion", str(caught.exception))

    def test_rejects_boolean_api_version(self) -> None:
        """bool 是 int 的子类，True 不能被当成 apiVersion=1 放行。"""
        with self.assertRaises(ManifestError):
            parse_manifest(manifest_payload(apiVersion=True))

    def test_rejects_bad_version_format(self) -> None:
        for bad in ("1", "v1.0", "1.0.0.0", "abc"):
            with self.subTest(bad=bad):
                with self.assertRaises(ManifestError):
                    parse_manifest(manifest_payload(version=bad))

    def test_rejects_absolute_entry_path(self) -> None:
        """绝对路径指向插件目录之外，是宿主审计不到的代码来源。"""
        with self.assertRaises(ManifestError):
            parse_manifest(manifest_payload(entry="C:/evil.py"))

    def test_rejects_parent_escape_in_entry(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(manifest_payload(entry="../outside.py"))

    def test_rejects_parent_escape_in_page(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(manifest_payload(page="../../evil.qml"))

    def test_rejects_non_python_entry(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(manifest_payload(entry="entry.exe"))

    def test_rejects_non_qml_page(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(manifest_payload(page="page.py"))

    def test_accepts_page_when_valid(self) -> None:
        manifest = parse_manifest(manifest_payload(page="page.qml"))
        self.assertTrue(manifest.has_page)
        self.assertEqual(manifest.page, "page.qml")

    def test_rejects_unknown_permission(self) -> None:
        """未知权限必须报错：静默忽略会让作者以为声明生效了。"""
        with self.assertRaises(ManifestError) as caught:
            parse_manifest(manifest_payload(permissions=["fs:write", "fs:destroy"]))
        self.assertIn("fs:destroy", str(caught.exception))

    def test_rejects_non_list_permissions(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(manifest_payload(permissions="fs:read"))

    def test_accepts_known_permissions(self) -> None:
        manifest = parse_manifest(manifest_payload(permissions=["snapshot:read", "action:invoke"]))
        self.assertEqual(manifest.permissions, frozenset({"snapshot:read", "action:invoke"}))

    def test_flags_sensitive_permissions(self) -> None:
        manifest = parse_manifest(manifest_payload(
            permissions=["fs:read", "fs:write", "exec"],
            paths={"fs:read": ["~/.dsh"], "fs:write": ["~/.dsh"]},
        ))
        self.assertEqual(manifest.sensitive_permissions, frozenset({"fs:write", "exec"}))

    def test_parses_path_roots(self) -> None:
        manifest = parse_manifest(manifest_payload(
            permissions=["fs:read"],
            paths={"fs:read": ["~/.dsh", "D:/exports"]},
        ))
        self.assertEqual(manifest.path_roots["fs:read"], ("~/.dsh", "D:/exports"))

    def test_rejects_unknown_paths_key(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            parse_manifest(manifest_payload(paths={"fs:destroy": ["C:/"]}))
        self.assertIn("fs:destroy", str(caught.exception))

    def test_rejects_empty_paths_list(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(manifest_payload(
                permissions=["fs:read"], paths={"fs:read": []},
            ))

    def test_rejects_paths_with_non_string_entries(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(manifest_payload(
                permissions=["fs:read"], paths={"fs:read": [123]},
            ))

    def test_write_permission_also_requires_paths(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            parse_manifest(manifest_payload(permissions=["fs:write"]))
        self.assertIn("paths", str(caught.exception))

    def test_exec_permission_does_not_require_paths(self) -> None:
        """exec 不是文件权限，不该被 paths 规则误伤。"""
        manifest = parse_manifest(manifest_payload(permissions=["exec"]))
        self.assertEqual(manifest.permissions, frozenset({"exec"}))

    def test_rejects_duplicate_action_keys(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(manifest_payload(actions=[
                {"key": "switch-account", "label": "切换"},
                {"key": "switch-account", "label": "又切换"},
            ]))

    def test_rejects_action_without_label(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(manifest_payload(actions=[{"key": "switch-account"}]))

    def test_reads_manifest_file_with_bom(self) -> None:
        """Windows 编辑器会写 BOM，带 BOM 不等于坏文件。"""
        root = make_temp_dir(self)
        path = root / "plugin.json"
        raw = json.dumps(manifest_payload(), ensure_ascii=False)
        path.write_bytes(b"\xef\xbb\xbf" + raw.encode("utf-8"))
        self.assertEqual(load_manifest_file(path).id, "demo-plugin")

    def test_missing_manifest_file_reports_clear_error(self) -> None:
        root = make_temp_dir(self)
        with self.assertRaises(ManifestError):
            load_manifest_file(root / "absent.json")


# ---------------------------------------------------------------------------
# 权限边界
# ---------------------------------------------------------------------------

class PluginApiPermissionTests(unittest.TestCase):
    def test_undeclared_snapshot_read_is_denied(self) -> None:
        api = PluginApi(parse_manifest(manifest_payload()), snapshot_provider=lambda: {"a": 1})
        with self.assertRaises(PermissionDenied):
            api.snapshot()

    def test_declared_snapshot_read_is_allowed(self) -> None:
        api = PluginApi(
            parse_manifest(manifest_payload(permissions=["snapshot:read"])),
            snapshot_provider=lambda: {"a": 1},
        )
        self.assertEqual(api.snapshot(), {"a": 1})

    def test_snapshot_returns_deep_copy(self) -> None:
        """插件就地修改副本不能影响宿主状态。"""
        state = {"nested": {"value": 1}}
        api = PluginApi(
            parse_manifest(manifest_payload(permissions=["snapshot:read"])),
            snapshot_provider=lambda: state,
        )
        api.snapshot()["nested"]["value"] = 999
        self.assertEqual(state["nested"]["value"], 1)

    def test_undeclared_invoke_is_denied(self) -> None:
        api = PluginApi(parse_manifest(manifest_payload()), action_runner=lambda _n, _p: None)
        with self.assertRaises(PermissionDenied):
            api.invoke("do-thing")

    def test_declared_invoke_reaches_runner(self) -> None:
        calls: list[tuple[str, dict]] = []
        api = PluginApi(
            parse_manifest(manifest_payload(permissions=["action:invoke"])),
            action_runner=lambda name, payload: calls.append((name, payload)) or "ok",
        )
        self.assertEqual(api.invoke("do-thing", {"x": 1}), "ok")
        self.assertEqual(calls, [("do-thing", {"x": 1})])

    def test_invoke_without_runner_reports_action_error(self) -> None:
        api = PluginApi(parse_manifest(manifest_payload(permissions=["action:invoke"])))
        with self.assertRaises(PluginActionError):
            api.invoke("do-thing")

    def test_has_reports_declared_permissions(self) -> None:
        api = PluginApi(parse_manifest(
            manifest_payload(permissions=["fs:read"], paths={"fs:read": ["~/.dsh"]})
        ))
        self.assertTrue(api.has("fs:read"))
        self.assertFalse(api.has("fs:write"))


class PluginApiFileAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir(self)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()
        (self.allowed / "inside.txt").write_text("hello", encoding="utf-8")
        (self.outside / "secret.txt").write_text("secret", encoding="utf-8")

    def _api(self, permissions, paths=None):
        """构造一个 API，并自动为文件权限补上合法的 paths 声明。

        清单现在要求 fs:read / fs:write 必须配 paths，所以这里按声明的权限
        自动补齐，让每个用例只需表达"我用到了哪些权限"。
        """
        declared = dict(paths or {})
        for permission in ("fs:read", "fs:write"):
            if permission in permissions and permission not in declared:
                declared[permission] = [str(self.allowed)]
        return PluginApi(
            parse_manifest(manifest_payload(permissions=permissions, paths=declared)),
            allowed_roots={"fs:read": [self.allowed], "fs:write": [self.allowed]},
        )

    def test_read_inside_allowed_root(self) -> None:
        api = self._api(["fs:read"])
        self.assertEqual(api.read_text(str(self.allowed / "inside.txt")), "hello")

    def test_read_outside_allowed_root_is_denied(self) -> None:
        """`..` 逃逸必须被挡住，否则 fs:read 等于全盘可读。"""
        api = self._api(["fs:read"])
        with self.assertRaises(PermissionDenied):
            api.read_text(str(self.outside / "secret.txt"))

    def test_traversal_path_is_denied(self) -> None:
        api = self._api(["fs:read"])
        with self.assertRaises(PermissionDenied):
            api.read_text(str(self.allowed / ".." / "outside" / "secret.txt"))

    def test_write_requires_declared_permission(self) -> None:
        api = self._api(["fs:read"])
        with self.assertRaises(PermissionDenied):
            api.write_text(str(self.allowed / "new.txt"), "data")

    def test_write_inside_allowed_root(self) -> None:
        api = self._api(["fs:write"])
        target = self.allowed / "new.txt"
        api.write_text(str(target), "data")
        self.assertEqual(target.read_text(encoding="utf-8"), "data")

    def test_write_outside_allowed_root_is_denied(self) -> None:
        api = self._api(["fs:write"])
        with self.assertRaises(PermissionDenied):
            api.write_text(str(self.outside / "new.txt"), "data")

    def test_list_dir_outside_root_is_denied(self) -> None:
        api = self._api(["fs:read"])
        with self.assertRaises(PermissionDenied):
            api.list_dir(str(self.outside))

    def test_fs_permission_without_paths_is_rejected_at_manifest_level(self) -> None:
        """声明 fs:read 却不给 paths，必须在加载时就报错。

        与其让作者困惑"我声明了权限为什么还不能读"，不如在清单校验阶段就指出
        缺少 paths——这样错误在插件中心里一眼可见，而不是等到运行时才失败。
        """
        with self.assertRaises(ManifestError) as caught:
            parse_manifest(manifest_payload(permissions=["fs:read"]))
        self.assertIn("paths", str(caught.exception))

    def test_fs_permission_with_empty_roots_is_denied_at_runtime(self) -> None:
        """即使清单合法，宿主没给出根目录时运行也必须拒绝，而不是放行。"""
        api = PluginApi(
            parse_manifest(manifest_payload(permissions=["fs:read"], paths={"fs:read": ["~/.dsh"]})),
        )
        with self.assertRaises(PermissionDenied):
            api.read_text(str(self.allowed / "inside.txt"))


    def test_exec_requires_declared_permission(self) -> None:
        api = self._api(["fs:read"])
        with self.assertRaises(PermissionDenied):
            api.run_command([sys.executable, "-c", "print(1)"])

    def test_exec_runs_when_declared(self) -> None:
        api = self._api(["exec", "fs:read"])
        out = api.run_command([sys.executable, "-c", "print('hi')"], cwd=str(self.allowed))
        self.assertIn("hi", out)

    def test_exec_rejects_empty_argv(self) -> None:
        api = self._api(["exec", "fs:read"])
        with self.assertRaises(PluginActionError):
            api.run_command([])


# ---------------------------------------------------------------------------
# 扫描与故障隔离
# ---------------------------------------------------------------------------

class ScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir(self)
        self.roots = [(self.root, False)]

    def test_finds_valid_plugin(self) -> None:
        write_plugin(self.root / "demo", entry_code="def load(api):\n    return None\n")
        result = scan_plugins(self.roots)
        self.assertEqual([entry.id for entry in result.entries], ["demo-plugin"])
        self.assertEqual(result.issues, [])

    def test_skips_directories_without_manifest(self) -> None:
        """没有清单的目录是用户杂物，不该被报成坏插件。"""
        (self.root / "random-notes").mkdir()
        result = scan_plugins(self.roots)
        self.assertEqual(result.entries, [])
        self.assertEqual(result.issues, [])

    def test_skips_underscore_and_dot_directories(self) -> None:
        (self.root / "_draft").mkdir()
        (self.root / ".hidden").mkdir()
        result = scan_plugins(self.roots)
        self.assertEqual(result.entries, [])
        self.assertEqual(result.issues, [])

    def test_broken_manifest_isolated_as_issue(self) -> None:
        """一个坏插件不能影响其他插件被发现。"""
        bad = self.root / "broken"
        bad.mkdir()
        (bad / "plugin.json").write_text("{not json", encoding="utf-8")
        write_plugin(self.root / "good", entry_code="def load(api):\n    return None\n")

        result = scan_plugins(self.roots)
        self.assertEqual([entry.id for entry in result.entries], ["demo-plugin"])
        self.assertEqual(len(result.issues), 1)
        self.assertIn("broken", str(result.issues[0].path))

    def test_duplicate_id_is_reported_and_ignored(self) -> None:
        write_plugin(self.root / "first", entry_code="def load(api):\n    return None\n")
        write_plugin(self.root / "second", entry_code="def load(api):\n    return None\n")
        result = scan_plugins(self.roots)
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(len(result.issues), 1)
        self.assertIn("重复", result.issues[0].message)

    def test_missing_entry_file_marks_error(self) -> None:
        write_plugin(self.root / "noentry")
        result = scan_plugins(self.roots)
        self.assertEqual(len(result.entries), 1)
        self.assertTrue(result.entries[0].entry_missing)
        self.assertEqual(result.entries[0].status, STATUS_ERROR)
        self.assertFalse(result.entries[0].loadable)

    def test_empty_roots_are_tolerated(self) -> None:
        result = scan_plugins([(self.root / "does-not-exist", False)])
        self.assertEqual(result.entries, [])
        self.assertEqual(result.issues, [])


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir(self)
        self.registry = PluginRegistry([(self.root, False)])

    def test_reload_discovers_plugins(self) -> None:
        write_plugin(self.root / "demo", entry_code="def load(api):\n    return None\n")
        self.registry.reload()
        self.assertEqual([entry.id for entry in self.registry.entries], ["demo-plugin"])
        self.assertEqual(len(self.registry.rows()), 1)

    def test_disable_then_reload_keeps_disabled(self) -> None:
        """禁用状态必须跨重扫保留，否则用户关掉的插件会自己回来。"""
        write_plugin(self.root / "demo", entry_code="def load(api):\n    return None\n")
        self.registry.reload()
        self.registry.set_enabled("demo-plugin", False)
        self.assertEqual(self.registry.get("demo-plugin").status, STATUS_DISABLED)

        self.registry.reload()
        entry = self.registry.get("demo-plugin")
        self.assertFalse(entry.enabled)
        self.assertEqual(entry.status, STATUS_DISABLED)
        self.assertFalse(entry.loadable)

    def test_reenable_restores_ready(self) -> None:
        write_plugin(self.root / "demo", entry_code="def load(api):\n    return None\n")
        self.registry.reload()
        self.registry.set_enabled("demo-plugin", False)
        self.registry.set_enabled("demo-plugin", True)
        self.assertEqual(self.registry.get("demo-plugin").status, STATUS_READY)
        self.assertTrue(self.registry.get("demo-plugin").loadable)

    def test_reenable_keeps_error_for_missing_entry(self) -> None:
        write_plugin(self.root / "noentry")
        self.registry.reload()
        self.registry.set_enabled("demo-plugin", False)
        self.registry.set_enabled("demo-plugin", True)
        self.assertEqual(self.registry.get("demo-plugin").status, STATUS_ERROR)

    def test_unknown_plugin_operations_are_noops(self) -> None:
        self.registry.reload()
        self.assertIsNone(self.registry.set_enabled("nope", True))
        self.assertIsNone(self.registry.get("nope"))
        self.registry.mark_error("nope", "x")  # 不应抛出


# ---------------------------------------------------------------------------
# 加载与卸载
# ---------------------------------------------------------------------------

class LoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir(self)
        self.registry = PluginRegistry([(self.root, False)])

    def _load(self, plugin_id: str = "demo-plugin"):
        self.registry.reload()
        entry = self.registry.get(plugin_id)
        api = PluginApi(entry.manifest)
        entry.instance = load_plugin(entry, api)
        return entry

    def test_loads_plugin_exposing_load(self) -> None:
        write_plugin(self.root / "demo", entry_code=(
            "class Box:\n"
            "    def unload(self):\n"
            "        self.unloaded = True\n"
            "def load(api):\n"
            "    api.log('hello')\n"
            "    return Box()\n"
        ))
        entry = self._load()
        self.assertIsNotNone(entry.instance)
        self.assertTrue(hasattr(entry.instance, "unload"))

    def test_missing_load_function_raises(self) -> None:
        write_plugin(self.root / "demo", entry_code="x = 1\n")
        self.registry.reload()
        entry = self.registry.get("demo-plugin")
        with self.assertRaises(PluginLoadError) as caught:
            load_plugin(entry, PluginApi(entry.manifest))
        self.assertIn("load(api)", str(caught.exception))

    def test_import_error_is_wrapped(self) -> None:
        write_plugin(self.root / "demo", entry_code="raise RuntimeError('boom')\n")
        self.registry.reload()
        entry = self.registry.get("demo-plugin")
        with self.assertRaises(PluginLoadError) as caught:
            load_plugin(entry, PluginApi(entry.manifest))
        self.assertIn("boom", str(caught.exception))

    def test_syntax_error_is_wrapped(self) -> None:
        write_plugin(self.root / "demo", entry_code="def load(api)\n    return None\n")
        self.registry.reload()
        entry = self.registry.get("demo-plugin")
        with self.assertRaises(PluginLoadError):
            load_plugin(entry, PluginApi(entry.manifest))

    def test_failure_inside_load_is_wrapped(self) -> None:
        write_plugin(self.root / "demo", entry_code=(
            "def load(api):\n"
            "    raise ValueError('bad config')\n"
        ))
        self.registry.reload()
        entry = self.registry.get("demo-plugin")
        with self.assertRaises(PluginLoadError) as caught:
            load_plugin(entry, PluginApi(entry.manifest))
        self.assertIn("bad config", str(caught.exception))

    def test_plugin_can_return_none(self) -> None:
        """load() 返回 None 是合法的（无状态插件）。"""
        write_plugin(self.root / "demo", entry_code="def load(api):\n    return None\n")
        self.registry.reload()
        entry = self.registry.get("demo-plugin")
        self.assertIsNone(load_plugin(entry, PluginApi(entry.manifest)))


class LoadAllIsolationTests(unittest.TestCase):
    """load_all 的核心承诺：一个插件坏掉，其余照常加载。"""

    def setUp(self) -> None:
        self.root = make_temp_dir(self)
        self.registry = PluginRegistry([(self.root, False)])

    def test_bad_plugin_does_not_block_good_ones(self) -> None:
        write_plugin(self.root / "good", entry_code="def load(api):\n    return object()\n")
        write_plugin(
            self.root / "bad",
            id="bad-plugin",
            entry_code="raise RuntimeError('explode')\n",
        )
        self.registry.reload()

        from codex_switch.plugins.loader import load_all

        errors: list[tuple[str, str]] = []
        loaded = load_all(
            self.registry,
            api_factory=lambda manifest: PluginApi(manifest),
            on_error=lambda pid, msg: errors.append((pid, msg)),
        )

        self.assertEqual(loaded, ["demo-plugin"])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][0], "bad-plugin")
        self.assertEqual(self.registry.get("bad-plugin").status, STATUS_ERROR)
        self.assertEqual(self.registry.get("demo-plugin").status, STATUS_READY)

    def test_disabled_plugin_is_not_loaded(self) -> None:
        write_plugin(self.root / "demo", entry_code="def load(api):\n    return object()\n")
        self.registry.reload()
        self.registry.set_enabled("demo-plugin", False)

        from codex_switch.plugins.loader import load_all

        loaded = load_all(self.registry, api_factory=lambda m: PluginApi(m))
        self.assertEqual(loaded, [])


if __name__ == "__main__":
    unittest.main()
