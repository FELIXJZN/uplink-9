import Foundation
import SwiftUI
import UIKit

struct LocalMessage: Codable, Equatable, Identifiable {
    var id = UUID()
    var me: Bool
    var text: String
    var at: Date
    var status: String
}

struct LocalThread: Codable, Equatable, Identifiable {
    var id: String
    var name: String
    var msgs: [LocalMessage]
    var unread = 0
}

/// A spot you saved on the map. Vikunja tasks with a label of the same name appear here.
struct Place: Codable, Equatable, Identifiable {
    var id = UUID()
    var name: String
    var lat: Double
    var lon: Double
}

/// A task pinned from the phone (kept on the phone, Vikunja is not changed).
struct QuestPin: Codable, Equatable {
    var lat: Double
    var lon: Double
    var place: String?
}

struct AppSettings: Codable, Equatable {
    var link: LinkConfig?
    var nodes: [NodeConfig] = NodeConfig.defaults
    var ntfyURL = ""
    var color: Phosphor = .green
    var plain = false
    var sounds = true
    var haptics = true
    // PERSONAL tab
    var vikunjaURL = ""
    var vikunjaProject = 0          // 0 = all projects
    var places: [Place] = []
    var questPins: [String: QuestPin] = [:]
    var nearbyAlerts = true

    init() {}

    /// Every field is optional when reading, so settings saved by an older version still load
    /// (and the pairing survives the update).
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let d = AppSettings()
        link = try c.decodeIfPresent(LinkConfig.self, forKey: .link)
        nodes = try c.decodeIfPresent([NodeConfig].self, forKey: .nodes) ?? d.nodes
        ntfyURL = try c.decodeIfPresent(String.self, forKey: .ntfyURL) ?? d.ntfyURL
        color = (try? c.decodeIfPresent(Phosphor.self, forKey: .color)) ?? d.color
        plain = try c.decodeIfPresent(Bool.self, forKey: .plain) ?? d.plain
        sounds = try c.decodeIfPresent(Bool.self, forKey: .sounds) ?? d.sounds
        haptics = try c.decodeIfPresent(Bool.self, forKey: .haptics) ?? d.haptics
        vikunjaURL = try c.decodeIfPresent(String.self, forKey: .vikunjaURL) ?? d.vikunjaURL
        vikunjaProject = try c.decodeIfPresent(Int.self, forKey: .vikunjaProject) ?? d.vikunjaProject
        places = try c.decodeIfPresent([Place].self, forKey: .places) ?? d.places
        questPins = try c.decodeIfPresent([String: QuestPin].self, forKey: .questPins) ?? d.questPins
        nearbyAlerts = try c.decodeIfPresent(Bool.self, forKey: .nearbyAlerts) ?? d.nearbyAlerts
    }
}

enum LinkState: Equatable {
    case notPaired, connecting, online, offline(String)

    var label: String {
        switch self {
        case .notPaired: return "NOT PAIRED"
        case .connecting: return "CONNECTING"
        case .online: return "ONLINE"
        case .offline: return "OFFLINE"
        }
    }
}

enum Probe: Equatable { case checking, up(Double), down }

struct NodeRow: Identifiable {
    var name: String
    var detail: String
    var probe: Probe
    var id: String { name }
}

/// Everything the app shows. Works on its own; when paired and reachable, the handheld's data wins.
@MainActor
final class AppStore: ObservableObject {
    @Published var settings: AppSettings { didSet { if settings != oldValue { saveSettings() } } }
    @Published private(set) var linkState: LinkState = .notPaired
    @Published private(set) var status: DeviceStatus?
    @Published private(set) var deviceThreads: [MessageThread] = []
    @Published private(set) var deviceTapes: [Tape] = []
    @Published private(set) var localThreads: [LocalThread]
    @Published private(set) var phone = PhoneReading()
    @Published private(set) var probes: [UUID: Probe] = [:]
    @Published private(set) var loadHistory: [Double] = []
    @Published var toast: String?
    @Published var pendingPair: LinkConfig?

    private let sound = SoundPlayer()
    private let watch = WatchBridge()
    private let defaults = UserDefaults.standard
    private var timer: Timer?
    private var tick = 0
    private var ntfySince = "10m"
    private var ntfySent: Set<String> = []
    private var refreshing = false

    static let notesID = "phone-notes"
    static let ntfyID = "phone-ntfy"

    init() {
        let ud = UserDefaults.standard
        let saved = ud.data(forKey: "settings").flatMap { try? JSONDecoder().decode(AppSettings.self, from: $0) } ?? AppSettings()
        settings = saved
        localThreads = ud.data(forKey: "threads").flatMap { try? JSONDecoder().decode([LocalThread].self, from: $0) }
            ?? [LocalThread(id: Self.notesID, name: "PHONE NOTES", msgs: [])]
        linkState = saved.link == nil ? .notPaired : .connecting
        watch.onRefreshRequest = { [weak self] in Task { await self?.refresh(full: true) } }
        watch.activate()
    }

