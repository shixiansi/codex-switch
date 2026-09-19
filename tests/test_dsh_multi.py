"""DSH 多开插件与核心逻辑的测试。

覆盖四件事：

1. 内置插件 ``dsh-multi`` 能被注册表发现并通过清单校验（含敏感权限声明）；
2. 核心逻辑的**纯函数**行为：启动计划、URL 解析、注册表读写；
3. 用假的 Popen 驱动真实状态机，验证"未就绪不算成功""启动失败要清理进程"
   这类只在运行时才暴露的缺陷；
4. 页面用到的调用桥方法确实存在且能被 QML 调用（本项目踩过的坑）。

这些测试都**不会真的启动 DSH**：``InstanceManager`` 的 ``popen`` 是注入的，
因此测试在几毫秒内跑完，也不会残留进程或占用端口。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TEST_TMP_ROOT = PROJECT_ROOT / ".tmp" / "test-dsh-multi"

BUILTIN_ROOT = SRC / "codex_switch" / "builtin_plugins"
PLUGIN_DIR = BUILTIN_ROOT / "dsh-multi"


def make_temp_dir(case: unittest.TestCase) -> Path:
    """工作区内的临时目录（受限环境不允许写系统临时目录）。"""
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"{case._testMethodName}-", dir=str(TEST_TMP_ROOT)))
    case.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
    return root


# ---------------------------------------------------------------------------
# 1. 插件目录与清单
# ---------------------------------------------------------------------------

class BuiltinPluginLayoutTests(unittest.TestCase):
    """插件目录本身必须符合插件规范。"""

    def test_plugin_directory_exists(self) -> None:
        self.assertTrue(PLUGIN_DIR.is_dir(), f"缺少内置插件目录：{PLUGIN_DIR}")

    def test_required_files_exist(self) -> None:
        for name in ("plugin.json", "entry.py", "page.qml"):
            self.assertTrue((PLUGIN_DIR / name).is_file(), f"缺少文件：{name}")

    def test_manifest_is_valid(self) -> None:
        from codex_switch.plugins import load_manifest_file

        manifest = load_manifest_file(PLUGIN_DIR / "plugin.json")
        self.assertEqual(manifest.id, "dsh-multi")
        self.assertEqual(manifest.api_version, 1)
        self.assertEqual(manifest.entry, "entry.py")
        self.assertEqual(manifest.page, "page.qml")

    def test_manifest_declares_the_permissions_it_actually_uses(self) -> None:
        """插件要启动外部进程，就必须声明 exec；文件权限也必须带 paths。"""
        from codex_switch.plugins import load_manifest_file
        from codex_switch.plugins.manifest import (
            PERMISSION_EXEC,
            PERMISSION_FS_READ,
            PERMISSION_FS_WRITE,
        )

        manifest = load_manifest_file(PLUGIN_DIR / "plugin.json")
        self.assertIn(PERMISSION_EXEC, manifest.permissions)
        self.assertIn(PERMISSION_FS_READ, manifest.permissions)
        self.assertIn(PERMISSION_FS_WRITE, manifest.permissions)
        # 声明了文件权限就必须给出根目录，否则加载阶段就会报错。
        self.assertIn(PERMISSION_FS_READ, manifest.path_roots)
        self.assertIn(PERMISSION_FS_WRITE, manifest.path_roots)

    def test_plugin_is_discovered_by_the_registry(self) -> None:
        from codex_switch.plugins.registry import PluginRegistry, builtin_plugin_root

        registry = PluginRegistry([(builtin_plugin_root(), True)])
        registry.reload()
        entry = registry.get("dsh-multi")
        self.assertIsNotNone(entry, "内置插件没有被发现")
        self.assertNotEqual(entry.status, "error", entry.error)
        self.assertFalse(entry.entry_missing)


# ---------------------------------------------------------------------------
# 2. 纯函数：启动计划与 URL 解析
# ---------------------------------------------------------------------------

class ParseWebUrlTests(unittest.TestCase):
    """URL 解析是"实例是否真的就绪"的唯一判据，必须稳。"""

    def test_parses_the_real_dsh_output_line(self) -> None:
        from codex_switch import dsh_instances as core

        text = "dsh web: http://127.0.0.1:12124/?token=5QQqBv1i7twoHU8vBrK_pcKMEmi_IxpRAbnt0jjY_6k\n"
        self.assertEqual(
            core.parse_web_url(text),
            "http://127.0.0.1:12124/?token=5QQqBv1i7twoHU8vBrK_pcKMEmi_IxpRAbnt0jjY_6k",
        )

    def test_returns_empty_when_not_ready(self) -> None:
        from codex_switch import dsh_instances as core

        self.assertEqual(core.parse_web_url(""), "")
        self.assertEqual(core.parse_web_url("starting up...\n"), "")

    def test_uses_the_last_line_when_restarted(self) -> None:
        """日志里出现两次 URL 时取最后一条（重启后的才是当前的）。"""
        from codex_switch import dsh_instances as core

        text = (
            "dsh web: http://127.0.0.1:1111/?token=old\n"
            "dsh web: http://127.0.0.1:2222/?token=new\n"
        )
        self.assertIn("2222", core.parse_web_url(text))


class BuildPlanTests(unittest.TestCase):
    """启动计划是纯函数：算出来的 argv/env 必须可以直接执行。"""

    def setUp(self) -> None:
        from codex_switch import dsh_instances as core

        self.core = core
        self.tmp = make_temp_dir(self)

    def _plan(self, **kwargs):
        instance = self.core.new_instance("probe", **kwargs)
        return instance, self.core.build_plan(instance, base_env={"PATH": "x"})

    def test_web_instance_gets_port_and_no_open(self) -> None:
        """多开时每个实例都不该抢默认浏览器焦点，所以必须带 --no-open。"""
        _, plan = self._plan(kind="web", port=0)
        self.assertIn("--profile", plan.argv)
        self.assertEqual(plan.argv[plan.argv.index("--profile") + 1], "web")
        self.assertIn("--no-open", plan.argv)
        self.assertIn("--port", plan.argv)
        self.assertEqual(plan.argv[plan.argv.index("--port") + 1], "0")

    def test_explicit_port_is_passed_through(self) -> None:
        _, plan = self._plan(kind="web", port=18999)
        self.assertEqual(plan.argv[plan.argv.index("--port") + 1], "18999")

    def test_shared_home_does_not_set_dsh_home(self) -> None:
        """默认共用 ~/.dsh：不能注入 DSH_HOME，否则会悄悄换掉用户的登录态。"""
        _, plan = self._plan(kind="web")
        self.assertNotIn("DSH_HOME", plan.env)

    def test_isolated_home_sets_dsh_home(self) -> None:
        instance, plan = self._plan(kind="web", isolate=True)
        self.assertEqual(plan.env["DSH_HOME"], instance.home)
        self.assertTrue(instance.home, "独立模式必须给出 home 路径")

    def test_invalid_port_is_rejected(self) -> None:
        instance = self.core.Instance(id="a", name="b", port=70000)
        with self.assertRaises(self.core.DshError):
            self.core.build_plan(instance)

    def test_invalid_profile_name_is_rejected(self) -> None:
        """profile 会成为目录名，必须挡住路径穿越式的名字。"""
        instance = self.core.Instance(id="a", name="b", profile="../evil")
        with self.assertRaises(self.core.DshError):
            self.core.build_plan(instance)

    def test_extra_args_are_split_without_leaving_quotes(self) -> None:
        _, plan = self._plan(kind="web", extra_args='--trusted-host "my host"')
        self.assertIn("--trusted-host", plan.argv)
        self.assertIn("my host", plan.argv)

    def test_plan_does_not_create_directories(self) -> None:
        """build_plan 是纯的：目录创建应该只发生在 start 里。"""
        instance = self.core.new_instance("pure", isolate=True)
        self.core.build_plan(instance)
        self.assertFalse(Path(instance.home).exists(), "build_plan 不应创建目录")


# ---------------------------------------------------------------------------
# 3. 注册表
# ---------------------------------------------------------------------------

class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        from codex_switch import dsh_instances as core

        self.core = core
        self.root = make_temp_dir(self)
        self.registry = core.InstanceRegistry(self.root)

    def test_save_and_load_round_trip(self) -> None:
        instance = self.core.new_instance("dev", kind="web", port=1234)
        self.registry.save([instance])
        loaded = self.registry.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].name, "dev")
        self.assertEqual(loaded[0].port, 1234)

    def test_corrupt_file_yields_empty_list_not_a_crash(self) -> None:
        """一份坏 JSON 不该让整个插件页面打不开。"""
        self.registry.ensure()
        self.registry.path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(self.registry.load(), [])

    def test_find_by_id_and_by_name(self) -> None:
        instance = self.core.new_instance("dev", kind="web")
        self.registry.save([instance])
        self.assertEqual(self.registry.find(instance.id).name, "dev")
        self.assertEqual(self.registry.find("dev").id, instance.id)

    def test_find_unknown_raises_a_displayable_error(self) -> None:
        with self.assertRaises(self.core.DshError):
            self.registry.find("nope")

    def test_upsert_updates_in_place(self) -> None:
        instance = self.core.new_instance("dev", kind="web", port=1)
        self.registry.upsert(instance)
        instance.port = 4321
        self.registry.upsert(instance)
        loaded = self.registry.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].port, 4321)

    def test_remove(self) -> None:
        instance = self.core.new_instance("dev", kind="web")
        self.registry.save([instance])
        self.registry.remove("dev")
        self.assertEqual(self.registry.load(), [])


# ---------------------------------------------------------------------------
# 4. 运行时状态机（用假的 Popen）
# ---------------------------------------------------------------------------

class _FakeProcess:
    """假的子进程：由测试决定何时"退出"以及退出码。"""

    def __init__(self, pid: int = 4242, exit_code: int | None = None) -> None:
        self.pid = pid
        self._exit_code = exit_code
        self.terminated = False

    def poll(self):
        return self._exit_code

    def terminate(self) -> None:
        self.terminated = True
        self._exit_code = 0


class _FakePopen:
    """可编程的 Popen：把日志写进真实文件，模拟 dsh 的输出。"""

    def __init__(self, log_path: Path, *, lines: list[str], exit_code: int | None = None,
                 pid: int = 4242) -> None:
        self.log_path = Path(log_path)
        self.lines = lines
        self.pid = pid
        self._exit_code = exit_code

    def __call__(self, argv, **kwargs):
        # 真实实现会把 stdout 指到日志文件；这里直接把内容写进去。
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("".join(self.lines), encoding="utf-8")
        return _FakeProcess(pid=self.pid, exit_code=self._exit_code)


class ManagerStateTests(unittest.TestCase):
    """状态机必须能区分"真的起来了"和"进程活着但没就绪"。"""

    def setUp(self) -> None:
        from codex_switch import dsh_instances as core

        self.core = core
        self.root = make_temp_dir(self)
        # 让日志与注册表都落在工作区的临时目录里：既避免污染真实 ~/.dsh，
        # 也保证受限环境下有写权限。
        self.addCleanup(self._restore_env)
        self._previous = os.environ.get("DSH_INSTANCES_DIR")
        os.environ["DSH_INSTANCES_DIR"] = str(self.root)

    def _restore_env(self) -> None:
        if self._previous is None:
            os.environ.pop("DSH_INSTANCES_DIR", None)
        else:
            os.environ["DSH_INSTANCES_DIR"] = self._previous

    def _manager(self, popen, **kwargs):
        registry = self.core.InstanceRegistry(self.root)
        return registry, self.core.InstanceManager(
            registry, popen=popen, poll_interval=0.0,
            start_timeout=kwargs.pop("start_timeout", 2.0), **kwargs,
        )

    def _instance(self):
        return self.core.new_instance("dev", kind="web", port=0)

    def test_start_becomes_running_when_url_appears(self) -> None:
        instance = self._instance()
        log_path = self.core.resolve_log_path(instance.name)
        popen = _FakePopen(
            log_path,
            lines=["booting\n", "dsh web: http://127.0.0.1:32123/?token=tok\n"],
        )
        _, manager = self._manager(popen)
        state = manager.start(instance)
        self.assertEqual(state.status, self.core.STATUS_RUNNING)
        self.assertIn("32123", state.url)
        self.assertEqual(state.port, 32123)

    def test_process_alive_without_url_is_not_reported_as_ready(self) -> None:
        """只输出启动信息、始终不给 URL：必须超时失败，不能报成功。

        真实场景：端口被占用时 dsh 会重试，进程不会立刻退出。
        仅凭"进程还活着"就报成功，用户会拿到一个打不开的地址。
        """
        instance = self._instance()
        log_path = self.core.resolve_log_path(instance.name)
        popen = _FakePopen(log_path, lines=["booting\n"], exit_code=None)
        _, manager = self._manager(popen, start_timeout=0.3)
        with self.assertRaises(self.core.DshError) as ctx:
            manager.start(instance)
        self.assertIn("超时", str(ctx.exception))

    def test_immediate_exit_is_reported_as_failure_with_reason(self) -> None:
        instance = self._instance()
        log_path = self.core.resolve_log_path(instance.name)
        popen = _FakePopen(
            log_path,
            lines=["Error: listen EADDRINUSE: address already in use\n"],
            exit_code=1,
        )
        _, manager = self._manager(popen)
        with self.assertRaises(self.core.DshError) as ctx:
            manager.start(instance)
        self.assertIn("EADDRINUSE", str(ctx.exception))

    def test_timeout_does_not_leave_a_process_behind(self) -> None:
        """超时失败必须把进程收干净，否则会留下占着端口的孤儿进程。

        这是真正会泄漏的路径：进程还活着，但我们已判定启动失败。
        """
        instance = self._instance()
        log_path = self.core.resolve_log_path(instance.name)
        holder: dict = {}

        class RecordingPopen(_FakePopen):
            def __call__(self, argv, **kwargs):
                process = super().__call__(argv, **kwargs)
                holder["process"] = process
                return process

        # 始终不输出 URL 且不退出 → 触发超时。
        popen = RecordingPopen(log_path, lines=["booting\n"], exit_code=None)
        _, manager = self._manager(popen, start_timeout=0.3)
        with self.assertRaises(self.core.DshError):
            manager.start(instance)
        self.assertTrue(holder["process"].terminated, "超时后没有终止子进程")

    def test_self_exit_is_reported_as_failed_without_terminating(self) -> None:
        """进程自己退出的情况：已经死了，不该再去 terminate，但状态要是失败。"""
        instance = self._instance()
        log_path = self.core.resolve_log_path(instance.name)
        popen = _FakePopen(log_path, lines=["boom\n"], exit_code=1)
        _, manager = self._manager(popen, start_timeout=0.3)
        with self.assertRaises(self.core.DshError):
            manager.start(instance)
        # 失败后不留句柄，且状态是"失败"而不是"运行中"。
        self.assertEqual(manager.pid_of(instance.id), 0)
        self.assertEqual(manager.state(instance).status, self.core.STATUS_FAILED)

    def test_start_refuses_when_already_running(self) -> None:
        instance = self._instance()
        log_path = self.core.resolve_log_path(instance.name)
        popen = _FakePopen(
            log_path, lines=["dsh web: http://127.0.0.1:32123/?token=t\n"],
        )
        _, manager = self._manager(popen)
        manager.start(instance)
        with self.assertRaises(self.core.DshError) as ctx:
            manager.start(instance)
        self.assertIn("已经在运行", str(ctx.exception))

    def test_each_start_truncates_the_previous_log(self) -> None:
        """上一轮的 URL 会让"本次是否就绪"永远为真，必须清空日志。"""
        instance = self._instance()
        log_path = self.core.resolve_log_path(instance.name)
        popen = _FakePopen(
            log_path, lines=["dsh web: http://127.0.0.1:1111/?token=old\n"],
        )
        _, manager = self._manager(popen)
        manager.start(instance)
        self.assertEqual(manager.state(instance).port, 1111)

        # 第二轮改成"只启动、不给 URL"，若日志没被清空就会误判为已就绪。
        popen.lines = ["booting\n"]
        popen._exit_code = None
        with self.assertRaises(self.core.DshError):
            manager.start(instance)


class ProbeStateTests(unittest.TestCase):
    """重启后接管：只凭 pid 与日志判断，不能凭空认为在运行。"""

    def setUp(self) -> None:
        from codex_switch import dsh_instances as core

        self.core = core
        self.tmp = make_temp_dir(self)
        self.addCleanup(self._restore_env)
        self._previous = os.environ.get("DSH_INSTANCES_DIR")
        os.environ["DSH_INSTANCES_DIR"] = str(self.tmp)

    def _restore_env(self) -> None:
        if self._previous is None:
            os.environ.pop("DSH_INSTANCES_DIR", None)
        else:
            os.environ["DSH_INSTANCES_DIR"] = self._previous

    def test_instance_without_pid_is_stopped(self) -> None:
        """日志里有旧 URL 也不能算运行中：本会话并没有启动它。"""
        instance = self.core.new_instance("dev", kind="web")
        log_path = self.core.resolve_log_path(instance.name)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("dsh web: http://127.0.0.1:9999/?token=old\n", encoding="utf-8")

        state = self.core.probe_state(instance, pid=0)
        self.assertEqual(state.status, self.core.STATUS_STOPPED)

    def test_live_pid_is_running(self) -> None:
        instance = self.core.new_instance("dev", kind="web")
        log_path = self.core.resolve_log_path(instance.name)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("dsh web: http://127.0.0.1:9999/?token=t\n", encoding="utf-8")

        state = self.core.probe_state(instance, pid=os.getpid())
        self.assertEqual(state.status, self.core.STATUS_RUNNING)
        self.assertEqual(state.port, 9999)


# ---------------------------------------------------------------------------
# 5. 插件层（受控 API 下的行为）
# ---------------------------------------------------------------------------

class PluginBehaviourTests(unittest.TestCase):
    """在真实 PluginApi 下驱动插件，确认权限与返回值形状正确。"""

    def setUp(self) -> None:
        self.addCleanup(self._restore_env)
        self._previous = os.environ.get("DSH_INSTANCES_DIR")
        self.tmp = make_temp_dir(self)
        os.environ["DSH_INSTANCES_DIR"] = str(self.tmp)
        self.plugin = self._load_plugin()

    def _restore_env(self) -> None:
        if self._previous is None:
            os.environ.pop("DSH_INSTANCES_DIR", None)
        else:
            os.environ["DSH_INSTANCES_DIR"] = self._previous

    def _load_plugin(self):
        from codex_switch.plugins import PluginApi
        from codex_switch.plugins.loader import load_plugin
        from codex_switch.plugins.registry import PluginRegistry, builtin_plugin_root

        registry = PluginRegistry([(builtin_plugin_root(), True)])
        registry.reload()
        entry = registry.get("dsh-multi")
        self.assertIsNotNone(entry, "内置插件没有被发现")
        return load_plugin(entry, PluginApi(entry.manifest))

    def test_status_reports_an_empty_registry(self) -> None:
        status = self.plugin.status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["count"], 0)
        self.assertEqual(status["running"], 0)
        # 页面下拉框需要这个选项表。
        self.assertTrue(any(item["value"] == "web" for item in status["kinds"]))

    def test_create_then_list_then_remove(self) -> None:
        result = self.plugin.create({"name": "dev", "kind": "web", "port": "0"})
        self.assertTrue(result["ok"], result["message"])

        rows = self.plugin.instances()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "dev")
        self.assertEqual(rows[0]["status"], "stopped")
        # 页面直接渲染这些字段，必须存在。
        for key in ("statusLabel", "subtitle", "kindLabel", "homeLabel"):
            self.assertIn(key, rows[0])

        removed = self.plugin.remove("dev")
        self.assertTrue(removed["ok"], removed["message"])
        self.assertEqual(self.plugin.instances(), [])

    def test_duplicate_name_is_refused(self) -> None:
        self.plugin.create({"name": "dev", "kind": "web"})
        again = self.plugin.create({"name": "dev", "kind": "web"})
        self.assertFalse(again["ok"])
        self.assertIn("已存在", again["message"])

    def test_empty_name_is_refused(self) -> None:
        result = self.plugin.create({"name": "  ", "kind": "web"})
        self.assertFalse(result["ok"])

    def test_non_numeric_port_is_refused_with_a_readable_message(self) -> None:
        result = self.plugin.create({"name": "dev", "kind": "web", "port": "abc"})
        self.assertFalse(result["ok"])
        self.assertIn("端口", result["message"])

    def test_create_validates_the_plan_before_saving(self) -> None:
        """存下一个永远起不来的实例是最糟的结果，创建时就该拒绝。"""
        result = self.plugin.create({"name": "dev", "kind": "web", "port": "70000"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.plugin.instances(), [], "非法实例被落盘了")

    def test_isolated_instance_records_its_own_home(self) -> None:
        self.plugin.create({"name": "iso", "kind": "web", "isolate": True})
        row = self.plugin.instances()[0]
        self.assertTrue(row["isolated"])
        self.assertTrue(row["home"])

    def test_detail_exposes_command_and_log_path(self) -> None:
        self.plugin.create({"name": "dev", "kind": "web"})
        detail = self.plugin.detail("dev")
        self.assertTrue(detail["ok"])
        self.assertIn("--profile", detail["command"])
        self.assertTrue(detail["logPath"])

    def test_detail_of_unknown_instance_fails_softly(self) -> None:
        detail = self.plugin.detail("ghost")
        self.assertFalse(detail["ok"])
        self.assertTrue(detail["message"])

    def test_url_of_a_stopped_instance_explains_instead_of_returning_nothing(self) -> None:
        self.plugin.create({"name": "dev", "kind": "web"})
        result = self.plugin.url("dev")
        self.assertFalse(result["ok"])
        self.assertIn("没有运行", result["message"])

    def test_stopping_a_stopped_instance_is_not_an_error(self) -> None:
        self.plugin.create({"name": "dev", "kind": "web"})
        result = self.plugin.stop("dev")
        self.assertTrue(result["ok"])
        self.assertIn("本来就没有", result["message"])

    def test_log_of_a_never_started_instance_reads_as_empty(self) -> None:
        self.plugin.create({"name": "dev", "kind": "web"})
        result = self.plugin.log("dev")
        self.assertTrue(result["ok"])
        self.assertTrue(result["text"])

    def test_open_folder_reports_a_path(self) -> None:
        result = self.plugin.open_folder()
        self.assertTrue(result["ok"])
        self.assertTrue(result["path"])

    def test_run_action_reports_counts(self) -> None:
        self.plugin.create({"name": "dev", "kind": "web"})
        message = self.plugin.run_action("refresh-status")
        self.assertIn("1 个实例", message)

    def test_run_action_rejects_unknown_keys(self) -> None:
        self.assertIn("未知动作", self.plugin.run_action("nope"))

    def test_shutdown_keeps_instances_running(self) -> None:
        """关掉管理器不该把用户正在用的 DSH 一起带走。"""
        self.plugin.create({"name": "dev", "kind": "web"})
        self.plugin.shutdown()
        self.assertEqual(len(self.plugin.instances()), 1)


# ---------------------------------------------------------------------------
# 6. 调用桥（QML 能真的调到）
# ---------------------------------------------------------------------------

QT_READY = False
try:
    from codex_switch.ui_v2.qt_compat import QT_AVAILABLE

    QT_READY = bool(QT_AVAILABLE)
except Exception:  # noqa: BLE001
    pass


@unittest.skipUnless(QT_READY, "需要 PySide6 才能测调用桥")
class DshBridgeTests(unittest.TestCase):
    """插件页面调用的方法必须在调用桥的白名单里，否则点击会静默失效。"""

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QGuiApplication

        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_every_method_page_qml_calls_is_whitelisted(self) -> None:
        """页面里出现的每个 `instance.xxx(` 都必须在白名单里。

        正则要用 ``\\b`` 而不是 ``\\.``：页面里既有 ``page.instance.start(...)``
        也有裸的 ``instance.status()``，只匹配带点前缀的那种会漏掉一大半调用
        （曾经因此让这个测试形同虚设）。
        """
        import re

        from codex_switch.ui_v2.plugin_bridge import ALLOWED_METHODS

        page = (PLUGIN_DIR / "page.qml").read_text(encoding="utf-8")
        called = set(re.findall(r"\binstance\.([a-z_]+)\s*\(", page))
        self.assertTrue(called, "没有从 page.qml 解析出任何调用")
        # 这些是页面确实在用、且必须被检查到的关键方法。
        for name in ("install_plugin", "uninstall_plugin", "plugin_targets", "plugin_jobs"):
            self.assertIn(name, called, f"没有解析出页面里对 {name} 的调用")
        missing = sorted(name for name in called if name not in ALLOWED_METHODS)
        self.assertEqual(missing, [], f"这些方法不在调用桥白名单里：{missing}")

    def test_bridge_slots_exist_for_those_methods(self) -> None:
        from codex_switch.ui_v2.plugin_bridge import PluginCallBridge

        for name in ("instances", "detail", "log", "create", "start", "stop",
                     "stop_all", "url", "open_folder"):
            self.assertTrue(
                callable(getattr(PluginCallBridge, name, None)),
                f"调用桥缺少槽方法：{name}",
            )

    def test_bridge_calls_the_plugin_and_returns_data(self) -> None:
        import re

        from codex_switch.plugins import PluginApi
        from codex_switch.plugins.loader import load_plugin
        from codex_switch.plugins.registry import PluginRegistry, builtin_plugin_root
        from codex_switch.ui_v2.plugin_bridge import PluginCallBridge

        root = make_temp_dir(self)
        previous = os.environ.get("DSH_INSTANCES_DIR")
        os.environ["DSH_INSTANCES_DIR"] = str(root)

        def restore():
            if previous is None:
                os.environ.pop("DSH_INSTANCES_DIR", None)
            else:
                os.environ["DSH_INSTANCES_DIR"] = previous

        self.addCleanup(restore)

        registry = PluginRegistry([(builtin_plugin_root(), True)])
        registry.reload()
        instance = load_plugin(registry.get("dsh-multi"), PluginApi(registry.get("dsh-multi").manifest))
        bridge = PluginCallBridge(instance)

        created = bridge.create({"name": "dev", "kind": "web"})
        self.assertTrue(created["ok"], created["message"])
        self.assertEqual(len(bridge.instances()), 1)
        self.assertTrue(bridge.status()["ok"])
        self.assertTrue(bridge.detail("dev")["ok"])
        self.assertTrue(bridge.log("dev")["ok"])
        self.assertTrue(bridge.stop("dev")["ok"])
        self.assertTrue(bridge.remove("dev")["ok"])
        self.assertEqual(bridge.instances(), [])

    def test_bridge_swallows_plugin_exceptions(self) -> None:
        from codex_switch.ui_v2.plugin_bridge import PluginCallBridge

        class Boom:
            def instances(self):
                raise RuntimeError("boom")

        result = PluginCallBridge(Boom()).instances()
        # 桥对列表型返回给安全默认值，关键是**不冒泡**成 QML 报错。
        self.assertEqual(result, [])


@unittest.skipUnless(QT_READY, "需要 PySide6 才能跑 QML 渲染")
class DshPageRenderTests(unittest.TestCase):
    """页面必须真的能被 QML 引擎实例化。

    纯文本检查（"有没有这个方法名"）发现不了类型错误、绑定错误与拼错的
    属性名——那些只有真的 create() 一次才会暴露。
    """

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
        from PySide6.QtGui import QGuiApplication

        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self) -> None:
        self.addCleanup(self._restore_env)
        self._previous = os.environ.get("DSH_INSTANCES_DIR")
        self.root = make_temp_dir(self)
        os.environ["DSH_INSTANCES_DIR"] = str(self.root)

    def _restore_env(self) -> None:
        if self._previous is None:
            os.environ.pop("DSH_INSTANCES_DIR", None)
        else:
            os.environ["DSH_INSTANCES_DIR"] = self._previous

    def test_page_instantiates_and_renders_without_qml_errors(self) -> None:
        import re

        from PySide6.QtCore import QUrl, qInstallMessageHandler
        from PySide6.QtQml import QQmlComponent, QQmlEngine

        from codex_switch.plugins import PluginApi
        from codex_switch.plugins.loader import load_plugin
        from codex_switch.plugins.registry import PluginRegistry, builtin_plugin_root
        from codex_switch.ui_v2.plugin_bridge import PluginCallBridge

        messages: list[str] = []
        previous_handler = qInstallMessageHandler(
            lambda _mode, _ctx, text: messages.append(str(text))
        )
        self.addCleanup(qInstallMessageHandler, previous_handler)

        registry = PluginRegistry([(builtin_plugin_root(), True)])
        registry.reload()
        entry = registry.get("dsh-multi")
        instance = load_plugin(entry, PluginApi(entry.manifest))

        engine = QQmlEngine()
        # 引擎必须比 root 活得久：QQuickItem 的析构需要引擎仍存在，否则
        # teardown 会报 "Internal C++ object already deleted"。挂到 self 上
        # 让它们随测试实例一起存活。
        self._engine = engine
        engine.addImportPath(str(SRC / "codex_switch" / "ui_v2" / "qml"))
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(entry.page_path)))
        self.assertEqual(
            component.status(), QQmlComponent.Status.Ready,
            "\n".join(error.toString() for error in component.errors()),
        )

        root = component.create()
        self.assertIsNotNone(root, "\n".join(e.toString() for e in component.errors()))
        self._root = root

        # 宿主在实例后到时注入；这里模拟同样的注入与重注入。
        bridge = PluginCallBridge(instance)
        root.setProperty("instance", bridge)
        created = bridge.create({"name": "render-test", "kind": "web"})
        self.assertTrue(created["ok"], created["message"])
        root.setProperty("instance", None)
        root.setProperty("instance", bridge)
        self.assertEqual(len(bridge.instances()), 1)
        bridge.remove("render-test")

        # 只关心真正的 QML 缺陷；字体缺失与宿主上下文缺失是环境噪声。
        noise = ("font", "app is not defined", "of null", "Cannot find font")
        real = [
            text for text in messages
            if text.strip() and not any(token in text for token in noise)
            # Theme.qml 读的是宿主注入的 `app`；裸引擎下必然缺失，属预期。
            and "Theme.qml" not in text
        ]
        self.assertEqual(real, [], f"页面渲染产生了 QML 警告：{real}")

    def test_page_has_both_instance_injection_paths(self) -> None:
        """页面必须同时处理 onCompleted 与 onInstanceChanged。

        宿主可能先建页面、插件后加载完，只在 onCompleted 里取数据会拿到空表。
        """
        page = (PLUGIN_DIR / "page.qml").read_text(encoding="utf-8")
        self.assertIn("onInstanceChanged", page)
        self.assertIn("Component.onCompleted", page)

    def test_load_log_populates_text_even_when_empty(self) -> None:
        """没跑过的实例也必须给出可读文案。

        日志为空时若直接留空，用户会分不清"还没启动"和"日志坏了"。
        """
        page = (PLUGIN_DIR / "page.qml").read_text(encoding="utf-8")
        # 页面在拿不到文本时要有兜底，而不是留一片空白。
        self.assertIn("读取日志失败", page)
        # 插件侧对空日志返回占位说明。
        from codex_switch import dsh_instances as core

        registry = core.InstanceRegistry()
        instance = core.new_instance("no-log", kind="web")
        registry.upsert(instance)
        text = core.read_log(instance)
        self.assertTrue(text.strip(), "空日志没有给出任何提示文案")


@unittest.skipUnless(QT_READY, "需要 PySide6 才能跑 QML 窗口测试")
class DshPageLayoutTests(unittest.TestCase):
    """页面布局必须在**真实窗口**里验证。

    教训：用裸 ``QQmlComponent.create()``（没有 QQuickWindow）测量时，positioner
    的高度还停在 polish 之前的旧值——同一个页面会读出"内容永远不增长"的假象，
    从而把好代码改坏。所以这一组测试一律用 ``QQuickView`` 并多次 processEvents。

    覆盖两个真实缺陷：
    1. 内容变多时页面必须能滚动（否则靠下的卡片被挤出可视区）；
    2. 详情/日志必须能关闭（否则"打开后关不掉"）。
    """

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
        from PySide6.QtGui import QGuiApplication

        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self) -> None:
        self.addCleanup(self._restore_env)
        self._previous = os.environ.get("DSH_INSTANCES_DIR")
        self.root_dir = make_temp_dir(self)
        os.environ["DSH_INSTANCES_DIR"] = str(self.root_dir)
        self._build()

    def _restore_env(self) -> None:
        if self._previous is None:
            os.environ.pop("DSH_INSTANCES_DIR", None)
        else:
            os.environ["DSH_INSTANCES_DIR"] = self._previous

    def _build(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtQuick import QQuickView

        from codex_switch.plugins import PluginApi
        from codex_switch.plugins.loader import load_plugin
        from codex_switch.plugins.registry import PluginRegistry, builtin_plugin_root
        from codex_switch.ui_v2.plugin_bridge import PluginCallBridge

        registry = PluginRegistry([(builtin_plugin_root(), True)])
        registry.reload()
        entry = registry.get("dsh-multi")
        self.plugin = load_plugin(entry, PluginApi(entry.manifest))
        self.bridge = PluginCallBridge(self.plugin)

        view = QQuickView()
        view.engine().addImportPath(str(SRC / "codex_switch" / "ui_v2" / "qml"))
        view.setResizeMode(QQuickView.SizeRootObjectToView)
        view.resize(1000, 460)
        view.setSource(QUrl.fromLocalFile(str(entry.page_path)))
        view.show()
        self._pump()
        self.assertEqual(
            view.status(), QQuickView.Status.Ready,
            "\n".join(e.toString() for e in view.errors()),
        )
        # view 与 engine 都要保活到测试结束，否则析构顺序会崩。
        self._view = view
        self.page = view.rootObject()
        self.page.setProperty("instance", self.bridge)
        self._pump()

    @staticmethod
    def _pump(times: int = 12) -> None:
        """布局发生在 polish 阶段，一次 processEvents 不足以拿到最终高度。"""
        from PySide6.QtCore import QCoreApplication

        for _ in range(times):
            QCoreApplication.processEvents()

    def _content_height(self) -> float:
        from PySide6.QtQuick import QQuickItem

        self._pump()
        scroll = self.page.findChild(QQuickItem, "pageScroll")
        self.assertIsNotNone(scroll, "页面没有可滚动容器（缺少 pageScroll）")
        return float(scroll.property("contentHeight"))

    def test_content_grows_as_instances_are_added(self) -> None:
        """内容必须随实例数量增长——这正是它需要滚动的原因。"""
        empty = self._content_height()
        for index in range(4):
            self.plugin.create({"name": f"i{index}", "kind": "web", "isolate": True})
        self.page.setProperty("instance", None)
        self.page.setProperty("instance", self.bridge)
        few = self._content_height()

        for index in range(20):
            self.plugin.create({"name": f"j{index}", "kind": "web", "isolate": True})
        self.page.setProperty("instance", None)
        self.page.setProperty("instance", self.bridge)
        many = self._content_height()

        self.assertGreater(few, empty, "加入实例后内容高度没有增长")
        self.assertGreater(many, few, "实例继续增加后内容高度没有继续增长")

    def test_page_is_scrollable_when_content_overflows(self) -> None:
        """内容高于视口时，外层容器必须可滚动，否则下方内容永远看不到。"""
        from PySide6.QtQuick import QQuickItem

        for index in range(24):
            self.plugin.create({"name": f"i{index}", "kind": "web", "isolate": True})
        self.page.setProperty("instance", None)
        self.page.setProperty("instance", self.bridge)
        self._pump()

        scroll = self.page.findChild(QQuickItem, "pageScroll")
        self.assertGreater(
            float(scroll.property("contentHeight")), scroll.height(),
            "内容已超出视口，但容器不可滚动",
        )

    def test_detail_can_be_closed(self) -> None:
        """详情/日志面板必须能关闭。

        缺陷表现：打开后内容被挤到可视区外，卡片右上角的折叠箭头也点不到，
        用户会觉得"关不掉"。这里同时验证 toggle 与显式关闭两条路径。
        """
        from PySide6.QtCore import Q_ARG, QMetaObject

        self.plugin.create({"name": "dev", "kind": "web"})
        self.page.setProperty("instance", None)
        self.page.setProperty("instance", self.bridge)

        QMetaObject.invokeMethod(self.page, "toggleLog", Q_ARG("QVariant", "dev"))
        self._pump()
        self.assertEqual(self.page.property("selectedKey"), "dev", "日志没有打开")

        QMetaObject.invokeMethod(self.page, "toggleLog", Q_ARG("QVariant", "dev"))
        self._pump()
        self.assertEqual(self.page.property("selectedKey"), "", "再点一次没有收起")

        QMetaObject.invokeMethod(self.page, "toggleLog", Q_ARG("QVariant", "dev"))
        self._pump()
        QMetaObject.invokeMethod(self.page, "closeDetail")
        self._pump()
        self.assertEqual(self.page.property("selectedKey"), "", "closeDetail 没有关闭详情")


# ---------------------------------------------------------------------------
# 7. 与 script_runner 的共享实现（DRY 回归）
# ---------------------------------------------------------------------------

class SharedProcessUtilTests(unittest.TestCase):
    """进程/日志工具抽到 process_util 后，两边必须仍是同一份实现。"""

    def test_script_runner_reexports_the_shared_helpers(self) -> None:
        from codex_switch import process_util
        from codex_switch.ui_v2 import script_runner

        self.assertIs(script_runner.decode_output, process_util.decode_output)
        self.assertIs(script_runner.kill_pid, process_util.kill_pid)
        self.assertIs(script_runner.pid_alive, process_util.pid_alive)

    def test_decode_output_handles_chinese_code_pages(self) -> None:
        from codex_switch.process_util import decode_output

        self.assertEqual(decode_output("中文输出".encode("gbk")), "中文输出")
        self.assertEqual(decode_output("中文输出".encode("utf-8")), "中文输出")
        self.assertEqual(decode_output(b""), "")

    def test_read_log_text_tail_and_missing_file(self) -> None:
        from codex_switch.process_util import read_log_text

        root = make_temp_dir(self)
        path = root / "a.log"
        path.write_text("\n".join(f"line{i}" for i in range(50)), encoding="utf-8")

        self.assertIn("line49", read_log_text(path, tail_lines=5))
        self.assertNotIn("line0\n", read_log_text(path, tail_lines=5))
        # 缺日志是普通状态（还没跑过），不该抛异常。
        self.assertEqual(read_log_text(root / "missing.log"), "")

    def test_read_log_text_respects_max_bytes(self) -> None:
        from codex_switch.process_util import read_log_text

        root = make_temp_dir(self)
        path = root / "big.log"
        path.write_text("A" * 1000 + "TAIL", encoding="utf-8")
        text = read_log_text(path, max_bytes=10)
        self.assertTrue(text.endswith("TAIL"))


# ---------------------------------------------------------------------------
# 8. 插件安装（给某个/所有 DSH 环境装插件）
# ---------------------------------------------------------------------------

class PluginTargetTests(unittest.TestCase):
    """安装目标 = (harness home, profile)。这是"装到哪个环境"的唯一模型。"""

    def setUp(self) -> None:
        from codex_switch import dsh_instances as core
        from codex_switch import dsh_plugins as plugins

        self.core = core
        self.plugins = plugins

    def test_shared_target_always_present(self) -> None:
        """没有任何实例时，也必须能给共用的 ~/.dsh 装插件。"""
        targets = self.plugins.enumerate_targets([])
        self.assertEqual(len(targets), 1)
        self.assertTrue(targets[0].shared if hasattr(targets[0], "shared") else not targets[0].home)
        self.assertEqual(targets[0].profile, "web")

    def test_isolated_instances_become_separate_targets(self) -> None:
        instances = [
            self.core.new_instance("a", kind="web", isolate=True),
            self.core.new_instance("b", kind="web", isolate=True),
        ]
        targets = self.plugins.enumerate_targets(instances)
        # 一个共用 + 两个独立。
        self.assertEqual(len(targets), 3)
        isolated = [item for item in targets if item.home]
        self.assertEqual(len(isolated), 2)

    def test_shared_home_instances_collapse_into_one_target(self) -> None:
        """多个实例共用同一个 home 时是同一个环境，不该重复安装。"""
        instances = [
            self.core.new_instance("a", kind="web"),
            self.core.new_instance("b", kind="web"),
        ]
        targets = self.plugins.enumerate_targets(instances)
        self.assertEqual(len(targets), 1, "共用 home 的实例被重复列成了多个目标")

    def test_duplicate_isolated_homes_collapse(self) -> None:
        one = self.core.new_instance("a", kind="web", isolate=True)
        two = self.core.new_instance("a", kind="web", isolate=True)
        two.home = one.home
        targets = self.plugins.enumerate_targets([one, two])
        self.assertEqual(len(targets), 2)  # 共用 + 一个独立

    def test_find_target_reports_unknown_id(self) -> None:
        with self.assertRaises(self.plugins.PluginError):
            self.plugins.find_target("nope::web", [])

    def test_profile_dir_follows_the_home(self) -> None:
        target = self.plugins.PluginTarget(home="C:/tmp/h", profile="web")
        self.assertEqual(
            self.plugins.profile_dir(target),
            Path("C:/tmp/h") / "profiles" / "web",
        )


class PluginSpecValidationTests(unittest.TestCase):
    """包标识会传给 pnpm，必须挡掉明显有害/无意义的输入。"""

    def setUp(self) -> None:
        from codex_switch import dsh_plugins as plugins

        self.plugins = plugins

    def test_accepts_npm_name_and_local_path(self) -> None:
        self.assertEqual(self.plugins.validate_spec("  @scope/pkg  "), "@scope/pkg")
        self.assertEqual(self.plugins.validate_spec("D:\\我的插件"), "D:\\我的插件")

    def test_rejects_empty_and_flag_like_input(self) -> None:
        for bad in ("", "   ", "-D", "--save-dev"):
            with self.subTest(bad=bad):
                with self.assertRaises(self.plugins.PluginError):
                    self.plugins.validate_spec(bad)

    def test_rejects_newlines_and_overlong_input(self) -> None:
        for bad in ("a\nb", "a\rb", "a\x00b", "x" * 501):
            with self.subTest(bad=bad[:10]):
                with self.assertRaises(self.plugins.PluginError):
                    self.plugins.validate_spec(bad)


class PluginCommandTests(unittest.TestCase):
    """命令构造必须把 profile 带对，且路径里的空格不被拆开。"""

    def setUp(self) -> None:
        from codex_switch import dsh_plugins as plugins

        self.plugins = plugins

    def test_uses_dsh_plugin_with_the_target_profile(self) -> None:
        target = self.plugins.PluginTarget(home="", profile="tui")
        argv = self.plugins.build_plugin_command(target, ["add", "pkg"])
        self.assertIn("plugin", argv)
        self.assertEqual(argv[argv.index("--profile") + 1], "tui")
        self.assertEqual(argv[-2:], ["add", "pkg"])

    def test_invalid_profile_name_is_rejected(self) -> None:
        target = self.plugins.PluginTarget(home="", profile="../evil")
        with self.assertRaises(self.plugins.PluginError):
            self.plugins.build_plugin_command(target, ["add", "pkg"])


class ProfileReadTests(unittest.TestCase):
    """读某环境已装插件：不能为了刷新界面就去跑外部命令。"""

    def setUp(self) -> None:
        from codex_switch import dsh_plugins as plugins

        self.plugins = plugins
        self.root = make_temp_dir(self)

    def _target(self, profile: str = "web"):
        return self.plugins.PluginTarget(home=str(self.root / "home"), profile=profile)

    def _write_profile(self, payload, *, profile: str = "web", bom: bool = False) -> None:
        path = self.plugins.profile_dir(self._target(profile)) / "package.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        path.write_text(text, encoding="utf-8-sig" if bom else "utf-8")

    def test_missing_profile_reads_as_not_initialized(self) -> None:
        info = self.plugins.list_installed(self._target())
        self.assertFalse(info["exists"])
        self.assertEqual(info["count"], 0)
        self.assertTrue(info["ok"])

    def test_lists_dependencies_and_marks_active_layers(self) -> None:
        self._write_profile({
            "dependencies": {"my-plugin": "^1.0.0", "plain-lib": "^2.0.0"},
            "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "my-plugin"]}},
        })
        info = self.plugins.list_installed(self._target())
        rows = {row["name"]: row for row in info["plugins"]}
        self.assertTrue(rows["my-plugin"]["active"], "被 bundles 引用的依赖应标为已启用")
        self.assertFalse(rows["plain-lib"]["active"], "普通依赖不该标为已启用")
        self.assertIn("@deepseek-ai/dsh-base", info["builtinLayers"])

    def test_tolerates_bom_in_the_manifest(self) -> None:
        """Windows 上写出的 JSON 常带 BOM，必须能读——否则列表永远为空。"""
        self._write_profile({"dependencies": {"p": "1"}, "dsh": {"profile": {"bundles": []}}}, bom=True)
        info = self.plugins.list_installed(self._target())
        self.assertEqual(info["count"], 1)

    def test_corrupt_manifest_is_reported_not_raised(self) -> None:
        path = self.plugins.profile_dir(self._target()) / "package.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ broken", encoding="utf-8")
        info = self.plugins.list_installed(self._target())
        self.assertFalse(info["ok"])
        self.assertTrue(info["message"])


class InstallJobTests(unittest.TestCase):
    """任务管理：异步执行、串行、状态与日志。这些用注入的 runner 驱动，不跑真 pnpm。"""

    def setUp(self) -> None:
        from codex_switch import dsh_plugins as plugins

        self.plugins = plugins
        self.root = make_temp_dir(self)

    def _target(self, name: str = "env-a"):
        return self.plugins.PluginTarget(
            home=str(self.root / name), profile="web", label=name,
        )

    def _manager(self, runner):
        return self.plugins.InstallJobManager(log_dir=self.root / "logs", runner=runner)

    @staticmethod
    def _wait(manager, job_id: str, timeout: float = 10.0):
        import time as _time

        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            if not manager.job(job_id).running:
                return manager.job(job_id)
            _time.sleep(0.02)
        raise AssertionError(f"任务 {job_id} 没有在 {timeout}s 内结束")

    def test_successful_install_over_all_targets(self) -> None:
        calls: list[list[str]] = []

        def runner(argv, target, job):
            calls.append(list(argv))
            return 0, "dsh: done\n"

        manager = self._manager(runner)
        targets = [self._target("a"), self._target("b")]
        job = manager.submit(self.plugins.ACTION_INSTALL, "some-pkg", targets)
        done = self._wait(manager, job.id)

        self.assertEqual(done.status, self.plugins.JOB_SUCCESS)
        self.assertEqual(done.done, 2)
        # 两个环境各跑一次，且都指向各自的 profile。
        self.assertEqual(len(calls), 2)
        for argv in calls:
            self.assertIn("add", argv)
            self.assertIn("some-pkg", argv)

    def test_each_target_runs_in_its_own_home(self) -> None:
        """装到哪个环境由 DSH_HOME 决定——这是隔离的关键。"""
        seen: list[tuple[str, str]] = []

        def runner(argv, target, job):
            seen.append((str(target.resolved_home), str(job.id)))
            return 0, "ok\n"

        manager = self._manager(runner)
        first, second = self._target("a"), self._target("b")
        job = manager.submit(self.plugins.ACTION_INSTALL, "p", [first, second])
        self._wait(manager, job.id)

        homes = {home for home, _ in seen}
        self.assertEqual(homes, {str(first.resolved_home), str(second.resolved_home)})

    def test_partial_failure_is_reported_with_the_failing_target(self) -> None:
        """一个环境失败不该掩盖另一个成功，且要能指出是哪个环境。"""
        def runner(argv, target, job):
            if target.label == "b":
                return 1, "Error: ERR_PNPM_NO_MATCHING_VERSION\n"
            return 0, "ok\n"

        manager = self._manager(runner)
        job = manager.submit(
            self.plugins.ACTION_INSTALL, "p", [self._target("a"), self._target("b")],
        )
        done = self._wait(manager, job.id)

        self.assertEqual(done.status, self.plugins.JOB_FAILED)
        self.assertEqual(done.done, 2, "失败后仍应继续处理其余目标")
        self.assertIn("b", done.message)
        self.assertIn("ERR_PNPM_NO_MATCHING_VERSION", done.message)

    def test_concurrent_submission_is_refused(self) -> None:
        """pnpm 会写同一个目录，并发提交必须挡住。"""
        import threading

        release = threading.Event()

        def runner(argv, target, job):
            release.wait(5)
            return 0, "ok\n"

        manager = self._manager(runner)
        try:
            manager.submit(self.plugins.ACTION_INSTALL, "p", [self._target()])
            with self.assertRaises(self.plugins.PluginError) as ctx:
                manager.submit(self.plugins.ACTION_INSTALL, "q", [self._target()])
            self.assertIn("进行中", str(ctx.exception))
        finally:
            release.set()

    def test_job_log_records_the_command_and_output(self) -> None:
        """日志要能看到"实际执行了什么"，否则排查无从下手。"""
        def runner(argv, target, job):
            return 0, "pnpm output line\n"

        manager = self._manager(runner)
        job = manager.submit(self.plugins.ACTION_INSTALL, "my-pkg", [self._target()])
        self._wait(manager, job.id)
        text = manager.job_log(job.id)
        self.assertIn("plugin", text)
        self.assertIn("my-pkg", text)
        self.assertIn("pnpm output line", text)

    def test_uninstall_uses_remove(self) -> None:
        calls: list[list[str]] = []

        def runner(argv, target, job):
            calls.append(list(argv))
            return 0, "ok\n"

        manager = self._manager(runner)
        job = manager.submit(self.plugins.ACTION_UNINSTALL, "old-pkg", [self._target()])
        self._wait(manager, job.id)
        self.assertIn("remove", calls[0])
        self.assertNotIn("add", calls[0])

    def test_targets_are_snapshotted_at_submit_time(self) -> None:
        """后台线程晚于提交才跑，期间实例可能被删；不能那时再解析目标。"""
        captured: list[str] = []

        def runner(argv, target, job):
            captured.append(target.home)
            return 0, "ok\n"

        manager = self._manager(runner)
        # 直接构造一个"注册表里根本不存在"的目标：执行时若重新按 id 解析就会失败。
        ghost = self.plugins.PluginTarget(home=str(self.root / "ghost"), profile="web", label="ghost")
        job = manager.submit(self.plugins.ACTION_INSTALL, "p", [ghost])
        done = self._wait(manager, job.id)
        self.assertEqual(done.status, self.plugins.JOB_SUCCESS, done.message)
        self.assertEqual(captured, [ghost.home])

    def test_runner_exception_fails_the_job_instead_of_hanging(self) -> None:
        """任务抛异常必须变成"失败"，否则界面会永远转圈。"""
        def runner(argv, target, job):
            raise RuntimeError("boom")

        manager = self._manager(runner)
        job = manager.submit(self.plugins.ACTION_INSTALL, "p", [self._target()])
        done = self._wait(manager, job.id)
        self.assertEqual(done.status, self.plugins.JOB_FAILED)
        self.assertIn("boom", done.message)

    def test_empty_targets_is_refused(self) -> None:
        manager = self._manager(lambda *a: (0, ""))
        with self.assertRaises(self.plugins.PluginError):
            manager.submit(self.plugins.ACTION_INSTALL, "p", [])

    def test_unknown_action_is_refused(self) -> None:
        manager = self._manager(lambda *a: (0, ""))
        with self.assertRaises(self.plugins.PluginError):
            manager.submit("destroy", "p", [self._target()])


class PluginInstallEntryTests(unittest.TestCase):
    """插件层暴露给界面的方法：形状与失败路径都要稳。"""

    def setUp(self) -> None:
        self.addCleanup(self._restore_env)
        self._previous = os.environ.get("DSH_INSTANCES_DIR")
        self.root = make_temp_dir(self)
        os.environ["DSH_INSTANCES_DIR"] = str(self.root)
        self.plugin = self._load_plugin()

    def _restore_env(self) -> None:
        if self._previous is None:
            os.environ.pop("DSH_INSTANCES_DIR", None)
        else:
            os.environ["DSH_INSTANCES_DIR"] = self._previous

    def _load_plugin(self):
        from codex_switch.plugins import PluginApi
        from codex_switch.plugins.loader import load_plugin
        from codex_switch.plugins.registry import PluginRegistry, builtin_plugin_root

        registry = PluginRegistry([(builtin_plugin_root(), True)])
        registry.reload()
        return load_plugin(registry.get("dsh-multi"), PluginApi(registry.get("dsh-multi").manifest))

    def test_targets_include_shared_and_each_isolated_instance(self) -> None:
        self.plugin.create({"name": "iso", "kind": "web", "isolate": True})
        rows = self.plugin.plugin_targets()
        self.assertEqual(len(rows), 2)
        shared = [row for row in rows if row["shared"]]
        self.assertEqual(len(shared), 1)
        # 页面直接渲染这些字段。
        for key in ("id", "label", "home", "profile", "installedCount", "profileExists"):
            self.assertIn(key, rows[0])

    def test_installed_plugins_lists_without_running_dsh(self) -> None:
        result = self.plugin.installed_plugins("shared::web")
        self.assertTrue(result["ok"], result["message"])
        self.assertIn("plugins", result)

    def test_installed_plugins_unknown_target_fails_softly(self) -> None:
        result = self.plugin.installed_plugins("ghost::web")
        self.assertFalse(result["ok"])
        self.assertTrue(result["message"])

    def test_install_requires_a_spec_and_a_target(self) -> None:
        self.assertFalse(self.plugin.install_plugin({"spec": "", "targets": ["shared::web"]})["ok"])
        self.assertFalse(self.plugin.install_plugin({"spec": "pkg", "targets": []})["ok"])

    def test_install_rejects_unknown_target(self) -> None:
        result = self.plugin.install_plugin({"spec": "pkg", "targets": ["ghost::web"]})
        self.assertFalse(result["ok"])
        self.assertIn("目标", result["message"])

    def test_install_submits_a_job_for_the_selected_targets(self) -> None:
        submitted: list[tuple] = []

        def fake_submit(action, spec, targets):
            submitted.append((action, spec, [item.id for item in targets]))
            from codex_switch.dsh_plugins import InstallJob

            return InstallJob(id="job1", action=action, spec=spec, targets=list(targets))

        self.plugin.installer.submit = fake_submit  # type: ignore[assignment]
        result = self.plugin.install_plugin({"spec": "my-pkg", "targets": ["shared::web"]})
        self.assertTrue(result["ok"], result["message"])
        self.assertEqual(result["jobId"], "job1")
        self.assertEqual(submitted[0][0], "install")
        self.assertEqual(submitted[0][1], "my-pkg")

    def test_uninstall_uses_the_uninstall_action(self) -> None:
        captured: list[str] = []

        def fake_submit(action, spec, targets):
            captured.append(action)
            from codex_switch.dsh_plugins import InstallJob

            return InstallJob(id="j", action=action, spec=spec, targets=list(targets))

        self.plugin.installer.submit = fake_submit  # type: ignore[assignment]
        self.plugin.uninstall_plugin({"spec": "my-pkg", "targets": ["shared::web"]})
        self.assertEqual(captured, ["uninstall"])

    def test_job_log_reports_unknown_job_softly(self) -> None:
        result = self.plugin.plugin_job_log("nope")
        self.assertFalse(result["ok"])
        self.assertTrue(result["message"])

    def test_shutdown_stops_accepting_jobs_without_killing_instances(self) -> None:
        self.plugin.create({"name": "dev", "kind": "web"})
        self.plugin.shutdown()
        self.assertEqual(len(self.plugin.instances()), 1)


if __name__ == "__main__":
    unittest.main()
