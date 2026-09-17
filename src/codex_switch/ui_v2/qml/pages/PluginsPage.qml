import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// 插件中心: 管理已安装插件、查看权限、启用/禁用、打开插件目录。
//
// 页面只做展示与转发，不做任何文件系统操作——扫描/加载/卸载都在
// Python 侧的 codex_switch.plugins 里完成，视图模型只提供行数据。
Item {
    id: page

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space5
        spacing: Theme.space4

        SectionHeader {
            title: "插件中心"
            description: "插件可以扩展 CodexSwitch 的功能。每个插件必须声明所需权限，未声明的能力无法调用。"

            AppButton {
                text: "打开插件目录"
                iconName: "folder"
                onClicked: pluginsModel.openFolder()
            }
            AppButton {
                text: "重新扫描"
                iconName: "refresh"
                variant: "primary"
                onClicked: pluginsModel.rescan()
            }
        }

        // ---------- 加载失败/清单错误的插件 ----------
        // 单独置顶展示：坏插件必须一眼可见，否则用户只会觉得"插件没生效"。
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: issueColumn.implicitHeight + Theme.space3 * 2
            visible: pluginsModel.issueCount > 0
            radius: Theme.radius
            color: Theme.surface
            border.width: Theme.borderWidth
            border.color: Theme.danger

            ColumnLayout {
                id: issueColumn
                anchors.fill: parent
                anchors.margins: Theme.space3
                spacing: Theme.space1

                Text {
                    Layout.fillWidth: true
                    text: "有 " + pluginsModel.issueCount + " 个插件目录无法加载"
                    color: Theme.danger
                    font.pixelSize: Theme.fontSubtitle
                    font.weight: Font.DemiBold
                }

                Repeater {
                    model: pluginsModel.issues

                    delegate: Text {
                        required property var modelData
                        Layout.fillWidth: true
                        text: "· " + modelData.id + " — " + modelData.message
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontCaption
                        wrapMode: Text.Wrap
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.space4

            // ---------- 左：插件列表 ----------
            Rectangle {
                Layout.preferredWidth: 320
                Layout.fillHeight: true
                radius: Theme.radius
                color: Theme.surface
                border.width: Theme.borderWidth
                border.color: Theme.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.space3
                    spacing: Theme.space2

                    Text {
                        Layout.fillWidth: true
                        text: "已安装插件 (" + pluginsModel.count + ")"
                        color: Theme.text
                        font.pixelSize: Theme.fontSubtitle
                        font.weight: Font.DemiBold
                    }

                    EmptyState {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: pluginsModel.count === 0
                        iconName: "cube"
                        title: "还没有安装插件"
                        description: "把插件目录放入插件目录后点「重新扫描」。"
                        actionText: "打开插件目录"
                        onActionTriggered: pluginsModel.openFolder()
                    }

                    ListView {
                        id: pluginList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        visible: pluginsModel.count > 0
                        model: pluginsModel.items
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: ListRow {
                            required property var modelData

                            width: pluginList.width
                            iconName: "cube"
                            title: modelData.name
                            subtitle: "v" + modelData.version
                                + (modelData.author !== "" ? " · " + modelData.author : "")
                            badgeText: modelData.status === "ready" ? "已启用"
                                : (modelData.status === "disabled" ? "已禁用" : "错误")
                            badgeTone: modelData.status === "ready" ? "success"
                                : (modelData.status === "disabled" ? "unknown" : "danger")
                            selected: pluginsModel.selectedId === modelData.id
                            onClicked: pluginsModel.select(modelData.id)
                        }
                    }
                }
            }

            // ---------- 右：插件详情 ----------
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.radius
                color: Theme.surface
                border.width: Theme.borderWidth
                border.color: Theme.border

                EmptyState {
                    anchors.fill: parent
                    visible: pluginsModel.selectedId === ""
                    iconName: "cube"
                    title: "选择一个插件"
                    description: "左侧选择插件后可查看它的权限与状态。"
                }

                ScrollView {
                    anchors.fill: parent
                    anchors.margins: Theme.space4
                    visible: pluginsModel.selectedId !== ""
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                    ColumnLayout {
                        width: parent.width
                        spacing: Theme.space3

                        Text {
                            Layout.fillWidth: true
                            text: pluginsModel.selectedDetail.name || ""
                            color: Theme.text
                            font.pixelSize: Theme.fontTitle
                            font.weight: Font.DemiBold
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: (pluginsModel.selectedDetail.description || "") !== ""
                            text: pluginsModel.selectedDetail.description || ""
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontBody
                            wrapMode: Text.Wrap
                        }

                        DetailRow {
                            label: "标识"
                            value: pluginsModel.selectedDetail.id || ""
                            selectable: true
                        }
                        DetailRow {
                            label: "版本"
                            value: "v" + (pluginsModel.selectedDetail.version || "")
                        }
                        DetailRow {
                            label: "接口版本"
                            value: "apiVersion " + (pluginsModel.selectedDetail.apiVersion || "")
                        }
                        DetailRow {
                            label: "位置"
                            value: pluginsModel.selectedDetail.path || ""
                            tone: "muted"
                            selectable: true
                            wrap: true
                        }
                        DetailRow {
                            label: "来源"
                            value: pluginsModel.selectedDetail.builtin ? "内置" : "用户安装"
                        }

                        // 错误信息：插件处于错误态时必须显示原因。
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: errorText.implicitHeight + Theme.space3 * 2
                            visible: (pluginsModel.selectedDetail.error || "") !== ""
                            radius: Theme.radiusSm
                            color: Theme.surfaceAlt
                            border.width: Theme.borderWidth
                            border.color: Theme.danger

                            Text {
                                id: errorText
                                anchors.fill: parent
                                anchors.margins: Theme.space3
                                text: pluginsModel.selectedDetail.error || ""
                                color: Theme.danger
                                font.pixelSize: Theme.fontCaption
                                wrapMode: Text.Wrap
                            }
                        }

                        // ---- 权限 ----
                        Text {
                            Layout.fillWidth: true
                            Layout.topMargin: Theme.space2
                            text: "权限"
                            color: Theme.text
                            font.pixelSize: Theme.fontSubtitle
                            font.weight: Font.DemiBold
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: (pluginsModel.selectedDetail.permissions || []).length === 0
                            text: "该插件未申请任何权限。"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                        }

                        Repeater {
                            model: pluginsModel.selectedDetail.permissions || []

                            delegate: RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: Theme.space2

                                StatusBadge {
                                    text: modelData.name
                                    tone: "info"
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.label
                                    color: Theme.textMuted
                                    font.pixelSize: Theme.fontCaption
                                }
                            }
                        }

                        // ---- 操作 ----
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.topMargin: Theme.space3
                            spacing: Theme.space2

                            AppButton {
                                text: pluginsModel.selectedDetail.enabled ? "禁用" : "启用"
                                iconName: pluginsModel.selectedDetail.enabled ? "close" : "check"
                                variant: pluginsModel.selectedDetail.enabled ? "ghost" : "primary"
                                enabled: (pluginsModel.selectedDetail.id || "") !== ""
                                onClicked: pluginsModel.setEnabled(
                                    pluginsModel.selectedDetail.id,
                                    !pluginsModel.selectedDetail.enabled)
                            }
                        }

                        // ---- 插件声明的动作 ----
                        Text {
                            Layout.fillWidth: true
                            Layout.topMargin: Theme.space2
                            visible: (pluginsModel.selectedDetail.actions || []).length > 0
                            text: "可用动作"
                            color: Theme.text
                            font.pixelSize: Theme.fontSubtitle
                            font.weight: Font.DemiBold
                        }

                        Repeater {
                            model: pluginsModel.selectedDetail.actions || []

                            delegate: RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: Theme.space2

                                AppButton {
                                    text: modelData.label
                                    variant: "ghost"
                                    enabled: pluginsModel.selectedDetail.loaded === true
                                        && pluginsModel.selectedDetail.enabled === true
                                    onClicked: pluginsModel.runAction(
                                        pluginsModel.selectedDetail.id, modelData.key)
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.description || ""
                                    color: Theme.textMuted
                                    font.pixelSize: Theme.fontCaption
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
