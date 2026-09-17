"""插件体系。

四个部件，各司其职（SRP）：

* :mod:`~codex_switch.plugins.manifest` —— 清单解析与校验（纯函数，无副作用）
* :mod:`~codex_switch.plugins.api` —— 暴露给插件的受控能力面（安全边界）
* :mod:`~codex_switch.plugins.registry` —— 磁盘扫描与插件状态（故障隔离）
* :mod:`~codex_switch.plugins.loader` —— 加载/卸载（异常转换）

插件规范见 ``docs/plugins.md``。
"""

from __future__ import annotations

from .api import PermissionDenied, PluginActionError, PluginApi
from .loader import PluginLoadError, load_all, load_plugin, plugin_page_urls, unload_plugin
from .manifest import (
    API_VERSION,
    KNOWN_PERMISSIONS,
    ManifestError,
    PluginManifest,
    load_manifest_file,
    parse_manifest,
    permission_label,
)
from .registry import (
    PluginEntry,
    PluginIssue,
    PluginRegistry,
    STATUS_DISABLED,
    STATUS_ERROR,
    STATUS_READY,
    builtin_plugin_root,
    default_plugin_root,
    scan_plugins,
)

__all__ = [
    "API_VERSION",
    "KNOWN_PERMISSIONS",
    "ManifestError",
    "PermissionDenied",
    "PluginActionError",
    "PluginApi",
    "PluginEntry",
    "PluginIssue",
    "PluginLoadError",
    "PluginManifest",
    "PluginRegistry",
    "STATUS_DISABLED",
    "STATUS_ERROR",
    "STATUS_READY",
    "builtin_plugin_root",
    "default_plugin_root",
    "load_all",
    "load_manifest_file",
    "load_plugin",
    "parse_manifest",
    "permission_label",
    "plugin_page_urls",
    "scan_plugins",
    "unload_plugin",
]
