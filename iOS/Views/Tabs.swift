import SwiftUI

// MARK: - VITALS

struct VitalsTab: View {
    @EnvironmentObject private var store: AppStore
    private let spark = Array("▁▂▃▄▅▆▇█")

    var body: some View {
        TermPage {
            deviceSection
            TermText("")
            TermText("THIS PHONE", .dim)
            let p = store.phone
            line(gaugeLine("BATTERY", p.battery.map { Double($0) }, p.battery.map { "\($0)%" + (p.charging ? " +" : "") } ?? ""))
            line(gaugeLine("THERMAL", p.thermalPercent, p.thermal))
            if p.diskTotal > 0 {
                line(gaugeLine("STORAGE", Double(p.diskTotal - p.diskFree) / Double(p.diskTotal) * 100, human(p.diskFree) + " FREE"))
            }
            TermText("UPTIME    " + uptimeString(p.uptime))
        }
    }

    @ViewBuilder private var deviceSection: some View {
        TermText(store.deviceName, .dim)
        switch store.linkState {
        case .notPaired:
            TermText("NOT PAIRED.", .warn)
            TermText("OPEN [SETUP] OR SCAN THE PAIRING CODE IN SETTINGS > PHONE LINK ON THE HANDHELD.", .dim)
        case .connecting:
            TermText("CONNECTING...", .dim)
        case .offline(let reason):
            TermText("LINK OFFLINE", .bad)
            TermText(reason, .dim)
        case .online:
            if let s = store.status {
                let v = s.vitals
                let bat = v.battery.map { Double($0) }
                line(gaugeLine("BATTERY", bat, v.battery.map { "\($0)%" + (v.charging ? " +" : "") } ?? ""))
                line(gaugeLine("CPU TEMP", v.temp.map { min(100, $0 / 85 * 100) }, v.temp.map { String(format: "%.0f°C", $0) } ?? ""))
                line(gaugeLine("CPU LOAD", v.load, String(format: "%.0f%%", v.load)))
                if let used = v.memUsed, let total = v.memTotal, total > 0 {
                    line(gaugeLine("MEMORY", Double(used) / Double(total) * 100, "\(human(used))/\(human(total))"))
                }
                if v.diskTotal > 0 {
                    line(gaugeLine("STORAGE", Double(v.diskTotal - v.diskFree) / Double(v.diskTotal) * 100, human(v.diskFree) + " FREE"))
                }
                TermText("UPTIME    " + uptimeString(v.uptime))
                TermText("LOAD 32S  " + store.loadHistory.map { String(spark[min(7, Int($0 / 100 * 8))]) }.joined(), .dim)
                TermText("CONDITION: " + s.condition, s.condition == "NOMINAL" ? .normal : .bad)
            }
        }
    }

    private func line(_ g: (String, LineStyle)) -> some View { TermText(g.0, g.1) }
}

// MARK: - CARGO

struct CargoTab: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        TermPage {
            let p = store.phone
            TermText("THIS PHONE", .dim)
            if p.diskTotal > 0 {
                let g = gaugeLine("STORAGE", Double(p.diskTotal - p.diskFree) / Double(p.diskTotal) * 100, human(p.diskFree) + " FREE")
                TermText(g.0, g.1)
            }
            TermText("")
            TermText(store.deviceName, .dim)
            if let s = store.status, store.linked {
                let v = s.vitals
                if v.diskTotal > 0 {
                    let g = gaugeLine("INTERNAL", Double(v.diskTotal - v.diskFree) / Double(v.diskTotal) * 100, human(v.diskFree) + " FREE")
                    TermText(g.0, g.1)
                }
                if s.drives.isEmpty {
                    TermText("NO USB CARGO.", .dim)
                }
                ForEach(s.drives) { d in
                    if d.mounted, let free = d.free, d.size > 0 {
                        let g = gaugeLine(String(d.name.prefix(9)), Double(d.size - free) / Double(d.size) * 100, human(free) + " FREE")
                        TermText(g.0, g.1)
                    } else {
                        TermText(String(d.name.prefix(9)).padding(toLength: 10, withPad: " ", startingAt: 0) + human(d.size) + " NOT MOUNTED", .warn)
                    }
                }
                TermText("MOUNT AND EJECT ON THE HANDHELD.", .dim)
            } else {
                TermText("PAIR AND CONNECT TO SEE ITS DRIVES.", .dim)
            }
        }
    }
}

// MARK: - LOGS

struct LogsTab: View {
    @EnvironmentObject private var store: AppStore
    @State private var section = 0
    @State private var openThread: String?
    @State private var playing: Tape?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 16) {
                sectionButton("MESSAGES", 0)
                sectionButton("HOLOTAPES", 1)
                Spacer()
            }
            .padding(.vertical, 6)
            if section == 0 {
                if let id = openThread, let row = store.threadRows.first(where: { $0.id == id }) {
                    ThreadView(row: row) { openThread = nil }
                } else {
                    TermPage {
                        ForEach(store.threadRows) { row in
                            TermOption(label: row.name, tag: row.unread > 0 ? "\(row.unread) NEW" : row.source,
                                       style: row.unread > 0 ? .warn : .normal) {
                                store.markRead(row.id)
                                openThread = row.id
                            }
                        }
                        if !store.linked {
                            TermText("THE HANDHELD'S THREADS APPEAR HERE WHEN LINKED.", .dim)
                        }
                    }
                }
            } else {
                TermPage {
                    ForEach(store.tapes) { t in
                        TermOption(label: t.name, tag: clockString(t.secs)) { playing = t }
                    }
                    if !store.linked {
                        TermText("BUILT-IN TAPES. LINK TO HEAR THE HANDHELD'S OWN LOGS.", .dim)
                    }
                }
            }
        }
        .sheet(item: $playing) { tape in
            TapePlayer(tape: tape).environmentObject(store).environment(\.termTheme, store.theme)
        }
    }

    private func sectionButton(_ title: String, _ i: Int) -> some View {
        Button {
            store.play("clack")
            section = i
            openThread = nil
        } label: {
            TermText(section == i ? "[\(title)]" : title, section == i ? .normal : .dim, bold: section == i).fixedSize()
        }
        .buttonStyle(.plain)
    }
}

