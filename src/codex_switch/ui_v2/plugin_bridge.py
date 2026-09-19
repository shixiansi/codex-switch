"""把插件实例暴露给 QML 的调用桥。

**为什么需要它**：QML 只对注册过的 ``QObject`` 类型调用方法。把一个普通的
Python 对象作为 ``QVariant`` 传给 QML 后，``instance.someMethod()`` 会直接报
``Property 'someMethod' of object QVariant(...) is not a function``——
插件页面因此完全无法工作。

所以宿主不直接交出插件实例，而是包一层真正的 ``QObject``：QML 通过它调用
插件方法、拿返回值。

**风险防范**：插件代码是第三方代码，任何调用都可能抛异常。这里统一把异常
收敛成 ``{"ok": False, "message": ...}`` 而不是让它冒泡成 QML 报错——
一个插件抛错不该让整个界面崩溃，错误应当显示在该插件自己的页面里。
"""

from __future__ import annotations

from typing import Any

from .qt_compat import Property, QObject, Signal, Slot

# QML 侧可调用的插件方法白名单。
#
# 不做成"任意方法都能调"：插件实例上可能有内部方法（甚至宿主注入的东西），
# 逐个列出才能保证界面上能触发的行为是可审计的。
#
# 插件的同名方法共用同一个名字（例如两个插件都提供 status / remove），
# 调用桥按名字派发，因此这里是一份"允许被界面调用的方法名"总表，而不是
# "某个插件能调什么"——后者由插件自己是否实现该方法决定。
ALLOWED_METHODS = (
    # CodeBuddy 多账号
    "status",
    "accounts",
    "current",
    "switch",
    "save_current",
    "remove",
    "import_directory",
    "import_files",
    # DSH 多开
    "instances",
    "detail",
    "log",
    "create",
    "start",
    "stop",
    "stop_all",
    "url",
    "open_folder",
)


class PluginCallBridge(QObject):
    """插件实例的 QML 调用桥。

    每个方法都返回 ``QVariant``，页面拿到 dict 后用普通 JS 访问即可；
    失败时返回带 ``ok=False`` 和 ``message`` 的 dict，页面统一提示。
    """

    callFailed = Signal(str)

    def __init__(self, instance: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._instance = instance

    @Property(str, constant=True)
    def pluginName(self) -> str:
        return type(self._instance).__name__

    def _call(self, name: str, *args: Any) -> Any:
        """调用插件方法并把异常收敛成结构化结果。

        返回 ``None`` 表示插件没有这个方法，由调用方决定默认值。
        """
        if name not in ALLOWED_METHODS:
            message = f"插件方法 {name!r} 不在允许调用的白名单里。"
            self.callFailed.emit(message)
            return {"ok": False, "message": message}
        handler = getattr(self._instance, name, None)
        if not callable(handler):
            return None
        try:
            return handler(*args)
        except Exception as error:  # noqa: BLE001 - 插件异常不得冒泡到 QML
            message = f"{type(error).__name__}: {error}"
            self.callFailed.emit(message)
            return {"ok": False, "message": message}

    @Slot(result="QVariant")
    def status(self) -> Any:
        result = self._call("status")
        return result if result is not None else {}

    @Slot(result="QVariantList")
    def accounts(self) -> Any:
        result = self._call("accounts")
        return result if isinstance(result, list) else []

    @Slot(result="QVariant")
    def current(self) -> Any:
        result = self._call("current")
        return result if result is not None else {}

    @Slot(str, result="QVariant")
    def switch(self, key: str) -> Any:
        return self._call("switch", str(key))

    @Slot(str, result="QVariant")
    def save_current(self, label: str) -> Any:
        return self._call("save_current", str(label))

    @Slot(str, result="QVariant")
    def remove(self, key: str) -> Any:
        return self._call("remove", str(key))

    @Slot(str, result="QVariant")
    def import_directory(self, directory: str) -> Any:
        return self._call("import_directory", str(directory))

    @Slot("QVariantList", result="QVariant")
    def import_files(self, paths: Any) -> Any:
        """导入一组凭据文件路径。

        参数类型必须是 ``QVariantList``：QML 传进来的是 JS 数组，
        声明成 ``str`` 会让 Qt 匹配不到签名而**静默不派发**——按钮点了
        没反应且没有任何报错（这个坑在本项目里已经踩过一次）。
        """
        cleaned = [str(item) for item in (paths or []) if str(item or "").strip()]
        return self._call("import_files", cleaned)

    # -- DSH 多开 --------------------------------------------------------
    # 这一组方法名与 CodeBuddy 插件不重叠（status / remove 已在上方定义，
    # 两个插件语义一致，直接复用）。
    @Slot(result="QVariantList")
    def instances(self) -> Any:
        result = self._call("instances")
        return result if isinstance(result, list) else []

    @Slot(str, result="QVariant")
    def detail(self, key: str) -> Any:
        result = self._call("detail", str(key))
        return result if result is not None else {}

    @Slot(str, result="QVariant")
    def log(self, key: str) -> Any:
        result = self._call("log", str(key))
        return result if result is not None else {"ok": False, "message": "", "text": ""}

    @Slot("QVariantMap", result="QVariant")
    def create(self, payload: Any) -> Any:
        """新建 DSH 实例。

        参数声明成 ``QVariantMap``：QML 传进来的是 JS 对象，声明成 ``str``
        或其他类型会让 Qt 匹配不到签名而**静默不派发**。
        """
        return self._call("create", dict(payload or {}))

    @Slot(str, result="QVariant")
    def start(self, key: str) -> Any:
        return self._call("start", str(key))

    @Slot(str, result="QVariant")
    def stop(self, key: str) -> Any:
        return self._call("stop", str(key))

    @Slot(result="QVariant")
    def stop_all(self) -> Any:
        return self._call("stop_all")

    @Slot(str, result="QVariant")
    def url(self, key: str) -> Any:
        return self._call("url", str(key))

    @Slot(result="QVariant")
    def open_folder(self) -> Any:
        result = self._call("open_folder")
        return result if result is not None else {}


__all__ = ["ALLOWED_METHODS", "PluginCallBridge"]
