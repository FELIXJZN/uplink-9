import Foundation
import WatchConnectivity
import WatchKit

/// Receives the status the iPhone app hands over, and asks the phone for fresh data.
@MainActor
final class WatchStore: NSObject, ObservableObject {
    @Published private(set) var snapshot: WatchSnapshot?
    @Published private(set) var watchBattery: Int?
    @Published private(set) var requesting = false

    override init() {
        super.init()
        WKInterfaceDevice.current().isBatteryMonitoringEnabled = true
        readBattery()
        if WCSession.isSupported() {
            WCSession.default.delegate = self
            WCSession.default.activate()
        }
    }

    var phoneReachable: Bool { WCSession.isSupported() && WCSession.default.isReachable }

    func readBattery() {
        let level = WKInterfaceDevice.current().batteryLevel
        watchBattery = level >= 0 ? Int((level * 100).rounded()) : nil
    }

    /// Tap anywhere: ask the phone to check the handheld again.
    func requestRefresh() {
        readBattery()
        WKInterfaceDevice.current().play(.click)
        guard phoneReachable else { return }
        requesting = true
        WCSession.default.sendMessage(["refresh": true], replyHandler: nil) { [weak self] _ in
            Task { @MainActor in self?.requesting = false }
        }
        Task {
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            requesting = false
        }
    }

    fileprivate func apply(_ context: [String: Any]) {
        guard let data = context[WatchSnapshot.key] as? Data, let s = WatchSnapshot.decode(data) else { return }
        let changed = snapshot?.condition != s.condition && snapshot != nil
        snapshot = s
        requesting = false
        if changed { WKInterfaceDevice.current().play(s.condition == "NOMINAL" ? .success : .notification) }
    }
}

extension WatchStore: WCSessionDelegate {
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        let context = session.receivedApplicationContext
        Task { @MainActor in self.apply(context) }
    }

    nonisolated func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        Task { @MainActor in self.apply(applicationContext) }
    }
}
