"""插件加载与卸载。

这里是**故障隔离**真正发生的地方。加载第三方代码永远可能失败（语法错、
缺依赖、作者写了死循环的模块级代码），所以：

* 每次加载都在 try/except 里，异常被转换成 :class:`PluginLoadError`，
  只影响该插件；
* 插件入口必须提供 ``load(api)`` 函数，返回一个对象（可为 ``None``）；
* 宿主**不把内部对象交给插件**，只给 :class:`~codex_switch.plugins.api.PluginApi`；
* 卸载时调用插件自己的 ``unload()``（如果提供了），且卸载失败不阻断退出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import importlib.util
import sys

from .api import PluginApi
from .manifest import PluginManifest
from .registry import PluginEntry, PluginRegistry


class PluginLoadError(Exception):
    """插件加载失败。消息面向插件作者。"""


# 插件模块在 sys.modules 里的前缀，避免和宿主自身模块撞名。
MODULE_PREFIX = "codex_switch_plugin_"


def _import_module_from_path(entry: PluginEntry) -> Any:
    """按文件路径导入插件入口模块。

    用显式的唯一模块名（含插件 id）而不是让 Python 从目录名推断：插件目录名
    可能不是合法标识符（带连字符），直接 import 会失败。
    """
    path = entry.entry_path
    if not path.is_file():
        raise PluginLoadError(f"缺少入口文件：{path}")

    module_name = f"{MODULE_PREFIX}{entry.id.replace('-', '_')}"
    # 重新加载前先移除旧模块，否则插件更新后仍会命中旧字节码。
    sys.modules.pop(module_name, None)

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PluginLoadError(f"无法为入口文件建立导入规格：{path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # 加载失败就把半成品清掉，避免后续 import 命中一个残缺模块。
        sys.modules.pop(module_name, None)
        raise
    return module


def load_plugin(entry: PluginEntry, api: PluginApi) -> Any:
    """加载单个插件并返回其实例。

    Raises:
        PluginLoadError: 入口缺失、导入失败、或未提供 ``load`` 函数。
            原始异常通过 ``__cause__`` 保留，便于在主日志里看到真实堆栈。
    """
    if entry.entry_missing:
        raise PluginLoadError(f"缺少入口文件：{entry.manifest.entry}")

    try:
        module = _import_module_from_path(entry)
    except PluginLoadError:
        raise
    except BaseException as error:  # noqa: BLE001 - 插件代码什么都可能抛
        raise PluginLoadError(
            f"导入插件 {entry.manifest.id!r} 的入口失败：{type(error).__name__}: {error}"
        ) from error

    loader = getattr(module, "load", None)
    if not callable(loader):
        raise PluginLoadError(
            f"插件 {entry.manifest.id!r} 的入口没有提供 load(api) 函数。"
        )

    try:
        return loader(api)
    except BaseException as error:  # noqa: BLE001 - 同上
        raise PluginLoadError(
            f"执行插件 {entry.manifest.id!r} 的 load() 失败："
            f"{type(error).__name__}: {error}"
        ) from error


def unload_plugin(entry: PluginEntry) -> None:
    """尽力卸载插件；任何失败都只记录，不抛出。

    退出流程不能被一个坏插件卡住——那会让程序无法关闭。
    """
    instance = entry.instance
    if instance is None:
        return
    teardown = getattr(instance, "unload", None)
    if callable(teardown):
        try:
            teardown()
        except BaseException:  # noqa: BLE001 - 卸载失败不阻断退出
            pass
    entry.instance = None


def load_all(
    registry: PluginRegistry,
    *,
    api_factory: Callable[[PluginManifest], PluginApi],
    on_error: Callable[[str, str], None] | None = None,
) -> list[str]:
    """加载注册表里所有可加载的插件。

    单个插件失败只标记该插件为错误状态，继续加载其余的。

    Returns:
        成功加载的插件 id 列表。
    """
    loaded: list[str] = []
    for entry in registry.entries:
        if not entry.loadable:
            continue
        try:
            api = api_factory(entry.manifest)
            entry.instance = load_plugin(entry, api)
            registry.mark_ready(entry.id)
            loaded.append(entry.id)
        except PluginLoadError as error:
            registry.mark_error(entry.id, str(error))
            if on_error is not None:
                on_error(entry.id, str(error))
    return loaded


def plugin_page_urls(registry: PluginRegistry) -> dict[str, str]:
    """已加载插件中"带页面"的那些，返回 ``{插件id: QML文件绝对路径}``。

    宿主把它交给 QML 侧的插件宿主控件去动态加载。
    """
    urls: dict[str, str] = {}
    for entry in registry.entries:
        if entry.instance is None or not entry.manifest.has_page:
            continue
        page = entry.page_path
        if page is not None and page.is_file():
            urls[entry.id] = str(page)
    return urls


__all__ = [
    "PluginLoadError",
    "load_all",
    "load_plugin",
    "plugin_page_urls",
    "unload_plugin",
]
