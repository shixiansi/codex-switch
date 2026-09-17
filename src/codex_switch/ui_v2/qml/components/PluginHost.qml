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

        // createObject(parent) 只建立父子关系，**不会**给创建出来的对象尺寸。
        // 不铺满的话页面根对象是 0x0，页面内部的 anchors.fill: parent 也就
        // 没有可填充的空间，表现为所有内容挤成一堆叠在一起。
        // 插件页面通常不会自己设 anchors（它不知道宿主给了多大地方），
        // 所以由宿主负责摆放。
        if (item.hasOwnProperty("anchors")) {
            item.anchors.fill = placeholder
        }

        loadedItem = item
    }

    onPageUrlChanged: build()
    onInstanceChanged: {
        // 实例通常后到（宿主先建页面、插件随后才加载完）。
        // 已经建好页面时只需把新实例换进去，不必销毁重建——
        // build() 里会先 teardown，重建会丢掉页面当前的状态（滚动位置、
        // 正在编辑的内容），也会闪一下。
        if (loadedItem) {
            loadedItem.instance = host.instance
            return
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
