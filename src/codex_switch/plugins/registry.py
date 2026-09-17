"""插件发现与注册表。

扫描插件目录、校验清单、维护"已装载插件"列表。核心约束是**故障隔离**：
一个插件目录坏了（清单缺字段、JSON 语法错、id 重复），只能让那一个插件变成
"不可用"并在插件中心显示原因，绝不能让主程序启动失败或让其他插件受牵连。

因此这里不抛异常给调用方，而是把失败收进 :class:`PluginIssue` 列表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any

from .manifest import MANIFEST_FILE_NAME, ManifestError, PluginManifest, load_manifest_file


# 插件状态：宿主能识别出的全部状态，插件中心按这个渲染。
STATUS_READY = "ready"          # 清单与入口都在，可加载
STATUS_DISABLED = "disabled"    # 被用户禁用
STATUS_ERROR = "error"          # 清单或入口有问题，不可加载


@dataclass
class PluginIssue:
    """一条插件问题记录。``path`` 用于让用户能定位到是哪个目录。"""

    plugin_id: str
    path: Path
    message: str

    def to_row(self) -> dict[str, Any]:
        return {"id": self.plugin_id, "path": str(self.path), "message": self.message}


@dataclass
class PluginEntry:
    """注册表里的一个插件：清单 + 位置 + 状态。

    可变对象：加载/启用状态会随用户操作变化。
    """

    manifest: PluginManifest
    directory: Path
    builtin: bool = False
    enabled: bool = True
    status: str = STATUS_READY
    error: str = ""
    instance: Any = None
    # 目录里是否存在清单声明的入口文件。缺失时即便清单合法也不能加载。
    entry_missing: bool = False

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def entry_path(self) -> Path:
        return self.directory / self.manifest.entry

    @property
    def page_path(self) -> Path | None:
        if not self.manifest.page:
            return None
        return self.directory / self.manifest.page

    @property
    def loadable(self) -> bool:
        return self.status == STATUS_READY and self.enabled and not self.entry_missing

    def to_row(self) -> dict[str, Any]:
        row = self.manifest.to_row()
        row.update({
            "path": str(self.directory),
            "builtin": self.builtin,
            "enabled": self.enabled,
            "status": self.status,
            "error": self.error,
            "entryMissing": self.entry_missing,
            "loaded": self.instance is not None,
        })
        return row


@dataclass
class ScanResult:
    entries: list[PluginEntry] = field(default_factory=list)
    issues: list[PluginIssue] = field(default_factory=list)


def default_plugin_root() -> Path:
    """用户级插件目录。

    放在用户目录而不是程序目录：程序升级/重装不会清掉用户装的插件。
    """
    import os

    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "CodexSwitch" / "plugins"
    return Path.home() / ".codex-switch" / "plugins"


def builtin_plugin_root() -> Path:
    """随程序分发的内置插件目录（只读语义，但实现上不强制）。

    需要处理两种运行形态：

    * 源码运行：插件目录就在 ``codex_switch/builtin_plugins``，
      即 ``__file__`` 的上一级包目录下；
    * PyInstaller 冻结运行：程序和数据被解包到 ``sys._MEIPASS``，
      ``__file__`` 指向那个临时目录。spec 里把内置插件按
      ``codex_switch/builtin_plugins`` 的相对结构打了进去，所以这里
      必须先看 ``_MEIPASS``，否则冻结后**一个插件都找不到**——
      表现就是插件中心永远显示「已安装插件 (0)」。

    与 :mod:`codex_switch.resources` 的资产查找保持同一套约定。
    """
    candidates: list[Path] = []
    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root:
        candidates.append(Path(pyinstaller_root) / "codex_switch" / "builtin_plugins")
    candidates.append(Path(__file__).resolve().parent.parent / "builtin_plugins")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    # 都不存在时返回源码形态的路径，便于报错信息里给出可读位置。
    return candidates[-1]


def scan_plugins(roots: list[tuple[Path, bool]] | None = None) -> ScanResult:
    """扫描若干插件根目录。

    Args:
        roots: ``(目录, 是否内置)`` 列表；为 ``None`` 时使用内置 + 用户两级。
            先扫到的同名 id 优先（内置优先，避免用户目录里的同名插件
            静默顶掉程序自带的能力）。

    Returns:
        :class:`ScanResult`。任何单个插件的失败都进 ``issues``，不抛出。
    """
    if roots is None:
        roots = [(builtin_plugin_root(), True), (default_plugin_root(), False)]

    result = ScanResult()
    seen_ids: dict[str, Path] = {}

    for root, builtin in roots:
        if not root.is_dir():
            continue
        try:
            candidates = sorted(item for item in root.iterdir() if item.is_dir())
        except OSError as error:
            result.issues.append(PluginIssue(
                plugin_id=root.name, path=root, message=f"无法读取插件目录：{error}",
            ))
            continue

        for directory in candidates:
            # 约定：以 "_" 或 "." 开头的目录是草稿/禁用目录，跳过而不报错。
            if directory.name.startswith(("_", ".")):
                continue
            manifest_path = directory / MANIFEST_FILE_NAME
            if not manifest_path.is_file():
                # 没有清单的目录不算插件目录（可能是 README、脚本残留），
                # 静默跳过，避免把用户的杂物报成"坏插件"。
                continue
            try:
                manifest = load_manifest_file(manifest_path)
            except ManifestError as error:
                result.issues.append(PluginIssue(
                    plugin_id=directory.name, path=directory, message=str(error),
                ))
                continue

            previous = seen_ids.get(manifest.id)
            if previous is not None:
                result.issues.append(PluginIssue(
                    plugin_id=manifest.id,
                    path=directory,
                    message=f"插件 id 与 {previous} 重复，已忽略本目录。",
                ))
                continue
            seen_ids[manifest.id] = directory

            entry_missing = not (directory / manifest.entry).is_file()
            entry = PluginEntry(
                manifest=manifest,
                directory=directory,
                builtin=builtin,
                entry_missing=entry_missing,
            )
            if entry_missing:
                entry.status = STATUS_ERROR
                entry.error = f"缺少入口文件：{manifest.entry}"
            result.entries.append(entry)

    return result


class PluginRegistry:
    """已发现插件的内存注册表。

    持有 :class:`PluginEntry` 列表并提供启停、查询。加载/卸载本身由
    :mod:`codex_switch.plugins.loader` 负责，注册表只管状态。
    """

    def __init__(self, roots: list[tuple[Path, bool]] | None = None) -> None:
        self._roots = roots
        self._entries: dict[str, PluginEntry] = {}
        self._issues: list[PluginIssue] = []
        self._disabled: set[str] = set()

    # -- 扫描 -----------------------------------------------------------
    def reload(self) -> None:
        """重新扫描磁盘。用户禁用状态跨扫描保留。"""
        # 保留已加载的实例状态，避免重扫把正在用的插件实例丢掉。
        existing = {key: entry.instance for key, entry in self._entries.items()}
        result = scan_plugins(self._roots)
        entries: dict[str, PluginEntry] = {}
        for entry in result.entries:
            if entry.id in self._disabled:
                entry.enabled = False
                entry.status = STATUS_DISABLED
            entry.instance = existing.get(entry.id)
            entries[entry.id] = entry
        self._entries = entries
        self._issues = result.issues

    # -- 查询 -----------------------------------------------------------
    @property
    def entries(self) -> list[PluginEntry]:
        return sorted(self._entries.values(), key=lambda item: (not item.builtin, item.id))

    @property
    def issues(self) -> list[PluginIssue]:
        return list(self._issues)

    def get(self, plugin_id: str) -> PluginEntry | None:
        return self._entries.get(str(plugin_id or ""))

    def rows(self) -> list[dict[str, Any]]:
        return [entry.to_row() for entry in self.entries]

    def issue_rows(self) -> list[dict[str, Any]]:
        return [issue.to_row() for issue in self._issues]

    # -- 状态变更 -------------------------------------------------------
    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginEntry | None:
        """启用/禁用插件。禁用状态被记住，重扫后依然生效。"""
        entry = self._entries.get(str(plugin_id or ""))
        if entry is None:
            return None
        entry.enabled = bool(enabled)
        if not enabled:
            self._disabled.add(entry.id)
            entry.status = STATUS_DISABLED
        else:
            self._disabled.discard(entry.id)
            if entry.entry_missing:
                entry.status = STATUS_ERROR
                entry.error = f"缺少入口文件：{entry.manifest.entry}"
            else:
                entry.status = STATUS_READY
                entry.error = ""
        return entry

    def mark_error(self, plugin_id: str, message: str) -> None:
        entry = self._entries.get(str(plugin_id or ""))
        if entry is not None:
            entry.status = STATUS_ERROR
            entry.error = str(message)

    def mark_ready(self, plugin_id: str) -> None:
        entry = self._entries.get(str(plugin_id or ""))
        if entry is not None:
            entry.status = STATUS_READY
            entry.error = ""


__all__ = [
    "PluginEntry",
    "PluginIssue",
    "PluginRegistry",
    "ScanResult",
    "STATUS_DISABLED",
    "STATUS_ERROR",
    "STATUS_READY",
    "builtin_plugin_root",
    "default_plugin_root",
    "scan_plugins",
]
