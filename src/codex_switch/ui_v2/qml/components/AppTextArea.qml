import QtQuick
import QtQuick.Controls
import theme

// Styled multi-line input. The inner TextArea's `textEdited` signal is
// forwarded so callers can react to user edits without binding loops.
ScrollView {
    id: control

    property alias text: area.text
    property alias placeholderText: area.placeholderText
    property alias readOnly: area.readOnly
    property alias wrapMode: area.wrapMode

    signal textEdited()

    implicitHeight: 96
    clip: true

    background: Rectangle {
        radius: Theme.radiusSm
        color: Theme.surface
        border.width: Theme.borderWidth
        border.color: area.activeFocus ? Theme.accent : Theme.border

        Behavior on border.color {
            ColorAnimation { duration: Theme.durationFast }
        }
    }

    TextArea {
        id: area
        font.pixelSize: Theme.fontBody
        color: Theme.text
        placeholderTextColor: Theme.textFaint
        selectByMouse: true
        wrapMode: TextArea.Wrap
        selectionColor: Theme.accent
        selectedTextColor: Theme.accentText
        background: null
        leftPadding: Theme.space2 + 2
        rightPadding: Theme.space2 + 2
        topPadding: Theme.space1 + 2
        bottomPadding: Theme.space1 + 2

        onTextEdited: control.textEdited()
    }
}
