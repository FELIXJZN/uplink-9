import CoreLocation
import Foundation
import MapKit
import UIKit

/// A Vikunja task, plus where it is on the map (if anywhere).
struct Quest: Identifiable, Equatable {
    enum Source: String { case description = "IN TASK", label = "BY LABEL", pin = "PINNED ON PHONE" }

    var task: VikunjaTask
    var coordinate: CLLocationCoordinate2D?
    var place: String?
    var source: Source?
    var id: Int { task.id }

    static func == (a: Quest, b: Quest) -> Bool {
        a.task == b.task && a.place == b.place && a.source == b.source &&
            a.coordinate?.latitude == b.coordinate?.latitude && a.coordinate?.longitude == b.coordinate?.longitude
    }
}

/// Quests that share a spot on the map, drawn as one marker.
struct QuestSpot: Identifiable {
    var id: String
    var coordinate: CLLocationCoordinate2D
    var title: String
    var quests: [Quest]
    var overdue: Bool { quests.contains { $0.task.overdue } }
}

/// Loads Vikunja tasks, works out where they are, and tracks where you are.
@MainActor
final class QuestStore: NSObject, ObservableObject {
    @Published private(set) var tasks: [VikunjaTask] = []
    @Published private(set) var projectNames: [Int: String] = [:]
    @Published private(set) var status = "NOT SET UP"
    @Published private(set) var loading = false
    @Published private(set) var location: CLLocation?
    @Published private(set) var heading: Double = 0
    @Published private(set) var locationAllowed = false

