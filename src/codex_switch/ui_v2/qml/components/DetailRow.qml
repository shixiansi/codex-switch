import QtQuick
import QtQuick.Layouts
import theme

// Label/value line used throughout detail panels.
RowLayout {
    id: root

    property string label: ""
    property string value: ""
    property string tone: ""
    property bool selectable: false
    property bool wrap: false

    Layout.fillWidth: true
    spacing: Theme.space3

    Text {
        text: root.label
        color: Theme.textMuted
        font.pixelSize: Theme.fontCaption
        Layout.preferredWidth: 104
        Layout.alignment: Qt.AlignTop
        elide: Text.ElideRight
        visible: root.label !== ""
    }

    TextEdit {
        id: valueText
        text: root.value
        color: root.tone !== "" ? Theme.toneColor(root.tone) : Theme.text
        font.pixelSize: Theme.fontBody
        selectByMouse: root.selectable
        readOnly: true
        wrapMode: root.wrap ? TextEdit.Wrap : TextEdit.NoWrap
        Layout.fillWidth: true
        clip: true
        activeFocusOnPress: root.selectable
    }
}
