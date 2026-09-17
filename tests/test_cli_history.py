"""项目级历史读取的测试。

全部在临时目录里构造**合成的 codex 会话文件**，不依赖用户真实数据——
否则测试结果会随用户机器上的会话内容变化，等于没有断言。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codex_switch.ui_v2.terminal.cli_history import (  # noqa: E402
    MAX_PROMPTS,
    PromptHistoryReader,
)

TMP_ROOT = PROJECT_ROOT / ".tmp" / "test-cli-history"


def make_root(case: unittest.TestCase) -> Path:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"{case._testMethodName}-", dir=str(TMP_ROOT)))
    case.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
    return root


def write_session(
    sessions_root: Path,
    cwd: str,
    prompts: list[str],
    *,
    session_id: str = "abc",
    extra_lines: list[dict] | None = None,
    day: str = "01",
) -> Path:
    """写一个合成的 codex rollout 文件。"""
    folder = sessions_root / "2026" / "09" / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-2026-09-{day}T00-00-00-{session_id}.jsonl"
    lines: list[dict] = [
        {
            "timestamp": "2026-09-01T00:00:00.000Z",
            "ordinal": 0,
            "type": "session_meta",
            "payload": {"session_id": session_id, "cwd": cwd, "cli_version": "0.154.0"},
        }
    ]
    for prompt in prompts:
        lines.append({
            "timestamp": "2026-09-01T00:00:01.000Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": prompt},
        })
    lines.extend(extra_lines or [])
    path.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
        encoding="utf-8",
    )
    return path


class PromptExtractionTests(unittest.TestCase):
    """从会话文件里提取提示词。"""

    def setUp(self) -> None:
        self.root = make_root(self)
        self.reader = PromptHistoryReader(self.root)

    def test_reads_prompts_for_matching_cwd(self) -> None:
        write_session(self.root, r"F:\proj", ["第一条", "第二条"])
        self.assertEqual(self.reader.prompts_for(r"F:\proj"), ["第一条", "第二条"])

    def test_ignores_other_projects(self) -> None:
        write_session(self.root, r"F:\a", ["A 项目的"], session_id="a")
        write_session(self.root, r"F:\b", ["B 项目的"], session_id="b")
        self.assertEqual(self.reader.prompts_for(r"F:\a"), ["A 项目的"])
        self.assertEqual(self.reader.prompts_for(r"F:\b"), ["B 项目的"])

    def test_path_normalisation(self) -> None:
        """大小写、斜杠方向、结尾分隔符的差异都要能对上。"""
        write_session(self.root, r"F:\Proj\Sub", ["消息"])
        for variant in (
            r"F:\Proj\Sub",
            r"f:\proj\sub",
            "F:/Proj/Sub",
            "f:/proj/sub",
            "F:\\Proj\\Sub\\",
        ):
            with self.subTest(variant=variant):
                self.assertEqual(self.reader.prompts_for(variant), ["消息"])

    def test_system_injections_are_skipped(self) -> None:
        """AGENTS.md / 环境上下文这类不是用户敲的，不该进历史。"""
        write_session(self.root, r"F:\p", [
            "# AGENTS.md instructions for F:\\p\n\n<INSTRUCTIONS>规则</INSTRUCTIONS>",
            "<environment_context>cwd=...</environment_context>",
            "真正的问题",
        ])
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["真正的问题"])

    def test_image_placeholders_are_skipped(self) -> None:
        write_session(self.root, r"F:\p", [
            '<image name=[Image #1] path="C:\\tmp\\a.png"></image>',
            "文字问题",
        ])
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["文字问题"])

    def test_prompt_from_response_item(self) -> None:
        """另一种存放形式：response_item + role=user。"""
        write_session(self.root, r"F:\p", [], extra_lines=[{
            "type": "response_item",
            "payload": {
                "role": "user",
                "content": [{"type": "input_text", "text": "来自 response_item"}],
            },
        }])
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["来自 response_item"])

    def test_very_long_prompts_are_skipped(self) -> None:
        """几千字的粘贴内容不该塞回输入框。"""
        write_session(self.root, r"F:\p", ["短问题", "x" * 5000])
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["短问题"])

    def test_blank_prompts_are_skipped(self) -> None:
        write_session(self.root, r"F:\p", ["", "  ", "有内容"])
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["有内容"])

    def test_consecutive_duplicates_are_collapsed(self) -> None:
        write_session(self.root, r"F:\p", ["继续", "继续", "继续", "换一个"])
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["继续", "换一个"])

    def test_multiple_sessions_are_merged_in_time_order(self) -> None:
        earlier = write_session(self.root, r"F:\p", ["早的"], session_id="old", day="01")
        later = write_session(self.root, r"F:\p", ["晚的"], session_id="new", day="02")
        os.utime(earlier, (1_600_000_000, 1_600_000_000))
        os.utime(later, (1_700_000_000, 1_700_000_000))
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["早的", "晚的"])

    def test_unknown_cwd_returns_empty(self) -> None:
        write_session(self.root, r"F:\p", ["消息"])
        self.assertEqual(self.reader.prompts_for(r"Z:\nope"), [])
        self.assertEqual(self.reader.prompts_for(""), [])

    def test_missing_root_returns_empty(self) -> None:
        reader = PromptHistoryReader(self.root / "does-not-exist")
        self.assertEqual(reader.prompts_for(r"F:\p"), [])

    def test_corrupt_lines_do_not_break_reading(self) -> None:
        path = write_session(self.root, r"F:\p", ["好的"])
        with path.open("a", encoding="utf-8") as handle:
            handle.write("这不是 JSON\n")
            handle.write('{"type":"event_msg","payload":{"type":"user_message","message":"之后"}}\n')
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["好的", "之后"])

    def test_corrupt_meta_file_is_ignored(self) -> None:
        folder = self.root / "2026" / "09" / "01"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "rollout-broken.jsonl").write_text("{ 不是 JSON\n", encoding="utf-8")
        write_session(self.root, r"F:\p", ["正常的"])
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["正常的"])

    def test_result_is_capped(self) -> None:
        write_session(self.root, r"F:\p", [f"消息 {i}" for i in range(MAX_PROMPTS + 50)])
        prompts = self.reader.prompts_for(r"F:\p")
        self.assertEqual(len(prompts), MAX_PROMPTS)
        self.assertEqual(prompts[-1], f"消息 {MAX_PROMPTS + 49}", "应保留最新的")


class CacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_root(self)
        self.reader = PromptHistoryReader(self.root)

    def test_repeated_reads_use_cache(self) -> None:
        """第二次读取应命中缓存，不再重新解析会话文件。

        用"统计解析调用次数"来验证，而不是改动文件内容：
        改内容会连带影响 cwd 匹配与 mtime 判据，测出来的不是缓存行为。
        """
        from unittest import mock

        import codex_switch.ui_v2.terminal.cli_history as module

        write_session(self.root, r"F:\p", ["消息"])
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["消息"])

        with mock.patch.object(
            module, "_prompts_from_file", wraps=module._prompts_from_file
        ) as spy:
            again = self.reader.prompts_for(r"F:\p")
        self.assertEqual(again, ["消息"])
        self.assertEqual(spy.call_count, 0, "第二次读取仍然解析了文件，没有走缓存")

    def test_cache_invalidated_when_session_updates(self) -> None:
        path = write_session(self.root, r"F:\p", ["旧消息"])
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["旧消息"])
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "新消息"},
            }, ensure_ascii=False) + "\n")
        # mtime 精度可能只有秒级，显式推后一点确保判据变化。
        stamp = path.stat().st_mtime + 1.0
        os.utime(path, (stamp, stamp))
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["旧消息", "新消息"],
                         "会话更新后缓存没有失效")

    def test_invalidate_clears_cache(self) -> None:
        write_session(self.root, r"F:\p", ["消息"])
        self.reader.prompts_for(r"F:\p")
        self.reader.invalidate()
        self.assertEqual(self.reader.prompts_for(r"F:\p"), ["消息"])


class SeedingTests(unittest.TestCase):
    """把项目级历史接进输入框。"""

    def test_seed_puts_project_history_before_local(self) -> None:
        """项目历史在时间上更早，应排在前面（↑ 先翻到最近的本地消息）。"""
        from codex_switch.ui_v2.terminal.input_assist import InputHistory

        history = InputHistory()
        history.record("s", "本次发的")
        added = history.seed("s", ["以前发的 1", "以前发的 2"])
        self.assertEqual(added, 2)
        self.assertEqual(
            history.entries("s"),
            ["以前发的 1", "以前发的 2", "本次发的"],
        )

    def test_seed_is_idempotent(self) -> None:
        """重复载入不应把同一条反复塞进去。"""
        from codex_switch.ui_v2.terminal.input_assist import InputHistory

        history = InputHistory()
        self.assertEqual(history.seed("s", ["A", "B"]), 2)
        self.assertEqual(history.seed("s", ["A", "B"]), 0)
        self.assertEqual(history.entries("s"), ["A", "B"])

    def test_seed_skips_items_already_in_history(self) -> None:
        from codex_switch.ui_v2.terminal.input_assist import InputHistory

        history = InputHistory()
        history.record("s", "B")
        self.assertEqual(history.seed("s", ["A", "B", "C"]), 2)
        self.assertEqual(history.entries("s"), ["A", "C", "B"])

    def test_seed_with_empty_list_changes_nothing(self) -> None:
        from codex_switch.ui_v2.terminal.input_assist import InputHistory

        history = InputHistory()
        self.assertEqual(history.seed("s", []), 0)
        self.assertEqual(history.entries("s"), [])

    def test_seed_respects_max_history(self) -> None:
        from codex_switch.ui_v2.terminal.input_assist import MAX_HISTORY, InputHistory

        history = InputHistory()
        history.seed("s", [f"第 {i} 条" for i in range(MAX_HISTORY + 100)])
        self.assertEqual(len(history.entries("s")), MAX_HISTORY)


if __name__ == "__main__":
    unittest.main()