    var theme: TermTheme { TermTheme(phosphor: settings.color, plain: settings.plain) }
    var linked: Bool { linkState == .online && status != nil }
    var deviceName: String { status?.device ?? settings.link?.name ?? "UPLINK-9" }

    // MARK: life cycle

    func start() {
        guard timer == nil else { return }
        play("hum")
        phone = PhoneVitals.read()
        Task { await refresh(full: true) }
        Task { await probeNodesIfNeeded(force: true) }
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.step() }
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    private func step() async {
        tick += 1
        phone = PhoneVitals.read()
        if tick % 2 == 0 { await refresh(full: tick % 10 == 0) }
        if tick % 10 == 5 { await probeNodesIfNeeded(force: false) }
        if tick % 10 == 3 { await pollNtfy() }
        pushToWatch()
    }

    // MARK: handheld link

    func refresh(full: Bool) async {
        guard let config = settings.link, !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        let client = LinkClient(config: config)
        do {
            let s = try await client.status()
            let wasOnline = linkState == .online
            status = s
            linkState = .online
            loadHistory = Array((loadHistory + [s.vitals.load]).suffix(32))
            if full || !wasOnline {
                deviceThreads = try await client.messages()
                deviceTapes = try await client.tapes()
            }
            if !wasOnline { play("chirp") }
        } catch {
            let text = (error as? LocalizedError)?.errorDescription ?? "CAN'T REACH THE DEVICE"
            if linkState == .online { play("buzz") }
            linkState = .offline(text)
        }
        pushToWatch()
    }

    func handle(url: URL) {
        if let config = LinkConfig(url: url) {
            pendingPair = config
            play("chirp")
        } else {
            showToast("THAT LINK IS NOT AN UPLINK-9 PAIRING CODE")
        }
    }

    func pair(_ config: LinkConfig) {
        settings.link = config
        pendingPair = nil
        status = nil
        linkState = .connecting
        loadHistory = []
        Task { await refresh(full: true) }
    }

    func unpair() {
        settings.link = nil
        status = nil
        deviceThreads = []
        deviceTapes = []
        linkState = .notPaired
        Task { await probeNodesIfNeeded(force: true) }
    }

    // MARK: nodes

    /// What SIGNAL shows: the handheld's pings when linked, the phone's own TCP checks otherwise.
    var nodeRows: [NodeRow] {
        if linked, let s = status {
            return s.nodes.map { n -> NodeRow in
                let p: Probe = n.up == nil ? .checking : (n.up == true ? .up(n.ms ?? 0) : .down)
                return NodeRow(name: n.name, detail: n.host, probe: p)
            }
        }
        return settings.nodes.map { NodeRow(name: $0.name, detail: "\($0.host):\($0.port)", probe: probes[$0.id] ?? .checking) }
    }

    func probeNodesIfNeeded(force: Bool) async {
        guard force || !linked else { return }
        let nodes = settings.nodes
        await withTaskGroup(of: (UUID, Double?).self) { group in
            for n in nodes {
                group.addTask { (n.id, await NodeProbe.check(host: n.host, port: n.port)) }
            }
            for await (id, ms) in group {
                probes[id] = ms.map { Probe.up($0) } ?? Probe.down
            }
        }
    }

    func pingNow() {
        play("blip")
        Task {
            await refresh(full: false)
            await probeNodesIfNeeded(force: true)
            showToast("NODES CHECKED")
        }
    }

    // MARK: messages

    struct ThreadRow: Identifiable {
        var id: String
        var name: String
        var source: String
        var unread: Int
        var lines: [(text: String, style: LineStyle)]
    }

    private static func line(me: Bool, text: String, status: String, from: String) -> (text: String, style: LineStyle) {
        if me {
            let failed = status == "FAILED"
            return ("YOU> " + text + (failed ? "  [FAILED]" : ""), failed ? LineStyle.bad : LineStyle.dim)
        }
        return (String(from.prefix(10)) + "> " + text, LineStyle.normal)
    }

    var threadRows: [ThreadRow] {
        var rows: [ThreadRow] = []
        if linked {
            for t in deviceThreads {
                let lines = t.msgs.map { m in Self.line(me: m.me, text: m.t, status: m.status, from: t.name) }
                rows.append(ThreadRow(id: "device:" + t.id, name: t.name, source: deviceName, unread: t.unread, lines: lines))
            }
        }
        for t in localThreads {
            let lines = t.msgs.map { m in Self.line(me: m.me, text: m.text, status: m.status, from: "NTFY") }
            rows.append(ThreadRow(id: "local:" + t.id, name: t.name, source: t.id == Self.ntfyID ? "NTFY" : "PHONE",
                                  unread: t.unread, lines: lines))
        }
        return rows
    }

