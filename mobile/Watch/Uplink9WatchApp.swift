import SwiftUI

@main
struct Uplink9WatchApp: App {
    @StateObject private var store = WatchStore()

    var body: some Scene {
        WindowGroup {
            WatchRootView().environmentObject(store)
        }
    }
}
