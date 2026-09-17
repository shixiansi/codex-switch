"""风险审查层测试（无 Qt 依赖）。

分三层：

* **策略层**（:mod:`review`）：模式 × 风险的动作矩阵、规则优先级、词表匹配；
* **持久化**（:mod:`policy_store`）：残缺/损坏配置的容错回退；
* **闸门**（:class:`TerminalManager`）：真的不按键、授权后只按一次、
  菜单变了不补发、超时按拒绝、列表菜单与预算这两条硬底线关不掉。

这里刻意用**短超时**的 PolicyConfig（而不是 policy_store 的 5 秒下限），
否则每个超时用例都要等好几秒。
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
for _p in (_SRC, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("CODEX_SWITCH_DISABLE_OPEN_URL", "1")

from tests.helpers import workspace_tempdir  # noqa: E402
from tests.test_terminal import _FakeBackend  # noqa: E402

from codex_switch.ui_v2.terminal import policy_store  # noqa: E402
from codex_switch.ui_v2.terminal.completion import detect_menu  # noqa: E402
from codex_switch.ui_v2.terminal.manager import (  # noqa: E402
    EVENT_REVIEW,
    REVIEW_DENIED,
    REVIEW_EXPIRED,
    REVIEW_PENDING,
    TerminalManager,
)
from codex_switch.ui_v2.terminal.review import (  # noqa: E402
    Action,
    AnswerRequest,
    MODE_BALANCED,
    MODE_FULL,
    MODE_OBSERVE,
    MODE_OFF,
    MODE_STRICT,
    PolicyConfig,
    ReviewPolicy,
    Risk,
    normalize_mode,
)

# 真实菜单样本，与 codex/claude 的输出保持一致。
SAFE_MENU = "› 1. Yes, continue\n  2. No, quit\n"
RISKY_MENU = "› 1. Delete all files\n  2. No, cancel\n"
WATCH_MENU = "› 1. Run the tool\n  2. Skip\n"
LIST_MENU = (
    "  1d ago  首次会话\n"
    "› 2d ago  重构任务\n"
    "  3d ago  修 bug\n"
    "  ↓ more\n"
    "enter resume  ctrl+a archive  esc exit\n"
)


class _ManagerHarness(unittest.TestCase):
    """带假 PTY 后端的 manager，供闸门测试使用。"""

    def make_manager(self, *, mode: str = MODE_BALANCED, **overrides) -> TerminalManager:
        config = PolicyConfig(mode=mode, **overrides)
        manager = TerminalManager(poll_interval=0.05, policy=ReviewPolicy(config))
        manager.auto_answer = True
        return manager

    def start(self, manager: TerminalManager) -> tuple[str, _FakeBackend]:
        store: dict[str, _FakeBackend] = {}

        def make(command, cwd, env):
            backend = _FakeBackend(command, cwd, env)
            store["last"] = backend
            return backend

        session_id = manager.create_session("t", "codex", "", backend_factory=make)
        manager.start()
        self.addCleanup(manager.shutdown)
        return session_id, store["last"]

    @staticmethod
    def written(backend: _FakeBackend) -> str:
        return "".join(backend.write_calls())

    def wait_for(self, predicate, timeout: float = 4.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()

    def wait_for_write(self, backend: _FakeBackend, timeout: float = 3.0) -> str:
        self.wait_for(lambda: bool(backend.write_calls()), timeout=timeout)
        return self.written(backend)


# ==========================================================================
# 策略矩阵
# ==========================================================================


class PolicyMatrixTests(unittest.TestCase):
    def _action(self, mode: str, *, label: str = "", prompt: str = "", kind: str = "numbered") -> Action:
        choices = (label,) if label else ("是", "否")
        request = AnswerRequest(
            session_id="s",
            kind=kind,
            choices=choices,
            intended_index=0,
            intended_payload="1",
            intended_label=label,
            prompt=prompt,
        )
        return ReviewPolicy(PolicyConfig(mode=mode)).evaluate(request).action

    def test_safe_is_silent_in_every_enabled_mode(self) -> None:
        """安全默认项在所有"启用"的模式下都不打扰用户。

        这是"闸门不会毁掉现有体验"的核心保证：``Yes, continue`` 仍然零打扰。
        """
        for mode in (MODE_STRICT, MODE_BALANCED, MODE_OBSERVE, MODE_FULL):
            with self.subTest(mode=mode):
                self.assertIs(self._action(mode, label="Yes, continue"), Action.SILENT)

    def test_risky_asks_in_strict_and_balanced(self) -> None:
        for mode in (MODE_STRICT, MODE_BALANCED):
            with self.subTest(mode=mode):
                self.assertIs(self._action(mode, label="Delete all files"), Action.ASK)

    def test_risky_only_notifies_when_observing(self) -> None:
        self.assertIs(self._action(MODE_OBSERVE, label="Delete all files"), Action.NOTIFY)

    def test_watch_asks_when_strict_and_notifies_when_balanced(self) -> None:
        self.assertIs(self._action(MODE_STRICT, label="Run the tool"), Action.ASK)
        self.assertIs(self._action(MODE_BALANCED, label="Run the tool"), Action.NOTIFY)

    def test_off_blocks_everything(self) -> None:
        for label in ("Yes, continue", "Delete all files", "Run the tool"):
            with self.subTest(label=label):
                self.assertIs(self._action(MODE_OFF, label=label), Action.BLOCK)

    def test_full_mode_releases_risky(self) -> None:
        """完全放行就该真的放行，否则名不副实。"""
        self.assertIs(self._action(MODE_FULL, label="Delete all files"), Action.SILENT)

    def test_list_menu_blocked_even_in_full_mode(self) -> None:
        """列表菜单是硬底线：这是正确性问题（第一项是个随机会话），不是安全策略。"""
        action = self._action(MODE_FULL, label="会话二", kind="list")
        self.assertIs(action, Action.BLOCK)

    def test_budget_blocks_even_in_full_mode(self) -> None:
        request = AnswerRequest(
            session_id="s",
            kind="numbered",
            choices=("Yes",),
            intended_index=0,
            intended_payload="1",
            intended_label="Yes",
            budget_exhausted=True,
        )
        decision = ReviewPolicy(PolicyConfig(mode=MODE_FULL)).evaluate(request)
        self.assertIs(decision.action, Action.BLOCK)
        self.assertEqual(decision.rule_id, "budget")

    def test_declined_menu_is_not_re_asked(self) -> None:
        request = AnswerRequest(
            session_id="s",
            kind="numbered",
            choices=("Delete all", "No"),
            intended_index=0,
            intended_payload="1",
            intended_label="Delete all",
            declined=True,
        )
        decision = ReviewPolicy().evaluate(request)
        self.assertIs(decision.action, Action.BLOCK)
        self.assertEqual(decision.rule_id, "declined")


class ClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ReviewPolicy()

    def test_risk_beats_safe_when_both_present(self) -> None:
        """一句话里同时有危险词与安全词时，必须判高危。"""
        self.assertIs(self.policy.classify("Confirm delete? [Y/n]"), Risk.RISKY)

    def test_confirm_prompt_carries_the_risk(self) -> None:
        """confirm 型的选项文本是"是/否"，风险只能靠提示原文。"""
        for prompt, expected in (
            ("Overwrite existing file? [Y/n]", Risk.RISKY),
            ("Delete the branch permanently? [Y/n]", Risk.RISKY),
            ("Continue with the plan? [Y/n]", Risk.SAFE),
        ):
            with self.subTest(prompt=prompt):
                self.assertIs(self.policy.classify(prompt), expected)

    def test_single_letter_safe_words_do_not_leak(self) -> None:
        """``[Y/n]`` 里天然含 y。若把 y 当安全词，任何确认提示都会被判成安全。"""
        self.assertIsNot(self.policy.classify("Proceed? [Y/n]"), Risk.SAFE)

    def test_unknown_text_is_watch_not_safe(self) -> None:
        """认不出来必须是"待确认"，不能倒向安全——那是 fail-open。"""
        self.assertIs(self.policy.classify("Run the analysis"), Risk.WATCH)

    def test_empty_text_is_watch(self) -> None:
        self.assertIs(self.policy.classify(""), Risk.WATCH)

    def test_risk_keyword_matches_word_variants(self) -> None:
        """``delete`` 要能命中 deleted / delete_all，否则变形词就是绕过路径。"""
        for text in ("deleted 3 files", "delete_all", "force-delete now"):
            with self.subTest(text=text):
                self.assertIs(self.policy.classify(text), Risk.RISKY)

    def test_safe_keyword_requires_whole_word(self) -> None:
        """``no`` 不能被 nothing 命中，否则危险选项会被判成安全项。"""
        self.assertIsNot(self.policy.classify("Nothing will be removed"), Risk.SAFE)

    def test_chinese_keywords(self) -> None:
        self.assertIs(self.policy.classify("删除全部文件"), Risk.RISKY)
        self.assertIs(self.policy.classify("继续"), Risk.SAFE)
        self.assertIs(self.policy.classify("清空工作区"), Risk.RISKY)


# ==========================================================================
# 持久化容错
# ==========================================================================


class PolicyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        # 不用 tempfile.TemporaryDirectory：受限环境下系统临时目录会被拒绝写入，
        # 于是 save 静默失败、读取拿到默认值，测试会以误导性的方式失败。
        # 项目内已有 workspace_tempdir() 专门处理这件事。
        self._tmp = workspace_tempdir()
        self.root = self._tmp.__enter__()
        self.addCleanup(lambda: self._tmp.__exit__(None, None, None))

    def test_missing_file_yields_balanced(self) -> None:
        self.assertEqual(policy_store.load_config(self.root).mode, MODE_BALANCED)

    def test_corrupt_json_falls_back_to_balanced(self) -> None:
        policy_store.policy_path(self.root).write_text("{ 这不是 json", encoding="utf-8")
        self.assertEqual(policy_store.load_config(self.root).mode, MODE_BALANCED)

    def test_unknown_mode_never_falls_back_to_full(self) -> None:
        """手改坏配置时闸门必须收紧，绝不能因此整个打开。"""
        self.assertEqual(normalize_mode("safety-first"), MODE_BALANCED)
        self.assertEqual(normalize_mode(None), MODE_BALANCED)
        self.assertEqual(normalize_mode("FULL"), MODE_FULL)

    def test_wrong_field_types_fall_back_per_field(self) -> None:
        config = policy_store.config_from_dict(
            {
                "mode": "strict",
                "reviewTimeoutSeconds": "很久",
                "budget": {"windowSeconds": None, "maxWrites": "abc"},
                "sound": {"enabled": "maybe"},
            }
        )
        self.assertEqual(config.mode, MODE_STRICT, "合法字段应保留")
        self.assertEqual(config.review_timeout_seconds, 60.0)
        self.assertEqual(config.budget_window_seconds, 60.0)
        self.assertEqual(config.budget_max_writes, 20)
        self.assertTrue(config.sound_enabled)

    def test_empty_risk_keywords_fall_back_to_defaults(self) -> None:
        """空风险词表等于关掉风险判定，属于静默削弱安全边界，必须回退默认。"""
        config = policy_store.config_from_dict({"riskKeywords": []})
        self.assertEqual(len(config.risk_keywords), len(policy_store.DEFAULT_RISK_KEYWORDS))

    def test_numeric_bounds_are_clamped(self) -> None:
        config = policy_store.config_from_dict(
            {"reviewTimeoutSeconds": 999999, "budget": {"maxWrites": 100000}}
        )
        self.assertLessEqual(config.review_timeout_seconds, 3600.0)
        self.assertLessEqual(config.budget_max_writes, 1000)

    def test_roundtrip(self) -> None:
        original = PolicyConfig(mode=MODE_STRICT, sound_enabled=False)
        policy_store.save_config(self.root, original)
        loaded = policy_store.load_config(self.root)
        self.assertEqual(loaded.mode, MODE_STRICT)
        self.assertFalse(loaded.sound_enabled)

    def test_non_dict_payload_falls_back(self) -> None:
        config = policy_store.config_from_dict(["not", "an", "object"])
        self.assertEqual(config.mode, MODE_BALANCED)


# ==========================================================================
# 菜单检测：提示原文
# ==========================================================================


class PromptDetectionTests(unittest.TestCase):
    def test_confirm_menu_keeps_original_prompt(self) -> None:
        menu = detect_menu("Overwrite existing file? [Y/n] ")
        self.assertTrue(menu.awaiting)
        self.assertEqual(menu.kind, "confirm")
        self.assertIn("Overwrite", menu.prompt)

    def test_lowest_confirm_prompt_wins(self) -> None:
        """尾部窗口里可能同时有历史提示，真正等待回答的是最靠下的那条。"""
        menu = detect_menu("Continue? [Y/n]\n...一堆输出...\nDelete everything? [Y/n] ")
        self.assertIn("Delete everything", menu.prompt)

    def test_numbered_menu_has_no_prompt(self) -> None:
        menu = detect_menu("› 1. Yes\n  2. No")
        self.assertEqual(menu.prompt, "")


# ==========================================================================
# 闸门：真的按不按键
# ==========================================================================


class GateTests(_ManagerHarness):
    def test_risky_menu_does_not_press_anything(self) -> None:
        """核心回归：高风险菜单在授权之前一个键都不能发。"""
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))
        time.sleep(0.6)
        self.assertEqual(self.written(backend), "", "授权前不应发送任何按键")
        self.assertTrue(manager.has_pending_review(session_id))

    def test_safe_menu_still_automatic(self) -> None:
        """安全默认项的行为与改造前完全一致：立即自动应答。"""
        manager = self.make_manager()
        _session_id, backend = self.start(manager)
        backend.push(SAFE_MENU.encode())
        self.assertIn("1", self.wait_for_write(backend))

    def test_watch_menu_notifies_but_still_answers(self) -> None:
        """平衡模式下"认不出"的菜单只提示、不拦截：否则噪音会逼用户关掉闸门。"""
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        events: list[dict] = []
        manager._on_event = lambda sid, event, payload: (
            events.append(payload) if event == EVENT_REVIEW else None
        )
        backend.push(WATCH_MENU.encode())
        self.assertIn("1", self.wait_for_write(backend))
        self.assertFalse(manager.has_pending_review(session_id))
        self.assertTrue(any(item.get("state") == "notice" for item in events))

    def test_approve_sends_exactly_once(self) -> None:
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))
        self.assertTrue(manager.resolve_review(session_id, True))
        self.assertIn("1", self.wait_for_write(backend))

    def test_deny_never_sends_and_is_not_re_asked(self) -> None:
        """拒绝之后同一个菜单不该再弹一次——否则用户会被反复骚扰。"""
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))
        self.assertFalse(manager.resolve_review(session_id, False))
        time.sleep(0.8)
        self.assertEqual(self.written(backend), "")
        self.assertFalse(
            manager.has_pending_review(session_id), "拒绝后不应再次挂起同一个菜单"
        )

    def test_no_retry_while_waiting_for_authorisation(self) -> None:
        """挂起期间**不能重试**：用户还没看清就把键刷出去等于绕过审查。"""
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        deadline = time.time() + 3.0
        while time.time() < deadline:
            backend.push(RISKY_MENU.encode())
            time.sleep(0.15)
        self.assertTrue(manager.has_pending_review(session_id))
        self.assertEqual(self.written(backend), "", "挂起期间不应有任何按键写入")

    def test_timeout_denies_instead_of_releasing(self) -> None:
        """超时按拒绝处理，绝不超时放行。"""
        manager = self.make_manager(review_timeout_seconds=5.0)
        manager.policy.config.review_timeout_seconds = 0.4
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))
        self.wait_for(lambda: not manager.has_pending_review(session_id), timeout=3.0)
        time.sleep(0.4)
        self.assertFalse(manager.has_pending_review(session_id))
        self.assertEqual(self.written(backend), "", "超时不得放行")

    def test_stale_approval_is_discarded(self) -> None:
        """菜单在等待期间变了，批准必须作废——用户批准的是他看到的那一屏。

        真实情形：等待授权时 TUI 换了一屏。这里推入另一个菜单让轮询线程读到，
        再批准先前那次请求；因为菜单已不同，按键不得发出，也不能"补偿性地"发。
        """
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))

        # 屏幕换成另一个菜单：会话的 choices 随之改变。
        backend.push("› 1. Format the disk\n  2. No, cancel\n".encode())
        self.wait_for(
            lambda: manager.session(session_id).choices[:1] == ["Format the disk"], timeout=3.0
        )
        self.assertFalse(manager.resolve_review(session_id, True), "菜单已变，批准应作废")
        time.sleep(0.4)
        self.assertEqual(self.written(backend), "", "菜单已变，不得补发按键")

    def test_off_mode_presses_nothing(self) -> None:
        manager = self.make_manager(mode=MODE_OFF)
        _session_id, backend = self.start(manager)
        backend.push(SAFE_MENU.encode())
        time.sleep(0.8)
        self.assertEqual(self.written(backend), "")

    def test_full_mode_still_skips_list_menu(self) -> None:
        manager = self.make_manager(mode=MODE_FULL)
        _session_id, backend = self.start(manager)
        backend.push(LIST_MENU.encode())
        time.sleep(1.0)
        self.assertEqual(self.written(backend), "", "列表菜单即使完全放行也不能自动应答")

    def test_budget_stops_automatic_writes(self) -> None:
        manager = self.make_manager(budget_max_writes=1, budget_window_seconds=60.0)
        session_id, backend = self.start(manager)
        session = manager.session(session_id)
        # 直接构造"预算已用尽"的状态，避免依赖真实时序等待。
        session.auto_write_times = [time.monotonic()]
        self.assertTrue(manager._budget_exhausted(session, time.monotonic()))
        backend.push(SAFE_MENU.encode())
        time.sleep(0.8)
        self.assertEqual(self.written(backend), "", "预算耗尽后应降级为手动")

    def test_human_approval_bypasses_budget(self) -> None:
        """人工放行不是自动化，没理由被限流；否则预算会把用户卡死。"""
        manager = self.make_manager(budget_max_writes=1)
        session_id, backend = self.start(manager)
        session = manager.session(session_id)
        session.auto_write_times = [time.monotonic()]
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))
        self.assertTrue(manager.resolve_review(session_id, True))
        self.assertIn("1", self.wait_for_write(backend))

    def test_allow_kind_answers_later_same_menu_without_asking(self) -> None:
        """“本会话允许此类”之后，同类菜单再现时不再打扰。

        用**同类但不同内容**的菜单验证：按钮承诺的是"此类"，不是"这一条"。
        """
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))
        self.assertTrue(manager.resolve_review(session_id, True, allow_kind=True))
        self.assertTrue(self.wait_for(lambda: bool(backend.write_calls())))

        # 换一个内容不同、但同属编号菜单的高风险菜单。
        backend.push("› 1. Format the disk\n  2. No, cancel\n".encode())
        self.wait_for(
            lambda: manager.session(session_id).choices[:1] == ["Format the disk"], timeout=3.0
        )
        self.assertFalse(
            manager.has_pending_review(session_id),
            "已允许此类后不应再次要求授权",
        )
        self.assertTrue(
            self.wait_for(lambda: "1" in self.written(backend), timeout=3.0),
            "已允许此类后应直接应答",
        )

    def test_allow_kind_does_not_cover_list_menu(self) -> None:
        """“此类”永不覆盖列表菜单：它的第一项是个随机会话，自动点没有语义。"""
        manager = self.make_manager(mode=MODE_FULL)
        session_id, backend = self.start(manager)
        manager.session(session_id).approved_kinds.add("list")
        backend.push(LIST_MENU.encode())
        time.sleep(1.0)
        self.assertEqual(self.written(backend), "")

    def test_menu_is_not_asked_twice_while_still_on_screen(self) -> None:
        """回归：同一屏菜单只弹一次授权。

        应答经写入队列延迟约 0.25s 发出，而轮询间隔也是 0.25s；早期实现没有
        "这一屏已处理"标记，导致菜单多停留一拍就再弹一次，用户看到连续两个
        授权框（先批准的那个还悬着）。
        """
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        # 持续推同一个菜单，模拟 TUI 一直重绘这一屏。
        deadline = time.time() + 2.5
        while time.time() < deadline:
            backend.push(RISKY_MENU.encode())
            time.sleep(0.1)
        session = manager.session(session_id)
        self.assertEqual(
            len(session.answered_menus), 1, "同一屏只应被记录/询问一次"
        )
        self.assertTrue(manager.has_pending_review(session_id), "应仍处于待授权")

    def test_approved_menu_is_not_re_asked_before_screen_clears(self) -> None:
        """授权后、菜单还没从屏幕消失的这段时间里不能再次询问。"""
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))
        manager.resolve_review(session_id, True)
        # 菜单仍在屏幕上重绘
        deadline = time.time() + 1.5
        while time.time() < deadline:
            backend.push(RISKY_MENU.encode())
            time.sleep(0.1)
        self.assertFalse(
            manager.has_pending_review(session_id), "刚批准过的菜单不应再次挂起"
        )

    def test_session_flag_can_veto_automatic_answer(self) -> None:
        """会话级开关是否决项：只要会话被标记为不允许，就不该自动按键。"""
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        manager.session(session_id).auto_answer_enabled = False
        backend.push(SAFE_MENU.encode())
        time.sleep(0.8)
        self.assertEqual(self.written(backend), "")

    def test_removing_session_drops_pending_review(self) -> None:
        """会话被清除后不该再弹它的授权框。"""
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))
        manager.remove_session(session_id)
        self.assertFalse(manager.has_pending_review(session_id))
        self.assertEqual(manager.pending_reviews(), [])


class ReviewEventTests(_ManagerHarness):
    def test_pending_event_carries_what_will_be_sent(self) -> None:
        """事件必须带够界面展示所需的信息：要替你按哪个键、为什么。"""
        manager = self.make_manager()
        events: list[dict] = []
        manager._on_event = lambda sid, event, payload: (
            events.append(payload) if event == EVENT_REVIEW else None
        )
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))

        pending = [item for item in events if item.get("state") == REVIEW_PENDING]
        self.assertTrue(pending, "应发出待授权事件")
        review = pending[-1]["review"]
        self.assertEqual(review["risk"], "risky")
        self.assertEqual(review["payload"], "1")
        self.assertIn("Delete all files", review["label"])
        self.assertTrue(review["reason"])

    def test_denied_event_is_emitted(self) -> None:
        manager = self.make_manager()
        events: list[dict] = []
        manager._on_event = lambda sid, event, payload: (
            events.append(payload) if event == EVENT_REVIEW else None
        )
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))
        manager.resolve_review(session_id, False)
        self.assertTrue(any(item.get("state") == REVIEW_DENIED for item in events))

    def test_expired_event_is_emitted(self) -> None:
        manager = self.make_manager()
        manager.policy.config.review_timeout_seconds = 0.4
        events: list[dict] = []
        manager._on_event = lambda sid, event, payload: (
            events.append(payload) if event == EVENT_REVIEW else None
        )
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(
            lambda: any(item.get("state") == REVIEW_EXPIRED for item in events), timeout=4.0
        )
        self.assertTrue(any(item.get("state") == REVIEW_EXPIRED for item in events))


class SummaryTests(_ManagerHarness):
    def test_summary_exposes_review_state(self) -> None:
        manager = self.make_manager()
        session_id, backend = self.start(manager)
        backend.push(RISKY_MENU.encode())
        self.wait_for(lambda: manager.has_pending_review(session_id))
        summary = next(item for item in manager.summaries() if item.session_id == session_id)
        self.assertTrue(summary.review_pending)
        self.assertEqual(summary.review_risk, "risky")
        self.assertTrue(summary.review_label)
        payload = summary.to_dict()
        self.assertTrue(payload["reviewPending"])
        self.assertEqual(payload["reviewMode"], MODE_BALANCED)
        self.assertTrue(payload["reviewModeLabel"])


if __name__ == "__main__":
    unittest.main()
