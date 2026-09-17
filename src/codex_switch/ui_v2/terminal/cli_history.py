"""读取 AI CLI 的**项目级**历史提示词。

需求背景：用户希望在输入框按 ↑ 时，能翻出"这个项目里以前发给 AI 的话"，
而不只是本次运行、当前会话内发过的那几条。

数据来源（不修改 CLI 任何文件，只读）：

* **codex**：``~/.codex/sessions/<年>/<月>/<日>/rollout-*.jsonl``
  每个文件首行是 ``session_meta``，其中 ``payload.cwd`` 记录该会话的工作目录；
  用户消息以 ``event_msg`` / ``payload.type == "user_message"`` 出现。
  按 ``cwd`` 过滤即可得到"某个项目的历史"。

设计取舍：

* **只读**。不动 CLI 的存储，避免把它的数据写坏——这与 CodeBuddy 那边
  "不改插件源码"的原则一致。
* **按需读取 + 缓存**。目录可能有上百个会话文件、单个文件上百 KB；
  每次按 ↑ 都全量扫描会卡界面。这里按 (目录, mtime) 缓存结果。
* **跳过系统注入**。``AGENTS.md`` 说明、环境上下文这类内容不是用户敲的，
  放进历史里毫无意义且会淹没真正有用的提示词。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# 历史最多保留多少条。太多会让 ↑ 翻很久，也没有保留价值。
MAX_PROMPTS = 300

# 单个会话文件最多读多少行。超长会话（几万行）没必要全读，
# 用户想翻的通常是最近说过的话。
MAX_LINES_PER_FILE = 4000

# 这些标记说明该条不是用户手敲的，而是 CLI 注入的上下文。
_SKIP_MARKERS = (
    "# AGENTS.md instructions",
    "<INSTRUCTIONS>",
    "<environment_context>",
    "<user_instructions>",
    "<skill>",
)

# 过短或纯符号的内容没有复用价值。
_MIN_LENGTH = 2

# 过长的内容不进历史：按 ↑ 会把输入框塞满一整屏文字，反而没法编辑。
# 真实数据里确实有用户粘贴几千字分析结论的情况。
_MAX_LENGTH = 2000


def codex_home() -> Path:
    """codex 的数据目录，遵循它自己的 ``CODEX_HOME`` 约定。"""
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override)
    return Path.home() / ".codex"


def sessions_root() -> Path:
    return codex_home() / "sessions"


@dataclass
class _CacheEntry:
    mtime: float
    prompts: list[str] = field(default_factory=list)


class PromptHistoryReader:
    """按项目目录读取 codex 的历史提示词。

    结果按 "cwd → 提示词列表（由旧到新）" 缓存，并以会话文件的
    mtime 之和作为失效判据：目录里任一会话有更新，缓存就重建。
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else sessions_root()
        self._cache: dict[str, _CacheEntry] = {}

    # -- 公共接口 ------------------------------------------------------
    def prompts_for(self, cwd: str) -> list[str]:
        """返回该项目目录下的历史提示词（由旧到新）。

        目录不存在、没有会话、或解析全部失败时返回空列表——
        历史读不出来绝不该影响输入框本身的可用性。
        """
        key = self._normalize(cwd)
        if not key:
            return []
        files = self._session_files(key)
        if not files:
            return []
        stamp = self._stamp(files)
        cached = self._cache.get(key)
        if cached is not None and cached.mtime == stamp:
            return list(cached.prompts)

        prompts: list[str] = []
        for path in files:
            prompts.extend(_prompts_from_file(path))
        # 同一个提示词连续重复没有意义，去重后再截断。
        prompts = _dedupe_consecutive(prompts)
        if len(prompts) > MAX_PROMPTS:
            prompts = prompts[-MAX_PROMPTS:]
        self._cache[key] = _CacheEntry(mtime=stamp, prompts=list(prompts))
        return prompts

    def invalidate(self) -> None:
        self._cache.clear()

    # -- 内部 ----------------------------------------------------------
    @staticmethod
    def _normalize(cwd: str) -> str:
        """统一成小写、正斜杠、去掉尾分隔符。

        codex 记录的是 ``F:\\codex-switch`` 这类 Windows 路径，而界面给的
        可能是另一种写法；不统一就会因为一个字符之差全部匹配不上。
        """
        text = str(cwd or "").strip().strip('"')
        if not text:
            return ""
        return text.replace("\\", "/").rstrip("/").lower()

    def _session_files(self, key: str) -> list[Path]:
        root = self._root
        if not root.is_dir():
            return []
        matches: list[Path] = []
        try:
            candidates = list(root.rglob("rollout-*.jsonl"))
        except OSError:
            return []
        for path in candidates:
            try:
                if self._cwd_of(path) == key:
                    matches.append(path)
            except OSError:
                continue
        matches.sort(key=_safe_mtime)
        return matches

    @staticmethod
    def _cwd_of(path: Path) -> str:
        """读会话首行的 ``payload.cwd``。"""
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                first = handle.readline()
        except OSError:
            return ""
        try:
            record = json.loads(first)
        except (json.JSONDecodeError, ValueError):
            return ""
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return ""
        return PromptHistoryReader._normalize(str(payload.get("cwd") or ""))

    @staticmethod
    def _stamp(files: list[Path]) -> float:
        """用 mtime 之和当失效判据：任何一个文件更新都会改变它。"""
        return sum(_safe_mtime(path) for path in files)


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _dedupe_consecutive(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if out and out[-1] == item:
            continue
        out.append(item)
    return out


def _prompts_from_file(path: Path) -> list[str]:
    """从一个 rollout 文件里提取用户提示词（由旧到新）。"""
    out: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= MAX_LINES_PER_FILE:
                    break
                prompt = _prompt_from_line(line)
                if prompt:
                    out.append(prompt)
    except OSError:
        return out
    return out


def _prompt_from_line(line: str) -> str:
    """从一行 JSON 里取出用户提示词；不是用户消息则返回空串。"""
    text = line.strip()
    if not text or "user_message" not in text and '"user"' not in text:
        # 快速预筛：绝大多数行都不是用户消息，先做字符串判断可以
        # 避免把每行都丢给 json.loads（大文件下差别很明显）。
        return ""
    try:
        record = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(record, dict):
        return ""

    payload = record.get("payload")
    if not isinstance(payload, dict):
        return ""

    message = ""
    if record.get("type") == "event_msg" and payload.get("type") == "user_message":
        message = str(payload.get("message") or "")
    elif record.get("type") == "response_item" and payload.get("role") == "user":
        content = payload.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") in ("input_text", "text"):
                    parts.append(str(item.get("text") or ""))
            message = "".join(parts)
        elif isinstance(content, str):
            message = content

    message = message.strip()
    if len(message) < _MIN_LENGTH:
        return ""
    # 超长内容（几千字的分析结论、粘贴的日志）不适合塞回输入框。
    if len(message) > _MAX_LENGTH:
        return ""
    if any(marker in message for marker in _SKIP_MARKERS):
        return ""
    # 图片附件占位符不是用户敲的文字，留着没有复用价值。
    if message.startswith("<image ") and "</image>" in message:
        return ""
    return message


__all__ = [
    "MAX_PROMPTS",
    "PromptHistoryReader",
    "codex_home",
    "sessions_root",
]
