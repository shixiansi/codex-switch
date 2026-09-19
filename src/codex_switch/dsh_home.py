"""DSH harness home 的解析（唯一实现）。

DSH 自己按 ``DSH_HOME`` > ``~/.dsh`` 的优先级决定 harness home，所有用户数据
（``settings.yaml``、``sessions/``、``profiles/``）都在这一个根下。CodexSwitch
里有两处需要这个规则：CodeBuddy 账号快照，以及 DSH 多开。

放在独立模块而不是各自复制一份：路径解析一旦有两份实现，"哪一份才是对的"
就会成为排查问题时的额外噪声（DRY）。本模块**不依赖 Qt，也不依赖任何业务
模块**，因此插件核心逻辑可以在没有 Qt 的环境里导入。
"""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_HOME_DIR_NAME = ".dsh"


def resolve_home() -> Path:
    """按 DSH 自己的优先级解析 harness home：``DSH_HOME`` > ``~/.dsh``。

    每次调用都重新读环境变量，而不是在导入时定好：测试与命令行工具会在
    运行期切换 ``DSH_HOME``。
    """
    override = os.environ.get("DSH_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_HOME_DIR_NAME


__all__ = ["DEFAULT_HOME_DIR_NAME", "resolve_home"]
