"""审查策略的持久化（纯逻辑，无 Qt 依赖）。

策略存在与 ``profiles.json`` 同级的独立文件 ``terminal_policy.json``：

* 不必改动 ``profiles.json`` 的结构与版本号，也就不会牵动 ``ProfileStore.load()``
  那个二十多元素的元组、``AppSession``、``SESSION_FIELDS`` 与快照层；
* 配置写坏时删掉文件即可回到默认，没有迁移风险。

**容错原则**：文件缺失、JSON 非法、字段类型不对，一律**逐字段回退到默认值**，
且默认值是 balanced——任何解析失败都不得把闸门打开成"完全放行"。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .logging_setup import get_logger
from .review import (
    DEFAULT_MODE,
    DEFAULT_RISK_KEYWORDS,
    DEFAULT_SAFE_KEYWORDS,
    PolicyConfig,
    normalize_mode,
)

log = get_logger()

POLICY_FILENAME = "terminal_policy.json"

# 数值边界。上限存在的意义是"界面填错不会把闸门变成摆设"，
# 例如把预算写成 100000 就等于取消了限流。
_TIMEOUT_MIN, _TIMEOUT_MAX = 5.0, 3600.0
_WINDOW_MIN, _WINDOW_MAX = 5.0, 3600.0
_WRITES_MIN, _WRITES_MAX = 1, 1000
_COOLDOWN_MIN, _COOLDOWN_MAX = 0.0, 300.0


def policy_path(root_dir: Path) -> Path:
    return Path(root_dir) / POLICY_FILENAME


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
    return default


def _as_float(value: Any, default: float, *, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:  # NaN
        return default
    return max(low, min(high, parsed))


def _as_int(value: Any, default: int, *, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def _as_keywords(value: Any, default: tuple[str, ...], *, fallback_on_empty: bool) -> tuple[str, ...]:
    """把配置里的词表收敛成非空字符串元组。

    ``fallback_on_empty=True`` 用于风险词表：空表等于关掉风险判定，
    属于静默削弱安全边界，因此空表回退默认而不是"就是空"。
    """
    if not isinstance(value, (list, tuple)):
        return default if fallback_on_empty else ()
    items = tuple(str(item).strip() for item in value if str(item).strip())
    if not items and fallback_on_empty:
        return default
    return items


def config_from_dict(payload: Any) -> PolicyConfig:
    """把一份（可能残缺、可能是错的）配置对象解析成策略。"""
    if not isinstance(payload, dict):
        if payload is not None:
            log.warning("审查策略不是对象，已整体回退默认值")
        return PolicyConfig()

    notify = payload.get("notify") if isinstance(payload.get("notify"), dict) else {}
    sound = payload.get("sound") if isinstance(payload.get("sound"), dict) else {}
    budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}

    return PolicyConfig(
        mode=normalize_mode(payload.get("mode", DEFAULT_MODE)),
        review_timeout_seconds=_as_float(
            payload.get("reviewTimeoutSeconds"),
            60.0,
            low=_TIMEOUT_MIN,
            high=_TIMEOUT_MAX,
        ),
        budget_window_seconds=_as_float(
            budget.get("windowSeconds"),
            60.0,
            low=_WINDOW_MIN,
            high=_WINDOW_MAX,
        ),
        budget_max_writes=_as_int(
            budget.get("maxWrites"),
            20,
            low=_WRITES_MIN,
            high=_WRITES_MAX,
        ),
        notify_system=_as_bool(notify.get("systemNotification"), True),
        notify_toast=_as_bool(notify.get("toast"), True),
        window_alert=_as_bool(notify.get("windowAlert"), True),
        steal_focus=_as_bool(notify.get("stealFocus"), False),
        sound_enabled=_as_bool(sound.get("enabled"), True),
        sound_strong=_as_bool(sound.get("strong"), False),
        sound_cooldown_seconds=_as_float(
            sound.get("cooldownSeconds"),
            5.0,
            low=_COOLDOWN_MIN,
            high=_COOLDOWN_MAX,
        ),
        risk_keywords=_as_keywords(
            payload.get("riskKeywords"), DEFAULT_RISK_KEYWORDS, fallback_on_empty=True
        ),
        safe_keywords=_as_keywords(
            payload.get("safeKeywords", payload.get("safeDefaults")),
            DEFAULT_SAFE_KEYWORDS,
            fallback_on_empty=False,
        ),
    )


def config_to_dict(config: PolicyConfig) -> dict[str, Any]:
    """序列化成稳定的 JSON 结构（字段名与界面/文档一致）。"""
    return {
        "version": 1,
        "mode": config.mode,
        "reviewTimeoutSeconds": config.review_timeout_seconds,
        "timeoutAction": "deny",
        "notify": {
            "systemNotification": config.notify_system,
            "toast": config.notify_toast,
            "windowAlert": config.window_alert,
            "stealFocus": config.steal_focus,
        },
        "sound": {
            "enabled": config.sound_enabled,
            "strong": config.sound_strong,
            "cooldownSeconds": config.sound_cooldown_seconds,
        },
        "budget": {
            "windowSeconds": config.budget_window_seconds,
            "maxWrites": config.budget_max_writes,
        },
        "riskKeywords": list(config.risk_keywords),
        "safeKeywords": list(config.safe_keywords),
    }


def load_config(root_dir: Path) -> PolicyConfig:
    """读取策略；任何异常都回退默认（balanced）。"""
    path = policy_path(root_dir)
    if not path.exists():
        return PolicyConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("审查策略读取失败，已回退默认（balanced）：%s", exc)
        return PolicyConfig()
    return config_from_dict(payload)


def save_config(root_dir: Path, config: PolicyConfig) -> None:
    """写回策略文件；失败只记录日志，不影响终端可用性。"""
    path = policy_path(root_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(config_to_dict(config), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("审查策略写入失败：%s", exc)


__all__ = [
    "POLICY_FILENAME",
    "config_from_dict",
    "config_to_dict",
    "load_config",
    "policy_path",
    "save_config",
]
