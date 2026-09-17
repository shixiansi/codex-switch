import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme

// 动态加载插件自带页面的宿主控件。
//
// QML 的 StackLayout 要求子组件在编译期静态声明，而插件页面是运行时才发现
// 的文件，所以这里用 Qt.createComponent 动态创建。
//
// 隔离原则：插件页面加载失败只在本控件内显示错误，绝不影响插件中心本身。
Item {
    id: host

    // 插件 id 与它的 QML 页面绝对路径。
    property string pluginId: ""
    property string pageUrl: ""
    // 插件实例，注入给页面。
    property var instance: null

    // 当前创建出来的页面对象。
    property var loadedItem: null
    property string loadError: ""

    function teardown() {
        if (loadedItem) {
            // 页面是动态创建的，宿主不销毁就没人回收。
            loadedItem.destroy()
            loadedItem = null
        }
    }

    function build() {
        teardown()
        loadError = ""

        if (pageUrl === "") {
            return
        }

        // 插件页面随插件升级而变化，不能复用 QML 的组件缓存，
        // 否则重新扫描后会继续显示旧页面。
        var component = Qt.createComponent(pageUrl, Component.PreferSynchronous)
        if (!component) {
            loadError = "无法创建组件：" + pageUrl
            return
        }
        if (component.status === Component.Error) {
            loadError = component.errorString()
            return
        }
        if (component.status !== Component.Ready) {
            loadError = "页面尚未就绪。"
            return
        }

        var item = component.createObject(placeholder, {
            "instance": host.instance
        })
        if (!item) {
            loadError = "页面创建失败。"
            return
        }
        loadedItem = item
    }

    onPageUrlChanged: build()
    onInstanceChanged: {
        // 实例后到（插件异步加载）时，把实例补进已创建的页面。
        if (loadedItem) {
            loadedItem.instance = host.instance
        }
        build()
    }

    Component.onDestruction: teardown()

    Item {
        id: placeholder
        anchors.fill: parent

        // 页面未配置：属于插件作者的问题，说清楚而不是留一片空白。
        Text {
            anchors.centerIn: parent
            visible: host.pageUrl === "" && host.loadError === ""
            text: "该插件没有提供页面。"
            color: Theme.textMuted
            font.pixelSize: Theme.fontBody
        }

        // 页面加载失败：显示真实错误，方便插件作者定位。
        Text {
            anchors.fill: parent
            anchors.margins: Theme.space4
            visible: host.loadError !== ""
            text: "插件页面加载失败：\n" + host.loadError
            color: Theme.danger
            font.pixelSize: Theme.fontCaption
            wrapMode: Text.Wrap
        }
    }
}
