import Foundation
import WatchConnectivity

/// Hands the latest status to the Watch and listens for its refresh requests.
final class WatchBridge: NSObject, WCSessionDelegate {
    var onRefreshRequest: (() -> Void)?
    private var lastSent: Data?

    func activate() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    /// The Watch reads the latest context whenever it opens, even if the phone app is closed by then.
    func send(_ snapshot: WatchSnapshot) {
        guard WCSession.isSupported(), WCSession.default.activationState == .activated,
              WCSession.default.isPaired, WCSession.default.isWatchAppInstalled,
              let data = snapshot.encoded(), data != lastSent else { return }
        lastSent = data
        try? WCSession.default.updateApplicationContext([WatchSnapshot.key: data])
    }

    // MARK: WCSessionDelegate

    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {}

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()   // switching to another Watch
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        if message["refresh"] != nil {
            DispatchQueue.main.async { self.onRefreshRequest?() }
        }
    }
}
