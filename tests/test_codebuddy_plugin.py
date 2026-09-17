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


if __name__ == "__main__":
    unittest.main()
