import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// DSH 多开插件页面。
//
// 由插件中心的插件宿主控件（PluginHost）动态加载，因此这里不能用任何编译期
// 才存在的单例或上下文属性——所有数据都通过 `instance` 拿。而 `instance`
// 是宿主包装后的 PluginCallBridge（一个真正的 QObject），不是插件的 Python
// 对象本身：QML 无法对 QVariant 包装的普通对象调用方法。
Item {
    id: page

    // 为 null 表示插件未加载，页面显示占位提示。
    property var instance: null

    property var instances: []
    property var status: ({})
    property var selected: ({})     // 当前选中的实例详情
    property string selectedKey: ""
    property string message: ""
    property string messageTone: ""
    property string logText: ""

    // 新建表单
    property string formName: ""
    property string formKind: "web"
    property int formPort: 0
    property bool formIsolate: false
    property bool formExtraOpen: false

    // 删除确认
    property string pendingRemoveKey: ""
    property string pendingRemoveName: ""

    function reload() {
        if (!instance) return
        status = instance.status()
        instances = instance.instances()
        if (selectedKey !== "") {
            var stillThere = false
            for (var i = 0; i < instances.length; i++) {
                if (instances[i].name === selectedKey) { stillThere = true; break }
            }
            if (stillThere)
                selected = instance.detail(selectedKey)
            else {
                selectedKey = ""
                selected = ({})
                logText = ""
            }
        }
    }

    function notify(result) {
        message = (result && result.message) ? result.message : ""
        messageTone = (result && result.ok) ? "success" : "danger"
        reload()
    }

    function select(key) {
        selectedKey = key
        selected = instance ? instance.detail(key) : ({})
        logText = ""
    }

    function createInstance() {
        if (!instance) return
        var payload = {
            "name": formName,
            "kind": formKind,
            "port": String(formPort),
            "isolate": formIsolate,
            "extraArgs": ""
        }
        var result = instance.create(payload)
        notify(result)
        if (result && result.ok) {
            formName = ""
            formPort = 0
            formIsolate = false
            formExtraOpen = false
            if (result.id) select(result.id)
        }
    }

    function openInstance(key) {
        if (!instance) return
        var result = instance.url(key)
        if (result && result.ok && result.url !== "") {
            Qt.openUrlExternally(result.url)
            message = "已交给系统浏览器打开：" + result.url
            messageTone = "success"
        } else {
            message = (result && result.message) ? result.message : "拿不到访问地址。"
            messageTone = "danger"
        }
    }

    function copyUrl(key) {
        if (!instance) return
        var result = instance.url(key)
        if (result && result.ok && result.url !== "") {
            clipHelper.text = result.url
            clipHelper.selectAll()
            clipHelper.copy()
            message = "访问地址已复制到剪贴板。"
            messageTone = "success"
        } else {
            message = (result && result.message) ? result.message : "拿不到访问地址。"
            messageTone = "danger"
        }
    }

    function loadLog(key) {
        if (!instance) return
        var result = instance.log(key)
        logText = (result && result.text) ? result.text : ""
        if (result && result.ok === false)
            logText = result.message || "读取日志失败。"
    }

    function openStoreFolder() {
        if (!instance) return
        var result = instance.open_folder()
        if (result && result.ok) {
            Qt.openUrlExternally("file:///" + String(result.path).replace(/\\/g, "/"))
            message = "已打开多开数据目录：" + result.path
            messageTone = "success"
        } else {
            message = (result && result.message) ? result.message : "打不开目录。"
            messageTone = "danger"
        }
    }

    function askRemove(key, name) {
        pendingRemoveKey = key
        pendingRemoveName = name
        confirmRemove.open()
    }

    // instance 可能是创建后才注入的（宿主先建页面、插件后加载完），
    // 所以两个时机都要拉一次数据，只在 onCompleted 里读会拿到空列表。
    onInstanceChanged: if (instance) reload()
    Component.onCompleted: if (instance) reload()

    // 剪贴板辅助：QML 的 TextEdit 有 copy()，用它就不必引入 QtQuick.
    // Clipboard 之外的东西（该项目其它页面也是这个做法）。
    TextEdit {
        id: clipHelper
        visible: false
        width: 0
        height: 0
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space5
        spacing: Theme.space4

        SectionHeader {
            title: "DSH 多开"
            description: "同时运行多个 DSH 实例，各自独立端口。默认共用 ~/.dsh（沿用登录态与设置），勾选独立 home 可做完全隔离。"

            AppButton {
                text: "刷新"
                iconName: "refresh"
                enabled: page.instance !== null
                onClicked: page.reload()
            }
            AppButton {
                text: "数据目录"
                iconName: "folder"
                enabled: page.instance !== null
                onClicked: page.openStoreFolder()
            }
            AppButton {
                text: "全部停止"
                variant: "ghost"
                enabled: page.instance !== null && page.status.running > 0
                onClicked: page.notify(page.instance.stop_all())
            }
            AppButton {
                text: "新建实例"
                iconName: "plus"
                variant: "primary"
                enabled: page.instance !== null
                onClicked: newDialog.open()
            }
        }

        // ---------- 概览 ----------
        AppCard {
            Layout.fillWidth: true
            title: "概览"

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space4

                StatCard {
                    Layout.fillWidth: true
                    label: "实例总数"
                    value: String(page.status.count || 0)
                }
                StatCard {
                    Layout.fillWidth: true
                    label: "正在运行"
                    value: String(page.status.running || 0)
                    tone: (page.status.running > 0) ? "success" : ""
                }
            }

            DetailRow {
                Layout.fillWidth: true
                label: "harness home"
                value: page.status.dshHome || ""
                tone: "muted"
                selectable: true
                wrap: true
            }
            DetailRow {
                Layout.fillWidth: true
                label: "数据目录"
                value: page.status.storeDir || ""
                tone: "muted"
                selectable: true
                wrap: true
            }
        }

        // ---------- 操作结果 ----------
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

        // ---------- 实例列表 ----------
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 200
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
                    text: "实例 (" + page.instances.length + ")"
                    color: Theme.text
                    font.pixelSize: Theme.fontSubtitle
                    font.weight: Font.DemiBold
                }

                EmptyState {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: page.instances.length === 0
                    iconName: "grid"
                    title: "还没有实例"
                    description: "点右上角「新建实例」添加一个，再点「启动」把它跑起来。"
                    actionText: "新建实例"
                    onActionTriggered: newDialog.open()
                }

                ListView {
                    id: instanceList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    visible: page.instances.length > 0
                    model: page.instances
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        required property var modelData
                        width: instanceList.width
                        implicitHeight: cardLayout.implicitHeight + Theme.space3 * 2
                        radius: Theme.radiusSm
                        color: page.selectedKey === modelData.name ? Theme.surfaceAlt : "transparent"

                        ColumnLayout {
                            id: cardLayout
                            anchors.fill: parent
                            anchors.margins: Theme.space3
                            spacing: Theme.space2

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.space2

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    RowLayout {
                                        spacing: Theme.space2
                                        Text {
                                            text: modelData.name
                                            color: Theme.text
                                            font.pixelSize: Theme.fontBody
                                            font.weight: Font.DemiBold
                                        }
                                        StatusBadge {
                                            text: modelData.statusLabel
                                            tone: modelData.status === "running" ? "success"
                                                : (modelData.status === "failed" ? "danger"
                                                : (modelData.status === "starting" ? "warning" : "unknown"))
                                        }
                                        StatusBadge {
                                            visible: modelData.isolated === true
                                            text: "独立 home"
                                            tone: "info"
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.subtitle
                                        color: Theme.textMuted
                                        font.pixelSize: Theme.fontCaption
                                        elide: Text.ElideRight
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        visible: modelData.url !== ""
                                        text: modelData.url
                                        color: Theme.accent
                                        font.pixelSize: Theme.fontCaption
                                        elide: Text.ElideMiddle
                                    }
                                }

                                AppButton {
                                    text: "启动"
                                    variant: "primary"
                                    enabled: page.instance !== null && modelData.running !== true
                                    onClicked: page.notify(page.instance.start(modelData.name))
                                }
                                AppButton {
                                    text: "停止"
                                    enabled: page.instance !== null && modelData.running === true
                                    onClicked: page.notify(page.instance.stop(modelData.name))
                                }
                                AppButton {
                                    text: "打开"
                                    enabled: modelData.running === true
                                    onClicked: page.openInstance(modelData.name)
                                }
                                AppButton {
                                    text: "日志"
                                    variant: "ghost"
                                    onClicked: {
                                        page.select(modelData.name)
                                        page.loadLog(modelData.name)
                                    }
                                }
                                AppButton {
                                    text: "删除"
                                    variant: "ghost"
                                    onClicked: page.askRemove(modelData.name, modelData.name)
                                }
                            }
                        }
                    }
                }
            }
        }

        // ---------- 详情 / 日志 ----------
        AppCard {
            Layout.fillWidth: true
            visible: page.selectedKey !== ""
            title: "详情：" + page.selectedKey
            collapsible: true
            expanded: true

            DetailRow {
                Layout.fillWidth: true
                label: "状态"
                value: page.selected.statusLabel || ""
            }
            DetailRow {
                Layout.fillWidth: true
                visible: (page.selected.pid || 0) > 0
                label: "进程号"
                value: String(page.selected.pid || "")
            }
            DetailRow {
                Layout.fillWidth: true
                visible: (page.selected.url || "") !== ""
                label: "访问地址"
                value: page.selected.url || ""
                selectable: true
                wrap: true
            }
            DetailRow {
                Layout.fillWidth: true
                label: "harness home"
                value: page.selected.homeLabel || ""
                tone: "muted"
                selectable: true
                wrap: true
            }
            DetailRow {
                Layout.fillWidth: true
                label: "启动命令"
                value: page.selected.command || page.selected.planError || ""
                tone: page.selected.planError ? "danger" : "muted"
                selectable: true
                wrap: true
            }
            DetailRow {
                Layout.fillWidth: true
                label: "日志文件"
                value: page.selected.logPath || ""
                tone: "muted"
                selectable: true
                wrap: true
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space2

                AppButton {
                    text: "打开地址"
                    variant: "primary"
                    enabled: (page.selected.url || "") !== ""
                    onClicked: page.openInstance(page.selectedKey)
                }
                AppButton {
                    text: "复制地址"
                    enabled: (page.selected.url || "") !== ""
                    onClicked: page.copyUrl(page.selectedKey)
                }
                AppButton {
                    text: "刷新日志"
                    iconName: "refresh"
                    onClicked: page.loadLog(page.selectedKey)
                }
            }

            // 日志正文。用只读 TextArea 而不是 Text：日志可能很长，
            // 需要能选中复制。
            AppTextArea {
                Layout.fillWidth: true
                Layout.preferredHeight: 180
                readOnly: true
                text: page.logText
                placeholderText: "点「刷新日志」查看该实例的输出。"
            }
        }
    }

    // ---------- 新建实例 ----------
    Popup {
        id: newDialog
        modal: true
        focus: true
        anchors.centerIn: parent
        width: Math.min(460, page.width - Theme.space6 * 2)
        padding: Theme.space4

        background: Rectangle {
            radius: Theme.radius
            color: Theme.surface
            border.width: Theme.borderWidth
            border.color: Theme.border
        }

        contentItem: ColumnLayout {
            spacing: Theme.space3

            Text {
                Layout.fillWidth: true
                text: "新建 DSH 实例"
                color: Theme.text
                font.pixelSize: Theme.fontSubtitle
                font.weight: Font.DemiBold
            }

            Text {
                Layout.fillWidth: true
                text: "实例名"
                color: Theme.textMuted
                font.pixelSize: Theme.fontCaption
            }
            AppTextField {
                Layout.fillWidth: true
                placeholderText: "例如 dev-1"
                text: page.formName
                onTextEdited: page.formName = text
            }

            Text {
                Layout.fillWidth: true
                text: "类型"
                color: Theme.textMuted
                font.pixelSize: Theme.fontCaption
            }
            AppComboBox {
                Layout.fillWidth: true
                options: page.status.kinds || []
                selectedValue: page.formKind
                onSelectionChanged: function (value) { page.formKind = value }
            }

            Text {
                Layout.fillWidth: true
                text: "端口（0 表示自动分配，推荐）"
                color: Theme.textMuted
                font.pixelSize: Theme.fontCaption
            }
            AppTextField {
                Layout.fillWidth: true
                placeholderText: "0"
                text: String(page.formPort)
                validator: IntValidator { bottom: 0; top: 65535 }
                onTextEdited: page.formPort = parseInt(text) || 0
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space2

                AppSwitch {
                    id: isolateSwitch
                    checked: page.formIsolate
                    onToggled: page.formIsolate = checked
                }
                Text {
                    Layout.fillWidth: true
                    text: "使用独立 harness home（账号与设置完全隔离，首次需重新登录）"
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontCaption
                    wrapMode: Text.WordWrap
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Theme.space1
                spacing: Theme.space2

                Item { Layout.fillWidth: true }

                AppButton {
                    text: "取消"
                    variant: "ghost"
                    onClicked: newDialog.close()
                }
                AppButton {
                    text: "创建"
                    variant: "primary"
                    enabled: page.formName.trim() !== ""
                    onClicked: {
                        page.createInstance()
                        newDialog.close()
                    }
                }
            }
        }
    }

    // ---------- 删除确认 ----------
    ConfirmDialog {
        id: confirmRemove
        confirm: ({
            "title": "删除实例",
            "message": "确定要删除实例「" + page.pendingRemoveName + "」吗？",
            "detail": "运行中的实例会先被停止。实例的独立 home 目录不会被删除。",
            "confirmText": "删除",
            "danger": true
        })
        onConfirmed: {
            page.notify(page.instance.remove(page.pendingRemoveKey))
            page.pendingRemoveKey = ""
            page.pendingRemoveName = ""
        }
        onCancelled: {
            page.pendingRemoveKey = ""
            page.pendingRemoveName = ""
        }
    }
}
