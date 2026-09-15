import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme

// Renders a form schema (list of field descriptors from Python) into inputs and
// emits the collected payload on submit. Field values live in `values`, keyed by
// the schema's `key` so the payload shape always matches Python's expectations.
ColumnLayout {
    id: root

    property var fields: []
    property var values: ({})
    property string submitText: "保存"
    property string cancelText: "取消"
    property bool submitting: false

    signal submitted(var payload)
    signal cancelled()

    spacing: Theme.space3

    function reset(sourceFields, initialValues) {
        var collected = {}
        var source = sourceFields || []
        for (var i = 0; i < source.length; i++) {
            var field = source[i]
            if (!field || !field.key)
                continue
            if (field.type === "switch")
                collected[field.key] = field.value === true
            else if (field.type === "multichoice")
                collected[field.key] = (field.values || []).slice()
            else
                collected[field.key] = field.value === undefined || field.value === null ? "" : field.value
        }
        if (initialValues) {
            for (var key in initialValues)
                collected[key] = initialValues[key]
        }
        root.values = collected
    }

    function setValue(key, value) {
        var next = {}
        for (var existing in root.values)
            next[existing] = root.values[existing]
        next[key] = value
        root.values = next
    }

    function collect() {
        var payload = {}
        for (var key in root.values)
            payload[key] = root.values[key]
        return payload
    }

    onFieldsChanged: root.reset(root.fields, null)

    Repeater {
        model: root.fields

        delegate: ColumnLayout {
            id: fieldWrapper

            required property var modelData

            Layout.fillWidth: true
            spacing: Theme.space1
            visible: fieldWrapper.modelData.type !== "info"

            Text {
                Layout.fillWidth: true
                text: fieldWrapper.modelData.label || fieldWrapper.modelData.key
                color: Theme.textMuted
                font.pixelSize: Theme.fontCaption
                elide: Text.ElideRight
            }

            // -- text / number ------------------------------------------
            AppTextField {
                Layout.fillWidth: true
                visible: fieldWrapper.modelData.type === "text"
                    || fieldWrapper.modelData.type === "number"
                    || fieldWrapper.modelData.type === "password"
                    || fieldWrapper.modelData.type === "path"
                placeholderText: fieldWrapper.modelData.placeholder || ""
                echoMode: fieldWrapper.modelData.type === "password" ? TextInput.Password : TextInput.Normal
                text: String(root.values[fieldWrapper.modelData.key] === undefined
                    ? "" : root.values[fieldWrapper.modelData.key])
                onTextEdited: root.setValue(fieldWrapper.modelData.key, text)
            }

            // -- textarea -----------------------------------------------
            AppTextArea {
                Layout.fillWidth: true
                Layout.preferredHeight: 96
                visible: fieldWrapper.modelData.type === "textarea"
                text: String(root.values[fieldWrapper.modelData.key] === undefined
                    ? "" : root.values[fieldWrapper.modelData.key])
                onTextEdited: root.setValue(fieldWrapper.modelData.key, text)
            }

            // -- choice --------------------------------------------------
            AppComboBox {
                Layout.fillWidth: true
                visible: fieldWrapper.modelData.type === "choice"
                options: fieldWrapper.modelData.options || []
                selectedValue: String(root.values[fieldWrapper.modelData.key] === undefined
                    ? "" : root.values[fieldWrapper.modelData.key])
                onSelectionChanged: function (value) {
                    root.setValue(fieldWrapper.modelData.key, value)
                }
            }

            // -- switch --------------------------------------------------
            RowLayout {
                Layout.fillWidth: true
                visible: fieldWrapper.modelData.type === "switch"
                spacing: Theme.space2

                AppSwitch {
                    checked: root.values[fieldWrapper.modelData.key] === true
                    onToggled: root.setValue(fieldWrapper.modelData.key, checked)
                }

                Text {
                    Layout.fillWidth: true
                    text: root.values[fieldWrapper.modelData.key] === true ? "已启用" : "已关闭"
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontCaption
                }
            }

            // -- multichoice ---------------------------------------------
            Flow {
                Layout.fillWidth: true
                visible: fieldWrapper.modelData.type === "multichoice"
                spacing: Theme.space1 + 2

                Repeater {
                    model: fieldWrapper.modelData.options || []

                    delegate: Rectangle {
                        id: chip

                        required property var modelData

                        readonly property bool selected: {
                            var current = root.values[fieldWrapper.modelData.key] || []
                            return current.indexOf(chip.modelData.value) !== -1
                        }

                        width: chipText.implicitWidth + Theme.space3 * 2
                        height: Theme.controlHeightSm
                        radius: height / 2
                        color: chip.selected ? Theme.accentSoft : Theme.surface
                        border.width: Theme.borderWidth
                        border.color: chip.selected ? Theme.accent : Theme.border

                        Text {
                            id: chipText
                            anchors.centerIn: parent
                            text: chip.modelData.label
                            color: chip.selected ? Theme.accent : Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                var current = (root.values[fieldWrapper.modelData.key] || []).slice()
                                var index = current.indexOf(chip.modelData.value)
                                if (index === -1)
                                    current.push(chip.modelData.value)
                                else
                                    current.splice(index, 1)
                                root.setValue(fieldWrapper.modelData.key, current)
                            }
                        }
                    }
                }
            }
        }
    }

    // Info-only fields (used for confirmations).
    Repeater {
        model: root.fields

        delegate: Text {
            required property var modelData

            Layout.fillWidth: true
            visible: modelData.type === "info"
            text: String(modelData.value === undefined || modelData.value === null ? "" : modelData.value)
            color: Theme.textMuted
            font.pixelSize: Theme.fontBody
            wrapMode: Text.WordWrap
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: Theme.space2
        spacing: Theme.space2

        Item { Layout.fillWidth: true }

        AppButton {
            text: root.cancelText
            variant: "ghost"
            onClicked: root.cancelled()
        }

        AppButton {
            text: root.submitText
            variant: "primary"
            enabled: !root.submitting
            onClicked: root.submitted(root.collect())
        }
    }
}
