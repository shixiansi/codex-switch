"""DSH 多开插件。

同时运行多个 DSH 实例，每个实例一个独立端口。实例可以用共用的 ``~/.dsh``
（沿用登录态与设置），也可以指定自己独立的 harness home（通过 ``DSH_HOME``
注入）做完全隔离。

设计要点
--------
1. **不通过宿主的 ``api.run_command`` 启动**。那个 API 是
   ``subprocess.run(..., timeout=120)``，而 DSH 实例是永不退出的常驻进程：
   用它启动会阻塞满 120 秒再抛超时，还会卡住界面。因此这里用
   ``subprocess.Popen`` 自己启动，并把输出重定向到日志文件。
2. **复用核心逻辑**。实例注册表、启动计划、URL 解析都在
   :mod:`codex_switch.dsh_instances` 里，命令行与界面共用同一套实现。
3. **不在插件里 import Qt**。插件核心逻辑必须能在没有 Qt 的环境里导入并
   单测，所以"打开浏览器"这件事交给页面用 ``Qt.openUrlExternally`` 完成，
   插件只负责把 URL 解析出来。
4. **权限即实情**。本插件声明 ``exec``（它确实要启动外部进程）与
   ``fs:read`` / ``fs:write``（写实例注册表与日志），根目录限定在 ``~/.dsh``。
   敏感权限会在插件中心标出，方便用户判断是否信任。
"""

from __future__ import annotations

from codex_switch import dsh_instances as core
from codex_switch import dsh_plugins as plugins


