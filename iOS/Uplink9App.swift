import SwiftUI

@main
struct Uplink9App: App {
    @StateObject private var store = AppStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(store)
                .preferredColorScheme(.dark)
                .onOpenURL { store.handle(url: $0) }
        }
    }
}
