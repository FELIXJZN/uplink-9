import SwiftUI

/// Settings: pairing, nodes, ntfy, look and sound.
struct SetupView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.termTheme) private var theme
    @Environment(\.dismiss) private var dismiss

    @State private var host = ""
    @State private var port = "8909"
    @State private var token = ""
    @State private var nodeName = ""
    @State private var nodeHost = ""
    @State private var nodePort = "22"
    @State private var ntfy = ""
    @State private var confirmUnpair = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                TermText("SETUP", bold: true)
                Button {
                    store.play("blip")
                    dismiss()
                } label: { TermText("[DONE]", bold: true).fixedSize() }
                .buttonStyle(.plain)
            }
            TermRule()
            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    linkSection
                    TermText("")
                    nodesSection
                    TermText("")
                    ntfySection
                    TermText("")
                    lookSection
                    TermText("")
                    TermText("UPLINK-9 MOBILE \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "")", .dim)
                }
            }
            .scrollIndicators(.hidden)
        }
        .padding(20)
        .background(Color.black.ignoresSafeArea())
        .onAppear { ntfy = store.settings.ntfyURL }
        .confirmationDialog("Unpair from \(store.deviceName)?", isPresented: $confirmUnpair, titleVisibility: .visible) {
            Button("Unpair", role: .destructive) { store.unpair() }
        } message: {
            Text("The phone stops reading the handheld until you pair again.")
        }
    }

    // MARK: sections

    @ViewBuilder private var linkSection: some View {
        TermText("HANDHELD LINK", .dim)
        if let link = store.settings.link {
            TermText("PAIRED WITH \(link.name)")
            TermText("\(link.host):\(link.port) · \(store.linkState.label)", store.linked ? .dim : .warn)
            TermOption(label: "CHECK NOW") { Task { await store.refresh(full: true) } }
            TermOption(label: "UNPAIR", style: .bad) { confirmUnpair = true }
        } else {
            TermText("ON THE HANDHELD: SETTINGS > PHONE LINK > SHOW PAIRING CODE, THEN SCAN IT WITH THE CAMERA APP.", .dim)
            TermText("OR TYPE IT IN:", .dim)
            field("ADDRESS", text: $host, keyboard: .URL)
            field("PORT", text: $port, keyboard: .numberPad)
            field("TOKEN", text: $token, keyboard: .asciiCapable, secure: true)
            TermOption(label: "PAIR") {
                guard !host.isEmpty, !token.isEmpty else {
                    store.showToast("ADDRESS AND TOKEN ARE NEEDED")
                    return
                }
                store.pair(LinkConfig(host: host.trimmingCharacters(in: .whitespaces), port: Int(port) ?? 8909,
                                      token: token.trimmingCharacters(in: .whitespaces), name: "UPLINK-9"))
                token = ""
            }
        }
    }

    @ViewBuilder private var nodesSection: some View {
        TermText("NODES (USED WHEN NOT LINKED)", .dim)
        ForEach(store.settings.nodes) { n in
            HStack {
                TermText("\(n.name)  \(n.host):\(n.port)")
                Button {
                    store.play("clack")
                    store.settings.nodes.removeAll { $0.id == n.id }
                } label: { TermText("[X]", .bad).fixedSize() }
                .buttonStyle(.plain)
                .accessibilityLabel("Remove \(n.name)")
            }
        }
        field("NAME", text: $nodeName, keyboard: .asciiCapable)
        field("HOST", text: $nodeHost, keyboard: .URL)
        field("PORT", text: $nodePort, keyboard: .numberPad)
        TermOption(label: "ADD NODE") {
            guard !nodeHost.isEmpty else {
                store.showToast("A HOST IS NEEDED")
                return
            }
            store.settings.nodes.append(NodeConfig(name: (nodeName.isEmpty ? nodeHost : nodeName).uppercased(),
                                                   host: nodeHost, port: Int(nodePort) ?? 22))
            nodeName = ""
            nodeHost = ""
            nodePort = "22"
            Task { await store.probeNodesIfNeeded(force: true) }
        }
    }

    @ViewBuilder private var ntfySection: some View {
        TermText("NTFY TOPIC (TWO-WAY MESSAGES FROM THE PHONE)", .dim)
        field("URL", text: $ntfy, keyboard: .URL)
        TermOption(label: "SAVE TOPIC", tag: store.settings.ntfyURL.isEmpty ? "OFF" : "ON") {
            let value = ntfy.trimmingCharacters(in: .whitespaces)
            guard value.isEmpty || value.hasPrefix("https://") || value.hasPrefix("http://") else {
                store.showToast("USE A FULL URL, LIKE HTTPS://NTFY.SH/YOUR-TOPIC")
                return
            }
            store.settings.ntfyURL = value
            store.syncNtfyThread()
            store.showToast(value.isEmpty ? "NTFY OFF" : "NTFY THREAD ADDED TO LOGS")
        }
    }

    @ViewBuilder private var lookSection: some View {
        TermText("LOOK AND SOUND", .dim)
        TermOption(label: "DISPLAY COLOR", tag: store.settings.plain ? "GREEN (PLAIN)" : store.settings.color.rawValue.uppercased()) {
            let all = Phosphor.allCases
            let i = all.firstIndex(of: store.settings.color) ?? 0
            store.settings.color = all[(i + 1) % all.count]
        }
        TermOption(label: "PLAIN MODE (REALISM)", tag: store.settings.plain ? "ON" : "OFF") { store.settings.plain.toggle() }
        TermOption(label: "SOUNDS", tag: store.settings.sounds ? "ON" : "OFF") { store.settings.sounds.toggle() }
        TermOption(label: "HAPTICS", tag: store.settings.haptics ? "ON" : "OFF") { store.settings.haptics.toggle() }
    }

    // MARK: helpers

    private func field(_ label: String, text: Binding<String>, keyboard: UIKeyboardType, secure: Bool = false) -> some View {
        HStack(spacing: 8) {
            TermText(label.padding(toLength: 8, withPad: " ", startingAt: 0), .dim).fixedSize()
            Group {
                if secure {
                    SecureField("", text: text)
                } else {
                    TextField("", text: text)
                }
            }
            .font(.system(size: termFontSize, design: .monospaced))
            .foregroundStyle(theme.bright)
            .tint(theme.bright)
            .keyboardType(keyboard)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .padding(.vertical, 6)
            .overlay(alignment: .bottom) { Rectangle().fill(theme.dim).frame(height: 1) }
        }
    }
}

/// Shown when the camera opens an uplink9:// pairing link.
struct PairView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    let config: LinkConfig

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            TermText("PAIRING CODE RECEIVED", .warn, bold: true)
            TermRule()
            TermText("DEVICE    \(config.name)")
            TermText("ADDRESS   \(config.host):\(config.port)")
            TermText("")
            TermText("THIS PHONE WILL READ THE HANDHELD'S STATUS AND CAN SEND MESSAGES THROUGH IT.", .dim)
            TermText("")
            TermOption(label: "PAIR") {
                store.pair(config)
                dismiss()
            }
            TermOption(label: "CANCEL", style: .dim) { dismiss() }
            Spacer()
        }
        .padding(20)
        .background(Color.black.ignoresSafeArea())
        .presentationDetents([.medium])
    }
}
