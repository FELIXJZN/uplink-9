import CoreLocation
import MapKit
import SwiftUI

/// PERSONAL: your Vikunja tasks as quests on a map, on an offline radar, and in a log.
struct PersonalTab: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var quests: QuestStore
    @State private var section = 0
    @State private var position: MapCameraPosition = .userLocation(fallback: .automatic)
    @State private var center = CLLocationCoordinate2D(latitude: 50.85, longitude: 4.35)
    @State private var opened: [Quest]?

    private let sections = ["MAP", "RADAR", "QUESTS"]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 14) {
                ForEach(sections.indices, id: \.self) { i in
                    Button {
                        store.play("clack")
                        section = i
                    } label: {
                        TermText(section == i ? "[\(sections[i])]" : sections[i], section == i ? .normal : .dim, bold: section == i).fixedSize()
                    }
                    .buttonStyle(.plain)
                }
                Spacer()
                Button {
                    store.play("blip")
                    Task { await quests.refresh(force: true) }
                } label: { TermText(quests.loading ? "[...]" : "[SYNC]", .dim).fixedSize() }
                .buttonStyle(.plain)
                .accessibilityLabel("Sync quests")
            }
            statusLine
            switch section {
            case 0: QuestMap(position: $position, center: $center) { opened = $0 }
            case 1: QuestRadar { opened = $0 }
            default: QuestLog { opened = [$0] }
            }
        }
        .padding(.top, 4)
        .onAppear {
            quests.startLocation()
            Task { await quests.refresh() }
        }
        .onDisappear { quests.stopLocation() }
        .sheet(isPresented: Binding(get: { opened != nil }, set: { if !$0 { opened = nil } })) {
            if let list = opened {
                QuestCard(quests: list, mapCenter: center) { c in
                    opened = nil
                    section = 0
                    withAnimation { position = .camera(MapCamera(centerCoordinate: c, distance: 900)) }
                }
                .environmentObject(store)
                .environmentObject(quests)
                .environment(\.termTheme, store.theme)
            }
        }
    }

    private var statusLine: some View {
        let all = quests.quests
        let placed = all.filter { $0.coordinate != nil }.count
        let ok = quests.status == "ONLINE"
        return TermText("VIKUNJA \(ok ? "ONLINE" : quests.status) · \(all.count) QUESTS · \(placed) ON MAP", ok ? .dim : .warn)
            .lineLimit(2)
    }
}

// MARK: - Map (Apple MapKit: no key, no account)

