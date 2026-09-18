import QtQuick
import QtQuick.Controls
import theme

// 带样式的下拉菜单。
//
// 默认的 Menu 走 Qt 的 Basic 样式：白底黑字、无圆角无边框，与本应用的设计语言
// （低对比 surface + 1px 描边 + 8px 圆角）完全不搭，看起来像"没做完"。
// 这里统一背景与内边距。
Menu {
    id: control

    padding: Theme.space1

    // 宽度必须自己算。
    //
    // Menu 的隐式宽度来自 contentItem，而我们把子项做成了自定义组件后，
    // 它不再把这个宽度透传上来——实测菜单被压成 8px 宽（正好等于左右 padding），
    // 文字全被挤没。这里按最宽的子项显式撑开，并给一个可读的下限。
    width: {
        var widest = 0
        for (var i = 0; i < control.count; ++i) {
            var entry = control.itemAt(i)
            if (entry && entry.implicitWidth > widest)
                widest = entry.implicitWidth
        }
        return Math.max(200, widest + control.leftPadding + control.rightPadding)
    }

    background: Rectangle {
        radius: Theme.radiusSm
        color: Theme.surface
        border.width: Theme.borderWidth
        border.color: Theme.border
    }
}
