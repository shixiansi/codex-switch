"""提示音。

自动应答被拦下时用户可能没看屏幕，一声提示音比一条通知更容易把注意力拉回来。

实现选择：**标准库 winsound**，不是 QtMultimedia。原因有两条：

1. 本机装的是 ``PySide6-Essentials``，**没有 QtMultimedia**（site-packages 里
   只有 ``QtMultimedia.pyi`` 占位，既无 ``QtMultimedia.pyd`` 也无 multimedia 插件），
   所以 QSoundEffect / QMediaPlayer 全部不可用；
2. 为了"响一声"再引入 ``PySide6-Addons``（几十 MB）并改打包配置，收益极低。

``MessageBeep`` 是异步的（实测耗时 ≈0ms），可以直接在 GUI 线程调用；
``Beep`` 会阻塞（实测 150ms 阻塞 0.154s），因此"强提醒"必须放进短命线程。

非 Windows 平台或发声失败时静默跳过：**声音失败绝不能影响授权流程**。
"""

from __future__ import annotations

import sys
import threading
import time

from .logging_setup import get_logger

log = get_logger()

# 事件级别 → 系统提示音。
# 用系统声音方案（而不是自定义波形），这样自动遵守用户的音量与静音设置。
_SOUND_ASTERISK = "asterisk"
_SOUND_EXCLAMATION = "exclamation"

# 强提醒的蜂鸣参数（仅在 sound_strong=True 时使用）。
_STRONG_BEEPS = ((880, 120), (0, 60), (880, 120))


def is_supported() -> bool:
    """当前平台是否支持播放提示音。"""
    if sys.platform != "win32":
        return False
    try:
        import winsound  # noqa: F401
    except ImportError:
        return False
    return True


class SoundPlayer:
    """带冷却窗口的提示音播放器。

    冷却的意义：一串菜单同时冒出来时不应该连珠炮式地响。冷却**按事件计数**，
    而不是按重试计数——重试只是"菜单还在"的技术细节，不该重复打扰用户。
    """

    def __init__(self, cooldown_seconds: float = 5.0, *, enabled: bool = True) -> None:
        self.cooldown_seconds = float(cooldown_seconds)
        self.enabled = bool(enabled)
        #: 是否使用更醒目的自定义蜂鸣（默认关，尊重系统声音方案）。
        self.strong = False
        self._last_played_at = 0.0
        self._play_count = 0

    def configure(
        self,
        *,
        enabled: bool | None = None,
        cooldown_seconds: float | None = None,
        strong: bool | None = None,
    ) -> None:
        if enabled is not None:
            self.enabled = bool(enabled)
        if cooldown_seconds is not None:
            self.cooldown_seconds = float(cooldown_seconds)
        if strong is not None:
            self.strong = bool(strong)

    @property
    def play_count(self) -> int:
        """实际响过的次数（供测试与排查）。"""
        return self._play_count

    def play(self, *, urgent: bool, now: float | None = None) -> bool:
        """播放提示音；返回是否真的响了。

        冷却窗口内直接返回 False——调用方不需要关心，这只是防打扰。
        """
        if not self.enabled:
            return False
        if not is_supported():
            return False
        moment = time.monotonic() if now is None else now
        if self._last_played_at and moment - self._last_played_at < self.cooldown_seconds:
            return False
        self._last_played_at = moment
        self._play_count += 1
        try:
            if self.strong:
                self._play_strong()
            else:
                self._play_system(urgent=urgent)
            return True
        except Exception:  # noqa: BLE001 - 发不出声不该影响任何流程
            log.debug("提示音播放失败", exc_info=True)
            return False

    def _play_system(self, *, urgent: bool) -> None:
        import winsound

        if urgent:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        else:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)

    def _play_strong(self) -> None:
        """自定义蜂鸣序列。

        ``Beep`` 是同步阻塞的，必须放到短命线程：在 GUI 线程上把窗口卡住
        几百毫秒是不可接受的。
        """
        import winsound

        def run() -> None:
            try:
                for frequency, duration in _STRONG_BEEPS:
                    if frequency <= 0:
                        time.sleep(duration / 1000.0)
                    else:
                        winsound.Beep(frequency, duration)
            except Exception:  # noqa: BLE001
                log.debug("强提醒蜂鸣失败", exc_info=True)

        threading.Thread(target=run, daemon=True, name="terminal-beep").start()


__all__ = ["SoundPlayer", "is_supported"]
