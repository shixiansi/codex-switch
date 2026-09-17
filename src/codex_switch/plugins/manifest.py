"""插件清单（``plugin.json``）的解析与校验。

清单是插件与宿主之间唯一的静态契约：宿主在**加载任何插件代码之前**先读它，
据此判断这个插件是否可信、是否兼容、能调用哪些能力。因此这里的校验必须严格
到"宁可拒绝加载，也不放行一个语义不明的插件"。

设计取舍（KISS / YAGNI）：

* 只支持一种插件类型（Python 后端 + QML 页面），所以清单里没有 ``type`` 字段。
  将来真要扩展，再加字段并提升 ``API_VERSION`` 即可，不需要现在就抽象。
* 校验全部是纯函数，不碰文件系统、不 import 插件代码——这样它能被单测直接覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any


# 宿主当前支持的插件契约版本。插件声明不匹配就拒绝加载：
# 让一个按旧契约写的插件在新宿主上跑起来，比直接报错危险得多。
API_VERSION = 1

MANIFEST_FILE_NAME = "plugin.json"

# 插件 id 会成为目录名、注册表键和日志前缀，因此限定成保守的 slug。
PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")

# 语义化版本，允许 1.2 / 1.2.3 两种写法（插件作者不必为内部工具补全三位）。
VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")

REQUIRED_FIELDS = ("id", "name", "version", "apiVersion", "entry")


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------

# 权限是能力白名单：插件在清单里声明什么，运行时才能用什么。
# 未声明的能力调用会被直接拒绝，而不是"默默允许"。
PERMISSION_SNAPSHOT_READ = "snapshot:read"
PERMISSION_ACTION_INVOKE = "action:invoke"
PERMISSION_FS_READ = "fs:read"
PERMISSION_FS_WRITE = "fs:write"
PERMISSION_EXEC = "exec"

KNOWN_PERMISSIONS = frozenset({
    PERMISSION_SNAPSHOT_READ,
    PERMISSION_ACTION_INVOKE,
    PERMISSION_FS_READ,
    PERMISSION_FS_WRITE,
    PERMISSION_EXEC,
})

# 声明这些权限时插件属于"高权限"，插件中心会显著标出，提醒用户它动得了什么。
SENSITIVE_PERMISSIONS = frozenset({
    PERMISSION_FS_WRITE,
    PERMISSION_EXEC,
})

PERMISSION_LABELS = {
    PERMISSION_SNAPSHOT_READ: "读取应用状态",
    PERMISSION_ACTION_INVOKE: "触发应用动作",
    PERMISSION_FS_READ: "读取指定文件",
    PERMISSION_FS_WRITE: "写入指定文件",
    PERMISSION_EXEC: "执行外部命令",
}


def permission_label(permission: str) -> str:
    """中文说明，未知权限原样返回，便于作者定位拼写错误。"""
    return PERMISSION_LABELS.get(permission, permission)


def is_sensitive_permission(permission: str) -> bool:
    return permission in SENSITIVE_PERMISSIONS


class ManifestError(Exception):
    """清单不可用。消息面向插件作者，必须指出具体是哪个字段错了。"""


@dataclass(frozen=True)
class PluginManifest:
    """一个已校验通过的插件清单。"""

    id: str
    name: str
    version: str
    api_version: int
    entry: str
    description: str = ""
    author: str = ""
    page: str = ""
    permissions: frozenset[str] = field(default_factory=frozenset)
    # 声明式动作：插件把可执行动作登记在清单里，宿主据此生成按钮，
    # 不需要插件在加载时反向操作宿主 UI（减少插件能造成的破坏面）。
    actions: tuple[dict[str, str], ...] = ()
    # 文件权限的根目录白名单：``{"fs:read": [...], "fs:write": [...]}``。
    # 声明了 fs:read / fs:write 却没有对应根目录时，那次文件访问会被拒绝——
    # 不允许"没配根目录就等于全盘可访问"。
    path_roots: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def has_page(self) -> bool:
        return bool(self.page)

    @property
    def sensitive_permissions(self) -> frozenset[str]:
        return frozenset(p for p in self.permissions if is_sensitive_permission(p))

    def to_row(self) -> dict[str, Any]:
        """给插件中心列表用的展示行。"""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "apiVersion": self.api_version,
            "description": self.description,
            "author": self.author,
            "permissions": [permission_label(item) for item in sorted(self.permissions)],
            "sensitiveCount": len(self.sensitive_permissions),
            "hasPage": self.has_page,
            "actionCount": len(self.actions),
        }


def _parse_path_roots(
    data: dict[str, Any], permissions: frozenset[str], *, source: str,
) -> dict[str, tuple[str, ...]]:
    """解析 ``paths``：每种文件权限各自允许访问的根目录。

    规则：声明了 ``fs:read`` / ``fs:write`` 权限的插件，**必须**同时给出对应
    的 ``paths`` 根目录。否则那次文件访问在运行时会一律被拒绝——与其让作者
    困惑于"我声明了权限为什么还不能读"，不如在加载时就报错说清楚。
    """
    raw = data.get("paths", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: 字段 'paths' 必须是对象。")

    file_permissions = (PERMISSION_FS_READ, PERMISSION_FS_WRITE)
    roots: dict[str, tuple[str, ...]] = {}
    for key, value in raw.items():
        if key not in file_permissions:
            allowed = "、".join(file_permissions)
            raise ManifestError(f"{source}: 'paths' 里的键 {key!r} 无效，只能是：{allowed}。")
        # 空数组必须拒绝：`all()` 对空列表恒为真，只写 all(...) 会放行
        # `"fs:read": []`，而那等于"声明了权限但没有可访问的根目录"。
        if (not isinstance(value, list) or not value
                or not all(isinstance(item, str) and item.strip() for item in value)):
            raise ManifestError(f"{source}: 'paths.{key}' 必须是非空字符串数组。")
        roots[key] = tuple(item.strip() for item in value)

    for permission in file_permissions:
        if permission in permissions and permission not in roots:
            raise ManifestError(
                f"{source}: 声明了权限 {permission!r} 就必须在 'paths' 里给出可访问的根目录，"
                f"例如 \"paths\": {{\"{permission}\": [\"~/.dsh\"]}}。"
            )
    return roots


def _require_text(data: dict[str, Any], key: str, *, source: str, max_length: int = 200) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{source}: 缺少必填字段 {key!r}（必须是非空字符串）。")
    text = value.strip()
    if len(text) > max_length:
        raise ManifestError(f"{source}: 字段 {key!r} 过长（上限 {max_length} 字符）。")
    return text


def _parse_api_version(data: dict[str, Any], *, source: str) -> int:
    raw = data.get("apiVersion")
    # bool 是 int 的子类，显式排除，否则 True 会被当成 1。
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ManifestError(f"{source}: 字段 'apiVersion' 必须是整数。")
    if raw != API_VERSION:
        raise ManifestError(
            f"{source}: 插件声明 apiVersion={raw}，本程序只支持 {API_VERSION}。"
            " 请更新插件或升级程序。"
        )
    return raw


def _parse_permissions(data: dict[str, Any], *, source: str) -> frozenset[str]:
    raw = data.get("permissions", [])
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise ManifestError(f"{source}: 字段 'permissions' 必须是字符串数组。")
    permissions: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ManifestError(f"{source}: 'permissions' 里存在空项或非字符串项。")
        name = item.strip()
        # 未知权限一律拒绝：静默忽略会让作者以为声明生效了，实际没有。
        if name not in KNOWN_PERMISSIONS:
            known = "、".join(sorted(KNOWN_PERMISSIONS))
            raise ManifestError(f"{source}: 未知权限 {name!r}。可用权限：{known}。")
        permissions.add(name)
    return frozenset(permissions)


def _parse_actions(data: dict[str, Any], *, source: str) -> tuple[dict[str, str], ...]:
    raw = data.get("actions", [])
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ManifestError(f"{source}: 字段 'actions' 必须是对象数组。")

    actions: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        where = f"{source}: actions[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{where} 必须是对象。")
        key = item.get("key")
        label = item.get("label")
        if not isinstance(key, str) or not key.strip():
            raise ManifestError(f"{where} 缺少非空的 'key'。")
        if not isinstance(label, str) or not label.strip():
            raise ManifestError(f"{where} 缺少非空的 'label'。")
        clean_key = key.strip()
        if not PLUGIN_ID_RE.match(clean_key):
            raise ManifestError(
                f"{where} 的 'key' 必须是小写字母开头的 slug（小写字母/数字/连字符，3-64 位）。"
            )
        if clean_key in seen:
            raise ManifestError(f"{where} 的 'key' 与前面重复：{clean_key!r}。")
        seen.add(clean_key)
        actions.append({
            "key": clean_key,
            "label": label.strip(),
            "description": str(item.get("description") or "").strip(),
        })
    return tuple(actions)


def _check_relative_path(value: str, *, field_name: str, source: str) -> str:
    """入口/页面必须是插件目录内的相对路径。

    绝对路径和 ``..`` 会让插件引用到自身目录之外的文件，那是宿主无法审计的
    代码来源，直接拒绝。
    """
    if Path(value).is_absolute() or value.startswith(("/", "\\")):
        raise ManifestError(f"{source}: 字段 {field_name!r} 必须是相对路径，不能是绝对路径。")
    parts = Path(value).parts
    if ".." in parts:
        raise ManifestError(f"{source}: 字段 {field_name!r} 不能包含 '..'。")
    return value


def parse_manifest(payload: Any, *, source: str = MANIFEST_FILE_NAME) -> PluginManifest:
    """校验一份已解析的清单数据。

    Args:
        payload: ``json.loads`` 的结果。
        source: 出错时显示给用户的位置描述（通常是文件路径）。

    Raises:
        ManifestError: 任何字段缺失或语义不合法时，消息里点明具体字段。
    """
    if not isinstance(payload, dict):
        raise ManifestError(f"{source}: 顶层必须是 JSON 对象。")

    plugin_id = _require_text(payload, "id", source=source, max_length=64)
    if not PLUGIN_ID_RE.match(plugin_id):
        raise ManifestError(
            f"{source}: 插件 id {plugin_id!r} 不合法。"
            " 必须是小写字母开头、只含小写字母/数字/连字符，长度 3-64。"
        )

    version = _require_text(payload, "version", source=source, max_length=32)
    if not VERSION_RE.match(version):
        raise ManifestError(f"{source}: 版本号 {version!r} 不合法，应形如 1.0 或 1.0.0。")

    entry = _require_text(payload, "entry", source=source, max_length=200)
    entry = _check_relative_path(entry, field_name="entry", source=source)
    if Path(entry).suffix.lower() != ".py":
        raise ManifestError(f"{source}: 入口文件必须是 .py（当前为 {entry!r}）。")

    page = str(payload.get("page") or "").strip()
    if page:
        page = _check_relative_path(page, field_name="page", source=source)
        if Path(page).suffix.lower() != ".qml":
            raise ManifestError(f"{source}: 页面文件必须是 .qml（当前为 {page!r}）。")

    permissions = _parse_permissions(payload, source=source)
    return PluginManifest(
        id=plugin_id,
        name=_require_text(payload, "name", source=source, max_length=64),
        version=version,
        api_version=_parse_api_version(payload, source=source),
        entry=entry,
        description=str(payload.get("description") or "").strip()[:500],
        author=str(payload.get("author") or "").strip()[:100],
        page=page,
        permissions=permissions,
        actions=_parse_actions(payload, source=source),
        path_roots=_parse_path_roots(payload, permissions, source=source),
    )


def load_manifest_file(path: Path) -> PluginManifest:
    """从磁盘读取并校验 ``plugin.json``。"""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as error:
        raise ManifestError(f"未找到插件清单：{path}") from error
    except OSError as error:
        raise ManifestError(f"无法读取插件清单 {path}：{error}") from error
    except UnicodeDecodeError as error:
        raise ManifestError(f"插件清单 {path} 不是 UTF-8 文本：{error}") from error

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ManifestError(f"插件清单 {path} 不是合法 JSON：{error}") from error
    return parse_manifest(payload, source=str(path))


__all__ = [
    "API_VERSION",
    "KNOWN_PERMISSIONS",
    "MANIFEST_FILE_NAME",
    "ManifestError",
    "PERMISSION_ACTION_INVOKE",
    "PERMISSION_EXEC",
    "PERMISSION_FS_READ",
    "PERMISSION_FS_WRITE",
    "PERMISSION_LABELS",
    "PERMISSION_SNAPSHOT_READ",
    "PluginManifest",
    "SENSITIVE_PERMISSIONS",
    "is_sensitive_permission",
    "load_manifest_file",
    "parse_manifest",
    "permission_label",
]
