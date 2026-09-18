"""待附加图片的校验与描述（纯逻辑，无 Qt 依赖）。

AI CLI 的图片输入只有一条通道：**把图片放进系统剪贴板，再让 CLI 自己粘贴**。
PTY 是纯文本流，不能直接传二进制，因此这里不负责"传输"，只负责在动手之前
把用户选中的文件检查干净——路径存在、是文件、格式受支持、体积不过分。

先校验再动剪贴板有两个好处：

* 用户拿到的是**明确的中文原因**（"不支持这种格式"），而不是附加失败后
  一脸茫然；
* 不会为了一个坏文件去反复改写系统剪贴板。

支持格式来自 codex 二进制的实测：``image/png``、``image/jpeg``、``image/gif``、
``image/webp``、``image/bmp``、``image/tiff``。claude 走同一套剪贴板机制。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# 受支持的扩展名。与 codex 二进制里出现的 image/* MIME 类型对应。
SUPPORTED_EXTENSIONS: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
)

# 单张图片体积上限。
#
# 上限的意义不是"省流量"，而是拦住明显放错的文件（比如把整个截图目录里的
# 原始导出 100MB PSD 拖进来）。超过这个尺寸的图对模型也没有额外价值。
MAX_IMAGE_BYTES = 20 * 1024 * 1024

# 打开文件对话框时用的过滤器。
FILE_DIALOG_FILTER = "图片 (*.png *.jpg *.jpeg *.gif *.webp *.bmp *.tif *.tiff)"


@dataclass(frozen=True)
class PreparedImage:
    """一张已校验、可安全送去附加的图片。"""

    path: Path
    size_bytes: int

    @property
    def extension(self) -> str:
        return self.path.suffix.lower()

    @property
    def name(self) -> str:
        return self.path.name

    def size_label(self) -> str:
        """人类可读的体积，用于界面提示。"""
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB"):
            if size < 1024 or unit == "MB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} MB"

    def to_dict(self) -> dict[str, object]:
        """给界面用的展示信息。"""
        return {
            "path": str(self.path),
            "name": self.name,
            "sizeBytes": self.size_bytes,
            "sizeLabel": self.size_label(),
            "extension": self.extension,
        }


def _clean_path(raw_path: object) -> Path:
    """把界面传来的路径收敛成 Path（去掉 file:// 前缀、引号与 URL 转义）。

    QML 的 FileDialog 给的是 ``file:///F:/...`` 这种 URL。直接切掉 ``file://``
    会留下 ``/F:/...``，在 Windows 上不是一个有效路径，因此这里用 Qt 的
    ``QUrl.toLocalFile()`` 处理，并退回手工处理以支持无 Qt 环境。
    """
    text = str(raw_path or "").strip()
    if text.startswith("file:"):
        try:
            from PySide6.QtCore import QUrl

            local = QUrl(text).toLocalFile()
            if local:
                return Path(local.strip().strip('"'))
        except Exception:  # noqa: BLE001 - 无 Qt 环境时走下面的手工分支
            pass
        # 手工兜底：file:///F:/x -> F:/x ；file://host/F:/x 也一并处理。
        remainder = text[len("file:") :]
        while remainder.startswith("//"):
            remainder = remainder[1:]
        # 去掉可能残留的主机名段（file://server/share）。
        if not text.startswith("file:///"):
            head, sep, tail = remainder.partition("/")
            if sep and ":" not in head:
                remainder = tail
        # Windows 上 /F:/x 的前导斜杠必须去掉，否则不是有效路径。
        if len(remainder) > 2 and remainder[0] == "/" and remainder[2] == ":":
            remainder = remainder[1:]
        text = remainder
    return Path(text.strip().strip('"'))


def prepare_image(raw_path: object) -> PreparedImage:
    """校验一个待附加的图片路径。

    不合法时抛 :class:`ValueError`，消息是可直接展示给用户的中文原因。
    """
    path = _clean_path(raw_path)
    if not str(path) or str(path) == ".":
        raise ValueError("没有选择图片。")

    try:
        if not path.exists():
            raise ValueError(f"图片不存在：{path.name or path}")
        if not path.is_file():
            raise ValueError(f"这不是一个文件：{path.name}")
        size = path.stat().st_size
    except OSError as exc:  # 权限、路径过长等
        raise ValueError(f"无法读取图片：{exc}") from exc

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        allowed = "、".join(item.lstrip(".") for item in SUPPORTED_EXTENSIONS)
        raise ValueError(f"不支持这种格式（{path.suffix or '无扩展名'}）。可用：{allowed}")

    if size <= 0:
        raise ValueError(f"图片是空文件：{path.name}")
    if size > MAX_IMAGE_BYTES:
        limit = MAX_IMAGE_BYTES // (1024 * 1024)
        raise ValueError(f"图片太大（超过 {limit} MB）：{path.name}")

    return PreparedImage(path=path, size_bytes=size)


__all__ = [
    "FILE_DIALOG_FILTER",
    "MAX_IMAGE_BYTES",
    "SUPPORTED_EXTENSIONS",
    "PreparedImage",
    "prepare_image",
]
