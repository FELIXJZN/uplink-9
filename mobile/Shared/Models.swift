import Foundation

// MARK: - What the Uplink-9 phone link sends (see uplink/link.py in the uplink-9 repo)
// Decoded with .convertFromSnakeCase, so "disk_free" arrives as diskFree.

struct Vitals: Codable, Equatable {
    var battery: Int?
    var charging: Bool
    var temp: Double?
    var load: Double
    var memUsed: Int64?
    var memTotal: Int64?
    var diskFree: Int64
    var diskTotal: Int64
    var uptime: Int
}

struct DriveInfo: Codable, Equatable, Identifiable {
    var name: String
    var size: Int64
    var mounted: Bool
    var free: Int64?
    var id: String { name }
}

struct NodeInfo: Codable, Equatable, Identifiable {
    var name: String
    var host: String
    var role: String
    var up: Bool?
    var ms: Double?
    var id: String { name }
}

struct DeviceStatus: Codable, Equatable {
    var api: Int
    var device: String
    var version: String
    var time: Int
    var vitals: Vitals
    var condition: String
    var drives: [DriveInfo]
    var nodes: [NodeInfo]
    var vpn: String?
    var unread: Int
}

struct Message: Codable, Equatable {
    var me: Bool
    var t: String
    var at: Int
    var status: String
}

struct MessageThread: Codable, Equatable, Identifiable {
    var id: String
    var name: String
    var unread: Int
    var msgs: [Message]
}

struct MessagesResponse: Codable { var threads: [MessageThread] }

struct Tape: Codable, Equatable, Identifiable {
    var id: String
    var name: String
    var secs: Int
    var lines: [String]
    var builtin: Bool

    /// The same three tapes the handheld ships with, so the phone has them without a link.
    static let builtins: [Tape] = [
        Tape(id: "builtin-build-log", name: "BUILD LOG 01", secs: 46, lines: [
            "LOG ENTRY. FELIX RECORDING.", "THE UPLINK RACK IS COMING TOGETHER.", "THREE THINKCENTRES ON THEIR SHELVES.",
            "PVE-1 ROUTES. PVE-2 PLAYS. PVE-3 REMEMBERS.", "THE CONTROL PANEL PRINT CAME OUT CLEAN.",
            "ESP32 READS THE VPN SWITCH NOW.", "NEXT: WIRE THE STANDBY LAMP.", "END LOG."], builtin: true),
        Tape(id: "builtin-venue", name: "VENUE CHECKLIST", secs: 38, lines: [
            "ARRIVAL PROCEDURE. LISTEN CAREFULLY.", "ONE. FIND THE VENUE RJ45. PLUG INTO WAN.",
            "TWO. FLIP MAIN POWER. WAIT FOR PVE-1.", "THREE. SELECT TUNNEL. TAILSCALE OR TWINGATE.",
            "FOUR. CHECK THE LAMPS. GREEN MEANS GO.", "FIVE. START THE STREAM.", "END OF PROCEDURE."], builtin: true),
        Tape(id: "builtin-late", name: "LATE SESSION", secs: 52, lines: [
            "IT IS 03:12. STUDIO IS QUIET.", "THE KICK FINALLY SITS RIGHT.", "TUNED IT DOWN A SEMITONE. MORE WEIGHT.",
            "PSY LEAD NEEDS LESS RESONANCE.", "BOUNCED THE STEMS TO PVE-3.",
            "IF YOU FIND THIS TAPE, PLAY THE DROP LOUD.", "SIGNING OFF."], builtin: true),
    ]
}

struct TapesResponse: Codable { var tapes: [Tape] }

// MARK: - What the phone hands the Watch (WatchConnectivity application context)

struct WatchNode: Codable, Equatable, Identifiable {
    var name: String
    var up: Bool?
    var ms: Double?
    var id: String { name }
}

struct WatchMessage: Codable, Equatable, Identifiable {
    var from: String
    var text: String
    var id: String { from + text }
}

struct WatchSnapshot: Codable, Equatable {
    var device: String
    /// NOT PAIRED, ONLINE or OFFLINE
    var link: String
    var condition: String
    var battery: Int?
    var temp: Double?
    var load: Double?
    var nodes: [WatchNode]
    var messages: [WatchMessage]
    var phoneBattery: Int?
    var updated: Date

    static let key = "snapshot"

    func encoded() -> Data? { try? JSONEncoder().encode(self) }
    static func decode(_ data: Data) -> WatchSnapshot? { try? JSONDecoder().decode(WatchSnapshot.self, from: data) }
}
