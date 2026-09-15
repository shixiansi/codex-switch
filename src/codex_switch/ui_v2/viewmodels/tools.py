from __future__ import annotations

from typing import Any

from ..qt_compat import Property, Signal, Slot
from .base import SnapshotViewModel


class ToolsViewModel(SnapshotViewModel):
    """配置中心扩展: model batch testing, account pool, MCP and Skills."""

    chatChanged = Signal()
    batchChanged = Signal()
    poolChanged = Signal()
    mcpChanged = Signal()
    skillsChanged = Signal()
    formChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        self._chat: dict[str, Any] = {}
        self._batch: dict[str, Any] = {}
        self._pool: dict[str, Any] = {}
        self._poolGroups: list[dict[str, Any]] = []
        self._poolChannels: list[dict[str, Any]] = []
        self._mcp: list[dict[str, Any]] = []
        self._mcpDetail: dict[str, Any] = {}
        self._skillGroups: list[dict[str, Any]] = []
        self._skillRepos: list[dict[str, Any]] = []
        self._form: list[dict[str, Any]] = []
        self._formTitle = ""
        super().__init__(self._build_items, parent)

    # -- properties ------------------------------------------------------
    @Property("QVariantMap", notify=chatChanged)
    def chat(self) -> dict[str, Any]:
        return dict(self._chat)

    @Property("QVariantMap", notify=batchChanged)
    def batch(self) -> dict[str, Any]:
        return dict(self._batch)

    @Property("QVariantMap", notify=poolChanged)
    def accountPool(self) -> dict[str, Any]:
        return dict(self._pool)

    @Property("QVariantList", notify=poolChanged)
    def poolGroups(self) -> list[dict[str, Any]]:
        return list(self._poolGroups)

    @Property("QVariantList", notify=poolChanged)
    def poolChannels(self) -> list[dict[str, Any]]:
        return list(self._poolChannels)

    @Property("QVariantList", notify=mcpChanged)
    def mcpServers(self) -> list[dict[str, Any]]:
        return list(self._mcp)

    @Property("QVariantMap", notify=mcpChanged)
    def mcpDetail(self) -> dict[str, Any]:
        return dict(self._mcpDetail)

    @Property(str, notify=mcpChanged)
    def selectedMcpName(self) -> str:
        """Name of the MCP server the preview panel is showing."""
        return str(self._mcpDetail.get("name") or "")

    @Property("QVariantList", notify=skillsChanged)
    def skillGroups(self) -> list[dict[str, Any]]:
        return list(self._skillGroups)

    @Property("QVariantList", notify=skillsChanged)
    def skillRepos(self) -> list[dict[str, Any]]:
        return list(self._skillRepos)

    @Property("QVariantList", notify=formChanged)
    def formFields(self) -> list[dict[str, Any]]:
        return list(self._form)

    @Property(str, notify=formChanged)
    def formTitle(self) -> str:
        return self._formTitle

    @Property("QVariantList", notify=batchChanged)
    def batchProfiles(self) -> list[dict[str, Any]]:
        return list(self._controller.snapshot().get("profiles") or [])

    # -- building --------------------------------------------------------
    def _build_items(self) -> list[dict[str, Any]]:
        state = dict(self._controller.snapshot() or {})

        chat = dict(state.get("chat") or {})
        if chat != self._chat:
            self._chat = chat
            self.chatChanged.emit()

        batch = dict(state.get("model_batch") or {})
        if batch != self._batch:
            self._batch = batch
            self.batchChanged.emit()

        pool = dict(state.get("account_pool") or {})
        groups = list(state.get("account_pool_groups") or [])
        channels = list(state.get("account_pool_channels") or [])
        if (pool, groups, channels) != (self._pool, self._poolGroups, self._poolChannels):
            self._pool, self._poolGroups, self._poolChannels = pool, groups, channels
            self.poolChanged.emit()

        mcp = list(state.get("mcp_servers") or [])
        mcp_detail = dict(state.get("mcp_detail") or {})
        if (mcp, mcp_detail) != (self._mcp, self._mcpDetail):
            self._mcp, self._mcpDetail = mcp, mcp_detail
            self.mcpChanged.emit()

        groups_rows = list(state.get("skill_groups") or [])
        repos = list(state.get("skill_repos") or [])
        if (groups_rows, repos) != (self._skillGroups, self._skillRepos):
            self._skillGroups, self._skillRepos = groups_rows, repos
            self.skillsChanged.emit()

        return [
            {"key": "models", "label": "模型测试", "count": len(batch.get("results") or []),
             "available": bool(batch.get("exists"))},
            {"key": "pool", "label": "号池渠道", "count": int(pool.get("totalChannels") or 0),
             "available": True},
            {"key": "mcp", "label": "MCP 服务", "count": len(mcp), "available": True},
            {"key": "skills", "label": "Skills 组", "count": len(groups_rows), "available": True},
        ]

    # -- model test / chat ------------------------------------------------
    @Slot(str)
    def selectBatchProfile(self, profile_id: str) -> None:
        self._controller.selectProfile(str(profile_id))

    @Slot()
    def runBatchTest(self) -> None:
        self._controller.runModelBatch()

    @Slot()
    def cancelBatchTest(self) -> None:
        self._controller.cancelModelBatch()

    @Slot(str, str, str)
    def sendChat(self, prompt: str, model: str = "", wire_api: str = "") -> None:
        self._controller.sendChat(str(prompt), str(model), str(wire_api))

    @Slot()
    def clearChat(self) -> None:
        self._controller.clearChat()

    # -- account pool -----------------------------------------------------
    @Slot(str)
    def selectPoolGroup(self, group_id: str) -> None:
        self._controller.selectPoolGroup(str(group_id))

    @Slot()
    def beginCreatePoolGroup(self) -> None:
        self._form = self._controller.poolGroupForm("")
        self._formTitle = "新增号池组"
        self.formChanged.emit()
        self._controller.openDrawer("pool-group-form")

    @Slot(str)
    def beginEditPoolGroup(self, group_id: str) -> None:
        self._form = self._controller.poolGroupForm(str(group_id))
        if not self._form:
            self.report_error("号池组不存在。")
            return
        self._formTitle = "编辑号池组"
        self.formChanged.emit()
        self._controller.openDrawer("pool-group-form")

    @Slot("QVariantMap")
    def submitPoolGroupForm(self, payload) -> None:
        self._controller.savePoolGroupForm(dict(payload or {}))

    @Slot(str)
    def removePoolGroup(self, group_id: str) -> None:
        self._controller.deletePoolGroup(str(group_id))

    @Slot()
    def beginCreatePoolChannel(self) -> None:
        self._form = self._controller.poolChannelForm("")
        self._formTitle = "新增号池渠道"
        self.formChanged.emit()
        self._controller.openDrawer("pool-channel-form")

    @Slot(str)
    def beginEditPoolChannel(self, channel_id: str) -> None:
        self._form = self._controller.poolChannelForm("", str(channel_id))
        if not self._form:
            self.report_error("号池渠道不存在。")
            return
        self._formTitle = "编辑号池渠道"
        self.formChanged.emit()
        self._controller.openDrawer("pool-channel-form")

    @Slot("QVariantMap")
    def submitPoolChannelForm(self, payload) -> None:
        self._controller.savePoolChannelForm(dict(payload or {}))

    @Slot(str)
    def removePoolChannel(self, channel_id: str) -> None:
        self._controller.deletePoolChannel(str(channel_id))

    @Slot(str)
    def testPoolChannel(self, channel_id: str) -> None:
        self._controller.testPoolChannel(str(channel_id))

    @Slot()
    def testAllPoolChannels(self) -> None:
        self._controller.testAllPoolChannels()

    # -- MCP ---------------------------------------------------------------
    @Slot(str)
    def selectMcpServer(self, name: str) -> None:
        self._controller.selectMcpServer(str(name))

    @Slot()
    def beginCreateMcp(self) -> None:
        self._form = self._controller.mcpForm("")
        self._formTitle = "新增 MCP 服务"
        self.formChanged.emit()
        self._controller.openDrawer("mcp-form")

    @Slot(str)
    def beginEditMcp(self, name: str) -> None:
        self._form = self._controller.mcpForm(str(name))
        if not self._form:
            self.report_error("MCP 服务不存在。")
            return
        self._formTitle = "编辑 MCP 服务"
        self.formChanged.emit()
        self._controller.openDrawer("mcp-form")

    @Slot("QVariantMap")
    def submitMcpForm(self, payload) -> None:
        self._controller.saveMcpForm(dict(payload or {}))

    @Slot(str)
    def removeMcp(self, name: str) -> None:
        self._controller.deleteMcpServer(str(name))

    @Slot()
    def restoreDefaultMcp(self) -> None:
        self._controller.restoreDefaultMcp()

    # -- Skills ------------------------------------------------------------
    @Slot()
    def beginCreateSkillGroup(self) -> None:
        self._form = self._controller.skillGroupForm("")
        self._formTitle = "新增 Skills 组"
        self.formChanged.emit()
        self._controller.openDrawer("skill-group-form")

    @Slot(str)
    def beginEditSkillGroup(self, group_id: str) -> None:
        self._form = self._controller.skillGroupForm(str(group_id))
        if not self._form:
            self.report_error("Skills 组不存在。")
            return
        self._formTitle = "编辑 Skills 组"
        self.formChanged.emit()
        self._controller.openDrawer("skill-group-form")

    @Slot("QVariantMap")
    def submitSkillGroupForm(self, payload) -> None:
        self._controller.saveSkillGroupForm(dict(payload or {}))

    @Slot(str)
    def removeSkillGroup(self, group_id: str) -> None:
        self._controller.deleteSkillGroup(str(group_id))

    @Slot(str)
    def beginCreateSkill(self, group_id: str) -> None:
        self._form = self._controller.skillForm(str(group_id), "")
        self._formTitle = "新增 Skill"
        self.formChanged.emit()
        self._controller.openDrawer("skill-form")

    @Slot(str, str)
    def beginEditSkill(self, group_id: str, skill_id: str) -> None:
        self._form = self._controller.skillForm(str(group_id), str(skill_id))
        if not self._form:
            self.report_error("Skill 不存在。")
            return
        self._formTitle = "编辑 Skill"
        self.formChanged.emit()
        self._controller.openDrawer("skill-form")

    @Slot("QVariantMap")
    def submitSkillForm(self, payload) -> None:
        self._controller.saveSkillForm(dict(payload or {}))

    @Slot(str, str)
    def removeSkill(self, group_id: str, skill_id: str) -> None:
        self._controller.deleteSkill(str(group_id), str(skill_id))

    @Slot()
    def beginCreateSkillRepo(self) -> None:
        self._form = self._controller.skillRepoForm("")
        self._formTitle = "新增 Skills 仓库"
        self.formChanged.emit()
        self._controller.openDrawer("skill-repo-form")

    @Slot(str)
    def beginEditSkillRepo(self, repo_id: str) -> None:
        self._form = self._controller.skillRepoForm(str(repo_id))
        if not self._form:
            self.report_error("Skills 仓库不存在。")
            return
        self._formTitle = "编辑 Skills 仓库"
        self.formChanged.emit()
        self._controller.openDrawer("skill-repo-form")

    @Slot("QVariantMap")
    def submitSkillRepoForm(self, payload) -> None:
        self._controller.saveSkillRepoForm(dict(payload or {}))

    @Slot(str)
    def removeSkillRepo(self, repo_id: str) -> None:
        self._controller.deleteSkillRepo(str(repo_id))

    @Slot(str)
    def installSkillRepo(self, repo_id: str) -> None:
        self._controller.installSkillRepo(str(repo_id))


__all__ = ["ToolsViewModel"]
