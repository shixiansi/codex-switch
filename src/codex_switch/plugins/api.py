"""插件运行时能拿到的受控 API 面。

插件拿到的是这个对象，而**不是** ``workspace`` / ``session`` 内部对象。
这是安全边界的核心：故意做窄，插件就只能做宿主允许的事。

三条硬规则：

1. **能力必须声明**：没在 ``plugin.json`` 里声明的权限，调用时直接抛
   :class:`PermissionDenied`，而不是静默返回空值——静默失败会让插件作者
   以为功能坏了，而用户以为插件"没那么大权限"。
2. **默认只读**：``snapshot()`` 给的是深拷贝，插件改不动宿主状态。
3. **文件访问限定在声明过的根目录内**：``fs:read`` / ``fs:write`` 都必须
   带 ``paths`` 声明，路径解析后必须落在声明的根之内，挡住 ``..`` 逃逸。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import copy
import os

from .manifest import (
    PERMISSION_ACTION_INVOKE,
    PERMISSION_EXEC,
    PERMISSION_FS_READ,
    PERMISSION_FS_WRITE,
    PERMISSION_SNAPSHOT_READ,
    PluginManifest,
)


class PermissionDenied(Exception):
    """插件调用了未声明的能力。"""


class PluginActionError(Exception):
    """插件动作执行失败（非权限问题）。"""


class PluginApi:
    """暴露给单个插件实例的能力网关。

    宿主为每个插件构造一个实例，按该插件清单里声明的权限决定放行哪些调用。
    """

    def __init__(
        self,
        manifest: PluginManifest,
        *,
        snapshot_provider: Callable[[], dict[str, Any]] | None = None,
        action_runner: Callable[[str, dict[str, Any]], Any] | None = None,
        allowed_roots: dict[str, list[Path]] | None = None,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self._manifest = manifest
        self._snapshot_provider = snapshot_provider
        self._action_runner = action_runner
        self._logger = logger
        # 权限 -> 允许访问的根目录列表。清单里声明 fs:read 时同时要给出
        # paths，宿主解析成绝对路径后存这里，供 _resolve_within 校验。
        self._allowed_roots = {
            key: [Path(item).expanduser().resolve(strict=False) for item in value]
            for key, value in (allowed_roots or {}).items()
        }

    # -- 元信息 ---------------------------------------------------------
    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    def log(self, message: object) -> None:
        """插件日志，统一带插件 id 前缀，方便在宿主日志里溯源。"""
        if self._logger is not None:
            self._logger(f"[plugin:{self._manifest.id}] {message}")

    # -- 能力 -----------------------------------------------------------
    def has(self, permission: str) -> bool:
        """插件可自查是否拿到了某项权限（用于优雅降级，而不是靠抛异常判断）。"""
        return permission in self._manifest.permissions

    def _require(self, permission: str) -> None:
        if permission not in self._manifest.permissions:
            raise PermissionDenied(
                f"插件 {self._manifest.id!r} 未声明权限 {permission!r}，"
                "请在 plugin.json 的 permissions 中声明后重试。"
            )

    def snapshot(self, key: str = "") -> Any:
        """读取宿主状态的**只读副本**。

        返回深拷贝：插件即使就地修改也影响不到宿主，避免"插件改坏了配置库
        却查不出是谁改的"。
        """
        self._require(PERMISSION_SNAPSHOT_READ)
        if self._snapshot_provider is None:
            return {} if not key else None
        data = self._snapshot_provider()
        safe = copy.deepcopy(data)
        if not key:
            return safe
        if isinstance(safe, dict):
            return safe.get(key)
        return None

    def invoke(self, action: str, payload: dict[str, Any] | None = None) -> Any:
        """触发宿主登记的某个动作。

        插件不能拿到宿主对象的引用，只能通过动作名调用宿主预先登记好的能力，
        因此插件能做的事完全由宿主白名单决定。
        """
        self._require(PERMISSION_ACTION_INVOKE)
        if self._action_runner is None:
            raise PluginActionError("宿主未提供任何可调用动作。")
        name = str(action or "").strip()
        if not name:
            raise PluginActionError("动作名不能为空。")
        return self._action_runner(name, dict(payload or {}))

    # -- 文件访问 -------------------------------------------------------
    def _resolve_within(self, raw_path: str, *, permission: str) -> Path:
        roots = self._allowed_roots.get(permission) or []
        if not roots:
            raise PermissionDenied(
                f"插件 {self._manifest.id!r} 声明了 {permission!r} 但没有可访问的根目录，"
                "请在 plugin.json 的 paths 中声明。"
            )
        candidate = Path(os.path.expandvars(raw_path)).expanduser().resolve(strict=False)
        for root in roots:
            # 先比路径本身，再比"是否在其下"。用 Path.is_relative_to 语义，
            # 但显式比较避免大小写敏感/盘符差异带来的漏判。
            if candidate == root or root in candidate.parents:
                return candidate
        allowed = "、".join(str(item) for item in roots)
        raise PermissionDenied(
            f"插件 {self._manifest.id!r} 只能访问 {allowed}，拒绝访问：{candidate}"
        )

    def read_text(self, path: str, *, encoding: str = "utf-8") -> str:
        """读取一个已声明根目录内的文本文件。"""
        self._require(PERMISSION_FS_READ)
        target = self._resolve_within(path, permission=PERMISSION_FS_READ)
        try:
            return target.read_text(encoding=encoding)
        except OSError as error:
            raise PluginActionError(f"读取失败 {target}：{error}") from error

    def write_text(self, path: str, content: str, *, encoding: str = "utf-8") -> None:
        """写入一个已声明根目录内的文本文件（原子替换，避免半截文件）。"""
        self._require(PERMISSION_FS_WRITE)
        target = self._resolve_within(path, permission=PERMISSION_FS_WRITE)
        temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(temp, "w", encoding=encoding, newline="\n") as handle:
                handle.write(content)
            os.replace(temp, target)
        except OSError as error:
            temp.unlink(missing_ok=True)
            raise PluginActionError(f"写入失败 {target}：{error}") from error

    def list_dir(self, path: str) -> list[str]:
        """列出已声明根目录内某个目录的条目名。"""
        self._require(PERMISSION_FS_READ)
        target = self._resolve_within(path, permission=PERMISSION_FS_READ)
        try:
            return sorted(item.name for item in target.iterdir())
        except OSError as error:
            raise PluginActionError(f"列目录失败 {target}：{error}") from error

    def run_command(self, argv: list[str], *, cwd: str = "") -> str:
        """执行外部命令并返回标准输出。

        这是最高危的能力，仅在插件显式声明 ``exec`` 时可用。命令以列表传入，
        不经过 shell，避免插件拼字符串造成的注入；工作目录也必须落在已声明的
        ``fs:read`` 根内。
        """
        self._require(PERMISSION_EXEC)
        if not argv or not all(isinstance(item, str) and item for item in argv):
            raise PluginActionError("argv 必须是非空的字符串列表。")
        workdir = None
        if cwd:
            workdir = self._resolve_within(cwd, permission=PERMISSION_FS_READ)
        import subprocess  # 局部导入：未声明 exec 的插件根本走不到这里

        try:
            completed = subprocess.run(
                argv,
                cwd=str(workdir) if workdir else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise PluginActionError(f"命令执行失败：{error}") from error
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip() or f"退出码 {completed.returncode}"
            raise PluginActionError(f"命令返回失败：{detail}")
        return completed.stdout


__all__ = ["PermissionDenied", "PluginActionError", "PluginApi"]
