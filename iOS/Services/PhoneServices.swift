import Foundation
import Network
import UIKit

// MARK: - This phone's own vitals

struct PhoneReading: Equatable {
    var battery: Int?
    var charging = false
    var thermal = "NOMINAL"
    var thermalPercent: Double = 25
    var diskFree: Int64 = 0
    var diskTotal: Int64 = 0
    var uptime = 0
}

@MainActor
enum PhoneVitals {
    static func read() -> PhoneReading {
        let device = UIDevice.current
        device.isBatteryMonitoringEnabled = true
        var r = PhoneReading()
        if device.batteryLevel >= 0 {
            r.battery = Int((device.batteryLevel * 100).rounded())
        }
        r.charging = device.batteryState == .charging || device.batteryState == .full
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: (r.thermal, r.thermalPercent) = ("NOMINAL", 25)
        case .fair: (r.thermal, r.thermalPercent) = ("FAIR", 55)
        case .serious: (r.thermal, r.thermalPercent) = ("SERIOUS", 80)
        case .critical: (r.thermal, r.thermalPercent) = ("CRITICAL", 97)
        @unknown default: (r.thermal, r.thermalPercent) = ("UNKNOWN", 25)
        }
        let home = URL(fileURLWithPath: NSHomeDirectory())
        if let values = try? home.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey, .volumeTotalCapacityKey]) {
            r.diskFree = values.volumeAvailableCapacityForImportantUsage ?? 0
            r.diskTotal = Int64(values.volumeTotalCapacity ?? 0)
        }
        r.uptime = Int(ProcessInfo.processInfo.systemUptime)
        return r
    }
}

// MARK: - Node checks without the handheld
// A phone can't ping, so it opens a TCP connection instead (SSH on port 22 by default).

struct NodeConfig: Codable, Equatable, Identifiable {
    var id = UUID()
    var name: String
    var host: String
    var port: Int = 22

    static let defaults = [
        NodeConfig(name: "PVE-1", host: "pve-1"), NodeConfig(name: "PVE-2", host: "pve-2"),
        NodeConfig(name: "PVE-3", host: "pve-3"), NodeConfig(name: "REDRABBIT", host: "redrabbit"),
    ]
}

enum NodeProbe {
    /// Milliseconds to connect, or nil when the host doesn't answer within the timeout.
    static func check(host: String, port: Int, timeout: Double = 2.5) async -> Double? {
        guard let nwPort = NWEndpoint.Port(rawValue: UInt16(clamping: port)) else { return nil }
        return await withCheckedContinuation { (cont: CheckedContinuation<Double?, Never>) in
            let connection = NWConnection(host: NWEndpoint.Host(host), port: nwPort, using: .tcp)
            let start = Date()
            let lock = NSLock()
            var finished = false
            func finish(_ value: Double?) {
                lock.lock()
                defer { lock.unlock() }
                if finished { return }
                finished = true
                connection.cancel()
                cont.resume(returning: value)
            }
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready: finish(Date().timeIntervalSince(start) * 1000)
                case .failed, .waiting: finish(nil)
                default: break
                }
            }
            connection.start(queue: .global(qos: .utility))
            DispatchQueue.global().asyncAfter(deadline: .now() + timeout) { finish(nil) }
        }
    }
}

// MARK: - ntfy (two-way messages straight from the phone)

struct NtfyMessage: Decodable {
    var id: String
    var time: Int
    var event: String
    var message: String?
}

enum Ntfy {
    static func send(_ text: String, topicURL: String) async throws -> String? {
        guard let url = URL(string: topicURL) else { throw LinkError.unreachable("BAD NTFY ADDRESS") }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.httpBody = Data(text.utf8)
        req.setValue("Uplink-9 phone", forHTTPHeaderField: "Title")
        let (data, response) = try await URLSession.shared.data(for: req)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw LinkError.server("NTFY REFUSED THE MESSAGE") }
        return (try? JSONDecoder().decode(NtfyMessage.self, from: data))?.id
    }

    static func poll(topicURL: String, since: String) async throws -> [NtfyMessage] {
        let base = topicURL.hasSuffix("/") ? String(topicURL.dropLast()) : topicURL
        guard let url = URL(string: "\(base)/json?poll=1&since=\(since)") else { return [] }
        let (data, _) = try await URLSession.shared.data(from: url)
        return String(decoding: data, as: UTF8.self)
            .split(separator: "\n")
            .compactMap { try? JSONDecoder().decode(NtfyMessage.self, from: Data($0.utf8)) }
            .filter { $0.event == "message" }
    }
}
