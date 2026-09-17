"""读取 AI CLI 的**项目级**历史提示词。

需求背景：用户希望在输入框按 ↑ 时，能翻出"这个项目里以前发给 AI 的话"，
而不只是本次运行、当前会话内发过的那几条。

支持的 CLI 与数据来源（**全部只读**，不修改 CLI 任何文件）：

* **codex**：``~/.codex/sessions/<年>/<月>/<日>/rollout-*.jsonl``
  每个文件首行是 ``session_meta``，其中 ``payload.cwd`` 记录该会话的工作目录；
  用户消息以 ``event_msg`` / ``payload.type == "user_message"`` 出现。
  按 ``cwd`` 过滤即可得到"某个项目的历史"。

* **claude**：``~/.claude/history.jsonl``
  每行含 ``display``（提示词）、``project``（项目目录）、``timestamp``。

设计取舍：

* **只读**。不动 CLI 的存储，避免把它的数据写坏——这与 CodeBuddy 那边
  "不改插件源码"的原则一致。
* **按需读取 + 缓存**。codex 可能有上百个会话文件、单个上百 KB；
  每次按 ↑ 都全量扫描会卡界面。这里按 (项目, mtime) 缓存结果。
* **跳过系统注入**。``AGENTS.md`` 说明、环境上下文这类内容不是用户敲的，
  放进历史里毫无意义且会淹没真正有用的提示词。
* **格式差异各自封装**。两个 CLI 的存储形状完全不同（一个是一堆按日期
  分目录的会话文件、一个是单个 jsonl），因此各自实现、共用过滤与归一化。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

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
    "<command-name>",
    "<local-command",
)

# 过短或纯符号的内容没有复用价值。
_MIN_LENGTH = 2

# 过长的内容不进历史：按 ↑ 会把输入框塞满一整屏文字，反而没法编辑。
# 真实数据里确实有用户粘贴几千字分析结论的情况。
_MAX_LENGTH = 2000


# ---------------------------------------------------------------------------
# 共用工具
# ---------------------------------------------------------------------------

def normalize_path(cwd: str) -> str:
    """统一成小写、正斜杠、去掉尾分隔符。

    codex 记录的是 ``F:\\codex-switch``，claude 是 ``F:\\编程\\codex-switch``，
    界面给的可能是另一种写法；不统一就会因为一个字符之差全部匹配不上。
    """
    text = str(cwd or "").strip().strip('"')
    if not text:
        return ""
    return text.replace("\\", "/").rstrip("/").lower()


def accept_prompt(text: str) -> str:
    """判断一条内容是否适合进历史；适合则返回原文，否则返回空串。"""
    message = str(text or "").strip()
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


def dedupe_consecutive(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if out and out[-1] == item:
            continue
        out.append(item)
    return out


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------

class HistorySource(Protocol):
    """从一个 CLI 的存储里按项目取历史提示词。"""

    def prompts_for(self, cwd: str) -> list[str]:  # pragma: no cover - 协议
        ...


@dataclass
class _CacheEntry:
    stamp: float
    prompts: list[str] = field(default_factory=list)


class CodexHistorySource:
    """codex：按 cwd 归组 ~/.codex/sessions 下的会话文件。"""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else codex_home() / "sessions"
        self._cache: dict[str, _CacheEntry] = {}

    @property
    def root(self) -> Path:
        return self._root

    def prompts_for(self, cwd: str) -> list[str]:
        key = normalize_path(cwd)
        if not key:
            return []
        files = self._session_files(key)
        if not files:
            return []
        stamp = sum(_safe_mtime(path) for path in files)
        cached = self._cache.get(key)
        if cached is not None and cached.stamp == stamp:
            return list(cached.prompts)

        prompts: list[str] = []
        for path in files:
            prompts.extend(_prompts_from_codex_file(path))
        prompts = dedupe_consecutive(prompts)
        if len(prompts) > MAX_PROMPTS:
            prompts = prompts[-MAX_PROMPTS:]
        self._cache[key] = _CacheEntry(stamp=stamp, prompts=list(prompts))
        return prompts

    def invalidate(self) -> None:
        self._cache.clear()

    def _session_files(self, key: str) -> list[Path]:
        if not self._root.is_dir():
            return []
        try:
            candidates = list(self._root.rglob("rollout-*.jsonl"))
        except OSError:
            return []
        matches = [path for path in candidates if _codex_cwd_of(path) == key]
        matches.sort(key=_safe_mtime)
        return matches


class ClaudeHistorySource:
    """claude：单个 history.jsonl，每行带 project 字段。"""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else claude_home() / "history.jsonl"
        self._cache: dict[str, _CacheEntry] = {}

    @property
    def path(self) -> Path:
        return self._path

    def prompts_for(self, cwd: str) -> list[str]:
        key = normalize_path(cwd)
        if not key:
            return []
        if not self._path.is_file():
            return []
        stamp = _safe_mtime(self._path)
        cached = self._cache.get(key)
        if cached is not None and cached.stamp == stamp:
            return list(cached.prompts)

        prompts: list[str] = []
        try:
            with self._path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    record = _claude_record(line)
                    if record is None:
                        continue
                    project = normalize_path(str(record.get("project") or ""))
                    if project != key:
                        continue
                    prompt = accept_prompt(str(record.get("display") or ""))
                    if prompt:
                        prompts.append(prompt)
        except OSError:
            return []

        prompts = dedupe_consecutive(prompts)
        if len(prompts) > MAX_PROMPTS:
            prompts = prompts[-MAX_PROMPTS:]
        self._cache[key] = _CacheEntry(stamp=stamp, prompts=list(prompts))
        return prompts

    def invalidate(self) -> None:
        self._cache.clear()


# ---------------------------------------------------------------------------
# 门面
# ---------------------------------------------------------------------------

# 会话命令名 → 数据源种类。命令可能带参数（"codex --model x"），
# 因此按"命令里出现的可执行名"判断，而不是全等比较。
CLI_KINDS = ("codex", "claude")


def detect_cli(command: str) -> str:
    """从启动命令里认出是哪个 CLI；认不出返回空串。

    只取可执行文件名部分判断（``codex`` / ``claude``），忽略参数；
    否则 ``codex --model x`` 这种就匹配不上。
    """
    text = str(command or "").strip().strip('"')
    if not text:
        return ""
    # 取第一个词，并去掉可能的路径与 .exe/.cmd 后缀。
    first = text.split()[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1"):
        if first.endswith(suffix):
            first = first[: -len(suffix)]
    for kind in CLI_KINDS:
        if first == kind or first.startswith(f"{kind}-"):
            return kind
    return ""


class PromptHistoryReader:
    """按 CLI 从对应存储里取项目级历史提示词。

    对上层只暴露 :meth:`prompts_for`；具体用哪个数据源由会话命令决定。
    """

    def __init__(
        self,
        *,
        codex: HistorySource | None = None,
        claude: HistorySource | None = None,
    ) -> None:
        self._sources: dict[str, HistorySource] = {
            "codex": codex if codex is not None else CodexHistorySource(),
            "claude": claude if claude is not None else ClaudeHistorySource(),
        }

    def source_for(self, cli: str) -> HistorySource | None:
        return self._sources.get(str(cli or "").lower())

    def prompts_for(self, cwd: str, cli: str = "") -> list[str]:
        """返回该项目的历史提示词（由旧到新）。

        目录不存在、没有会话、或解析全部失败时返回空列表——
        历史读不出来绝不该影响输入框本身的可用性。

        ``cli`` 为空时依次尝试所有数据源并合并去重：界面偶尔拿不到
        确切命令（例如用户自定义命令），此时宁可多试也不要什么都不给。
        """
        kinds = [str(cli).lower()] if cli and str(cli).lower() in self._sources else list(self._sources)
        merged: list[str] = []
        for kind in kinds:
            source = self._sources.get(kind)
            if source is None:
                continue
            try:
                merged.extend(source.prompts_for(cwd))
            except Exception:  # noqa: BLE001 - 单个源失败不影响其他源
                continue
        if not merged:
            return []
        merged = dedupe_consecutive(merged)
        if len(merged) > MAX_PROMPTS:
            merged = merged[-MAX_PROMPTS:]
        return merged

    def invalidate(self) -> None:
        for source in self._sources.values():
            invalidate = getattr(source, "invalidate", None)
            if callable(invalidate):
                invalidate()


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

def codex_home() -> Path:
    """codex 的数据目录，遵循它自己的 ``CODEX_HOME`` 约定。"""
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override)
    return Path.home() / ".codex"


def claude_home() -> Path:
    """claude 的数据目录，遵循它自己的 ``CLAUDE_CONFIG_DIR`` 约定。"""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".claude"


def sessions_root() -> Path:
    return codex_home() / "sessions"


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

def _codex_cwd_of(path: Path) -> str:
    """读 codex 会话首行的 ``payload.cwd``。"""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            first = handle.readline()
    except OSError:
        return ""
    try:
        record = json.loads(first)
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(record, dict):
        return ""
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return ""
    return normalize_path(str(payload.get("cwd") or ""))


def _claude_record(line: str) -> dict | None:
    """解析 claude history.jsonl 的一行。"""
    text = line.strip()
    if not text:
        return None
    try:
        record = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _prompts_from_codex_file(path: Path) -> list[str]:
    """从一个 codex rollout 文件里提取用户提示词（由旧到新）。"""
    out: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= MAX_LINES_PER_FILE:
                    break
                record = _codex_record(line)
                if record is None:
                    continue
                prompt = accept_prompt(_codex_message(record))
                if prompt:
                    out.append(prompt)
    except OSError:
        return out
    return out


def _codex_record(line: str) -> dict | None:
    """解析一行，并对明显不是用户消息的行提前返回。"""
    text = line.strip()
    if not text:
        return None
    # 快速预筛：绝大多数行都不是用户消息，先做字符串判断可以避免
    # 把每行都丢给 json.loads（大文件下差别很明显）。
    if "user_message" not in text and '"user"' not in text:
        return None
    try:
        record = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    return record


def _codex_message(record: dict) -> str:
    """从一条记录里取出用户消息文本。"""
    payload = record.get("payload") or {}
    if record.get("type") == "event_msg" and payload.get("type") == "user_message":
        return str(payload.get("message") or "")
    if record.get("type") == "response_item" and payload.get("role") == "user":
        content = payload.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") in ("input_text", "text"):
                    parts.append(str(item.get("text") or ""))
            return "".join(parts)
        if isinstance(content, str):
            return content
    return ""


__all__ = [
    "CLI_KINDS",
    "MAX_PROMPTS",
    "ClaudeHistorySource",
    "CodexHistorySource",
    "HistorySource",
    "PromptHistoryReader",
    "accept_prompt",
    "claude_home",
    "codex_home",
    "detect_cli",
    "normalize_path",
    "sessions_root",
]
