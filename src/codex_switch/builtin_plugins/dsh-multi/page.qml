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

    // ---- 视图切换：0 = 实例，1 = 插件安装 ----
    property int activeTab: 0

    // ---- 插件安装 ----
    property var pluginTargets: []
    // 选中的目标：{ 目标id: true }。用对象而不是数组，切换是 O(1) 且不会重复。
    property var selectedTargets: ({})
    property string pluginSpec: ""
    // 正在查看"已装插件"的目标 id。
    property string inspectingTarget: ""
    property var installedPlugins: []
    property var installedBuiltin: []
    property string installMessage: ""
    property string installTone: ""
    // 任务列表与当前展开日志的任务 id。
    property var installJobs: []
    property string jobLogJobId: ""
    property string jobLogText: ""

    function reloadPluginTargets() {
        if (!instance) return
        pluginTargets = instance.plugin_targets()
    }

    function targetKey(row) {
        return row && row.id ? row.id : ""
    }

    function isTargetSelected(id) {
        return selectedTargets[id] === true
    }

    function toggleTarget(id) {
        var next = {}
        for (var key in selectedTargets)
            next[key] = selectedTargets[key]
        if (next[id] === true)
            delete next[id]
        else
            next[id] = true
        selectedTargets = next
    }

    function selectedTargetIds() {
        var out = []
        for (var key in selectedTargets) {
            if (selectedTargets[key] === true)
                out.push(key)
        }
        return out
    }

    function allTargetsSelected() {
        if (pluginTargets.length === 0) return false
        for (var i = 0; i < pluginTargets.length; i++) {
            if (!isTargetSelected(targetKey(pluginTargets[i]))) return false
        }
        return true
    }

    function toggleSelectAll() {
        if (allTargetsSelected()) {
            selectedTargets = ({})
            return
        }
        var next = {}
        for (var i = 0; i < pluginTargets.length; i++)
            next[targetKey(pluginTargets[i])] = true
        selectedTargets = next
    }

    // 只选独立 home 的目标（"给所有独立环境装，但不碰共用的那个"）。
    function selectIsolatedOnly() {
        var next = {}
        for (var i = 0; i < pluginTargets.length; i++) {
            var row = pluginTargets[i]
            if (row && row.isolated === true)
                next[targetKey(row)] = true
        }
        selectedTargets = next
    }

    function inspectTarget(id) {
        if (!instance) return
        inspectingTarget = id
        var result = instance.installed_plugins(id)
        installedPlugins = (result && result.plugins) ? result.plugins : []
        installedBuiltin = (result && result.builtinLayers) ? result.builtinLayers : []
        if (result && result.ok === false && result.message)
            installNotice(result.message, "danger")
    }

    function installNotice(text, tone) {
        installMessage = text || ""
        installTone = tone || "success"
    }

    function runPluginAction(action) {
        if (!instance) return
        var ids = selectedTargetIds()
        if (ids.length === 0) {
            installNotice("请先勾选至少一个安装目标。", "danger")
            return
        }
        var payload = { "spec": pluginSpec, "targets": ids }
        var result = action === "install"
            ? instance.install_plugin(payload)
            : instance.uninstall_plugin(payload)
        if (result && result.ok) {
            installNotice(result.message, "success")
            pluginSpec = ""
            // 任务在后台跑，靠定时器刷新进度。
            refreshJobs()
            jobPoller.start()
        } else {
            installNotice((result && result.message) ? result.message : "提交失败。", "danger")
        }
    }

    function refreshJobs() {
        if (!instance) return
        installJobs = instance.plugin_jobs()
        // 没有进行中的任务就停掉定时器：空转的 Timer 会一直唤醒界面。
        var running = false
        for (var i = 0; i < installJobs.length; i++) {
            if (installJobs[i].running === true) { running = true; break }
        }
        if (!running) {
            jobPoller.stop()
            // 任务结束后刷新一次已装列表与目标摘要，让结果立刻可见。
            reloadPluginTargets()
            if (inspectingTarget !== "")
                inspectTarget(inspectingTarget)
        }
        if (jobLogJobId !== "")
            loadJobLog(jobLogJobId)
    }

    function isJobRunning() {
        for (var i = 0; i < installJobs.length; i++) {
            if (installJobs[i].running === true) return true
        }
        return false
    }

    function loadJobLog(jobId) {
        if (!instance) return
        var result = instance.plugin_job_log(jobId)
        jobLogJobId = jobId
        jobLogText = (result && result.text) ? result.text : ""
        if (result && result.ok === false)
            jobLogText = result.message || "读取任务日志失败。"
    }

    Timer {
        id: jobPoller
        interval: 1000
        repeat: true
        running: false
        onTriggered: page.refreshJobs()
    }

    function reload() {
        if (!instance) return
        status = instance.status()
        instances = instance.instances()
        // 安装目标随实例列表变化（新增/删除实例会多出或少掉一个环境）。
        reloadPluginTargets()
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
            description: "同时运行多个 DSH 实例，各自独立端口。默认共用 ~/.dsh（沿用登录态与设置），勾选独立 home 可做完全隔离；也可以给任意一个环境安装 DSH 插件。"

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
                visible: page.activeTab === 0
                enabled: page.instance !== null && page.status.running > 0
                onClicked: page.notify(page.instance.stop_all())
            }
            AppButton {
                text: "新建实例"
                iconName: "plus"
                variant: "primary"
                visible: page.activeTab === 0
                enabled: page.instance !== null
                onClicked: newDialog.open()
            }
        }

        // ---------- 视图切换：实例 / 插件安装 ----------
        // 用分段控件而不是 TabBar：默认 TabBar 的粗黑样式与本应用不同。
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Theme.controlHeight
            radius: Theme.radiusSm
            color: Theme.surfaceAlt
            border.width: Theme.borderWidth
            border.color: Theme.border

            RowLayout {
                anchors.fill: parent
                anchors.margins: 2
                spacing: 2

                Repeater {
                    model: ["实例", "插件安装"]

                    delegate: Rectangle {
                        required property var modelData
                        required property int index

                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: Theme.radiusSm - 2
                        color: page.activeTab === index ? Theme.surface : "transparent"
                        border.width: page.activeTab === index ? Theme.borderWidth : 0
                        border.color: Theme.border

                        Text {
                            anchors.centerIn: parent
                            text: modelData
                            color: page.activeTab === index ? Theme.accent : Theme.textMuted
                            font.pixelSize: Theme.fontBody
                            font.weight: page.activeTab === index ? Font.DemiBold : Font.Normal
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                page.activeTab = index
                                if (index === 1) page.reloadPluginTargets()
                            }
                        }
                    }
                }
            }
        }

        // ---------- 概览 ----------
        AppCard {
            Layout.fillWidth: true
            visible: page.activeTab === 0
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
            visible: page.activeTab === 0 && page.message !== ""
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
            visible: page.activeTab === 0
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

        // ================= 插件安装 =================
        // 装到哪个环境由 DSH_HOME 决定：每个独立 home 都是独立的环境，
        // 共用的 ~/.dsh 也是一个环境。这里可以单独装、也可以一次装到全部。
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: page.activeTab === 1
            spacing: Theme.space4

            // ---------- 目标选择 ----------
            AppCard {
                Layout.fillWidth: true
                title: "安装目标"
                subtitle: "勾选要安装到的环境。每个独立 home 是一个独立环境；多个实例共用同一个 home 时只出现一次。"

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space2

                    AppButton {
                        text: page.allTargetsSelected() ? "取消全选" : "全选"
                        variant: "soft"
                        enabled: page.pluginTargets.length > 0
                        onClicked: page.toggleSelectAll()
                    }
                    AppButton {
                        text: "只选独立环境"
                        variant: "soft"
                        enabled: page.pluginTargets.length > 0
                        onClicked: page.selectIsolatedOnly()
                    }
                    AppButton {
                        text: "刷新"
                        iconName: "refresh"
                        variant: "ghost"
                        onClicked: page.reloadPluginTargets()
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: "已选 " + page.selectedTargetIds().length + " / " + page.pluginTargets.length
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontCaption
                    }
                }

                Repeater {
                    model: page.pluginTargets

                    delegate: Rectangle {
                        required property var modelData

                        Layout.fillWidth: true
                        implicitHeight: targetRow.implicitHeight + Theme.space3 * 2
                        radius: Theme.radiusSm
                        color: page.isTargetSelected(modelData.id) ? Theme.surfaceAlt : "transparent"
                        border.width: Theme.borderWidth
                        border.color: page.isTargetSelected(modelData.id) ? Theme.accent : Theme.border

                        // 整行可点：目标行本身就是一个勾选项，比只点小方框好按。
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.toggleTarget(modelData.id)
                        }

                        RowLayout {
                            id: targetRow
                            anchors.fill: parent
                            anchors.margins: Theme.space3
                            spacing: Theme.space3

                            // 勾选指示：用主题图标而不是默认 CheckBox（默认样式
                            // 与本应用的视觉规范不一致）。
                            Rectangle {
                                Layout.alignment: Qt.AlignVCenter
                                width: 18
                                height: 18
                                radius: 4
                                color: page.isTargetSelected(modelData.id) ? Theme.accent : "transparent"
                                border.width: Theme.borderWidth
                                border.color: page.isTargetSelected(modelData.id) ? Theme.accent : Theme.borderStrong

                                AppIcon {
                                    anchors.centerIn: parent
                                    name: "check"
                                    size: 12
                                    color: Theme.accentText
                                    visible: page.isTargetSelected(modelData.id)
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
                                        visible: modelData.shared === true
                                        text: "共用"
                                        tone: "info"
                                    }
                                    StatusBadge {
                                        visible: modelData.profileExists !== true
                                        text: "未初始化"
                                        tone: "unknown"
                                    }
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.home + " · profile " + modelData.profile
                                        + " · 已装 " + modelData.installedCount + " 个"
                                    color: Theme.textMuted
                                    font.pixelSize: Theme.fontCaption
                                    elide: Text.ElideMiddle
                                }
                            }

                            AppButton {
                                text: "查看已装"
                                variant: "ghost"
                                onClicked: page.inspectTarget(modelData.id)
                            }
                        }
                    }
                }
            }

            // ---------- 安装 / 卸载 ----------
            AppCard {
                Layout.fillWidth: true
                title: "安装插件"
                subtitle: "包可以是 npm 包名、本地目录、tarball 或 git 地址。安装会调用 dsh 自己的 plugin 命令（依赖 pnpm）。"

                AppTextField {
                    Layout.fillWidth: true
                    placeholderText: "例如 @scope/dsh-plugin 或 D:\\我的插件"
                    text: page.pluginSpec
                    onTextEdited: page.pluginSpec = text
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space2

                    AppButton {
                        text: "安装到选中环境"
                        iconName: "download"
                        variant: "primary"
                        enabled: page.instance !== null
                            && page.selectedTargetIds().length > 0
                            && page.pluginSpec.trim() !== ""
                            && !page.isJobRunning()
                        onClicked: page.runPluginAction("install")
                    }
                    AppButton {
                        text: "从选中环境卸载"
                        variant: "danger"
                        enabled: page.instance !== null
                            && page.selectedTargetIds().length > 0
                            && page.pluginSpec.trim() !== ""
                            && !page.isJobRunning()
                        onClicked: page.runPluginAction("uninstall")
                    }
                    Item { Layout.fillWidth: true }
                    BusyBar {
                        Layout.preferredWidth: 120
                        visible: page.isJobRunning()
                        running: page.isJobRunning()
                    }
                }

                Text {
                    Layout.fillWidth: true
                    visible: page.isJobRunning()
                    text: "安装进行中……不要在完成前关闭 CodexSwitch。"
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontCaption
                    wrapMode: Text.WordWrap
                }
            }

            // ---------- 安装结果提示 ----------
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: installMsgText.implicitHeight + Theme.space3 * 2
                visible: page.installMessage !== ""
                radius: Theme.radiusSm
                color: Theme.surfaceAlt
                border.width: Theme.borderWidth
                border.color: page.installTone === "success" ? Theme.accent : Theme.danger

                Text {
                    id: installMsgText
                    anchors.fill: parent
                    anchors.margins: Theme.space3
                    text: page.installMessage
                    color: page.installTone === "success" ? Theme.text : Theme.danger
                    font.pixelSize: Theme.fontCaption
                    wrapMode: Text.Wrap
                }
            }

            // ---------- 已装插件 ----------
            AppCard {
                Layout.fillWidth: true
                visible: page.inspectingTarget !== ""
                title: "已安装插件"
                subtitle: page.inspectingTarget

                EmptyState {
                    Layout.fillWidth: true
                    visible: page.installedPlugins.length === 0
                    iconName: "cube"
                    title: "这个环境还没有装过插件"
                    description: "环境未初始化时也会显示为空——第一次安装会自动创建。"
                }

                Repeater {
                    model: page.installedPlugins

                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        StatusBadge {
                            text: modelData.statusLabel
                            tone: modelData.statusTone
                        }
                        Text {
                            text: modelData.name
                            color: Theme.text
                            font.pixelSize: Theme.fontBody
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.spec
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                            elide: Text.ElideMiddle
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: page.installedBuiltin.length > 0
                    spacing: Theme.space2

                    Text {
                        text: "内置层"
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontCaption
                    }
                    Text {
                        Layout.fillWidth: true
                        text: page.installedBuiltin.join("、")
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontCaption
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // ---------- 任务与日志 ----------
            AppCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 220
                title: "安装任务"

                EmptyState {
                    Layout.fillWidth: true
                    visible: page.installJobs.length === 0
                    iconName: "log"
                    title: "还没有安装任务"
                    description: "提交安装后，这里会显示每个环境的执行进度与输出。"
                }

                ListView {
                    id: jobList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    implicitHeight: Math.min(contentHeight, 220)
                    clip: true
                    visible: page.installJobs.length > 0
                    model: page.installJobs
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        required property var modelData
                        width: jobList.width
                        implicitHeight: jobRow.implicitHeight + Theme.space2 * 2
                        radius: Theme.radiusSm
                        color: page.jobLogJobId === modelData.id ? Theme.surfaceAlt : "transparent"

                        RowLayout {
                            id: jobRow
                            anchors.fill: parent
                            anchors.margins: Theme.space2
                            spacing: Theme.space2

                            StatusBadge {
                                text: modelData.statusLabel
                                tone: modelData.status === "success" ? "success"
                                    : (modelData.status === "failed" ? "danger" : "warning")
                            }
                            Text {
                                text: modelData.actionLabel + " " + modelData.spec
                                color: Theme.text
                                font.pixelSize: Theme.fontBody
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.done + "/" + modelData.total + " · " + modelData.message
                                color: Theme.textMuted
                                font.pixelSize: Theme.fontCaption
                                elide: Text.ElideRight
                            }
                            AppButton {
                                text: "日志"
                                variant: "ghost"
                                onClicked: page.loadJobLog(modelData.id)
                            }
                        }
                    }
                }

                AppTextArea {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 180
                    visible: page.jobLogJobId !== ""
                    readOnly: true
                    text: page.jobLogText
                    placeholderText: "点任务右侧的「日志」查看输出。"
                }
            }
        }

        // ---------- 详情 / 日志 ----------
        AppCard {
            Layout.fillWidth: true
            visible: page.activeTab === 0 && page.selectedKey !== ""
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
