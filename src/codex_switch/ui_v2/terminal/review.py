"""自动应答的风险审查层（纯逻辑，无 Qt 依赖）。

背景：早期实现只有"检测到菜单就选第一项"这一条规则，没有任何风险判定，
等价于完全放行——一个把 ``1. Delete all files`` 放在首位的菜单会被直接点下去。

这里把"该不该替用户按键"独立成一层决策：

    detect_menu() ──► AnswerRequest ──► ReviewPolicy.evaluate() ──► Decision

决策是**纯函数**：给定模式、风险等级与少量状态标记（是否已被拒绝、预算是否耗尽），
输出四种动作之一。所有状态（预算计数、已拒绝签名）由 manager 持有并通过请求传入，
因此本模块可以直接单测，不需要线程、不需要 PTY。

设计取舍：

* **判定对象是"即将发送的那一项"**（confirm 型菜单另加原始提示行），而不是整屏
  菜单。被执行的只有我们选中的那一项；扫描整屏会把"菜单里恰好有个危险选项、
  但我们选的是安全项"误判成高危，制造噪音，反而会促使使用者关掉闸门。
* **fail-closed**：既不像安全默认词、又不含风险词的，一律算 ``watch``（认不出来）。
  它在默认的 balanced 模式下只通知不拦截，在 strict 下必须授权——绝不静默放行。
* **风险词用宽松后缀匹配、安全词用整词匹配**：``delete`` 要能命中 ``deleted`` /
  ``delete_all``；而 ``no`` 绝不能被 ``nothing`` 命中。把危险选项误判成安全项
  的代价，远大于多问一次。
* **单字母不进安全词表**：confirm 型菜单的原文形如 ``Proceed? [Y/n]``，里面天然
  含有 ``Y``。若把 ``y`` 当安全词，任何确认提示都会被判成"安全"，闸门等于没有。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Callable, Sequence

# --------------------------------------------------------------------------
# 模式
# --------------------------------------------------------------------------

MODE_OFF = "off"
MODE_STRICT = "strict"
MODE_BALANCED = "balanced"
MODE_OBSERVE = "observe"
MODE_FULL = "full"

MODES: tuple[str, ...] = (MODE_OFF, MODE_STRICT, MODE_BALANCED, MODE_OBSERVE, MODE_FULL)

MODE_LABELS: dict[str, str] = {
    MODE_OFF: "关闭",
    MODE_STRICT: "严格",
    MODE_BALANCED: "平衡",
    MODE_OBSERVE: "只通知",
    MODE_FULL: "完全放行",
}

MODE_DESCRIPTIONS: dict[str, str] = {
    MODE_OFF: "不自动应答任何菜单，全部由你手动选择。",
    MODE_STRICT: "只自动放行安全默认项；认不出的与高风险的都必须你授权。",
    MODE_BALANCED: "安全默认项直接放行；认不出的只提示；高风险的必须你授权。",
    MODE_OBSERVE: "照常自动应答，但对认不出的与高风险的都发出提示，不拦截。",
    MODE_FULL: "除会话列表外全部直接放行，不提示也不拦截。",
}

DEFAULT_MODE = MODE_BALANCED


def normalize_mode(value: object) -> str:
    """把外部值收敛成合法模式；未知值回退默认模式。

    **绝不回退成 ``full``**：配置文件被手改坏时不应该把闸门整个打开。
    """
    text = str(value or "").strip().lower()
    return text if text in MODES else DEFAULT_MODE


# --------------------------------------------------------------------------
# 风险等级
# --------------------------------------------------------------------------


class Risk(str, Enum):
    """即将发送的那一项（配合提示原文）的风险等级。"""

    SAFE = "safe"
    WATCH = "watch"
    RISKY = "risky"

    @property
    def label(self) -> str:
        return {"safe": "安全默认", "watch": "待确认", "risky": "高风险"}[self.value]


# 风险词：命中即高危。宁多勿少——多问一次只是打扰，漏掉一次可能不可逆。
DEFAULT_RISK_KEYWORDS: tuple[str, ...] = (
    # 文件与目录
    "delete",
    "remove",
    "rm -rf",
    "rmdir",
    "erase",
    "wipe",
    "overwrite",
    "format",
    "uninstall",
    "destroy",
    "discard",
    # 版本控制
    "reset --hard",
    "push --force",
    "force push",
    "clean -fd",
    # 数据库
    "drop table",
    "drop database",
    "truncate",
    # 系统与权限
    "sudo",
    "chmod 777",
    "shutdown",
    "reboot",
    # 不可逆语义
    "permanently",
    "irreversible",
    # 中文
    "删除",
    "清空",
    "覆盖",
    "格式化",
    "卸载",
    "强制",
    "丢弃",
    "永久",
    "重置",
)

# 安全词：命中即认为无副作用/默认项，可静默放行。
#
# 刻意**不含单字母**（y/n）：它们会命中 ``[Y/n]`` 这类提示原文。
DEFAULT_SAFE_KEYWORDS: tuple[str, ...] = (
    "yes",
    "continue",
    "allow",
    "allow once",
    "allow for this session",
    "approve",
    "keep",
    "skip",
    "no",
    "cancel",
    "quit",
    "deny",
    "abort",
    # 中文
    "是",
    "否",
    "继续",
    "允许",
    "确定",
    "取消",
    "跳过",
    "拒绝",
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def _is_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _risk_pattern(keyword: str) -> re.Pattern[str] | None:
    """风险词的匹配式。

    起首要求非字母数字边界（避免 ``enforce`` 命中 ``force``），结尾**不限**，
    以便命中 ``deleted`` / ``delete_all`` 这类变形。中日韩文字直接子串匹配。
    """
    word = str(keyword or "").strip().lower()
    if not word:
        return None
    if _is_cjk(word):
        return re.compile(re.escape(word))
    return re.compile(r"(?<![a-z0-9])" + re.escape(word))


def _safe_pattern(keyword: str) -> re.Pattern[str] | None:
    """安全词的匹配式：ASCII 要求整词，避免 ``no`` 命中 ``nothing``。"""
    word = str(keyword or "").strip().lower()
    if not word:
        return None
    if _is_cjk(word):
        return re.compile(re.escape(word))
    return re.compile(r"(?<![a-z0-9_])" + re.escape(word) + r"(?![a-z0-9_])")


# --------------------------------------------------------------------------
# 动作
# --------------------------------------------------------------------------


class Action(str, Enum):
    """审查结论对应的动作。"""

    #: 直接发送，不打扰用户（当前行为的等价物）
    SILENT = "silent"
    #: 直接发送，但同时发系统通知 + 提示音
    NOTIFY = "notify"
    #: 不发送，必须由用户授权
    ASK = "ask"
    #: 不发送，也不打扰用户，仅记录
    BLOCK = "block"

    @property
    def writes(self) -> bool:
        """该动作是否允许把按键发给 CLI。"""
        return self in (Action.SILENT, Action.NOTIFY)

    @property
    def notifies(self) -> bool:
        """该动作是否需要触发系统通知与提示音。"""
        return self in (Action.NOTIFY, Action.ASK)


# 模式 × 风险 → 动作。
#
# ``full`` 在这里对三种风险都放行；列表菜单与预算这两条硬底线由规则链在
# 到达矩阵之前拦下，因此**即使完全放行也关不掉**——这正是原实现"跟完全
# 不限制一样"的差别所在。
_MATRIX: dict[str, dict[Risk, Action]] = {
    MODE_OFF: {Risk.SAFE: Action.BLOCK, Risk.WATCH: Action.BLOCK, Risk.RISKY: Action.BLOCK},
    MODE_STRICT: {Risk.SAFE: Action.SILENT, Risk.WATCH: Action.ASK, Risk.RISKY: Action.ASK},
    MODE_BALANCED: {Risk.SAFE: Action.SILENT, Risk.WATCH: Action.NOTIFY, Risk.RISKY: Action.ASK},
    MODE_OBSERVE: {Risk.SAFE: Action.SILENT, Risk.WATCH: Action.NOTIFY, Risk.RISKY: Action.NOTIFY},
    MODE_FULL: {Risk.SAFE: Action.SILENT, Risk.WATCH: Action.SILENT, Risk.RISKY: Action.SILENT},
}


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------


@dataclass
class PolicyConfig:
    """审查策略的全部可调项（对应 terminal_policy.json）。"""

    mode: str = DEFAULT_MODE
    #: 授权超时秒数；到期一律按"拒绝"处理，不存在超时放行。
    review_timeout_seconds: float = 60.0
    #: 自主写入预算：window 秒内最多自动应答 max_writes 次，超出即降级为手动。
    #: 人工授权不计入预算——那不是自动化，没理由被限流。
    budget_window_seconds: float = 60.0
    budget_max_writes: int = 20
    #: 通知通道开关。
    notify_system: bool = True
    notify_toast: bool = True
    window_alert: bool = True
    #: 是否允许授权弹窗抢占焦点。默认关：抢焦点很粗暴，会打断别的工作。
    steal_focus: bool = False
    #: 提示音。
    sound_enabled: bool = True
    sound_strong: bool = False
    sound_cooldown_seconds: float = 5.0
    risk_keywords: tuple[str, ...] = DEFAULT_RISK_KEYWORDS
    safe_keywords: tuple[str, ...] = DEFAULT_SAFE_KEYWORDS

    def __post_init__(self) -> None:
        self.mode = normalize_mode(self.mode)
        # 风险词表不允许为空：空表等于关掉风险判定，属于静默削弱安全边界。
        if not self.risk_keywords:
            self.risk_keywords = DEFAULT_RISK_KEYWORDS
        self.risk_keywords = tuple(str(item) for item in self.risk_keywords if str(item).strip())
        self.safe_keywords = tuple(str(item) for item in self.safe_keywords if str(item).strip())


@dataclass(frozen=True)
class AnswerRequest:
    """一次"准备替用户按键"的请求快照。

    由 manager 构造，携带判定所需的全部输入：因此 :class:`ReviewPolicy` 不需要
    回头去读会话状态，决策完全可复现、可单测。
    """

    session_id: str
    kind: str
    choices: tuple[str, ...]
    intended_index: int
    intended_payload: str
    #: 即将选中的那一项的文本。confirm 型菜单的 "是/否" 是本工具自己造的展示文案，
    #: 不是 CLI 的原文，因此那种情况下这里传空串，只靠 prompt 判定。
    intended_label: str = ""
    #: confirm 型菜单命中的原始提示行（如 ``Overwrite file? [Y/n]``）。
    prompt: str = ""
    title: str = ""
    cwd: str = ""
    command: str = ""
    screen_tail: str = ""
    attempt: int = 1
    #: 该菜单此前已被用户拒绝过。
    declined: bool = False
    #: 该菜单本次是否已经问过用户（挂在待授权期间或刚授权过）。
    #: 用于避免"按键还在写入队列里、菜单尚未从屏幕消失"时被重复询问。
    asked: bool = False
    #: 自主写入预算已耗尽。
    budget_exhausted: bool = False

    @property
    def text(self) -> str:
        """用于风险判定的文本：提示原文 + 即将选中的那一项。"""
        parts = [item.strip() for item in (self.prompt, self.intended_label) if item and item.strip()]
        return "  ".join(parts)

    @property
    def signature(self) -> tuple[str, ...]:
        """菜单签名：用于"同一菜单只处理一次"与"拒绝后不再重复提示"。"""
        return tuple(self.choices)


@dataclass(frozen=True)
class Decision:
    """审查结论。"""

    action: Action
    rule_id: str
    reason: str
    risk: Risk

    @property
    def writes(self) -> bool:
        return self.action.writes

    @property
    def notifies(self) -> bool:
        return self.action.notifies


# --------------------------------------------------------------------------
# 策略
# --------------------------------------------------------------------------

# 规则签名：拿到请求、策略与**已由矩阵算出的基础结论**，返回覆盖结论或 None。
#
# 之所以让规则看到基础结论，是因为这些规则只该"收紧"矩阵的结果，而不该凭空
# 替换它：例如预算耗尽应当阻止**自主**按键，但不该阻止"询问用户"——把高风险
# 菜单从"问你"降级成"什么都不做"，用户既没被按键也没被告知，反而更糟。
RuleFn = Callable[[AnswerRequest, "ReviewPolicy", Decision], Decision | None]


def _rule_list_menu(request: AnswerRequest, policy: "ReviewPolicy", base: Decision) -> Decision | None:
    """无编号列表菜单永不自动应答。

    这不是安全判断而是**正确性**判断：这类菜单（codex 的 resume 选择器）的
    "第一项"是某个随机的历史会话，自动选它没有任何合理语义。因此它是硬底线，
    连 ``full`` 模式也绕不过去。
    """
    if request.kind != "list":
        return None
    return Decision(Action.BLOCK, "list_menu", "列表菜单需人工挑选，不自动应答", base.risk)


def _rule_declined(request: AnswerRequest, policy: "ReviewPolicy", base: Decision) -> Decision | None:
    if not request.declined:
        return None
    return Decision(Action.BLOCK, "declined", "同一菜单此前已被你拒绝，不再重复提示", base.risk)


def _rule_already_asked(request: AnswerRequest, policy: "ReviewPolicy", base: Decision) -> Decision | None:
    """这个菜单本次已经有过结论了：**不再打扰用户，但要继续重试按键**。

    必要性：应答要经写入队列延迟约 0.25s 才发出，而轮询间隔也是 0.25s。
    没有这条规则时，菜单在屏幕上多停一拍就会再弹一次授权框。

    关键区分（早期实现把两者混为一谈，导致故障）：

    * ``ASK``：确实不该问第二遍，挂起/阻塞等待答复；
    * ``NOTIFY``：只是"别再重复通知"，**按键必须照常重试**——菜单刚出现时
      TUI 还没开始读输入，第一次应答可能被丢弃。若在这里 BLOCK，日志会显示
      "已自动应答"、菜单却永远停在屏幕上（用户报的正是这个）。
    """
    if not request.asked:
        return None
    if base.action is Action.NOTIFY:
        return Decision(
            Action.SILENT, "already_asked", "该菜单本次已通知过，继续重试应答", base.risk
        )
    if base.action is Action.ASK:
        return Decision(Action.BLOCK, "already_asked", "该菜单本次已询问过，等待你的答复", base.risk)
    return None


def _rule_budget(request: AnswerRequest, policy: "ReviewPolicy", base: Decision) -> Decision | None:
    """自主写入超预算时停手。

    只拦"本来要自己按键"的动作（SILENT / NOTIFY）。若基础结论是 ASK，说明本来
    就要问用户——这时放行询问，人工授权也不计入预算，否则预算会把用户卡死。
    """
    if not request.budget_exhausted or not base.writes:
        return None
    window = int(policy.config.budget_window_seconds)
    limit = policy.config.budget_max_writes
    return Decision(
        Action.BLOCK,
        "budget",
        f"{window} 秒内自主应答已达 {limit} 次上限，已降级为手动",
        base.risk,
    )


# 守卫规则：在矩阵结论之上依次收紧。后面的规则看到的是前面覆盖后的结论。
_GUARDS: tuple[RuleFn, ...] = (
    _rule_list_menu,
    _rule_declined,
    _rule_already_asked,
    _rule_budget,
)

# 关闭模式：不自动应答任何菜单，全部交给用户手动选择。
# 它是矩阵里的一整行，因此直接对风险求值即可，无需单独规则。
_MODE_OFF_ACTION = Action.BLOCK


class ReviewPolicy:
    """把"要不要替用户按键"变成可测的纯函数。

    无状态：预算计数、已拒绝签名等运行期状态由 manager 持有并通过
    :class:`AnswerRequest` 传入。
    """

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()
        self._risk_res = tuple(
            pattern for pattern in (_risk_pattern(item) for item in self.config.risk_keywords) if pattern
        )
        self._safe_res = tuple(
            pattern for pattern in (_safe_pattern(item) for item in self.config.safe_keywords) if pattern
        )

    @property
    def mode(self) -> str:
        return self.config.mode

    @property
    def mode_label(self) -> str:
        return MODE_LABELS.get(self.config.mode, self.config.mode)

    def set_config(self, config: PolicyConfig) -> None:
        """热更新策略（界面切换模式时调用）。"""
        self.config = config
        self._risk_res = tuple(
            pattern for pattern in (_risk_pattern(item) for item in self.config.risk_keywords) if pattern
        )
        self._safe_res = tuple(
            pattern for pattern in (_safe_pattern(item) for item in self.config.safe_keywords) if pattern
        )

    def classify(self, text: str) -> Risk:
        """判定一段文本的风险等级。

        风险**优先于**安全：``Confirm delete? [Y/n]`` 两侧都有词时必须是高危。
        """
        value = str(text or "").strip().lower()
        if not value:
            return Risk.WATCH
        for pattern in self._risk_res:
            if pattern.search(value):
                return Risk.RISKY
        for pattern in self._safe_res:
            if pattern.search(value):
                return Risk.SAFE
        return Risk.WATCH

    def evaluate(self, request: AnswerRequest, *, skip_ask: bool = False) -> Decision:
        """对一次自动应答请求给出结论。

        两步：先按"模式 × 风险"查矩阵得到基础结论，再让守卫规则依次收紧。
        守卫只做覆盖（更严格），不会凭空放宽矩阵的结果。

        ``skip_ask=True`` 表示本会话已由用户授权这类菜单：把"要求授权"直接
        降级为静默放行（用户已经表达过"这类不用再问"）。硬底线不受影响——
        列表菜单、已拒绝、预算仍由守卫规则拦下。
        """
        risk = self.classify(request.text)
        action = _MATRIX[self.config.mode][risk]
        decision = Decision(action, f"matrix_{self.config.mode}", f"{self.mode_label}模式：判定为{risk.label}", risk)
        if skip_ask and decision.action is Action.ASK:
            decision = Decision(
                Action.SILENT, "session_approved", "你已允许本会话处理此类菜单", risk
            )
        for guard in _GUARDS:
            override = guard(request, self, decision)
            if override is not None:
                decision = override
        return decision

    def describe(self) -> dict[str, object]:
        """给界面用的策略摘要。"""
        return {
            "mode": self.config.mode,
            "modeLabel": self.mode_label,
            "modeDescription": MODE_DESCRIPTIONS.get(self.config.mode, ""),
            "reviewTimeoutSeconds": self.config.review_timeout_seconds,
            "budgetWindowSeconds": self.config.budget_window_seconds,
            "budgetMaxWrites": self.config.budget_max_writes,
            "soundEnabled": self.config.sound_enabled,
            "stealFocus": self.config.steal_focus,
            "riskKeywordCount": len(self.config.risk_keywords),
            "safeKeywordCount": len(self.config.safe_keywords),
        }


__all__ = [
    "Action",
    "AnswerRequest",
    "Decision",
    "DEFAULT_MODE",
    "DEFAULT_RISK_KEYWORDS",
    "DEFAULT_SAFE_KEYWORDS",
    "MODE_BALANCED",
    "MODE_FULL",
    "MODE_LABELS",
    "MODE_OBSERVE",
    "MODE_OFF",
    "MODE_STRICT",
    "MODE_DESCRIPTIONS",
    "MODES",
    "PolicyConfig",
    "ReviewPolicy",
    "Risk",
    "normalize_mode",
]
