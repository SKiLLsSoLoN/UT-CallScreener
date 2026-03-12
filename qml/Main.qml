import QtQuick 2.12
import QtQuick.Controls 2.12
import QtQuick.Layouts 1.12
import QtMultimedia 5.12
import Lomiri.Components 1.3
import QtDBus 2.12

MainView {
    id: root
    objectName: "mainView"
    applicationName: "callscreener.yourname"
    width:  units.gu(45)
    height: units.gu(80)

    // ── State mirrored from daemon ──────────────────────────────────────────
    property string appState:      "idle"
    property string callerNum:     "—"
    property string callerName:    "Waiting…"
    property int    secondsLeft:   10
    property string recordingPath: ""

    // ── DBus connection to daemon ───────────────────────────────────────────
    DBusInterface {
        id: screenerDbus
        service: "com.yourname.CallScreener"
        path:    "/com/yourname/CallScreener"
        iface:   "com.yourname.CallScreener"
        bus:     DBus.SessionBus

        Component.onCompleted: {
            screenerDbus.connectToSignal("IncomingCall",   handleIncomingCall)
            screenerDbus.connectToSignal("StateChanged",   handleStateChanged)
            screenerDbus.connectToSignal("TimerTick",      handleTimerTick)
            screenerDbus.connectToSignal("RecordingReady", handleRecordingReady)
        }
    }

    function handleIncomingCall(number, name) {
        root.callerNum  = number
        root.callerName = name
        addLog("Incoming: " + number + " (" + name + ")", "warn")
    }
    function handleStateChanged(state) {
        root.appState = state
        addLog("State → " + state, "info")
        if (state === "idle") {
            root.callerNum     = "—"
            root.callerName    = "Waiting…"
            root.secondsLeft   = 10
            root.recordingPath = ""
        }
    }
    function handleTimerTick(secs)   { root.secondsLeft   = secs }
    function handleRecordingReady(p) {
        root.recordingPath   = p
        playbackAudio.source = "file://" + p
        addLog("Recording ready — tap ▶ to listen", "success")
    }

    function sendPlayReply(key) { screenerDbus.call("PlayReply",  [key]); addLog("Reply: " + key, "success") }
    function sendAccept()       { screenerDbus.call("AcceptCall", []);    addLog("Accepting call…", "success") }
    function sendHangUp()       { screenerDbus.call("HangUp",     []);    addLog("Hanging up…", "danger") }

    Audio { id: playbackAudio }

    ListModel { id: logModel }
    function addLog(msg, kind) {
        logModel.append({ time: Qt.formatTime(new Date(), "hh:mm:ss"), msg: msg, kind: kind || "info" })
    }

    // ── UI ───────────────────────────────────────────────────────────────────
    Page {
        anchors.fill: parent

        header: PageHeader {
            id: pageHeader
            title: "Call Screener"
            StyleHints { foregroundColor: "#7efff5"; backgroundColor: "#0e0e11"; dividerColor: "#2a2a35" }
        }

        Rectangle { anchors.fill: parent; color: "#0e0e11" }

        ScrollView {
            anchors { top: pageHeader.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
            contentWidth: parent.width

            ColumnLayout {
                width: parent.width
                spacing: units.gu(1.5)
                anchors { left: parent.left; right: parent.right; margins: units.gu(1.5) }

                Item { height: units.gu(1) }

                // ── Caller card ─────────────────────────────────────────────
                Rectangle {
                    Layout.fillWidth: true
                    height: callerCol.implicitHeight + units.gu(3)
                    color: "#17171c"
                    border.color: root.appState !== "idle" ? "#7efff5" : "#2a2a35"
                    border.width: 1; radius: units.gu(2)
                    Behavior on border.color { ColorAnimation { duration: 400 } }

                    ColumnLayout {
                        id: callerCol
                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: units.gu(1.5) }
                        spacing: units.gu(0.5)

                        Rectangle {
                            visible: root.callerName === "Unknown caller"
                            width: badgeRow.implicitWidth + units.gu(2); height: units.gu(3)
                            color: "#330d0d"; border.color: "#ff6b6b"; border.width: 1; radius: height/2
                            Row {
                                id: badgeRow; anchors.centerIn: parent; spacing: units.gu(0.5)
                                Rectangle {
                                    width: units.gu(0.8); height: width; radius: width/2
                                    color: "#ff6b6b"; anchors.verticalCenter: parent.verticalCenter
                                    SequentialAnimation on opacity {
                                        running: true; loops: Animation.Infinite
                                        NumberAnimation { to: 0.2; duration: 600 }
                                        NumberAnimation { to: 1.0; duration: 600 }
                                    }
                                }
                                Label { text: "UNKNOWN CALLER"; font.pixelSize: units.gu(1.3); letterSpacing: 2; color: "#ff6b6b" }
                            }
                        }

                        Label { text: root.callerNum;  font.pixelSize: units.gu(3.2); font.weight: Font.Bold; color: "#e8e8f0" }
                        Label { text: root.callerName; font.pixelSize: units.gu(1.4); color: "#6b6b80" }
                    }
                }

                // ── Status pill ─────────────────────────────────────────────
                Rectangle {
                    Layout.fillWidth: true; height: units.gu(5.5)
                    color: "#17171c"
                    border.color: {
                        if (["screening","playing_reply"].indexOf(root.appState) >= 0) return "#7efff5"
                        if (["listening","accepted"].indexOf(root.appState) >= 0)      return "#06d6a0"
                        if (root.appState === "auto_ending")                           return "#ff6b6b"
                        return "#2a2a35"
                    }
                    border.width: 1; radius: height/2
                    Behavior on border.color { ColorAnimation { duration: 300 } }

                    Row {
                        anchors { fill: parent; leftMargin: units.gu(2); rightMargin: units.gu(2) }
                        spacing: units.gu(1)

                        Label {
                            text: {
                                switch(root.appState) {
                                    case "idle":          return "Waiting for incoming call…"
                                    case "screening":     return "Playing greeting to caller…"
                                    case "listening":     return "Caller responding — recording…"
                                    case "playing_reply": return "Playing reply to caller…"
                                    case "complete":      return "Tap ▶ to hear caller · accept or hang up"
                                    case "accepted":      return "Call connected — you are live"
                                    case "auto_ending":   return "Playing 'call you back'…"
                                    case "ended":         return "Call ended"
                                    default:              return root.appState
                                }
                            }
                            font.pixelSize: units.gu(1.4); color: "#e8e8f0"; elide: Text.ElideRight
                            width: parent.width - timerLbl.implicitWidth - units.gu(3)
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Label {
                            id: timerLbl
                            text: root.appState === "listening" ? root.secondsLeft + "s" : ""
                            font.pixelSize: units.gu(2.4); font.weight: Font.Bold
                            color: "#ffd166"; anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }

                // ── Countdown bar ────────────────────────────────────────────
                Rectangle {
                    Layout.fillWidth: true; height: units.gu(0.6)
                    color: "#2a2a35"; radius: height/2
                    visible: root.appState === "listening"
                    Rectangle {
                        width: parent.width * (root.secondsLeft / 10)
                        height: parent.height; radius: parent.radius
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "#7efff5" }
                            GradientStop { position: 1.0; color: "#ffd166" }
                        }
                        Behavior on width { NumberAnimation { duration: 900 } }
                    }
                }

                // ── Reply buttons ─────────────────────────────────────────────
                Rectangle {
                    Layout.fillWidth: true
                    height: repliesCol.implicitHeight + units.gu(3)
                    color: "#17171c"; border.color: "#2a2a35"; border.width: 1; radius: units.gu(2)

                    ColumnLayout {
                        id: repliesCol
                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: units.gu(1.5) }
                        spacing: units.gu(1)

                        Label { text: "PLAY PROMPT TO CALLER"; font.pixelSize: units.gu(1.2); letterSpacing: 2; color: "#6b6b80" }

                        component ReplyBtn: Rectangle {
                            property string icon:     "❓"
                            property string label:    ""
                            property string replyKey: ""
                            Layout.fillWidth: true; height: units.gu(6)
                            color: "#0e0e11"; border.color: "#2a2a35"; border.width: 1; radius: units.gu(1.2)
                            opacity: (root.appState === "idle" || root.appState === "ended" || root.appState === "accepted") ? 0.3 : 1.0

                            Row {
                                anchors { fill: parent; leftMargin: units.gu(1.5); rightMargin: units.gu(1.5) }
                                spacing: units.gu(1)
                                Label { text: icon; font.pixelSize: units.gu(2.2); anchors.verticalCenter: parent.verticalCenter }
                                Label { text: label; font.pixelSize: units.gu(1.5); color: "#e8e8f0"; width: parent.width - units.gu(7); wrapMode: Text.WordWrap; anchors.verticalCenter: parent.verticalCenter }
                                Label { text: "▶"; font.pixelSize: units.gu(1.4); color: "#6b6b80"; anchors.verticalCenter: parent.verticalCenter }
                            }

                            MouseArea {
                                anchors.fill: parent
                                enabled: root.appState !== "idle" && root.appState !== "ended" && root.appState !== "accepted"
                                onClicked: sendPlayReply(replyKey)
                            }
                        }

                        ReplyBtn { icon: "❓"; label: "What are you calling about?";          replyKey: "what_calling" }
                        ReplyBtn { icon: "🙋"; label: "Who is this please?";                  replyKey: "who_is_this" }
                        ReplyBtn { icon: "📝"; label: "Please leave your name and number.";   replyKey: "leave_message" }
                        ReplyBtn { icon: "🚫"; label: "Not interested — remove this number."; replyKey: "not_interested" }
                        ReplyBtn { icon: "⏸";  label: "One moment, let me get someone.";     replyKey: "hold_on" }
                    }
                }

                // ── Caller recording playback ─────────────────────────────────
                Rectangle {
                    Layout.fillWidth: true; height: units.gu(7)
                    color: "#17171c"; border.color: "#06d6a0"; border.width: 1; radius: units.gu(2)
                    visible: root.recordingPath !== ""

                    Row {
                        anchors { fill: parent; leftMargin: units.gu(2); rightMargin: units.gu(2) }
                        spacing: units.gu(1.5)
                        Label { text: "🎙"; font.pixelSize: units.gu(2.5); anchors.verticalCenter: parent.verticalCenter }
                        ColumnLayout {
                            spacing: units.gu(0.3); anchors.verticalCenter: parent.verticalCenter
                            Label { text: "CALLER'S RESPONSE"; font.pixelSize: units.gu(1.1); letterSpacing: 2; color: "#06d6a0" }
                            Label { text: "Tap ▶ to play back"; font.pixelSize: units.gu(1.4); color: "#e8e8f0" }
                        }
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            width: units.gu(5); height: width; radius: width/2
                            color: playbackAudio.playbackState === Audio.PlayingState ? "#06d6a0" : "#1a3a28"
                            border.color: "#06d6a0"; border.width: 1
                            anchors.verticalCenter: parent.verticalCenter
                            Label {
                                anchors.centerIn: parent
                                text: playbackAudio.playbackState === Audio.PlayingState ? "⏹" : "▶"
                                font.pixelSize: units.gu(2)
                                color: playbackAudio.playbackState === Audio.PlayingState ? "#0e0e11" : "#06d6a0"
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: playbackAudio.playbackState === Audio.PlayingState ? playbackAudio.stop() : playbackAudio.play()
                            }
                        }
                    }
                }

                // ── Accept / Hang up ──────────────────────────────────────────
                RowLayout {
                    Layout.fillWidth: true; spacing: units.gu(1.2)

                    Rectangle {
                        Layout.fillWidth: true; height: units.gu(8)
                        color: "#0a2218"; border.color: "#06d6a0"; border.width: 1; radius: units.gu(1.8)
                        opacity: (root.appState === "idle" || root.appState === "accepted" || root.appState === "ended") ? 0.3 : 1.0
                        ColumnLayout { anchors.centerIn: parent; spacing: units.gu(0.3)
                            Label { text: "📞"; font.pixelSize: units.gu(2.8); Layout.alignment: Qt.AlignHCenter }
                            Label { text: "ACCEPT"; font.pixelSize: units.gu(1.3); color: "#06d6a0"; letterSpacing: 1; Layout.alignment: Qt.AlignHCenter }
                        }
                        MouseArea {
                            anchors.fill: parent
                            enabled: root.appState !== "idle" && root.appState !== "accepted" && root.appState !== "ended"
                            onClicked: sendAccept()
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true; height: units.gu(8)
                        color: "#2e0a0a"; border.color: "#ff6b6b"; border.width: 1; radius: units.gu(1.8)
                        opacity: (root.appState === "idle" || root.appState === "ended") ? 0.3 : 1.0
                        ColumnLayout { anchors.centerIn: parent; spacing: units.gu(0.3)
                            Label { text: "📵"; font.pixelSize: units.gu(2.8); Layout.alignment: Qt.AlignHCenter }
                            Label { text: "HANG UP"; font.pixelSize: units.gu(1.3); color: "#ff6b6b"; letterSpacing: 1; Layout.alignment: Qt.AlignHCenter }
                        }
                        MouseArea {
                            anchors.fill: parent
                            enabled: root.appState !== "idle" && root.appState !== "ended"
                            onClicked: sendHangUp()
                        }
                    }
                }

                // ── Event log ─────────────────────────────────────────────────
                Rectangle {
                    Layout.fillWidth: true; height: units.gu(14)
                    color: "#17171c"; border.color: "#2a2a35"; border.width: 1; radius: units.gu(2); clip: true

                    ListView {
                        id: logView
                        anchors { fill: parent; margins: units.gu(1.5) }
                        model: logModel
                        spacing: units.gu(0.4)
                        verticalLayoutDirection: ListView.BottomToTop
                        delegate: Row {
                            spacing: units.gu(1); width: logView.width
                            Label { text: model.time; font.pixelSize: units.gu(1.2); color: "#7efff5" }
                            Label {
                                text: model.msg; font.pixelSize: units.gu(1.3); wrapMode: Text.WordWrap
                                width: logView.width - units.gu(8)
                                color: model.kind === "success" ? "#06d6a0"
                                     : model.kind === "warn"    ? "#ffd166"
                                     : model.kind === "danger"  ? "#ff6b6b" : "#e8e8f0"
                            }
                        }
                        Component.onCompleted: logModel.append({ time: "--:--:--", msg: "Connecting to daemon…", kind: "info" })
                    }
                }

                Item { height: units.gu(1) }
            }
        }
    }
}
