import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
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

    // ---- DSH 多开适配：CodeBuddy 凭据是按 harness home 各存一份的，
    // 所以每个独立实例（各自 DSH_HOME）都有自己当前登录的账号。 ----
    property var environments: []
    // 当前正在操作的环境 id；空串表示共用的 ~/.dsh。
    property string activeTarget: ""

    function reload() {
        if (!instance) return
        // 先取环境列表：目标可能因为实例被删而消失，需回退到共用环境。
        environments = instance.environments()
        if (activeTarget !== "" && !hasTarget(activeTarget))
            activeTarget = ""
        status = instance.status_of(activeTarget)
        current = status.current || {}
        accounts = instance.accounts_of(activeTarget)
    }

    function hasTarget(id) {
        for (var i = 0; i < environments.length; i++) {
            if (environments[i].id === id) return true
        }
        return false
    }

    function activeLabel() {
        for (var i = 0; i < environments.length; i++) {
            if (environments[i].id === activeTarget) return environments[i].label
        }
        return environments.length > 0 ? environments[0].label : ""
    }

    function selectTarget(id) {
        if (id === activeTarget) return
        activeTarget = id
        message = ""
        reload()
    }

    function notify(result) {
        message = (result && result.message) ? result.message : ""
        messageTone = (result && result.ok) ? "success" : "danger"
        reload()
    }

    // 导入结果除了摘要，还要把每个被跳过的文件原因列出来——
    // 只说"跳过 3 个"用户不知道该修哪个文件。
    function notifyImport(result) {
        if (!result) {
            message = "导入失败：没有返回结果。"
            messageTone = "danger"
            reload()
            return
        }
        var text = result.message || ""
        if (result.failed && result.failed.length > 0) {
            text += "\n" + result.failed.join("\n")
        }
        message = text
        messageTone = result.ok ? "success" : "danger"
        reload()
    }

    function importFromFiles() {
        if (!instance) return
        fileDialog.open()
    }

    function importFromDirectory() {
        if (!instance) return
        dirDialog.open()
    }

    // 图形化的文件选择器。用 QtQuick.Dialogs 而不是 QtWidgets 的
    // QFileDialog：本应用是 QGuiApplication，实例化 QFileDialog 会直接
    // 让进程崩溃（实测退出码 0xC0000409）。
    FileDialog {
        id: fileDialog
        title: "选择 CodeBuddy 凭据文件"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["凭据文件 (*.json *.info)", "所有文件 (*)"]
        onAccepted: page.notifyImport(page.instance.import_files(page.toPathList(selectedFiles)))
    }

    FolderDialog {
        id: dirDialog
        title: "选择包含凭据文件的目录"
        onAccepted: page.notifyImport(page.instance.import_directory(page.toPath(selectedFolder)))
    }

    // QML 的 url 是 file:// 形式，而插件的文件 API 要的是本地路径。
    function toPath(url) {
        var text = String(url)
        if (text.indexOf("file:///") === 0) {
            return decodeURIComponent(text.substring(8))
        }
        if (text.indexOf("file://") === 0) {
            return decodeURIComponent(text.substring(7))
        }
        return text
    }

    function toPathList(urls) {
        var out = []
        if (!urls) return out
        for (var i = 0; i < urls.length; i++) {
            out.push(toPath(urls[i]))
        }
        return out
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
                text: "导入凭据文件"
                iconName: "plus"
                enabled: page.instance !== null
                onClicked: page.importFromFiles()
            }
            AppButton {
                text: "导入目录"
                enabled: page.instance !== null
                onClicked: page.importFromDirectory()
            }
            AppButton {
                text: "保存当前账号"
                iconName: "plus"
                variant: "primary"
                enabled: page.instance !== null && page.current.available === true
                onClicked: page.notify(page.instance.save_current_of("", page.activeTarget))
            }
        }

        // ---------- 目标环境（DSH 多开适配） ----------
        // CodeBuddy 凭据是**按 harness home 各存一份**的：每个独立实例都有自己的
        // 当前账号。这里选一个环境，下面的"当前账号/切换/保存"都作用于它。
        AppCard {
            Layout.fillWidth: true
            visible: page.environments.length > 1
            title: "目标环境"
            subtitle: "CodeBuddy 凭据按 harness home 各存一份，所以每个独立实例各自登录。选择要操作的环境；账号快照库是共用的，可在各环境间复用同一批账号。"

            Repeater {
                model: page.environments

                delegate: Rectangle {
                    required property var modelData

                    Layout.fillWidth: true
                    implicitHeight: envRow.implicitHeight + Theme.space3 * 2
                    radius: Theme.radiusSm
                    color: page.activeTarget === modelData.id ? Theme.surfaceAlt : "transparent"
                    border.width: Theme.borderWidth
                    border.color: page.activeTarget === modelData.id ? Theme.accent : Theme.border

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.selectTarget(modelData.id)
                    }

                    RowLayout {
                        id: envRow
                        anchors.fill: parent
                        anchors.margins: Theme.space3
                        spacing: Theme.space3

                        // 选中指示：与「DSH 多开」的勾选控件保持同一视觉语言。
                        Rectangle {
                            Layout.alignment: Qt.AlignVCenter
                            width: 18
                            height: 18
                            radius: 9
                            color: page.activeTarget === modelData.id ? Theme.accent : "transparent"
                            border.width: Theme.borderWidth
                            border.color: page.activeTarget === modelData.id ? Theme.accent : Theme.borderStrong

                            Rectangle {
                                anchors.centerIn: parent
                                width: 6
                                height: 6
                                radius: 3
                                color: Theme.accentText
                                visible: page.activeTarget === modelData.id
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2

                            RowLayout {
                                spacing: Theme.space2
                                Text {
                                    text: modelData.label
                                    color: Theme.text
                                    font.pixelSize: Theme.fontBody
                                    font.weight: Font.DemiBold
                                }
                                StatusBadge {
                                    text: modelData.signedIn ? modelData.accountLabel : "未登录"
                                    tone: modelData.signedIn
                                        ? (modelData.refreshExpired ? "warning" : "success")
                                        : "unknown"
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: modelData.home
                                color: Theme.textMuted
                                font.pixelSize: Theme.fontCaption
                                elide: Text.ElideMiddle
                            }
                        }
                    }
                }
            }
        }

        // ---------- 当前账号 ----------
        // AppCard 的默认属性 content 会把子项放进它内部的 ColumnLayout，
        // 所以这里直接给子项加 Layout.* 属性，不要再嵌一层带 anchors 的布局。
        AppCard {
            Layout.fillWidth: true
            title: "当前生效账号"
            subtitle: page.activeLabel()

            Text {
                Layout.fillWidth: true
                visible: page.current.available !== true
                text: page.current.error
                    ? "读取当前凭据失败：" + page.current.error
                    : "该环境尚未登录 CodeBuddy。可从下面的快照选一个切换过去。"
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
                                // 明确把"切到哪个环境"传下去：多开时每个实例各有
                                // 自己的凭据文件，不指定就可能切错地方。
                                onClicked: page.notify(
                                    page.instance.switch_of(modelData.name, page.activeTarget))
                            }
                        }
                    }
                }
            }
        }
    }
}
