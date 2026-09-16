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
            description: "添加常用命令或 Python 脚本，可选择打开窗口或后台运行，同一脚本同时只允许一个实例。"

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
                            badgeText: modelData.status === "idle" ? modelData.kindLabel : modelData.statusLabel
                            badgeTone: modelData.status === "idle" ? "info" : modelData.statusTone
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

                            StatusBadge {
                                text: scriptsModel.selectedDetail.statusLabel || "未运行"
                                tone: scriptsModel.selectedDetail.statusTone || "unknown"
                                showDot: scriptsModel.selectedDetail.status === "running"
                            }

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
                        text: {
                            var detail = scriptsModel.selectedDetail
                            var parts = ["运行方式：" + (detail.runModeLabel || "打开窗口")]
                            if (detail.startedAt !== "")
                                parts.push("开始：" + detail.startedAt)
                            if (detail.finishedAt !== "")
                                parts.push("结束：" + detail.finishedAt)
                            if (detail.exitCode !== undefined && detail.exitCode !== null
                                    && detail.status !== "running")
                                parts.push("退出码：" + detail.exitCode)
                            return parts.join("　·　")
                        }
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontCaption
                        elide: Text.ElideRight
                        visible: scriptsModel.selectedId !== ""
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "工作目录：" + (scriptsModel.selectedDetail.workingDir || "程序目录")
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontCaption
                        elide: Text.ElideMiddle
                        visible: scriptsModel.selectedId !== ""
                    }

                    // ---- captured output (background runs only) ----
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(120, page.height * 0.28)
                        spacing: Theme.space1
                        visible: scriptsModel.selectedId !== ""

                        Text {
                            Layout.fillWidth: true
                            text: "运行输出"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: Theme.radiusSm
                            color: Theme.surfaceAlt
                            border.width: Theme.borderWidth
                            border.color: Theme.border

                            Flickable {
                                anchors.fill: parent
                                anchors.margins: Theme.space2
                                contentWidth: width
                                contentHeight: outputText.implicitHeight
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                                Text {
                                    id: outputText
                                    width: parent.width
                                    text: {
                                        var detail = scriptsModel.selectedDetail
                                        if (detail.output !== undefined && detail.output !== "")
                                            return detail.output
                                        if (detail.runMode === "hidden")
                                            return detail.status === "idle"
                                                ? "后台运行后，输出会显示在这里。"
                                                : "（暂无输出）"
                                        return "窗口模式不记录输出，请在弹出的窗口中查看。"
                                    }
                                    color: Theme.textMuted
                                    font.pixelSize: Theme.fontCaption
                                    font.family: "Consolas, monospace"
                                    wrapMode: Text.WrapAnywhere
                                }
                            }
                        }
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
                            enabled: !app.busy && !scriptsModel.selectedDetail.running
                            onClicked: scriptsModel.run(scriptsModel.selectedDetail.id)

                            ToolTip.visible: hovered
                            ToolTip.delay: 400
                            ToolTip.text: scriptsModel.selectedDetail.running
                                ? "脚本正在运行，同一脚本同时只允许运行一个实例"
                                : "按脚本设置的方式运行（打开窗口或后台运行）"
                        }
                        AppButton {
                            text: "停止"
                            iconName: "close"
                            variant: "danger"
                            enabled: !app.busy
                            visible: scriptsModel.selectedDetail.running === true
                            onClicked: scriptsModel.stop(scriptsModel.selectedDetail.id)
                        }
                        AppButton {
                            text: "打开日志"
                            iconName: "log"
                            enabled: !app.busy && scriptsModel.selectedDetail.logPath !== ""
                            visible: scriptsModel.selectedDetail.logPath !== undefined
                                && scriptsModel.selectedDetail.logPath !== ""
                            onClicked: app.openLocalPath(scriptsModel.selectedDetail.logPath)
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
