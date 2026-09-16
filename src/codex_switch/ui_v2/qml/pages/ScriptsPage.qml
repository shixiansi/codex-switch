import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// 脚本中心: 添加、运行、修改自定义脚本。
Item {
    id: page

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space5
        spacing: Theme.space4

        SectionHeader {
            title: "脚本中心"
            description: "添加常用命令或 Python 脚本，一键在新窗口中运行。"

            AppButton {
                text: "刷新"
                iconName: "refresh"
                enabled: !app.busy
                onClicked: app.refreshAll()
            }
            AppButton {
                text: "新增脚本"
                iconName: "plus"
                variant: "primary"
                onClicked: scriptsModel.beginCreate()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.space4

            // ---------- left: script list ----------
            Rectangle {
                Layout.preferredWidth: 300
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
                        text: "脚本列表 (" + scriptsModel.count + ")"
                        color: Theme.text
                        font.pixelSize: Theme.fontSubtitle
                        font.weight: Font.DemiBold
                    }

                    EmptyState {
                        Layout.fillWidth: true
                        visible: scriptsModel.count === 0
                        iconName: "terminal"
                        title: "还没有脚本"
                        description: "新增脚本后即可在此运行与修改。"
                        actionText: "新增脚本"
                        onActionTriggered: scriptsModel.beginCreate()
                    }

                    ListView {
                        id: scriptList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        visible: scriptsModel.count > 0
                        model: scriptsModel.items
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: ListRow {
                            required property var modelData

                            width: scriptList.width
                            iconName: "terminal"
                            title: modelData.name
                            subtitle: modelData.workingDir !== ""
                                ? modelData.workingDir : "默认工作目录"
                            badgeText: modelData.kindLabel
                            badgeTone: "info"
                            selected: scriptsModel.selectedId === modelData.id
                            onClicked: scriptsModel.select(modelData.id)
                        }
                    }
                }
            }

            // ---------- right: detail + actions ----------
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.radius
                color: Theme.surface
                border.width: Theme.borderWidth
                border.color: Theme.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.space3
                    spacing: Theme.space3

                    // ---- header ----
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        visible: scriptsModel.selectedId !== ""

                        Text {
                            Layout.fillWidth: true
                            text: scriptsModel.selectedDetail.name || ""
                            color: Theme.text
                            font.pixelSize: Theme.fontTitle
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.space2

                            Rectangle {
                                radius: Theme.radiusSm
                                color: Theme.surfaceAlt
                                implicitWidth: kindLabel.implicitWidth + Theme.space3
                                implicitHeight: kindLabel.implicitHeight + Theme.space1

                                Text {
                                    id: kindLabel
                                    anchors.centerIn: parent
                                    text: scriptsModel.selectedDetail.kindLabel || ""
                                    color: Theme.textMuted
                                    font.pixelSize: Theme.fontCaption
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: scriptsModel.selectedDetail.description || ""
                                color: Theme.textMuted
                                font.pixelSize: Theme.fontCaption
                                elide: Text.ElideRight
                                visible: scriptsModel.selectedDetail.description !== ""
                            }
                        }
                    }

                    EmptyState {
                        Layout.fillWidth: true
                        visible: scriptsModel.selectedId === ""
                        iconName: "terminal"
                        title: "未选择脚本"
                        description: "选择左侧脚本后可运行、修改或删除。"
                    }

                    // ---- content preview ----
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: Theme.radiusSm
                        color: Theme.surfaceAlt
                        border.width: Theme.borderWidth
                        border.color: Theme.border
                        visible: scriptsModel.selectedId !== ""

                        Flickable {
                            anchors.fill: parent
                            anchors.margins: Theme.space2
                            contentWidth: width
                            contentHeight: scriptContent.implicitHeight
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                            Text {
                                id: scriptContent
                                width: parent.width
                                text: scriptsModel.selectedDetail.content || ""
                                color: Theme.text
                                font.pixelSize: Theme.fontBody
                                font.family: "Consolas, monospace"
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "工作目录：" + (scriptsModel.selectedDetail.workingDir || "程序目录")
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontCaption
                        elide: Text.ElideMiddle
                        visible: scriptsModel.selectedId !== ""
                    }

                    // ---- actions ----
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2
                        visible: scriptsModel.selectedId !== ""

                        AppButton {
                            text: "运行脚本"
                            iconName: "terminal"
                            variant: "primary"
                            enabled: !app.busy
                            onClicked: scriptsModel.run(scriptsModel.selectedDetail.id)

                            ToolTip.visible: hovered
                            ToolTip.delay: 400
                            ToolTip.text: "在新窗口中运行，运行结束后窗口保持打开"
                        }
                        AppButton {
                            text: "修改"
                            iconName: "settings"
                            enabled: !app.busy
                            onClicked: scriptsModel.beginEdit(scriptsModel.selectedDetail.id)
                        }
                        AppButton {
                            text: "删除"
                            iconName: "close"
                            variant: "danger"
                            enabled: !app.busy
                            onClicked: scriptsModel.remove(scriptsModel.selectedDetail.id)
                        }
                        Item { Layout.fillWidth: true }
                    }
                }
            }
        }
    }
}