struct QuestMap: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var quests: QuestStore
    @Environment(\.termTheme) private var theme
    @Binding var position: MapCameraPosition
    @Binding var center: CLLocationCoordinate2D
    let open: ([Quest]) -> Void
    @State private var naming = false
    @State private var placeName = ""

    var body: some View {
        VStack(spacing: 6) {
            ZStack {
                Map(position: $position) {
                    UserAnnotation()
                    ForEach(store.settings.places) { p in
                        Annotation(p.name, coordinate: CLLocationCoordinate2D(latitude: p.lat, longitude: p.lon), anchor: .center) {
                            PlaceMarker(name: p.name)
                        }
                        .annotationTitles(.hidden)
                    }
                    ForEach(quests.spots) { spot in
                        Annotation(spot.title, coordinate: spot.coordinate, anchor: .center) {
                            Button {
                                store.play("blip")
                                store.tapFeedback()
                                open(spot.quests)
                            } label: {
                                QuestMarker(count: spot.quests.count, overdue: spot.overdue)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("\(spot.quests.count) quests at \(spot.title)")
                        }
                        .annotationTitles(.hidden)
                    }
                }
                .mapStyle(.standard(elevation: .flat, emphasis: .muted, pointsOfInterest: .excludingAll, showsTraffic: false))
                .mapControls {
                    MapUserLocationButton()
                    MapCompass()
                    MapScaleView()
                }
                .onMapCameraChange(frequency: .onEnd) { context in center = context.region.center }
                .environment(\.colorScheme, .dark)

                // crosshair for marking places and pinning quests
                Image(systemName: "plus")
                    .font(.system(size: 18, weight: .light))
                    .foregroundStyle(theme.bright.opacity(0.8))
                    .allowsHitTesting(false)
            }
            .overlay(Rectangle().stroke(theme.dim, lineWidth: 1))
            .clipped()

            HStack {
                TermText(String(format: "%.5f, %.5f", center.latitude, center.longitude), .dim)
                Button {
                    store.play("blip")
                    placeName = ""
                    naming = true
                } label: { TermText("[MARK PLACE]", bold: true).fixedSize() }
                .buttonStyle(.plain)
            }
        }
        .alert("Name this place", isPresented: $naming) {
            TextField("STUDIO", text: $placeName)
                .textInputAutocapitalization(.characters)
            Button("Save") {
                let name = placeName.trimmingCharacters(in: .whitespaces).uppercased()
                guard !name.isEmpty else { return }
                store.settings.places.append(Place(name: name, lat: center.latitude, lon: center.longitude))
                store.play("ok")
                store.showToast("PLACE SAVED. GIVE TASKS THE LABEL \(name) TO PUT THEM HERE.")
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Saved at the crosshair. Vikunja tasks with a label of this name appear here as quests.")
        }
    }
}

/// An original quest marker: a diamond with a ring, and a count when several quests share a spot.
struct QuestMarker: View {
    @Environment(\.termTheme) private var theme
    let count: Int
    let overdue: Bool

    var body: some View {
        let color = overdue ? theme.warn : theme.bright
        ZStack {
            Circle().stroke(color.opacity(0.45), lineWidth: 1.5).frame(width: 34, height: 34)
            Rectangle()
                .fill(Color.black)
                .overlay(Rectangle().stroke(color, lineWidth: 2.5))
                .frame(width: 16, height: 16)
                .rotationEffect(.degrees(45))
            if count > 1 {
                Text("\(count)")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(color)
            } else {
                Rectangle().fill(color).frame(width: 5, height: 5).rotationEffect(.degrees(45))
            }
        }
        .shadow(color: theme.plain ? .clear : color.opacity(0.8), radius: 4)
        .frame(width: 44, height: 44)
        .contentShape(Rectangle())
    }
}

struct PlaceMarker: View {
    @Environment(\.termTheme) private var theme
    let name: String

    var body: some View {
        VStack(spacing: 2) {
            Rectangle().stroke(theme.dim, lineWidth: 1.5).frame(width: 9, height: 9)
            Text(name)
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(theme.dim)
                .padding(.horizontal, 3)
                .background(Color.black.opacity(0.7))
        }
        .allowsHitTesting(false)
    }
}

// MARK: - Radar (no map, no network: just distance and direction from you)

struct QuestRadar: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var quests: QuestStore
    @Environment(\.termTheme) private var theme
    let open: ([Quest]) -> Void
    @State private var rangeIndex = 1
    private let ranges: [Double] = [500, 2_000, 10_000, 50_000]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if quests.location == nil {
                TermText(quests.locationAllowed ? "WAITING FOR A LOCATION FIX..." : "ALLOW LOCATION ACCESS IN IOS SETTINGS TO USE THE RADAR.", .warn)
            }
            GeometryReader { geo in
                let size = min(geo.size.width, geo.size.height)
                let range = ranges[rangeIndex]
                let blips = radarBlips(range: range, radius: size / 2 - 14)
                ZStack {
                    TimelineView(.animation(minimumInterval: 1 / 30, paused: theme.plain)) { timeline in
                        Canvas { ctx, canvasSize in
                            let c = CGPoint(x: canvasSize.width / 2, y: canvasSize.height / 2)
                            let r = size / 2 - 14
                            for i in 1...4 {
                                let rr = r * CGFloat(i) / 4
                                ctx.stroke(Path(ellipseIn: CGRect(x: c.x - rr, y: c.y - rr, width: rr * 2, height: rr * 2)),
                                           with: .color(theme.dim.opacity(i == 4 ? 0.9 : 0.5)), lineWidth: 1)
                            }
                            var cross = Path()
                            cross.move(to: CGPoint(x: c.x - r, y: c.y)); cross.addLine(to: CGPoint(x: c.x + r, y: c.y))
                            cross.move(to: CGPoint(x: c.x, y: c.y - r)); cross.addLine(to: CGPoint(x: c.x, y: c.y + r))
                            ctx.stroke(cross, with: .color(theme.dim.opacity(0.35)), lineWidth: 1)
                            if !theme.plain {
                                let t = timeline.date.timeIntervalSinceReferenceDate
                                let a = CGFloat(t.truncatingRemainder(dividingBy: 4) / 4 * 2 * .pi) - .pi / 2
                                var sweep = Path()
                                sweep.move(to: c)
                                sweep.addLine(to: CGPoint(x: c.x + cos(a) * r, y: c.y + sin(a) * r))
                                ctx.stroke(sweep, with: .color(theme.bright.opacity(0.7)), lineWidth: 1.5)
                            }
                            ctx.fill(Path(ellipseIn: CGRect(x: c.x - 3, y: c.y - 3, width: 6, height: 6)), with: .color(theme.bright))
                        }
                    }
                    ForEach(blips) { b in
                        Button {
                            store.play("blip")
                            open(b.spot.quests)
                        } label: {
                            QuestMarker(count: b.spot.quests.count, overdue: b.spot.overdue).scaleEffect(0.7)
                        }
                        .buttonStyle(.plain)
                        .position(x: size / 2 + b.offset.width, y: size / 2 + b.offset.height)
                        .accessibilityLabel("\(b.spot.title), \(b.label)")
                    }
                    TermText("N", .dim).fixedSize().position(x: size / 2, y: 6)
                }
                .frame(width: size, height: size)
                .rotationEffect(.degrees(-quests.heading))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            HStack {
                TermText("RANGE " + QuestStore.distanceText(ranges[rangeIndex]) + " · RINGS " + QuestStore.distanceText(ranges[rangeIndex] / 4), .dim)
                Button {
                    store.play("clack")
                    rangeIndex = (rangeIndex + 1) % ranges.count
                } label: { TermText("[RANGE]", bold: true).fixedSize() }
                .buttonStyle(.plain)
            }
            if let nearest = nearestSpot {
                TermText("NEAREST: \(nearest.title) · \(quests.directionText(to: nearest.coordinate))")
            }
        }
    }

    private struct Blip: Identifiable {
        var spot: QuestSpot
        var offset: CGSize
        var label: String
        var id: String { spot.id }
    }

    private func radarBlips(range: Double, radius: CGFloat) -> [Blip] {
        quests.spots.compactMap { spot -> Blip? in
            guard let d = quests.distance(to: spot.coordinate), let b = quests.bearing(to: spot.coordinate) else { return nil }
            let r = min(1, d / range) * Double(radius)      // beyond range: sits on the edge
            let a = (b - 90) * .pi / 180
            return Blip(spot: spot, offset: CGSize(width: cos(a) * r, height: sin(a) * r), label: quests.directionText(to: spot.coordinate))
        }
    }

    private var nearestSpot: QuestSpot? {
        quests.spots.min { (quests.distance(to: $0.coordinate) ?? .infinity) < (quests.distance(to: $1.coordinate) ?? .infinity) }
    }
}

