import SwiftUI

/// The terminal frame: title bar, tab strip, swipeable tabs, status footer.
struct RootView: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var quests: QuestStore
    @Environment(\.scenePhase) private var phase
    @State private var tab = 0
    @State private var showSetup = false

    static let tabs = ["VITALS", "CARGO", "LOGS", "SIGNAL", "PERSONAL"]
    static let personal = 4

    var body: some View {
        let theme = store.theme
        VStack(spacing: 0) {
            header
            tabStrip
            TermRule()
            Group {
                switch tab {
                case 0: VitalsTab()
                case 1: CargoTab()
                case 2: LogsTab()
                case 3: SignalTab()
                default: PersonalTab()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            // swipe sideways to change tab, except on PERSONAL where a swipe pans the map
            .simultaneousGesture(DragGesture(minimumDistance: 40).onEnded { g in
                guard tab != Self.personal, abs(g.translation.width) > 80,
                      abs(g.translation.width) > abs(g.translation.height) * 1.5 else { return }
                let next = tab + (g.translation.width < 0 ? 1 : -1)
                if (0..<Self.tabs.count).contains(next) { withAnimation(.easeOut(duration: 0.15)) { tab = next } }
            })
            TermRule()
            footer
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(Color.black.ignoresSafeArea())
        .overlay { if !theme.plain { Scanlines().ignoresSafeArea() } }
        .overlay(alignment: .top) { toast }
        .environment(\.termTheme, theme)
        .onChange(of: tab) { _, _ in
            store.play("clack")
            store.tapFeedback()
        }
        .onChange(of: phase) { _, newPhase in
            if newPhase == .active { store.start() } else { store.stop() }
        }
        .onAppear {
            quests.app = store
            store.start()
        }
        .sheet(isPresented: $showSetup) {
            SetupView().environmentObject(store).environmentObject(quests).environment(\.termTheme, theme)
        }
        .sheet(item: $store.pendingPair) { config in
            PairView(config: config).environmentObject(store).environment(\.termTheme, theme)
        }
    }

    private var header: some View {
        HStack {
            TermText("\(store.deviceName) // FIELD LINK", bold: true)
            TimelineView(.everyMinute) { context in
                TermText(context.date.formatted(date: .omitted, time: .shortened))
                    .frame(width: 90, alignment: .trailing)
            }
        }
        .padding(.bottom, 6)
    }

    private var tabStrip: some View {
        HStack(spacing: 6) {
            ForEach(Self.tabs.indices, id: \.self) { i in
                Button {
                    withAnimation(.easeOut(duration: 0.15)) { tab = i }
                } label: {
                    TermText(i == tab ? "[\(Self.tabs[i])]" : Self.tabs[i], i == tab ? .normal : .dim, bold: i == tab)
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)
                }
                .buttonStyle(.plain)
            }
        }
        .accessibilityElement(children: .contain)
    }

    private var footer: some View {
        HStack {
            TermText("LINK: \(store.linkState.label)", store.linked ? .dim : .warn)
            Button {
                store.play("blip")
                showSetup = true
            } label: {
                TermText("[SETUP]", .normal, bold: true).frame(width: 80, alignment: .trailing)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Setup")
        }
    }

    @ViewBuilder private var toast: some View {
        if let text = store.toast {
            TermText(text, .warn)
                .padding(10)
                .background(Color.black.opacity(0.9))
                .overlay(Rectangle().stroke(store.theme.warn, lineWidth: 1))
                .padding(.horizontal, 16)
                .padding(.top, 44)
                .transition(.opacity)
                .onTapGesture { store.toast = nil }
        }
    }
}

/// A screen of terminal lines that scrolls when it doesn't fit.
struct TermPage<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 3) { content }
                .padding(.vertical, 6)
        }
        .scrollIndicators(.hidden)
    }
}

/// A tappable terminal option: "> LABEL          TAG"
struct TermOption: View {
    @Environment(\.termTheme) private var theme
    @EnvironmentObject private var store: AppStore
    let label: String
    var tag = ""
    var style: LineStyle = .normal
    let action: () -> Void

    var body: some View {
        Button {
            store.play("blip")
            store.tapFeedback()
            action()
        } label: {
            HStack {
                TermText("> " + label, style)
                if !tag.isEmpty { TermText(tag, .dim).fixedSize() }
            }
            .padding(.vertical, 6)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
