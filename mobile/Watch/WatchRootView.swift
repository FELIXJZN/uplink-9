import SwiftUI
import WatchKit

/// Three tabs, nothing to scroll: turn the Digital Crown to switch, tap to refresh.
struct WatchRootView: View {
    @EnvironmentObject private var store: WatchStore
    @State private var crown = 0.0
    @State private var tab = 0

    private let tabs = ["STATUS", "NODES", "MSGS"]
    private let theme = TermTheme()

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                TermText(tabs[tab], bold: true)
                TermText(store.requesting ? "..." : (store.snapshot?.link ?? "WAITING"), store.snapshot?.link == "ONLINE" ? .dim : .warn)
                    .fixedSize()
            }
            Rectangle().fill(theme.dim).frame(height: 1)

            Group {
                switch tab {
                case 0: statusTab
                case 1: nodesTab
                default: messagesTab
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

            HStack(spacing: 5) {
                Spacer()
                ForEach(tabs.indices, id: \.self) { i in
                    Circle().fill(i == tab ? theme.bright : theme.dim).frame(width: 5, height: 5)
                }
                Spacer()
            }
        }
        .padding(.horizontal, 4)
        .background(Color.black.ignoresSafeArea())
        .environment(\.termTheme, theme)
        .focusable()
        .digitalCrownRotation($crown, from: 0, through: Double(tabs.count - 1), by: 1,
                              sensitivity: .low, isContinuous: true, isHapticFeedbackEnabled: true)
        .onChange(of: crown) { _, value in
            let next = ((Int(value.rounded()) % tabs.count) + tabs.count) % tabs.count
            if next != tab { tab = next }
        }
        .onTapGesture { store.requestRefresh() }
        .accessibilityAction(named: "Next tab") {
            tab = (tab + 1) % tabs.count
            crown = Double(tab)
        }
    }

    // MARK: tabs

    @ViewBuilder private var statusTab: some View {
        if let s = store.snapshot {
            TermText(s.device, .dim)
            TermText(s.condition, s.condition == "NOMINAL" ? .normal : (s.condition == "NO LINK" ? .warn : .bad), bold: true)
            if let b = s.battery { TermText("BAT  [\(bar(Double(b), width: 6))] \(b)%", b < 15 ? .bad : (b < 25 ? .warn : .normal)) }
            if let t = s.temp { TermText(String(format: "TEMP %.0f°C", t), t >= 75 ? .bad : .normal) }
            if let l = s.load { TermText("LOAD [\(bar(l, width: 6))] \(Int(l))%") }
        } else {
            TermText("OPEN UPLINK-9 ON", .dim)
            TermText("YOUR IPHONE ONCE.", .dim)
        }
        Spacer(minLength: 2)
        let updated = store.snapshot.map { " · " + $0.updated.formatted(date: .omitted, time: .shortened) } ?? ""
        TermText("WATCH \(store.watchBattery.map { "\($0)%" } ?? "--")" + updated, .dim)
    }

    @ViewBuilder private var nodesTab: some View {
        if let s = store.snapshot, !s.nodes.isEmpty {
            let up = s.nodes.filter { $0.up == true }.count
            TermText("\(up)/\(s.nodes.count) ONLINE", up == s.nodes.count ? .normal : .warn, bold: true)
            ForEach(s.nodes.prefix(4)) { n in
                let name = String(n.name.prefix(7)).padding(toLength: 8, withPad: " ", startingAt: 0)
                switch n.up {
                case .some(true): TermText(name + signalBars(n.ms))
                case .some(false): TermText(name + "DOWN", .bad)
                case .none: TermText(name + "....", .dim)
                }
            }
            if s.nodes.count > 4 { TermText("+\(s.nodes.count - 4) MORE", .dim) }
        } else {
            TermText("NO NODES YET.", .dim)
        }
    }

    @ViewBuilder private var messagesTab: some View {
        if let s = store.snapshot, !s.messages.isEmpty {
            ForEach(s.messages.suffix(3)) { m in
                TermText(m.text, m.text.hasPrefix("YOU>") ? .dim : .normal)
                    .lineLimit(2)
            }
        } else {
            TermText("NO MESSAGES.", .dim)
        }
    }
}
