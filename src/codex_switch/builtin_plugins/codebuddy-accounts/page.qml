import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// CodeBuddy 多账号插件页面。
//
// 由插件中心的插件宿主控件动态加载，因此这里不能用任何编译期才存在的
// 单例或上下文属性——所有数据都通过 `pluginRoot.instance` 拿。
Item {
    id: page

    // 宿主注入的调用桥（PluginCallBridge，是一个真正的 QObject）。
    // 为 null 表示插件未加载，页面显示占位提示。
    //
    // 注意：这里拿到的是宿主包装后的桥，不是插件的 Python 对象本身——
    // QML 无法对 QVariant 包装的普通对象调用方法。
    property var instance: null

    // 每次切到本页或账号变动后重新拉取，保证显示的是磁盘上的真实状态。
    property var accounts: []
    property var status: ({})
    property var current: ({})
    property string message: ""
    property string messageTone: ""

    function reload() {
        if (!instance) return
        status = instance.status()
        current = status.current || {}
        accounts = instance.accounts()
    }

    function notify(result) {
        message = (result && result.message) ? result.message : ""
        messageTone = (result && result.ok) ? "success" : "danger"
        reload()
    }

    // instance 可能是创建后才注入的（宿主先建页面、插件后加载完），
    // 所以两个时机都要拉一次数据，只在 onCompleted 里读会拿到空列表。
    onInstanceChanged: if (instance) reload()
    Component.onCompleted: if (instance) reload()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space5
        spacing: Theme.space4

        SectionHeader {
            title: "CodeBuddy 多账号"
            description: "在多个 CodeBuddy 账号之间切换。快照存在凭据文件之外，不改动 DSH 插件本身，插件升级不会丢失账号。"

            AppButton {
                text: "刷新"
                iconName: "refresh"
                enabled: page.instance !== null
                onClicked: page.reload()
            }
            AppButton {
                text: "保存当前账号"
                iconName: "plus"
                variant: "primary"
                enabled: page.instance !== null && page.current.available === true
                onClicked: page.notify(page.instance.save_current(""))
            }
        }

        // ---------- 当前账号 ----------
        // AppCard 的默认属性 content 会把子项放进它内部的 ColumnLayout，
        // 所以这里直接给子项加 Layout.* 属性，不要再嵌一层带 anchors 的布局。
        AppCard {
            Layout.fillWidth: true
            title: "当前生效账号"

            Text {
                Layout.fillWidth: true
                visible: page.current.available !== true
                text: page.current.error
                    ? "读取当前凭据失败：" + page.current.error
                    : "尚未登录 CodeBuddy。"
                color: Theme.textMuted
                font.pixelSize: Theme.fontBody
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                visible: page.current.available === true
                spacing: Theme.space3

                Text {
                    text: page.current.nickname || ""
                    color: Theme.text
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                }
                StatusBadge {
                    text: page.current.uidShort || ""
                    tone: "info"
                }
                StatusBadge {
                    visible: page.current.refreshExpired === true
                    text: "需重新登录"
                    tone: "warning"
                }
                Item { Layout.fillWidth: true }
            }

            DetailRow {
                Layout.fillWidth: true
                visible: page.current.available === true
                label: "域名"
                value: page.current.domain || ""
            }
            DetailRow {
                Layout.fillWidth: true
                visible: page.current.available === true
                label: "刷新令牌到期"
                value: page.current.refreshExpiresLabel || ""
                tone: page.current.refreshExpired === true ? "danger" : ""
            }
        }

        // ---------- 操作结果提示 ----------
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: messageText.implicitHeight + Theme.space3 * 2
            visible: page.message !== ""
            radius: Theme.radiusSm
            color: Theme.surfaceAlt
            border.width: Theme.borderWidth
            border.color: page.messageTone === "success" ? Theme.accent : Theme.danger

            Text {
                id: messageText
                anchors.fill: parent
                anchors.margins: Theme.space3
                text: page.message
                color: page.messageTone === "success" ? Theme.text : Theme.danger
                font.pixelSize: Theme.fontCaption
                wrapMode: Text.Wrap
            }
        }

        // ---------- 账号列表 ----------
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
                spacing: Theme.space2

                Text {
                    Layout.fillWidth: true
                    text: "账号快照 (" + page.accounts.length + ")"
                    color: Theme.text
                    font.pixelSize: Theme.fontSubtitle
                    font.weight: Font.DemiBold
                }

                EmptyState {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: page.accounts.length === 0
                    iconName: "profile"
                    title: "还没有账号快照"
                    description: "先登录一个 CodeBuddy 账号，再点「保存当前账号」把它存下来，之后就能在多个账号间切换。"
                }

                ListView {
                    id: accountList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    visible: page.accounts.length > 0
                    model: page.accounts
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        required property var modelData
                        width: accountList.width
                        implicitHeight: rowLayout.implicitHeight + Theme.space3 * 2
                        radius: Theme.radiusSm
                        color: modelData.current ? Theme.surfaceAlt : "transparent"

                        RowLayout {
                            id: rowLayout
                            anchors.fill: parent
                            anchors.margins: Theme.space3
                            spacing: Theme.space3

                            Text {
                                text: modelData.seq
                                color: Theme.textMuted
                                font.pixelSize: Theme.fontCaption
                                Layout.preferredWidth: 24
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                RowLayout {
                                    spacing: Theme.space2
                                    Text {
                                        text: modelData.nickname
                                        color: Theme.text
                                        font.pixelSize: Theme.fontBody
                                        font.weight: Font.DemiBold
                                    }
                                    StatusBadge {
                                        visible: modelData.current === true
                                        text: "当前"
                                        tone: "success"
                                    }
                                    StatusBadge {
                                        text: modelData.statusLabel
                                        tone: modelData.statusTone
                                    }
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.broken
                                        ? modelData.error
                                        : (modelData.uidShort + " · " + modelData.domain
                                           + " · 到期 " + modelData.refreshExpiresLabel)
                                    color: Theme.textMuted
                                    font.pixelSize: Theme.fontCaption
                                    elide: Text.ElideRight
                                }
                            }

                            AppButton {
                                text: "切换"
                                variant: "primary"
                                // 已经是当前账号就没必要再切；坏快照也不能切。
                                enabled: page.instance !== null
                                    && modelData.current !== true
                                    && modelData.broken !== true
                                onClicked: page.notify(page.instance.switch(modelData.name))
                            }
                        }
                    }
                }
            }
        }
    }
}