// MARK: - Quest log

struct QuestLog: View {
    @EnvironmentObject private var quests: QuestStore
    let open: (Quest) -> Void

    var body: some View {
        TermPage {
            let all = quests.quests
            let placed = all.filter { $0.coordinate != nil }
                .sorted { (quests.distance(to: $0.coordinate!) ?? .infinity) < (quests.distance(to: $1.coordinate!) ?? .infinity) }
            let unplaced = all.filter { $0.coordinate == nil }
            if all.isEmpty {
                TermText(quests.isSetUp ? "NO OPEN QUESTS. ALL CLEAR." : "ADD VIKUNJA IN [SETUP] TO SEE YOUR TASKS HERE.", .dim)
            }
            if !placed.isEmpty { TermText("ON THE MAP", .dim) }
            ForEach(placed) { q in
                TermOption(label: "◆ " + q.task.title, tag: quests.directionText(to: q.coordinate!), style: q.task.overdue ? .warn : .normal) { open(q) }
            }
            if !unplaced.isEmpty {
                TermText("")
                TermText("UNPLACED (OPEN ONE TO PIN IT)", .dim)
            }
            ForEach(unplaced) { q in
                TermOption(label: "◇ " + q.task.title, tag: q.task.due.map(dueText) ?? "", style: q.task.overdue ? .warn : .dim) { open(q) }
            }
        }
    }
}

func dueText(_ d: Date) -> String {
    let days = Calendar.current.dateComponents([.day], from: Calendar.current.startOfDay(for: Date()),
                                               to: Calendar.current.startOfDay(for: d)).day ?? 0
    switch days {
    case ..<0: return "OVERDUE"
    case 0: return "TODAY"
    case 1: return "TOMORROW"
    default: return "IN \(days)D"
    }
}