struct ThreadView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.termTheme) private var theme
    let row: AppStore.ThreadRow
    let close: () -> Void
    @State private var draft = ""
    @FocusState private var typing: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Button(action: close) { TermText("< \(row.name) · \(row.source)", .dim).lineLimit(1) }
                .buttonStyle(.plain)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 3) {
                        if row.lines.isEmpty { TermText("NO MESSAGES YET.", .dim) }
                        ForEach(row.lines.indices, id: \.self) { i in
                            TermText(row.lines[i].text, row.lines[i].style).id(i)
                        }
                    }
                }
                .onAppear { proxy.scrollTo(row.lines.count - 1, anchor: .bottom) }
                .onChange(of: row.lines.count) { _, n in withAnimation { proxy.scrollTo(n - 1, anchor: .bottom) } }
            }
            HStack {
                TermText("YOU>").fixedSize()
                TextField("", text: $draft)
                    .font(.system(size: termFontSize, design: .monospaced))
                    .foregroundStyle(theme.bright)
                    .tint(theme.bright)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                    .focused($typing)
                    .submitLabel(.send)
                    .onSubmit(send)
                Button(action: send) { TermText("[SEND]", .normal, bold: true).fixedSize() }
                    .buttonStyle(.plain)
                    .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(.vertical, 6)
            .overlay(alignment: .top) { Rectangle().fill(theme.dim).frame(height: 1) }
        }
    }

    private func send() {
        store.send(draft, to: row.id)
        draft = ""
    }
}

/// Plays a holotape: spinning reels, a progress bar, and the log typing out.
struct TapePlayer: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    let tape: Tape
    @State private var typed = 0
    @State private var playing = true
    @State private var tick = 0
    private let timer = Timer.publish(every: 0.04, on: .main, in: .common).autoconnect()

    private var total: Int { max(1, tape.lines.reduce(0) { $0 + $1.count }) }
    private var done: Bool { typed >= total }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            TermText("HOLOTAPE // \(tape.name)", bold: true)
            TermRule()
            let spin = Array("|/-\\")
            let r = playing && !done ? String(spin[(tick / 3) % 4]) : "|"
            TermText("   ( \(r) )=========( \(r) )")
            let frac = Double(typed) / Double(total)
            TermText("[\(bar(frac * 100, width: 16))] \(clockString(Int(frac * Double(tape.secs))))/\(clockString(tape.secs))", .dim)
            TermText(done ? "END OF TAPE." : playing ? "> PLAYING" : "> PAUSED", done || !playing ? .warn : .normal)
            TermText("")
            ScrollView {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(visibleLines.indices, id: \.self) { i in TermText(visibleLines[i]) }
                }
            }
            Spacer()
            HStack {
                Button { toggle() } label: { TermText(done ? "[REPLAY]" : playing ? "[PAUSE]" : "[PLAY]", bold: true) }
                Button { store.play("clack"); dismiss() } label: { TermText("[EJECT]", .dim).frame(alignment: .trailing) }
            }
            .buttonStyle(.plain)
        }
        .padding(20)
        .background(Color.black.ignoresSafeArea())
        .presentationDetents([.large])
        .onAppear { store.play("clack") }
        .onReceive(timer) { _ in
            tick += 1
            guard playing, !done else { return }
            typed += 1
            if typed % 2 == 0 { store.play("type") }
            if done { store.play("clack") }
        }
    }

    private var visibleLines: [String] {
        var left = typed
        var out: [String] = []
        for line in tape.lines where left > 0 {
            out.append(String(line.prefix(left)))
            left -= line.count
        }
        return out
    }

    private func toggle() {
        store.play("clack")
        if done {
            typed = 0
            playing = true
        } else {
            playing.toggle()
        }
    }
}

// MARK: - SIGNAL

struct SignalTab: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        TermPage {
            TermText("LINK      " + store.linkState.label + (store.settings.link.map { " · \($0.host)" } ?? ""),
                     store.linked ? .normal : .warn)
            if let s = store.status, store.linked {
                TermText("TUNNEL    " + (s.vpn ?? "UNKNOWN"))
            }
            TermText("")
            TermText(store.linked ? "NODES (PINGED BY \(store.deviceName))" : "NODES (CHECKED BY THIS PHONE)", .dim)
            ForEach(store.nodeRows) { row in
                switch row.probe {
                case .checking:
                    TermText(pad(row.name) + "....  CHECKING", .dim)
                case .up(let ms):
                    TermText(pad(row.name) + signalBars(ms) + "  " + String(format: "%.0f MS", ms))
                case .down:
                    TermText(pad(row.name) + "----  OFFLINE", .bad)
                }
            }
            TermText("")
            TermOption(label: "PING ALL NOW") { store.pingNow() }
            if !store.linked {
                TermText("THE PHONE OPENS A CONNECTION TO EACH NODE (SSH PORT 22 BY DEFAULT). EDIT NODES IN [SETUP].", .dim)
            }
        }
    }

    private func pad(_ s: String) -> String { String(s.prefix(9)).padding(toLength: 10, withPad: " ", startingAt: 0) }
}
