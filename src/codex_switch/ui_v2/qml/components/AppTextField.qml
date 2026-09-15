import QtQuick
import QtQuick.Controls
import theme

// Styled single-line input matching SearchField's visual language.
TextField {
    id: control

    implicitHeight: Theme.controlHeight
    leftPadding: Theme.space3
    rightPadding: Theme.space3
    font.pixelSize: Theme.fontBody
    color: Theme.text
    placeholderTextColor: Theme.textFaint
    selectByMouse: true
    verticalAlignment: TextInput.AlignVCenter
    selectionColor: Theme.accent
    selectedTextColor: Theme.accentText
    activeFocusOnTab: true

    background: Rectangle {
        radius: Theme.radiusSm
        color: control.enabled ? Theme.surface : Theme.surfaceAlt
        border.width: Theme.borderWidth
        border.color: control.activeFocus ? Theme.accent : Theme.border

        Behavior on border.color {
            ColorAnimation { duration: Theme.durationFast }
        }
    }
}
