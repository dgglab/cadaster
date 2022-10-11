import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import Qt.labs.settings

// Stuff from Python :)
import wow

ApplicationWindow {
    id: window
    title: "imv"
    visible: true

    width: 1000
    height: 800

    // Remember window settings on restart.
    Settings {
        property alias x: window.x
        property alias y: window.y
        property alias width: window.width
        property alias height: window.height
    }

    Text {
        visible: !minimap.loaded
        width: Math.max(parent.width / 2, Math.min(400, parent.width))
        wrapMode: Text.WordWrap
        text: "Click \"Open\" and select a tilescan folder. Choose the folder with the actual images within it, as in below:<br><ul><li>TileScanName<ul><li>leicametadata<ul><li>TileScanName.xlcf</ul><li><strong>TileScan_001</strong><ul><li>leicametadata<ul><li>TileScan_001.xlif</ul><li>TileScan_001--Stage000.jpg<li>TileScan_001--Stage001.jpg<li>...</ul></ul></ul><br>After choosing your image, use either wasd or arrow keys to move. Zoom with scroll wheel, pan with left click, draw scale rectangles with right click. You can also click on the minimap.<br><br>Screen captures will be saved into the specified folder with the specified prefix. After editing those fields, click on the image again to start moving.<br><br>TODO and wishlist:<ul><li>Be able to pick any of the folders and load properly.<li>Diagonal scale bars.<li>Angle measurements.<li>Scale up the minimap.<li>Handle other image types.<li><strong>Integrate with the microscope.</strong><li>Full-screen mode for maximum immersion.<li>Test with more tile scans.<li>... ?</ul>"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
    }

    // Parent of everything that should appear in captures.
    Item {
        id: captarget
        anchors.fill: parent
        visible: minimap.loaded

        // Forward motion events to the minimap.
        focus: true
        activeFocusOnTab: true
        Keys.onPressed: (e)=> {
            if (e.key == Qt.Key_Space)
                minimap.next();
            else if (e.key == Qt.Key_W || e.key == Qt.Key_Up)
                minimap.move(0, -1);
            else if (e.key == Qt.Key_A || e.key == Qt.Key_Left)
                minimap.move(-1, 0);
            else if (e.key == Qt.Key_S || e.key == Qt.Key_Down)
                minimap.move(0, 1);
            else if (e.key == Qt.Key_D || e.key == Qt.Key_Right)
                minimap.move(1, 0);
        }

        Image {
            id: image
            source: minimap.imagePath

            // For LUTs, include a custom fragment shader.
            layer.enabled: true
            layer.smooth: true
            layer.effect: ShaderEffect {
                property variant src: image
                property variant lo: lutslider.first.value
                property variant hi: lutslider.second.value
                fragmentShader: "lut.frag.qsb"
            }

            // Default scale should not overlap controls or minimap.
            function defaultScale() {
                let w = parent.width;
                let h = parent.height - Math.max(minimap.height, controls.height);
                return Math.min(w / width, h / height);
            }
            scale: defaultScale()
            transformOrigin: Item.TopLeft
        }

        // Scale bar handles
        Item { id: handle1 }
        Item { id: handle2 }
        MouseArea {
            anchors.fill: parent 
            acceptedButtons: Qt.RightButton
            drag.target: handle2
            drag.threshold: 0
            onPressed: function(e) {
                handle1.x = e.x;
                handle1.y = e.y;
                handle2.x = e.x;
                handle2.y = e.y;
                scalebox.visible = true;
            }
            onClicked: scalebox.visible = false
        }

        Rectangle {
            id: scalebox
            x: Math.min(handle1.x, handle2.x)
            y: Math.min(handle1.y, handle2.y)
            width: Math.abs(handle1.x - handle2.x)
            height: Math.abs(handle1.y - handle2.y)
            border.color: "black"
            color: "#00FFFFFF"
            antialiasing: true
            Text {
                visible: parent.width > 3 && parent.height > 3
                anchors.bottom: parent.top
                anchors.left: parent.left
                text: (parent.width / image.width * minimap.imageWidth / image.scale * 1000000).toFixed(1) + " \u03bcm"
            }
            Text {
                visible: parent.width > 3 && parent.height > 3
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                text: (parent.height / image.height * minimap.imageHeight / image.scale * 1000000).toFixed(1) + " \u03bcm"
                rotation: -90
                transformOrigin: Item.BottomLeft
            }
        }

        // Drag and zoom. The default drag handler is left click.
        DragHandler {
            target: image
            snapMode: DragHandler.NoSnap
        }
        WheelHandler {
            target: image
            property: "scale"
        }

        // The minimap is defined in Python.
        Minimap {
            id: minimap
            height: 200
            width: 500
            anchors.left: parent.left
            anchors.bottom: status.top
            // Forward clicks to the minimap.
            MouseArea {
                anchors.fill: parent
                onClicked: function(e) {
                    minimap.clicked(e.x, e.y);
                }
            }
            onImagePathChanged: scalebox.visible = false
        }

        // Status bar.
        Rectangle {
            id: status
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            width: childrenRect.width
            height: childrenRect.height
            color: "#88FFFFFF"
            Text {
                text: image.source + " " + image.width + "x" + image.height + " | " + (minimap.totalWidth * 1000).toFixed(1) + " mm x " + (minimap.totalHeight * 1000).toFixed(1) + " mm in total | Stage X: " + (minimap.positionX * 1000).toFixed(4) + " mm, Y: " + (minimap.positionY * 1000).toFixed(4) + " mm"
            }
        }
    }

    // Clicking anywhere random in the image should give it focus.
    MouseArea {
        anchors.fill: captarget
        propagateComposedEvents: true
        onClicked: function(e) {
            captarget.focus = true;
            e.accepted = false;
        }
    }


    // All the buttons and such on the bottom-right.
    ColumnLayout {
        id: controls
        anchors.right: parent.right
        anchors.bottom: parent.bottom

        RowLayout {
            Button {
                text: "Open"
                onClicked: loaddialog.open()
            }
            Button {
                text: "Capture"
                enabled: minimap.loaded
                onClicked: {
                    captarget.grabToImage(function(result) {
                        minimap.capture(
                            capturefolder.text,
                            captureprefix.text,
                            result.image);
                    });
                    captarget.focus = true;
                }
            }
            Button {
                text: "Reset zoom/pan"
                enabled: minimap.loaded
                onClicked: {
                    image.scale = image.defaultScale();
                    image.x = 0;
                    image.y = 0;
                    captarget.focus = true;
                }
            }
        }

        GroupBox {
            title: "Capture settings"
            Layout.fillWidth: true
            GridLayout {
                columns: 2
                anchors.fill: parent
                Text { text: "Save path" }
                RowLayout {
                    TextField {
                        id: capturefolder
                        selectByMouse: true
                        Layout.fillWidth: true
                        Settings {
                            category: "capture"
                            property alias folder: capturefolder.text
                        }
                    }
                    Button {
                        text: "Browse"
                        onClicked: capturedialog.open()
                    }
                }
                Text { text: "Prefix" }
                TextField {
                    id: captureprefix
                    selectByMouse: true
                    Layout.fillWidth: true
                    Settings {
                        category: "capture"
                        property alias prefix: captureprefix.text
                    }
                }
            }
        }

        GroupBox {
            title: "Histogram"
            ColumnLayout {
                // The histogram is defined in Python.
                Histogram {
                    source: minimap.imagePath
                    width: 300
                    height: 50
                }
                RangeSlider {
                    id: lutslider
                    enabled: minimap.loaded
                    Layout.fillWidth: true
                    from: 0
                    to: 1
                    first.value: 0
                    second.value: 1
                    stepSize: 0.01
                }
            }
        }
    }

    FolderDialog {
        id: capturedialog
        onAccepted: capturefolder.text = selectedFolder
    }

    FolderDialog {
        id: loaddialog
        onAccepted: {
            minimap.load(selectedFolder);
            captarget.focus = true;
        }
        Settings {
            category: "load"
            property alias folder: loaddialog.currentFolder
        }
    }
}