class DshMultiPlugin:
    """插件实例：持有宿主 API，暴露给页面调用的动作。"""

    def __init__(self, api) -> None:
        self.api = api
        self.registry = core.InstanceRegistry()
        self.manager = core.InstanceManager(self.registry)
        # 插件安装：给某个 DSH 环境（harness home + profile）装/卸插件。
        self.installer = plugins.InstallJobManager()

    # -- 只读状态 --------------------------------------------------------
    def status(self) -> dict:
        """插件整体状态，供页面顶部展示。"""
        try:
            instances = self.registry.load()
        except core.DshError as error:
            return {"ok": False, "error": str(error), "instances": [], "count": 0}

        states = self.manager.states(instances)
        running = sum(1 for state in states.values() if state.running)
        return {
            "ok": True,
            "error": "",
            "storeDir": str(self.registry.root),
            "dshHome": str(core.resolve_home()),
            "count": len(instances),
            "running": running,
            "kinds": [
                {"value": item, "label": core.KIND_LABELS.get(item, item)}
                for item in core.KINDS
            ],
        }

    def instances(self) -> list[dict]:
        """列出全部实例，并把运行时状态合并进展示行。"""
        try:
            instances = self.registry.load()
        except core.DshError as error:
            self.api.log(f"读取实例注册表失败：{error}")
            return []

        rows: list[dict] = []
        for instance in instances:
            state = self.manager.state(instance)
            row = instance.to_row()
            row.update(state.to_row())
            # 页面用固定字段渲染，这里把文案补齐，避免 QML 里堆逻辑。
            row["title"] = instance.name
            row["subtitle"] = _subtitle(instance, state)
            rows.append(row)
        return rows

    def detail(self, key: str) -> dict:
        """单个实例的详情（含启动计划预览，便于排查"到底跑了什么命令"）。"""
        try:
            instance = self.registry.find(key)
        except core.DshError as error:
            return {"ok": False, "message": str(error)}
        state = self.manager.state(instance)
        row = instance.to_row()
        row.update(state.to_row())

        plan_argv: list[str] = []
        plan_error = ""
        try:
            plan_argv = core.build_plan(instance).argv
        except core.DshError as error:
            plan_error = str(error)

        row.update({
            "ok": True,
            "message": "",
            "command": " ".join(plan_argv),
            "planError": plan_error,
            "logPath": str(core.resolve_log_path(instance.name)),
        })
        return row

    def log(self, key: str) -> dict:
        """读取实例日志尾部。"""
        try:
            instance = self.registry.find(key)
        except core.DshError as error:
            return {"ok": False, "message": str(error), "text": ""}
        return {"ok": True, "message": "", "text": core.read_log(instance)}

    # -- 动作 ------------------------------------------------------------
    def create(self, payload=None) -> dict:
        """新建一个实例。

        参数用 ``QVariantMap`` 而不是多个位置参数：QML 传进来的是 JS 对象，
        一旦槽签名与实参不匹配，Qt 会**静默不派发**（按钮点了没反应且没有
        任何报错）。一个 map 参数只有一种可能，不会踩这个坑。
        """
        data = payload if isinstance(payload, dict) else {}
        name = str(data.get("name") or "").strip()
        kind = str(data.get("kind") or core.KIND_WEB).strip()
        profile = str(data.get("profile") or "").strip()
        isolate = bool(data.get("isolate"))
        extra_args = str(data.get("extraArgs") or "").strip()

        try:
            port = int(str(data.get("port") or "0").strip() or "0")
        except ValueError:
            return {"ok": False, "message": "端口必须是数字（0 表示自动分配）。"}

        if not name:
            return {"ok": False, "message": "请填写实例名。"}

        try:
            instances = self.registry.load()
            if any(item.name == name for item in instances):
                return {"ok": False, "message": f"实例名 {name!r} 已存在，请换一个。"}
            instance = core.new_instance(
                name,
                kind=kind,
                profile=profile,
                port=port,
                isolate=isolate,
                extra_args=extra_args,
            )
            # 先验证启动计划合法，再落盘：否则会存下一个永远起不来的实例。
            core.build_plan(instance)
            self.registry.upsert(instance)
        except core.DshError as error:
            return {"ok": False, "message": str(error)}

        return {"ok": True, "message": f"已创建实例：{name}", "id": instance.id}

    def remove(self, key: str) -> dict:
        """删除一个实例（运行中则先停止）。"""
        try:
            instance = self.registry.find(key)
            if self.manager.state(instance).running:
                self.manager.stop(instance)
            self.registry.remove(instance.id)
        except core.DshError as error:
            return {"ok": False, "message": str(error)}
        return {"ok": True, "message": f"已删除实例：{instance.name}"}

    def start(self, key: str) -> dict:
        """启动一个实例（同步等待就绪，因此返回时状态是准的）。"""
        try:
            instance = self.registry.find(key)
            state = self.manager.start(instance)
        except core.DshError as error:
            return {"ok": False, "message": str(error)}

        if state.url:
            return {
                "ok": True,
                "message": f"{instance.name} 已就绪，访问地址已解析。",
                "url": state.url,
            }
        return {"ok": True, "message": f"{instance.name} 已启动。", "url": ""}

    def stop(self, key: str) -> dict:
        """停止一个实例。"""
        try:
            instance = self.registry.find(key)
            stopped = self.manager.stop(instance)
        except core.DshError as error:
            return {"ok": False, "message": str(error)}
        if not stopped:
            return {"ok": True, "message": f"{instance.name} 本来就没有在运行。"}
        return {"ok": True, "message": f"已停止实例：{instance.name}"}

    def stop_all(self) -> dict:
        """停止全部由本会话启动的实例。"""
        count = self.manager.stop_all()
        if not count:
            return {"ok": True, "message": "没有正在运行的实例。"}
        return {"ok": True, "message": f"已停止 {count} 个实例。"}

    def url(self, key: str) -> dict:
        """取实例的访问地址。

        只返回 URL，**不在这里打开浏览器**：打开动作由页面用
        ``Qt.openUrlExternally`` 完成，插件因此不必依赖 Qt。
        """
        try:
            instance = self.registry.find(key)
        except core.DshError as error:
            return {"ok": False, "message": str(error), "url": ""}
        state = self.manager.state(instance)
        if not state.url:
            if state.running:
                return {
                    "ok": False,
                    "url": "",
                    "message": "实例还在启动中，稍后再试；也可以先看日志确认进度。",
                }
            return {"ok": False, "url": "", "message": f"{instance.name} 当前没有运行。"}
        return {"ok": True, "url": state.url, "message": ""}

    def open_folder(self) -> dict:
        """返回多开数据目录，由页面交给系统文件管理器打开。"""
        try:
            self.registry.ensure()
        except core.DshError as error:
            return {"ok": False, "message": str(error), "path": ""}
        return {"ok": True, "path": str(self.registry.root), "message": ""}

    def shutdown(self) -> None:
        """插件被禁用/程序退出时调用。

        刻意**不**停止正在运行的实例：多开的意义就是让它们独立于
        CodexSwitch 存活，关掉管理器不该把用户正在用的 DSH 一起带走。
        """
        # 安装任务只停止"接新任务"：正在跑的 pnpm 让它写完更安全。
        self.installer.shutdown()
        self.api.log("DSH 多开插件已卸载，运行中的实例保持运行。")

    # -- 插件安装（给某个 DSH 环境装/卸插件） ------------------------------
    def plugin_targets(self) -> list[dict]:
        """列出所有可安装插件的 DSH 环境。

        包含"共用 ~/.dsh"以及每个独立 home 的实例。多个实例共用同一个
        home 时只出现一次——它们本来就是同一个环境。
        """
        try:
            instances = self.registry.load()
        except core.DshError as error:
            self.api.log(f"读取实例注册表失败：{error}")
            instances = []
        rows: list[dict] = []
        for target in plugins.enumerate_targets(instances):
            row = target.to_row()
            # 顺带把该环境已装数量带上，列表里就能看出"装过没有"。
            info = plugins.list_installed(target)
            row["installedCount"] = info["count"]
            row["profileExists"] = info["exists"]
            row["profilePath"] = info["path"]
            rows.append(row)
        return rows

    def installed_plugins(self, target_id: str) -> dict:
        """列出某个环境已安装的插件。"""
        try:
            target = plugins.find_target(target_id, self._instances())
        except plugins.PluginError as error:
            return {
                "ok": False, "message": str(error), "plugins": [],
                "builtinLayers": [], "count": 0, "exists": False, "path": "",
            }
        return plugins.list_installed(target)

    def install_plugin(self, payload=None) -> dict:
        """在选定环境里安装一个插件（异步，立即返回任务 id）。

        参数用 ``QVariantMap``：QML 传进来的是 JS 对象，槽签名一旦不匹配，
        Qt 会**静默不派发**（按钮点了没反应且没有任何报错）。
        """
        return self._submit_plugin_job(plugins.ACTION_INSTALL, payload)

    def uninstall_plugin(self, payload=None) -> dict:
        """在选定环境里卸载一个插件（异步）。"""
        return self._submit_plugin_job(plugins.ACTION_UNINSTALL, payload)

    def _submit_plugin_job(self, action: str, payload) -> dict:
        data = payload if isinstance(payload, dict) else {}
        raw_spec = str(data.get("spec") or "").strip()
        target_ids = data.get("targets")
        if isinstance(target_ids, str):
            target_ids = [target_ids]
        target_ids = [str(item) for item in (target_ids or []) if str(item or "").strip()]

        try:
            spec = plugins.validate_spec(raw_spec)
            instances = self._instances()
            if not target_ids:
                raise plugins.PluginError("请至少选择一个安装目标。")
            targets = [plugins.find_target(item, instances) for item in target_ids]
            job = self.installer.submit(action, spec, targets)
        except plugins.PluginError as error:
            return {"ok": False, "message": str(error)}

        verb = plugins.ACTION_LABELS.get(action, action)
        return {
            "ok": True,
            "jobId": job.id,
            "message": f"已开始{verb} {spec}（{len(targets)} 个环境），可在下方查看进度。",
        }

    def plugin_jobs(self) -> list[dict]:
        """列出安装任务（最近的在前）。"""
        return [job.to_row() for job in self.installer.jobs()]

    def plugin_job_log(self, job_id: str) -> dict:
        """读取某个安装任务的输出。"""
        try:
            return {
                "ok": True, "message": "",
                "text": self.installer.job_log(job_id),
                "job": self.installer.job(job_id).to_row(),
            }
        except plugins.PluginError as error:
            return {"ok": False, "message": str(error), "text": "", "job": {}}

    def _instances(self) -> list:
        try:
            return self.registry.load()
        except core.DshError:
            return []

    # -- 宿主动作入口 ----------------------------------------------------
    def run_action(self, action_key: str) -> str:
        """插件声明的动作入口，由插件中心调用。"""
        if action_key == "refresh-status":
            state = self.status()
            if not state.get("ok", False):
                return f"读取实例失败：{state.get('error', '')}"
            return (
                f"共 {state['count']} 个实例，"
                f"{state['running']} 个正在运行。"
            )
        return f"未知动作：{action_key}"


def _subtitle(instance: core.Instance, state: core.InstanceState) -> str:
    """实例列表的副标题：把用户最需要一眼看到的信息拼出来。"""
    parts = [f"{instance.kind} · profile {instance.profile}"]
    if state.running and state.port:
        parts.append(f"端口 {state.port}")
    elif instance.port:
        parts.append(f"端口 {instance.port}")
    else:
        parts.append("自动端口")
    parts.append("独立 home" if instance.home else "共用 ~/.dsh")
    if not state.running and state.message and state.status == core.STATUS_FAILED:
        parts.append(state.message)
    return " · ".join(parts)


def load(api):
    """插件入口：宿主加载插件时调用，返回插件实例。"""
    api.log("DSH 多开插件已加载。")
    return DshMultiPlugin(api)
