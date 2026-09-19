"""CodeBuddy 多账号插件的测试。

覆盖三件事：
1. 内置插件能被注册表发现并通过清单校验；
2. 插件在受控 API 下能正确读出账号、切换账号，且不改动除凭据文件外的东西；
3. 插件页面用到的调用桥（PluginCallBridge）确实能被 QML 调用——
   这是曾经踩过的坑，见 ``test_bridge_is_a_qobject_so_qml_can_call_it``。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TEST_TMP_ROOT = PROJECT_ROOT / ".tmp" / "test-codebuddy-plugin"

BUILTIN_ROOT = SRC / "codex_switch" / "builtin_plugins"
PLUGIN_DIR = BUILTIN_ROOT / "codebuddy-accounts"


def make_temp_dir(case: unittest.TestCase) -> Path:
    """工作区内的临时目录（受限环境不允许写系统临时目录）。"""
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"{case._testMethodName}-", dir=str(TEST_TMP_ROOT)))
    case.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
    return root


def make_credential(uid: str, nickname: str, *, domain: str = "www.codebuddy.cn") -> dict:
    return {
        "auth": {
            "accessToken": f"token-{uid}",
            "expiresAt": 4102444800000,
            "refreshToken": f"refresh-{uid}",
            "refreshExpiresAt": 4102444800000,
            "domain": domain,
        },
        "account": {"uid": uid, "nickname": nickname},
    }


class BuiltinPluginLayoutTests(unittest.TestCase):
    """插件目录本身必须符合插件规范。"""

    def test_plugin_directory_exists(self) -> None:
        self.assertTrue(PLUGIN_DIR.is_dir(), f"缺少内置插件目录：{PLUGIN_DIR}")

    def test_manifest_is_valid(self) -> None:
        from codex_switch.plugins import load_manifest_file

        manifest = load_manifest_file(PLUGIN_DIR / "plugin.json")
        self.assertEqual(manifest.id, "codebuddy-accounts")
        self.assertTrue(manifest.has_page)
        self.assertTrue(manifest.actions)

    def test_declared_files_exist(self) -> None:
        """清单里声明的入口与页面必须真的存在，否则扫描阶段就会变成错误状态。"""
        from codex_switch.plugins import load_manifest_file

        manifest = load_manifest_file(PLUGIN_DIR / "plugin.json")
        self.assertTrue((PLUGIN_DIR / manifest.entry).is_file())
        self.assertTrue((PLUGIN_DIR / manifest.page).is_file())

    def test_file_permissions_declare_paths(self) -> None:
        """用到 fs:read / fs:write 就必须声明根目录，否则运行期一律被拒绝。"""
        from codex_switch.plugins import load_manifest_file

        manifest = load_manifest_file(PLUGIN_DIR / "plugin.json")
        for permission in ("fs:read", "fs:write"):
            with self.subTest(permission=permission):
                self.assertIn(permission, manifest.permissions)
                self.assertIn(permission, manifest.path_roots)

    def test_page_does_not_touch_filesystem_directly(self) -> None:
        """插件页面只能通过宿主桥取数据，不得自己碰文件系统。

        页面里出现 FileIO / XMLHttpRequest / Qt.createComponent 之类的
        直接访问会绕过插件的权限模型。
        """
        page = (PLUGIN_DIR / "page.qml").read_text(encoding="utf-8")
        for forbidden in ("XMLHttpRequest", "FileIO", "import Qt.labs"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, page)


class PluginDiscoveryTests(unittest.TestCase):
    def test_registry_discovers_builtin_plugin(self) -> None:
        from codex_switch.plugins.registry import PluginRegistry, builtin_plugin_root

        registry = PluginRegistry([(builtin_plugin_root(), True)])
        registry.reload()
        entry = registry.get("codebuddy-accounts")
        self.assertIsNotNone(entry, "内置插件未被发现")
        self.assertEqual(entry.status, "ready")
        self.assertTrue(entry.manifest.has_page)

    def test_plugin_loads_through_the_loader(self) -> None:
        from codex_switch.plugins import PluginApi
        from codex_switch.plugins.loader import load_plugin
        from codex_switch.plugins.registry import PluginRegistry, builtin_plugin_root

        registry = PluginRegistry([(builtin_plugin_root(), True)])
        registry.reload()
        entry = registry.get("codebuddy-accounts")
        instance = load_plugin(entry, PluginApi(entry.manifest))
        self.assertTrue(hasattr(instance, "accounts"))
        self.assertTrue(hasattr(instance, "switch"))


class PluginBehaviourTests(unittest.TestCase):
    """在隔离的 DSH_HOME 下验证插件行为，不碰用户真实凭据。"""

    def setUp(self) -> None:
        self.home = make_temp_dir(self)
        self._saved_env = {
            key: os.environ.get(key)
            for key in ("DSH_HOME", "CODEBUDDY_ACCOUNTS_DIR", "DSH_CODEBUDDY_AUTH_FILE")
        }
        os.environ["DSH_HOME"] = str(self.home)
        # 让插件写到隔离目录里。
        os.environ.pop("CODEBUDDY_ACCOUNTS_DIR", None)
        os.environ.pop("DSH_CODEBUDDY_AUTH_FILE", None)
        self.addCleanup(self._restore_env)

        from codex_switch import codebuddy_core

        self.core = codebuddy_core
        self.auth_path = self.core.resolve_auth_path()
        self.store_dir = self.core.resolve_store_dir()

    def _restore_env(self) -> None:
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _make_instance(self):
        """按宿主的方式构造插件实例（入口模块 + load(api)）。"""
        from codex_switch.plugins import PluginApi
        from codex_switch.plugins.loader import load_plugin
        from codex_switch.plugins.registry import PluginRegistry, builtin_plugin_root

        registry = PluginRegistry([(builtin_plugin_root(), True)])
        registry.reload()
        entry = registry.get("codebuddy-accounts")
        return load_plugin(entry, PluginApi(entry.manifest))

    def _write_live(self, credential: dict) -> None:
        self.core.write_credential_file(self.auth_path, credential)

    def test_status_reports_empty_store(self) -> None:
        instance = self._make_instance()
        state = instance.status()
        self.assertEqual(state["count"], 0)
        self.assertEqual(state["current"], {"available": False, "error": "凭据文件不存在：" + str(self.auth_path)})

    def test_save_current_creates_snapshot(self) -> None:
        self._write_live(make_credential("uid-1", "甲"))
        instance = self._make_instance()
        result = instance.save_current("")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(instance.accounts()), 1)
        self.assertTrue(instance.accounts()[0]["current"])

    def test_switch_changes_live_credential(self) -> None:
        self._write_live(make_credential("uid-1", "甲"))
        instance = self._make_instance()
        instance.save_current("")

        # 换一个账号作为当前生效的凭据，再切回去。
        self._write_live(make_credential("uid-2", "乙"))
        instance.save_current("")

        result = instance.switch("甲")
        self.assertTrue(result["ok"], result)
        live = self.core.load_credential_file(self.auth_path)
        self.assertEqual(live["account"]["uid"], "uid-1")

    def test_switch_by_sequence_number(self) -> None:
        for uid, nickname in (("uid-1", "甲"), ("uid-2", "乙")):
            self._write_live(make_credential(uid, nickname))
            instance = self._make_instance()
            instance.save_current("")

        instance = self._make_instance()
        result = instance.switch("1")
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            self.core.load_credential_file(self.auth_path)["account"]["uid"], "uid-1"
        )

    def test_switch_to_unknown_account_reports_error_without_raising(self) -> None:
        self._write_live(make_credential("uid-1", "甲"))
        instance = self._make_instance()
        instance.save_current("")

        result = instance.switch("不存在")
        self.assertFalse(result["ok"])
        self.assertIn("没有匹配", result["message"])

    def test_switch_creates_backup_of_previous_credential(self) -> None:
        """切换前必须备份，误切了还能捞回来。"""
        self._write_live(make_credential("uid-1", "甲"))
        instance = self._make_instance()
        instance.save_current("")
        self._write_live(make_credential("uid-2", "乙"))
        instance.save_current("")

        instance.switch("甲")
        backups = list((self.home / "codebuddy-auth-backups").glob("*.json"))
        self.assertEqual(len(backups), 1)

    def test_remove_deletes_snapshot(self) -> None:
        self._write_live(make_credential("uid-1", "甲"))
        instance = self._make_instance()
        instance.save_current("")
        self.assertEqual(len(instance.accounts()), 1)

        result = instance.remove("甲")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(instance.accounts()), 0)

    def test_switch_does_not_modify_plugin_source(self) -> None:
        """核心承诺：切换只在凭据文件之外写副本，不碰插件源码。

        这里用"插件目录内容哈希不变"来验证——用户最担心的就是
        多开工具改了插件导致升级冲突。
        """
        def snapshot() -> dict:
            return {
                path.name: path.read_bytes()
                for path in PLUGIN_DIR.iterdir() if path.is_file()
            }

        before = snapshot()
        self._write_live(make_credential("uid-1", "甲"))
        instance = self._make_instance()
        instance.save_current("")
        instance.switch("1")
        self.assertEqual(snapshot(), before)

    def test_import_directory_brings_in_multiple_accounts(self) -> None:
        exports = make_temp_dir(self)
        for index, (uid, nickname) in enumerate((("uid-a", "甲"), ("uid-b", "乙")), start=1):
            (exports / f"acct{index}.info").write_text(
                json.dumps(make_credential(uid, nickname), ensure_ascii=False),
                encoding="utf-8",
            )
        # 非凭据文件必须被跳过，而不是被当成坏账号报错。
        (exports / "notes.txt").write_text("无关文件", encoding="utf-8")

        instance = self._make_instance()
        result = instance.import_directory(str(exports))
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["imported"]), 2)
        self.assertEqual(len(instance.accounts()), 2)

    def test_import_directory_reports_bad_files_without_aborting(self) -> None:
        exports = make_temp_dir(self)
        (exports / "good.info").write_text(
            json.dumps(make_credential("uid-a", "甲"), ensure_ascii=False), encoding="utf-8",
        )
        (exports / "broken.info").write_text("{not json", encoding="utf-8")

        instance = self._make_instance()
        result = instance.import_directory(str(exports))
        # 好的那个必须进来，坏的那个只记录失败。
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["imported"]), 1)
        self.assertEqual(len(result["failed"]), 1)

    def test_import_missing_directory_reports_error(self) -> None:
        instance = self._make_instance()
        result = instance.import_directory(str(self.home / "nope"))
        self.assertFalse(result["ok"])
        self.assertIn("不是目录", result["message"])

    def test_run_action_returns_summary(self) -> None:
        self._write_live(make_credential("uid-1", "甲"))
        instance = self._make_instance()
        instance.save_current("")
        message = instance.run_action("refresh")
        self.assertIn("1", message)
        self.assertIn("甲", message)

    def test_run_action_unknown_key_is_reported(self) -> None:
        instance = self._make_instance()
        self.assertIn("未知动作", instance.run_action("nope"))


QT_READY = False
try:
    from codex_switch.ui_v2.qt_compat import QT_AVAILABLE

    QT_READY = bool(QT_AVAILABLE)
except Exception:  # noqa: BLE001
    pass


@unittest.skipUnless(QT_READY, "需要 PySide6 才能测调用桥")
class PluginCallBridgeTests(unittest.TestCase):
    """调用桥必须真的是 QObject，否则 QML 调不动插件方法。"""

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QGuiApplication

        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def _bridge(self, instance):
        from codex_switch.ui_v2.plugin_bridge import PluginCallBridge

        return PluginCallBridge(instance)

    def test_bridge_is_a_qobject_so_qml_can_call_it(self) -> None:
        """回归测试：插件实例本身不能直接交给 QML。

        把普通 Python 对象作为 QVariant 传给 QML 后，``instance.foo()`` 会报
        "Property 'foo' of object QVariant(...) is not a function"，插件页面
        因此完全无法工作。宿主必须包一层 QObject。
        """
        from PySide6.QtCore import QObject

        instance = _StubInstance()
        bridge = self._bridge(instance)
        self.assertIsInstance(bridge, QObject)

    def test_bridge_exposes_plugin_data(self) -> None:
        bridge = self._bridge(_StubInstance())
        self.assertEqual(len(bridge.accounts()), 2)
        self.assertEqual(bridge.status()["count"], 2)

    def test_bridge_swallows_plugin_exceptions(self) -> None:
        """插件抛异常必须收敛成结构化结果，不能冒泡成界面报错。"""
        bridge = self._bridge(_StubInstance(explode=True))
        result = bridge.switch("anything")
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["message"])

    def test_bridge_rejects_methods_outside_the_whitelist(self) -> None:
        """只允许白名单里的方法，避免插件内部方法被界面随手触发。"""
        from codex_switch.ui_v2.plugin_bridge import ALLOWED_METHODS

        self.assertIn("switch", ALLOWED_METHODS)
        self.assertNotIn("__init__", ALLOWED_METHODS)
        self.assertNotIn("_call", ALLOWED_METHODS)

        bridge = self._bridge(_StubInstance())
        result = bridge._call("secret_internal")
        self.assertFalse(result["ok"])

    def test_every_method_the_page_calls_is_whitelisted(self) -> None:
        """页面里出现的每个 `instance.xxx(` 都必须在白名单里。

        正则用 ``\\b`` 而不是 ``\\.``：页面里既有 ``page.instance.foo(...)``
        也有裸的 ``instance.foo()``，只匹配带点前缀的那种会漏掉一半调用。
        """
        import re

        from codex_switch.ui_v2.plugin_bridge import ALLOWED_METHODS

        page = (PLUGIN_DIR / "page.qml").read_text(encoding="utf-8")
        called = set(re.findall(r"\binstance\.([a-z_]+)\s*\(", page))
        self.assertTrue(called, "没有从 page.qml 解析出任何调用")
        missing = sorted(name for name in called if name not in ALLOWED_METHODS)
        self.assertEqual(missing, [], f"这些方法不在调用桥白名单里：{missing}")

    def test_bridge_returns_empty_defaults_when_method_missing(self) -> None:
        """插件没有某个方法时返回安全默认值，而不是 None 让页面崩掉。"""
        bridge = self._bridge(_StubInstance(without=("accounts", "status")))
        self.assertEqual(bridge.accounts(), [])
        self.assertEqual(bridge.status(), {})


_MISSING = object()


class _StubInstance:
    """最小插件替身，用来测桥而不依赖真实凭据。

    ``without`` 里的方法名要表现得像"插件没有实现它"，
    所以用哨兵值遮蔽类方法，再在取属性时抛 ``AttributeError``。
    直接写 ``__getattr__`` 会把普通属性访问也一起弄坏。
    """

    def __init__(self, *, explode: bool = False, without: tuple[str, ...] = ()) -> None:
        self.explode = explode
        for name in without:
            # 实例属性遮蔽掉类方法，等价于"插件没实现这个方法"。
            object.__setattr__(self, name, _MISSING)

    def __getattribute__(self, name):
        value = object.__getattribute__(self, name)
        if value is _MISSING:
            raise AttributeError(name)
        return value

    def accounts(self):
        return [{"seq": 1, "nickname": "甲"}, {"seq": 2, "nickname": "乙"}]

    def status(self):
        return {"count": 2}

    def current(self):
        return {"available": True, "nickname": "甲"}

    def switch(self, key):
        if self.explode:
            raise RuntimeError("boom")
        return {"ok": True, "message": f"switched {key}"}

    def save_current(self, label):
        return {"ok": True, "message": "saved"}

    def remove(self, key):
        return {"ok": True, "message": "removed"}

    def import_directory(self, directory):
        return {"ok": True, "message": "imported"}

    def import_files(self, paths):
        if self.explode:
            raise RuntimeError("boom")
        return {"ok": True, "message": f"imported {len(paths)}", "paths": list(paths)}


class PluginImportTests(unittest.TestCase):
    """导入凭据文件的功能。

    整个流程在隔离的 ``DSH_HOME`` 里跑，绝不触碰用户真实凭据。
    覆盖三类容易出问题的地方：
    1. 文件形态差异（.json / 带 BOM 的 .info / 坏文件）；
    2. 坏文件不能中断整批导入，且原因要能定位到具体文件；
    3. 导入后账号要真的能列出来、能切换过去。
    """

    def setUp(self) -> None:
        self.home = make_temp_dir(self)
        self._previous = {
            "DSH_HOME": os.environ.get("DSH_HOME"),
            "CODEBUDDY_ACCOUNTS_DIR": os.environ.get("CODEBUDDY_ACCOUNTS_DIR"),
            "DSH_CODEBUDDY_AUTH_FILE": os.environ.get("DSH_CODEBUDDY_AUTH_FILE"),
        }
        os.environ["DSH_HOME"] = str(self.home)
        for key in ("CODEBUDDY_ACCOUNTS_DIR", "DSH_CODEBUDDY_AUTH_FILE"):
            os.environ.pop(key, None)
        self.addCleanup(self._restore_env)

        import importlib

        from codex_switch import codebuddy_core

        importlib.reload(codebuddy_core)
        self.core = codebuddy_core

        self.exports = make_temp_dir(self)
        self.plugin = self._load_plugin()

    def _restore_env(self) -> None:
        for key, value in self._previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import importlib

        from codex_switch import codebuddy_core

        importlib.reload(codebuddy_core)

    def _load_plugin(self):
        from codex_switch.plugins import PluginApi
        from codex_switch.plugins.loader import load_plugin
        from codex_switch.plugins.registry import PluginRegistry, builtin_plugin_root

        registry = PluginRegistry([(builtin_plugin_root(), True)])
        registry.reload()
        entry = registry.get("codebuddy-accounts")
        self.assertIsNotNone(entry, "内置插件没有被发现")
        return load_plugin(entry, PluginApi(entry.manifest))

    def _write(self, name: str, uid: str, nickname: str, *, bom: bool = False) -> Path:
        path = self.exports / name
        text = json.dumps(make_credential(uid, nickname), ensure_ascii=False)
        path.write_text(text, encoding="utf-8-sig" if bom else "utf-8")
        return path

    def test_import_single_json_file(self) -> None:
        path = self._write("a.json", "uid-aaa", "甲号")
        result = self.plugin.import_files([str(path)])
        self.assertTrue(result["ok"], result["message"])
        self.assertIn("甲号", result["message"])

    def test_import_info_file_with_bom(self) -> None:
        """codebuddy2api 导出的 .info 常带 BOM，必须能导入。"""
        path = self._write("b.info", "uid-bbb", "乙号", bom=True)
        result = self.plugin.import_files([str(path)])
        self.assertTrue(result["ok"], result["message"])
        self.assertIn("乙号", result["message"])

    def test_bad_file_is_skipped_without_losing_the_rest(self) -> None:
        """一个坏文件不该让整批导入失败，而且原因要能定位到文件名。"""
        good = self._write("good.json", "uid-good", "好号")
        bad = self.exports / "broken.json"
        bad.write_text("{ not json", encoding="utf-8")

        result = self.plugin.import_files([str(bad), str(good)])
        self.assertTrue(result["ok"], "好文件应当仍然被导入")
        self.assertTrue(result["failed"], "坏文件应当出现在失败列表里")
        self.assertTrue(any("broken.json" in item for item in result["failed"]),
                        f"失败原因没有指明是哪个文件：{result['failed']}")

    def test_import_directory_collects_json_and_info(self) -> None:
        self._write("a.json", "uid-a", "甲号")
        self._write("b.info", "uid-b", "乙号", bom=True)
        result = self.plugin.import_directory(str(self.exports))
        self.assertTrue(result["ok"], result["message"])
        self.assertEqual(len(result["imported"]), 2, result["imported"])

    def test_empty_selection_is_reported_not_crashed(self) -> None:
        result = self.plugin.import_files([])
        self.assertFalse(result["ok"])
        self.assertIn("没有选中", result["message"])

    def test_missing_path_is_rejected(self) -> None:
        result = self.plugin.import_files([str(self.exports / "nope.json")])
        self.assertFalse(result["ok"])

    def test_imported_account_appears_and_can_be_switched_to(self) -> None:
        """导入不是终点——账号要能列出来、能切过去，才算真的可用。"""
        path = self._write("a.json", "uid-aaa", "甲号")
        self.assertTrue(self.plugin.import_files([str(path)])["ok"])

        names = [row["nickname"] for row in self.plugin.accounts()]
        self.assertIn("甲号", names, f"导入的账号没出现在列表里：{names}")

        result = self.plugin.switch("甲号")
        self.assertTrue(result["ok"], result["message"])
        live = self.core.load_credential_file(self.core.resolve_auth_path())
        self.assertEqual(live["account"]["uid"], "uid-aaa")

    def test_directory_selection_expands_to_files(self) -> None:
        """页面的文件选择器可能返回目录，插件要能识别并展开。"""
        self._write("a.json", "uid-a", "甲号")
        result = self.plugin.import_files([str(self.exports)])
        self.assertTrue(result["ok"], result["message"])
        self.assertIn("甲号", result["message"])


class ImportBridgeTests(unittest.TestCase):
    """导入相关的桥接签名——写错会静默失效。"""

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QGuiApplication

        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_import_files_slot_takes_a_variant_list(self) -> None:
        """必须声明成 QVariantList。

        QML 传的是 JS 数组；若把签名写成 ``str``，Qt 匹配不到就不派发，
        按钮点了没反应且没有任何报错——这个坑本项目已经踩过一次。
        """
        from codex_switch.ui_v2.plugin_bridge import PluginCallBridge

        bridge = PluginCallBridge(_StubInstance())
        meta = bridge.metaObject()
        signature = None
        for index in range(meta.methodCount()):
            method = meta.method(index)
            if bytes(method.name()) == b"import_files":
                signature = method.methodSignature().data().decode()
        self.assertIsNotNone(signature, "桥上没有注册 import_files")
        self.assertIn("QVariantList", signature,
                      f"签名不是列表类型，QML 调用会静默失效：{signature}")

    def test_bridge_forwards_paths_to_the_plugin(self) -> None:
        from codex_switch.ui_v2.plugin_bridge import PluginCallBridge

        instance = _StubInstance()
        bridge = PluginCallBridge(instance)
        result = bridge.import_files(["G:/a.json", "G:/b.info"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["paths"], ["G:/a.json", "G:/b.info"])

    def test_bridge_strips_blank_paths(self) -> None:
        """空白项直接丢掉，不要送给插件当成路径。"""
        from codex_switch.ui_v2.plugin_bridge import PluginCallBridge

        bridge = PluginCallBridge(_StubInstance())
        result = bridge.import_files(["G:/a.json", "", "   ", None])
        self.assertEqual(result["paths"], ["G:/a.json"])


class PluginPageImportUiTests(unittest.TestCase):
    """插件页面必须真的把导入入口接出来，而不只是后端有方法。

    "后端有实现但界面没入口"是本项目真实出现过的问题：``import_directory``
    早就在插件与桥里实现了，页面却一直没有按钮，用户根本用不到。
    """

    def setUp(self) -> None:
        self.qml = (PLUGIN_DIR / "page.qml").read_text(encoding="utf-8")

    def test_page_has_import_actions(self) -> None:
        for marker in ("导入凭据文件", "导入目录"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.qml, f"页面上没有「{marker}」按钮")

    def test_page_calls_the_import_bridge_methods(self) -> None:
        self.assertIn("import_files(", self.qml)
        self.assertIn("import_directory(", self.qml)

    def test_page_imports_qtquick_dialogs(self) -> None:
        """文件选择器必须用 QtQuick.Dialogs。

        QtWidgets 的 QFileDialog 在本应用里**会让进程崩溃**（实测退出码
        0xC0000409），因为应用是 QGuiApplication 而非 QApplication。
        """
        self.assertIn("import QtQuick.Dialogs", self.qml)
        # 只看代码，不看注释：注释里正当地提到了这个反例（写清楚"不能用它"），
        # 直接搜全文会命中注释，导致测试永远失败。
        code = "\n".join(
            line for line in self.qml.splitlines()
            if not line.lstrip().startswith("//")
        )
        self.assertNotIn("QFileDialog", code, "代码里不应使用 QtWidgets 的 QFileDialog")

    def test_page_uses_file_and_folder_dialogs(self) -> None:
        self.assertIn("FileDialog {", self.qml)
        self.assertIn("FolderDialog {", self.qml)

    def test_page_converts_file_urls_to_local_paths(self) -> None:
        """选择器给的是 file:// URL，插件要的是本地路径，必须转换。"""
        self.assertIn("function toPath(", self.qml)
        self.assertIn("decodeURIComponent", self.qml,
                      "路径里的百分号转义（如空格 %20）必须解码")

    def test_manifest_declares_fs_read_for_import(self) -> None:
        """导入要读外部凭据文件，权限声明必须覆盖这一点。"""
        manifest = json.loads((PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"))
        self.assertIn("fs:read", manifest["permissions"])
        self.assertIn("fs:read", manifest.get("paths", {}))


class CodeBuddyEnvironmentTests(unittest.TestCase):
    """DSH 多开适配：CodeBuddy 凭据按 harness home 各存一份。

    因此"当前账号"是**按环境**而言的——给独立实例切换账号，必须写它自己的
    ``<home>/codebuddy-auth.json``，不能碰共用的 ``~/.dsh``。
    账号快照库则刻意共用一份，让同一批账号能在各环境间复用。
    """

    def setUp(self) -> None:
        self.root = make_temp_dir(self)
        self._saved = {
            key: os.environ.get(key)
            for key in ("DSH_HOME", "CODEBUDDY_ACCOUNTS_DIR", "DSH_CODEBUDDY_AUTH_FILE")
        }
        os.environ["DSH_HOME"] = str(self.root / "shared")
        os.environ["CODEBUDDY_ACCOUNTS_DIR"] = str(self.root / "accounts")
        os.environ.pop("DSH_CODEBUDDY_AUTH_FILE", None)
        self.addCleanup(self._restore)

        from codex_switch import codebuddy_core

        self.core = codebuddy_core
        self.shared_home = self.root / "shared"
        self.isolated_home = self.root / "isolated"
        self.isolated_home.mkdir(parents=True, exist_ok=True)
        self._seed_snapshots()

    def _restore(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _credential(self, uid: str, nickname: str) -> dict:
        return {
            "auth": {
                "accessToken": f"tok-{uid}",
                "expiresAt": 4102444800000,
                "refreshToken": f"ref-{uid}",
                "refreshExpiresAt": 4102444800000,
                "domain": "www.codebuddy.cn",
            },
            "account": {"uid": uid, "nickname": nickname},
        }

    def _seed_snapshots(self) -> None:
        """三个账号都进快照库，再把甲/乙分别写进两个环境的凭据文件。

        注意：``rows()`` 的 "current" 是拿当前凭据的 uid 去**匹配快照**得出的，
        所以被测的账号必须真的在快照库里，否则一律标成非当前。
        """
        for uid, nickname in (("uid-aaa", "甲号"), ("uid-bbb", "乙号"), ("uid-ccc", "丙号")):
            path = self.root / f"{nickname}.json"
            path.write_text(
                json.dumps(self._credential(uid, nickname), ensure_ascii=False),
                encoding="utf-8",
            )
            self.core.import_files([path])
        self.core.write_credential_file(
            self.core.resolve_auth_path(self.shared_home),
            self._credential("uid-aaa", "甲号"),
        )
        self.core.write_credential_file(
            self.core.resolve_auth_path(self.isolated_home),
            self._credential("uid-bbb", "乙号"),
        )

    # -- 路径解析 --------------------------------------------------------
    def test_auth_path_follows_the_given_home(self) -> None:
        shared = self.core.resolve_auth_path(self.shared_home)
        isolated = self.core.resolve_auth_path(self.isolated_home)
        self.assertNotEqual(shared, isolated)
        self.assertEqual(shared.parent, self.shared_home)
        self.assertEqual(isolated.parent, self.isolated_home)

    def test_explicit_home_ignores_the_auth_file_escape_hatch(self) -> None:
        """指定了环境就必须读写那个环境，不能被环境变量带偏。

        ``DSH_CODEBUDDY_AUTH_FILE`` 表达的是"当前进程用哪份凭据"；一旦用户
        明确选了目标环境，再用它会切错地方。
        """
        os.environ["DSH_CODEBUDDY_AUTH_FILE"] = str(self.root / "elsewhere.json")
        resolved = self.core.resolve_auth_path(self.isolated_home)
        self.assertEqual(resolved, self.isolated_home / "codebuddy-auth.json")

    def test_snapshot_store_is_shared_across_environments(self) -> None:
        """快照库共用，否则在 A 环境存的账号在 B 环境看不到。"""
        self.assertEqual(self.core.resolve_store_dir(), self.root / "accounts")
        self.assertIn("乙号--uid-bbb.json", self.core.SnapshotStore(
            self.core.resolve_store_dir()).list_names())

    # -- 每个环境各自的"当前账号" -----------------------------------------
    def test_current_is_per_environment(self) -> None:
        self.assertEqual(self.core.read_live_uid(self.shared_home), "uid-aaa")
        self.assertEqual(self.core.read_live_uid(self.isolated_home), "uid-bbb")

    def test_rows_mark_current_per_environment(self) -> None:
        store = self.core.SnapshotStore(self.core.resolve_store_dir())
        shared = [r["nickname"] for r in store.rows(self.shared_home) if r["current"]]
        isolated = [r["nickname"] for r in store.rows(self.isolated_home) if r["current"]]
        self.assertEqual(shared, ["甲号"])
        self.assertEqual(isolated, ["乙号"])

    def test_rows_without_home_keeps_the_old_behaviour(self) -> None:
        """不传 home 时按 DSH_HOME 解析，历史行为不变。"""
        store = self.core.SnapshotStore(self.core.resolve_store_dir())
        current = [r["nickname"] for r in store.rows() if r["current"]]
        self.assertEqual(current, ["甲号"])

    # -- 切换的作用范围 --------------------------------------------------
    def test_switch_to_isolated_home_leaves_shared_untouched(self) -> None:
        """核心断言：给独立实例切换账号，共用环境不受影响。"""
        result = self.core.switch_to("丙号", home=self.isolated_home)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(
            Path(result.detail["authPath"]),
            self.isolated_home / "codebuddy-auth.json",
        )
        self.assertEqual(self.core.read_live_uid(self.isolated_home), "uid-ccc")
        self.assertEqual(self.core.read_live_uid(self.shared_home), "uid-aaa",
                         "共用环境的凭据被误改了")

    def test_switch_to_shared_home_leaves_isolated_untouched(self) -> None:
        self.core.switch_to("丙号", home=self.shared_home)
        self.assertEqual(self.core.read_live_uid(self.shared_home), "uid-ccc")
        self.assertEqual(self.core.read_live_uid(self.isolated_home), "uid-bbb",
                         "独立实例的凭据被误改了")

    def test_switch_backs_up_only_the_target_environment(self) -> None:
        """备份只应出现在被切换的那个环境里。"""
        self.core.switch_to("丙号", home=self.isolated_home)
        self.assertTrue((self.isolated_home / "codebuddy-auth-backups").is_dir())
        self.assertFalse((self.shared_home / "codebuddy-auth-backups").exists())

    def test_save_current_reads_the_given_home(self) -> None:
        """从指定环境保存的应当是**那个环境**的账号。"""
        self.core.save_current(home=self.isolated_home)
        names = self.core.SnapshotStore(self.core.resolve_store_dir()).list_names()
        self.assertTrue(any("乙号" in name for name in names), names)


class CodeBuddyEnvironmentPluginTests(unittest.TestCase):
    """插件层：environments() 与 *_of 方法的行为。"""

    def setUp(self) -> None:
        self.root = make_temp_dir(self)
        self._saved = {
            key: os.environ.get(key)
            for key in ("DSH_HOME", "DSH_INSTANCES_DIR", "CODEBUDDY_ACCOUNTS_DIR",
                        "DSH_CODEBUDDY_AUTH_FILE")
        }
        os.environ["DSH_HOME"] = str(self.root / "shared")
        os.environ["DSH_INSTANCES_DIR"] = str(self.root / "instances")
        os.environ["CODEBUDDY_ACCOUNTS_DIR"] = str(self.root / "accounts")
        os.environ.pop("DSH_CODEBUDDY_AUTH_FILE", None)
        self.addCleanup(self._restore)
        self.plugin = self._load_plugin()

    def _restore(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _load_plugin(self):
        from codex_switch.plugins import PluginApi
        from codex_switch.plugins.loader import load_plugin
        from codex_switch.plugins.registry import PluginRegistry, builtin_plugin_root

        registry = PluginRegistry([(builtin_plugin_root(), True)])
        registry.reload()
        entry = registry.get("codebuddy-accounts")
        return load_plugin(entry, PluginApi(entry.manifest))

    def _add_instance(self, name: str):
        from codex_switch import dsh_instances

        registry = dsh_instances.InstanceRegistry()
        instance = dsh_instances.new_instance(name, kind="web", isolate=True)
        registry.upsert(instance)
        return instance

    def test_environments_always_include_the_shared_home(self) -> None:
        rows = self.plugin.environments()
        self.assertTrue(rows, "至少要列出共用环境")
        self.assertTrue(any(row["shared"] for row in rows))

    def test_isolated_instance_appears_as_its_own_environment(self) -> None:
        self._add_instance("dev-a")
        rows = self.plugin.environments()
        isolated = [row for row in rows if row["isolated"]]
        self.assertEqual(len(isolated), 1)
        self.assertIn("codebuddy-auth.json", isolated[0]["authPath"])
        # 页面直接渲染这些字段。
        for key in ("authPath", "signedIn", "accountLabel", "label", "home"):
            self.assertIn(key, isolated[0])

    def test_not_signed_in_environment_says_so(self) -> None:
        self._add_instance("dev-a")
        row = [r for r in self.plugin.environments() if r["isolated"]][0]
        self.assertFalse(row["signedIn"], "独立 home 里没有凭据，应显示未登录")
        self.assertEqual(row["accountLabel"], "未登录 CodeBuddy")

    def test_accounts_of_target_marks_no_current_when_not_signed_in(self) -> None:
        """未登录的环境里不该有任何账号被标成"当前"。

        把共用环境登录的账号也存进快照库，确保"没有 current"是因为**该环境
        没登录**，而不是因为快照库里恰好没有这个 uid。
        """
        from codex_switch import codebuddy_core

        credential = {
            "auth": {
                "accessToken": "tok-shared",
                "expiresAt": 4102444800000,
                "refreshToken": "ref-shared",
                "refreshExpiresAt": 4102444800000,
                "domain": "www.codebuddy.cn",
            },
            "account": {"uid": "uid-shared", "nickname": "共用号"},
        }
        source = self.root / "shared.json"
        source.write_text(json.dumps(credential, ensure_ascii=False), encoding="utf-8")
        codebuddy_core.import_credential_file(source)
        codebuddy_core.write_credential_file(
            codebuddy_core.resolve_auth_path(), credential)

        self._add_instance("dev-a")
        isolated = [r for r in self.plugin.environments() if r["isolated"]][0]
        rows = self.plugin.accounts(isolated["id"])
        self.assertTrue(rows)
        self.assertEqual([r["current"] for r in rows], [False] * len(rows))
        self.assertFalse(self.plugin.current(isolated["id"])["available"])

        # 而共用环境里，同一个"共用号"应当被标成当前——证明上面的 False
        # 确实来自"该环境未登录"，不是标记逻辑整体失效。
        shared_id = [r for r in self.plugin.environments() if r["shared"]][0]["id"]
        shared_rows = self.plugin.accounts(shared_id)
        current = [r["nickname"] for r in shared_rows if r["current"]]
        self.assertEqual(current, ["共用号"])

    def test_unknown_target_is_reported_not_raised(self) -> None:
        result = self.plugin.status("nope::web")
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"])

    def test_switch_of_isolated_environment_touches_only_that_home(self) -> None:
        """经由插件切换：只动目标环境。"""
        instance = self._add_instance("dev-a")
        home = instance.home

        # 先在共用环境放一份凭据，再从快照导入一个号用于切换
        from codex_switch import codebuddy_core

        credential = {
            "auth": {
                "accessToken": "tok-shared",
                "expiresAt": 4102444800000,
                "refreshToken": "ref-shared",
                "refreshExpiresAt": 4102444800000,
                "domain": "www.codebuddy.cn",
            },
            "account": {"uid": "uid-shared", "nickname": "共用号"},
        }
        codebuddy_core.write_credential_file(
            codebuddy_core.resolve_auth_path(), credential)

        source = self.root / "import.json"
        source.write_text(json.dumps({
            "auth": {
                "accessToken": "tok-x",
                "expiresAt": 4102444800000,
                "refreshToken": "ref-x",
                "refreshExpiresAt": 4102444800000,
                "domain": "www.codebuddy.cn",
            },
            "account": {"uid": "uid-xxx", "nickname": "独立号"},
        }, ensure_ascii=False), encoding="utf-8")
        codebuddy_core.import_credential_file(source)

        isolated = [r for r in self.plugin.environments() if r["isolated"]][0]
        result = self.plugin.switch("独立号", isolated["id"])
        self.assertTrue(result["ok"], result["message"])
        self.assertTrue((Path(home) / "codebuddy-auth.json").is_file())
        self.assertEqual(codebuddy_core.read_live_uid(Path(home)), "uid-xxx")
        self.assertEqual(codebuddy_core.read_live_uid(), "uid-shared",
                         "共用环境被误改了")


if __name__ == "__main__":
    unittest.main()
