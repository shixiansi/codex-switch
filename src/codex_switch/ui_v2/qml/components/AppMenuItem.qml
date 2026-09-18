import QtQuick
import QtQuick.Controls
import theme

// 带样式的菜单项：可选前置图标 + 悬停/高亮底色。
//
// 单独成组件而不是在每个 Menu 里重复写 contentItem/background（DRY），
// 也让菜单项的高度、内边距与其它控件保持一致。
MenuItem {
    id: control

    property string iconName: ""

    implicitHeight: Theme.controlHeight
    // 菜单不该窄到文字换行；给一个下限，长文案由 elide 收尾。
    implicitWidth: Math.max(200, labelRow.implicitWidth + Theme.space3 * 2)

    contentItem: Row {
        id: labelRow

        spacing: Theme.space2
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        anchors.leftMargin: Theme.space2

        AppIcon {
            name: control.iconName
            color: control.enabled ? Theme.textMuted : Theme.textFaint
            size: 15
            visible: control.iconName !== ""
            anchors.verticalCenter: parent.verticalCenter
        }

        Text {
            text: control.text
            color: control.enabled
                ? (control.highlighted ? Theme.accent : Theme.text)
                : Theme.textFaint
            font.pixelSize: Theme.fontBody
            font.weight: control.highlighted ? Font.Medium : Font.Normal
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
        }
    }

    background: Rectangle {
        radius: Theme.radiusSm
        // 底色始终是**不透明**的两种色调，靠 opacity 做淡入淡出。
        //
        // 不能写成 `highlighted ? Theme.surfaceHover : "transparent"` 再给 color
        // 加动画：Qt 会从 rgba(0,0,0,0) 也就是黑色开始插值，悬停时闪一下灰。
        // 这与 AppButton 的 ghost 变体是同一个坑，项目里有专门的用例守着。
        color: Theme.surfaceHover
        opacity: control.highlighted ? 1 : 0

        Behavior on opacity {
            NumberAnimation {
                duration: Theme.durationFast
                easing.type: Easing.OutCubic
            }
        }
    }
}
