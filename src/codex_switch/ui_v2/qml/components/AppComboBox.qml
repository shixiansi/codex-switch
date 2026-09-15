import QtQuick
import QtQuick.Controls
import theme

// Styled dropdown bound to a {value,label} option list.
ComboBox {
    id: control

    property var options: []
    // Named `selectedValue` because ComboBox.value is FINAL in Qt.
    property string selectedValue: ""

    implicitHeight: Theme.controlHeight
    font.pixelSize: Theme.fontBody
    leftPadding: Theme.space3
    rightPadding: Theme.space5
    hoverEnabled: true

    signal selectionChanged(string value)

    function indexForValue(value) {
        for (var i = 0; i < control.options.length; i++) {
            if (String(control.options[i].value) === String(value))
                return i
        }
        return -1
    }

    function labelForValue(value) {
        var index = control.indexForValue(value)
        return index === -1 ? "" : control.options[index].label
    }

    model: {
        var labels = []
        for (var i = 0; i < control.options.length; i++)
            labels.push(control.options[i].label)
        return labels
    }

    currentIndex: control.indexForValue(control.selectedValue)

    onActivated: function (index) {
        if (index >= 0 && index < control.options.length) {
            control.selectedValue = String(control.options[index].value)
            control.selectionChanged(control.selectedValue)
        }
    }

    onSelectedValueChanged: {
        var index = control.indexForValue(control.selectedValue)
        if (index !== control.currentIndex)
            control.currentIndex = index
    }

    contentItem: Text {
        leftPadding: 0
        text: control.displayText
        color: control.enabled ? Theme.text : Theme.textFaint
        font.pixelSize: Theme.fontBody
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: AppIcon {
        x: control.width - width - Theme.space2
        y: (control.height - height) / 2
        name: "chevron-right"
        color: Theme.textMuted
        size: 14
        rotation: 90
    }

    background: Rectangle {
        radius: Theme.radiusSm
        color: control.enabled ? Theme.surface : Theme.surfaceAlt
        border.width: Theme.borderWidth
        border.color: control.activeFocus ? Theme.accent : Theme.border
    }

    popup: Popup {
        y: control.height + Theme.space1
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + Theme.space2, 320)
        padding: Theme.space1

        background: Rectangle {
            radius: Theme.radiusSm
            color: Theme.surface
            border.width: Theme.borderWidth
            border.color: Theme.border
        }

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        }
    }

    delegate: ItemDelegate {
        id: optionItem

        required property int index
        required property string modelData

        width: control.width - Theme.space2
        height: Theme.controlHeight
        highlighted: control.highlightedIndex === index

        contentItem: Text {
            text: optionItem.modelData
            color: Theme.text
            font.pixelSize: Theme.fontBody
            verticalAlignment: Text.AlignVCenter
            leftPadding: Theme.space2
            elide: Text.ElideRight
        }

        background: Rectangle {
            radius: Theme.radiusSm
            color: optionItem.highlighted ? Theme.surfaceHover : "transparent"
        }
    }
}
