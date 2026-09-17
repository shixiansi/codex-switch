"""CodeBuddy 多账号插件。

为 DSH 的 CodeBuddy 插件（``@shatyuka/dsh-llm-codebuddy``）维护一个账号快照库，
让用户可以在多个账号之间切换。

设计要点
--------
1. **不改动插件源码**。快照库放在 ``~/.dsh/codebuddy-accounts/``，切换时
   只是原子地覆写 ``~/.dsh/codebuddy-auth.json``。CodeBuddy 插件升级、
   重装都不会影响这个目录。
2. **复用 CLI 的核心逻辑**。账号校验、快照读写、切换时机与命令行工具
   完全共用 ``codex_switch.codebuddy_core``，不存在第二套实现。
3. **遵守插件权限**。本插件声明的权限就是它实际用到的：
   ``fs:read`` / ``fs:write``（读写凭据与快照）、``action:invoke``、
   ``snapshot:read``。它不执行外部命令，也不联网。
"""

from __future__ import annotations

from pathlib import Path

from codex_switch import codebuddy_core as core


class CodeBuddyAccountsPlugin:
    """插件实例：持有宿主 API，暴露给页面调用的动作。"""

    def __init__(self, api) -> None:
        self.api = api
        self._store = core.SnapshotStore(core.resolve_store_dir())

    # -- 只读状态 --------------------------------------------------------
    def accounts(self) -> list[dict]:
        """列出全部账号快照，并标注当前生效的那个。"""
        rows = self._store.rows()
        # 页面用固定字段渲染，这里补齐展示用的文案，避免 QML 里堆逻辑。
        for row in rows:
            if row["broken"]:
                row["statusLabel"] = "快照损坏"
                row["statusTone"] = "danger"
            elif row["refreshExpired"]:
                row["statusLabel"] = "需重新登录"
                row["statusTone"] = "warning"
            else:
                row["statusLabel"] = "可用"
                row["statusTone"] = "success"
            row["currentLabel"] = "当前" if row["current"] else ""
        return rows

    def current(self) -> dict:
        """当前生效账号的信息；尚未登录时返回空。"""
        try:
            credential = core.load_credential_file(core.resolve_auth_path())
        except core.ToolError as error:
            return {"available": False, "error": str(error)}
        info = core.describe_credential(credential)
        return {
            "available": True,
            "nickname": info["nickname"],
            "uid": info["uid"],
            "uidShort": info["uid"][:8],
            "domain": info["domain"],
            "refreshExpiresLabel": info["refresh_expires_label"],
            "refreshExpired": info["refresh_expired"],
            "error": "",
        }

    def status(self) -> dict:
        """插件整体状态，供页面顶部展示。"""
        store_exists = self._store.root.is_dir()
        return {
            "authPath": str(core.resolve_auth_path()),
            "storeDir": str(self._store.root),
            "storeReady": store_exists,
            "count": len(self._store.list_names()),
            "current": self.current(),
            "dshHome": str(core.resolve_home()),
        }

    # -- 动作 ------------------------------------------------------------
    def switch(self, key: str) -> dict:
        """切换到指定账号（序号 / 快照名 / 昵称）。"""
        try:
            result = core.switch_to(str(key))
        except core.ToolError as error:
            return {"ok": False, "message": str(error)}
        detail = dict(result.detail)
        detail["ok"] = True
        # 明确告诉用户什么时候生效，否则会以为切换没成功。
        detail["message"] = (
            f"{result.message}。若 DSH 仍显示旧账号，重启 DSH 即可生效。"
        )
        return detail

    def save_current(self, label: str = "") -> dict:
        """把当前生效的凭据存为快照。"""
        try:
            result = core.save_current(str(label or "").strip())
        except core.ToolError as error:
            return {"ok": False, "message": str(error)}
        detail = dict(result.detail)
        detail["ok"] = True
        detail["message"] = result.message
        return detail

    def remove(self, key: str) -> dict:
        """删除一个快照。"""
        try:
            name = self._store.resolve(str(key))
            credential = self._store.read(name)
            info = core.describe_credential(credential)
            self._store.remove(name)
        except core.ToolError as error:
            return {"ok": False, "message": str(error)}
        return {
            "ok": True,
            "message": f"已删除快照：{info['nickname']}（{info['uid'][:8]}）",
        }

    def import_files(self, paths: list) -> dict:
        """导入若干个凭据文件（页面通过文件选择器拿到路径后调用）。

        与 ``import_directory`` 的区别：那个收一个目录、由插件自己遍历；
        这个直接收文件列表，因为图形界面的文件选择器允许用户精确挑选，
        也允许选中位于不同目录的多个文件。
        """
        candidates: list[Path] = []
        for item in paths or []:
            text = str(item or "").strip()
            if not text:
                continue
            path = Path(text).expanduser()
            if path.is_dir():
                # 用户选的可能是目录（不同对话框的返回值不一样），
                # 那就按目录展开，行为与 import_directory 一致。
                try:
                    candidates.extend(core.collect_import_files(path))
                except core.ToolError:
                    continue
            elif path.is_file():
                candidates.append(path)

        if not candidates:
            return {"ok": False, "message": "没有选中可导入的凭据文件。"}

        outcome = core.import_files(candidates)
        return self._import_outcome(outcome)

    def import_directory(self, directory: str) -> dict:
        """从一个目录批量导入凭据文件（支持 .json 与 codebuddy2api 的 .info）。"""
        path = Path(str(directory)).expanduser()
        try:
            targets = core.collect_import_files(path)
        except core.ToolError as error:
            return {"ok": False, "message": str(error)}
        if not targets:
            return {
                "ok": False,
                "message": f"{path} 下没有可导入的凭据文件（支持 .json 与 .info）。",
            }
        return self._import_outcome(core.import_files(targets))

    @staticmethod
    def _import_outcome(outcome: dict) -> dict:
        """把导入结果整理成页面统一消费的形状。

        失败项必须逐个带出来：只报"跳过 N 个"会让用户不知道该修哪个文件。
        """
        parts: list[str] = []
        if outcome["imported"]:
            parts.append(f"已导入 {len(outcome['imported'])} 个：" + "、".join(outcome["imported"]))
        if outcome["failed"]:
            parts.append(f"跳过 {len(outcome['failed'])} 个")
        return {
            "ok": bool(outcome["imported"]),
            "message": "；".join(parts) or "没有可导入的文件。",
            "imported": outcome["imported"],
            "failed": outcome["failed"],
        }

    # -- 宿主动作入口 ----------------------------------------------------
    def run_action(self, action_key: str) -> str:
        """插件声明的动作入口，由插件中心调用。"""
        if action_key == "refresh":
            state = self.status()
            return f"当前 {state['count']} 个账号快照，生效账号：{state['current'].get('nickname', '未知')}。"
        return f"未知动作：{action_key}"


def load(api):
    """插件入口：宿主加载插件时调用，返回插件实例。"""
    api.log("CodeBuddy 多账号插件已加载。")
    return CodeBuddyAccountsPlugin(api)