// MARK: - Quest card

struct QuestCard: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var quests: QuestStore
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    let quests_: [Quest]
    let mapCenter: CLLocationCoordinate2D
    let showOnMap: (CLLocationCoordinate2D) -> Void
    @State private var pinning: Quest?
    @State private var finishing: Quest?

    init(quests: [Quest], mapCenter: CLLocationCoordinate2D, showOnMap: @escaping (CLLocationCoordinate2D) -> Void) {
        self.quests_ = quests
        self.mapCenter = mapCenter
        self.showOnMap = showOnMap
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                TermText(quests_.count > 1 ? "\(quests_.count) QUESTS HERE" : "QUEST", .warn, bold: true)
                Button { dismiss() } label: { TermText("[CLOSE]", .dim).fixedSize() }.buttonStyle(.plain)
            }
            TermRule()
            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(live) { q in entry(q) }
                    if live.isEmpty { TermText("ALL DONE HERE.", .dim) }
                }
            }
            .scrollIndicators(.hidden)
        }
        .padding(20)
        .background(Color.black.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .confirmationDialog("Pin this quest", isPresented: Binding(get: { pinning != nil }, set: { if !$0 { pinning = nil } }),
                            titleVisibility: .visible, presenting: pinning) { q in
            ForEach(store.settings.places) { p in
                Button(p.name) { quests.pin(q, at: CLLocationCoordinate2D(latitude: p.lat, longitude: p.lon), place: p.name) }
            }
            if let here = quests.location?.coordinate {
                Button("Where I am now") { quests.pin(q, at: here, place: nil) }
            }
            Button("Map crosshair") { quests.pin(q, at: mapCenter, place: nil) }
            Button("Cancel", role: .cancel) {}
        } message: { _ in
            Text("Kept on this phone; the task in Vikunja is not changed.")
        }
        .confirmationDialog("Mark as done in Vikunja?", isPresented: Binding(get: { finishing != nil }, set: { if !$0 { finishing = nil } }),
                            titleVisibility: .visible, presenting: finishing) { q in
            Button("Mark done") { Task { await quests.complete(q) } }
            Button("Cancel", role: .cancel) {}
        } message: { q in
            Text(q.task.title)
        }
    }

    /// The same quests, kept current (pins and completions update while the card is open).
    private var live: [Quest] {
        let ids = Set(quests_.map { $0.id })
        return quests.quests.filter { ids.contains($0.id) }
    }

    @ViewBuilder private func entry(_ q: Quest) -> some View {
        TermText("◆ " + q.task.title, q.task.overdue ? .warn : .normal, bold: true)
        TermText(quests.projectNames[q.task.projectId].map { "PROJECT  " + $0 } ?? "PROJECT  #\(q.task.projectId)", .dim)
        if let due = q.task.due {
            TermText("DUE      " + due.formatted(date: .abbreviated, time: .omitted) + " · " + dueText(due), q.task.overdue ? .warn : .dim)
        }
        if let c = q.coordinate {
            TermText("WHERE    " + (q.place ?? String(format: "%.4f, %.4f", c.latitude, c.longitude)) + " · " + (q.source?.rawValue ?? ""), .dim)
            TermText("DISTANCE " + quests.directionText(to: c))
        } else {
            TermText("WHERE    NOT PLACED", .warn)
        }
        if !q.task.labelTitles.isEmpty {
            TermText("LABELS   " + q.task.labelTitles.joined(separator: ", "), .dim)
        }
        let text = q.task.plainDescription
        if !text.isEmpty {
            TermText(String(text.prefix(280)), .dim)
        }
        if let c = q.coordinate {
            TermOption(label: "NAVIGATE (APPLE MAPS)") { quests.navigate(to: q) }
            TermOption(label: "SHOW ON MAP") { showOnMap(c) }
        }
        TermOption(label: q.source == .pin ? "MOVE PIN..." : "PIN TO A PLACE...") { pinning = q }
        if q.source == .pin {
            TermOption(label: "UNPIN", style: .dim) { quests.unpin(q) }
        }
        if let url = VikunjaClient(base: store.settings.vikunjaURL, token: "").webURL(task: q.task.id) {
            TermOption(label: "OPEN IN VIKUNJA", style: .dim) { openURL(url) }
        }
        TermOption(label: "MARK DONE", style: .warn) { finishing = q }
        TermRule()
    }
}