    weak var app: AppStore?
    private let manager = CLLocationManager()
    private var lastLoad = Date.distantPast
    private var alerted: Set<Int> = []

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
        manager.distanceFilter = 15
        locationAllowed = [.authorizedWhenInUse, .authorizedAlways].contains(manager.authorizationStatus)
    }

    var token: String { Keychain.get(VikunjaClient.tokenKey) ?? "" }
    var isSetUp: Bool { !(app?.settings.vikunjaURL ?? "").isEmpty && !token.isEmpty }

    // MARK: location

    func startLocation() {
        switch manager.authorizationStatus {
        case .notDetermined: manager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse, .authorizedAlways:
            manager.startUpdatingLocation()
            if CLLocationManager.headingAvailable() { manager.startUpdatingHeading() }
        default: break
        }
    }

    func stopLocation() {
        manager.stopUpdatingLocation()
        manager.stopUpdatingHeading()
    }

    // MARK: tasks

    func refresh(force: Bool = false) async {
        guard let app else { return }
        guard isSetUp else {
            status = "NOT SET UP"
            return
        }
        guard force || Date().timeIntervalSince(lastLoad) > 60, !loading else { return }
        loading = true
        defer { loading = false }
        let client = VikunjaClient(base: app.settings.vikunjaURL, token: token)
        do {
            tasks = try await client.openTasks(project: app.settings.vikunjaProject)
            if projectNames.isEmpty {
                projectNames = Dictionary(uniqueKeysWithValues: (try? await client.projects())?.map { ($0.id, $0.title) } ?? [])
            }
            lastLoad = Date()
            status = "ONLINE"
            checkNearby()
        } catch {
            status = "OFFLINE: " + ((error as? LocalizedError)?.errorDescription ?? "ERROR")
        }
    }

    func complete(_ quest: Quest) async {
        guard let app else { return }
        do {
            try await VikunjaClient(base: app.settings.vikunjaURL, token: token).markDone(quest.task.id)
            tasks.removeAll { $0.id == quest.task.id }
            app.settings.questPins[String(quest.task.id)] = nil
            app.play("chirp")
            app.showToast("QUEST COMPLETE: " + quest.task.title)
        } catch {
            app.play("buzz")
            app.showToast("NOT MARKED DONE: " + ((error as? LocalizedError)?.errorDescription ?? "ERROR"))
        }
    }

    // MARK: matching tasks to places

    var quests: [Quest] {
        let settings = app?.settings ?? AppSettings()
        let places = Dictionary(settings.places.map { ($0.name.uppercased(), $0) }, uniquingKeysWith: { a, _ in a })
        return tasks.map { t in
            if let pin = settings.questPins[String(t.id)] {
                return Quest(task: t, coordinate: CLLocationCoordinate2D(latitude: pin.lat, longitude: pin.lon),
                             place: pin.place, source: .pin)
            }
            if let c = GeoText.coordinate(in: t.description ?? "") {
                return Quest(task: t, coordinate: c, place: nil, source: .description)
            }
            if let p = t.labelTitles.lazy.compactMap({ places[$0.uppercased()] }).first {
                return Quest(task: t, coordinate: CLLocationCoordinate2D(latitude: p.lat, longitude: p.lon),
                             place: p.name, source: .label)
            }
            return Quest(task: t, coordinate: nil, place: nil, source: nil)
        }
    }

    /// Quests on the map, grouped per spot (about 10 m).
    var spots: [QuestSpot] {
        var groups: [String: QuestSpot] = [:]
        for q in quests {
            guard let c = q.coordinate else { continue }
            let key = String(format: "%.4f,%.4f", c.latitude, c.longitude)
            if groups[key] == nil {
                groups[key] = QuestSpot(id: key, coordinate: c, title: q.place ?? q.task.title, quests: [])
            }
            groups[key]?.quests.append(q)
        }
        return Array(groups.values).sorted { $0.id < $1.id }
    }

    func distance(to c: CLLocationCoordinate2D) -> CLLocationDistance? {
        location?.distance(from: CLLocation(latitude: c.latitude, longitude: c.longitude))
    }

    /// Compass bearing from here to c, in degrees.
    func bearing(to c: CLLocationCoordinate2D) -> Double? {
        guard let from = location?.coordinate else { return nil }
        let lat1 = from.latitude * .pi / 180, lat2 = c.latitude * .pi / 180
        let dLon = (c.longitude - from.longitude) * .pi / 180
        let y = sin(dLon) * cos(lat2)
        let x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dLon)
        return (atan2(y, x) * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
    }

    func directionText(to c: CLLocationCoordinate2D) -> String {
        guard let d = distance(to: c), let b = bearing(to: c) else { return "NO FIX" }
        let dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        return QuestStore.distanceText(d) + " " + dirs[Int((b + 22.5) / 45) % 8]
    }

    static func distanceText(_ m: CLLocationDistance) -> String {
        m < 1000 ? String(format: "%.0f M", m) : String(format: "%.1f KM", m / 1000)
    }

    /// When you get close to a quest, say so once.
    private func checkNearby() {
        guard let app, app.settings.nearbyAlerts, location != nil else { return }
        for q in quests {
            guard let c = q.coordinate, let d = distance(to: c), d < 150, !alerted.contains(q.id) else { continue }
            alerted.insert(q.id)
            app.play("chirp")
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            app.showToast("QUEST NEARBY: " + q.task.title + (q.place.map { " @ " + $0 } ?? ""))
            break
        }
    }

    // MARK: actions on the phone

    func pin(_ quest: Quest, at c: CLLocationCoordinate2D, place: String?) {
        app?.settings.questPins[String(quest.id)] = QuestPin(lat: c.latitude, lon: c.longitude, place: place)
        app?.play("ok")
    }

    func unpin(_ quest: Quest) {
        app?.settings.questPins[String(quest.id)] = nil
    }

    func navigate(to quest: Quest) {
        guard let c = quest.coordinate else { return }
        let item = MKMapItem(placemark: MKPlacemark(coordinate: c))
        item.name = quest.task.title
        item.openInMaps(launchOptions: [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeWalking])
    }
}

extension QuestStore: CLLocationManagerDelegate {
    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            self.locationAllowed = status == .authorizedWhenInUse || status == .authorizedAlways
            if self.locationAllowed { self.startLocation() }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let last = locations.last else { return }
        Task { @MainActor in
            self.location = last
            self.checkNearby()
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateHeading newHeading: CLHeading) {
        let h = newHeading.trueHeading >= 0 ? newHeading.trueHeading : newHeading.magneticHeading
        Task { @MainActor in self.heading = h }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {}
}
