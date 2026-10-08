import SwiftUI

@main
struct Uplink9App: App {
    @StateObject private var store = AppStore()
    @StateObject private var quests = QuestStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(store)
                .environmentObject(quests)
                .preferredColorScheme(.dark)
                .onOpenURL { store.handle(url: $0) }
        }
    }
}