    func markRead(_ rowID: String) {
        if rowID.hasPrefix("local:"), let i = localThreads.firstIndex(where: { "local:" + $0.id == rowID }), localThreads[i].unread > 0 {
            localThreads[i].unread = 0
            saveThreads()
        }
    }

    func send(_ text: String, to rowID: String) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        play("ok")
        if rowID.hasPrefix("device:"), let config = settings.link {
            let threadID = String(rowID.dropFirst("device:".count))
            Task {
                do {
                    try await LinkClient(config: config).send(text, thread: threadID)
                    deviceThreads = (try? await LinkClient(config: config).messages()) ?? deviceThreads
                } catch {
                    play("buzz")
                    showToast("NOT SENT: " + ((error as? LocalizedError)?.errorDescription ?? "ERROR"))
                }
            }
            return
        }
        guard let i = localThreads.firstIndex(where: { "local:" + $0.id == rowID }) else { return }
        let isNtfy = localThreads[i].id == Self.ntfyID
        let message = LocalMessage(me: true, text: text, at: Date(), status: isNtfy ? "SENDING" : "LOCAL")
        localThreads[i].msgs.append(message)
        saveThreads()
        guard isNtfy else { return }
        let url = settings.ntfyURL
        Task {
            var status = "SENT"
            do {
                if let id = try await Ntfy.send(text, topicURL: url) { ntfySent.insert(id) }
            } catch {
                status = "FAILED"
                play("buzz")
            }
            if let t = localThreads.firstIndex(where: { $0.id == Self.ntfyID }),
               let m = localThreads[t].msgs.firstIndex(where: { $0.id == message.id }) {
                localThreads[t].msgs[m].status = status
                saveThreads()
            }
        }
    }

    /// Adds or removes the NTFY thread when the topic setting changes.
    func syncNtfyThread() {
        let has = localThreads.contains { $0.id == Self.ntfyID }
        if !settings.ntfyURL.isEmpty && !has {
            localThreads.append(LocalThread(id: Self.ntfyID, name: "NTFY", msgs: []))
        } else if settings.ntfyURL.isEmpty && has {
            localThreads.removeAll { $0.id == Self.ntfyID }
        }
        saveThreads()
    }

    private func pollNtfy() async {
        guard !settings.ntfyURL.isEmpty,
              let new = try? await Ntfy.poll(topicURL: settings.ntfyURL, since: ntfySince),
              let i = localThreads.firstIndex(where: { $0.id == Self.ntfyID }) else { return }
        if let last = new.last { ntfySince = last.id }
        let incoming = new.filter { !ntfySent.contains($0.id) }
        guard !incoming.isEmpty else { return }
        for m in incoming {
            localThreads[i].msgs.append(LocalMessage(me: false, text: m.message ?? "", at: Date(timeIntervalSince1970: Double(m.time)), status: ""))
        }
        localThreads[i].unread += incoming.count
        saveThreads()
        play("chirp")
        showToast("NEW NTFY MESSAGE")
    }

    // MARK: tapes

    var tapes: [Tape] { linked && !deviceTapes.isEmpty ? deviceTapes : Tape.builtins }

    // MARK: watch

    private func pushToWatch() {
        let messages: [WatchMessage] = threadRows
            .flatMap { row in row.lines.map { WatchMessage(from: row.name, text: $0.text) } }
            .suffix(3)
            .map { $0 }
        let snapshot = WatchSnapshot(
            device: deviceName,
            link: linkState.label,
            condition: linked ? (status?.condition ?? "NOMINAL") : "NO LINK",
            battery: linked ? status?.vitals.battery : nil,
            temp: linked ? status?.vitals.temp : nil,
            load: linked ? status?.vitals.load : nil,
            nodes: nodeRows.map { row -> WatchNode in
                switch row.probe {
                case .checking: return WatchNode(name: row.name, up: nil, ms: nil)
                case .up(let ms): return WatchNode(name: row.name, up: true, ms: ms)
                case .down: return WatchNode(name: row.name, up: false, ms: nil)
                }
            },
            messages: messages,
            phoneBattery: phone.battery,
            updated: Date())
        watch.send(snapshot)
    }

    // MARK: feedback

    func play(_ name: String) {
        guard !settings.plain else { return }
        if settings.sounds { sound.play(name) }
    }

    func tapFeedback() {
        guard settings.haptics else { return }
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }

    func showToast(_ text: String) {
        toast = text
        Task {
            try? await Task.sleep(nanoseconds: 3_500_000_000)
            if toast == text { toast = nil }
        }
    }

    // MARK: storage

    private func saveSettings() {
        if let d = try? JSONEncoder().encode(settings) { defaults.set(d, forKey: "settings") }
    }

    private func saveThreads() {
        for i in localThreads.indices where localThreads[i].msgs.count > 300 {
            localThreads[i].msgs.removeFirst(localThreads[i].msgs.count - 300)
        }
        if let d = try? JSONEncoder().encode(localThreads) { defaults.set(d, forKey: "threads") }
    }
}
