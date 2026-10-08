import CoreLocation
import Foundation
import Security

// MARK: - Keychain (the Vikunja token is kept here, not in plain settings)

enum Keychain {
    private static func query(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "uplink9",
         kSecAttrAccount as String: key]
    }

    static func set(_ value: String, for key: String) {
        SecItemDelete(query(key) as CFDictionary)
        guard !value.isEmpty else { return }
        var add = query(key)
        add[kSecValueData as String] = Data(value.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(add as CFDictionary, nil)
    }

    static func get(_ key: String) -> String? {
        var q = query(key)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
}

// MARK: - Tasks

struct VikunjaLabel: Decodable, Equatable {
    var title: String
}

struct VikunjaTask: Decodable, Equatable, Identifiable {
    var id: Int
    var title: String
    var description: String?
    var done: Bool
    var dueDate: String?
    var projectId: Int
    var priority: Int?
    var labels: [VikunjaLabel]?

    /// Vikunja sends "0001-01-01T00:00:00Z" when there is no due date.
    var due: Date? {
        guard let s = dueDate, !s.hasPrefix("0001") else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: s) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: s)
    }

    var overdue: Bool { (due ?? .distantFuture) < Date() }
    var labelTitles: [String] { (labels ?? []).map { $0.title } }

    /// Descriptions are HTML from Vikunja's editor; this is the plain text.
    var plainDescription: String {
        guard let d = description else { return "" }
        let noTags = d.replacingOccurrences(of: "<br\\s*/?>|</p>", with: "\n", options: .regularExpression)
            .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
            .replacingOccurrences(of: "&nbsp;", with: " ")
            .replacingOccurrences(of: "&amp;", with: "&")
            .replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
        return noTags.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

struct VikunjaProject: Decodable, Equatable {
    var id: Int
    var title: String
}

// MARK: - Finding a location in a task

enum GeoText {
    private static let patterns = [
        #"geo:\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)"#,                // geo:50.85,4.35
        #"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)"#,                                     // google.com/maps/@50.85,4.35,15z
        #"[?&](?:ll|q|daddr|sll|center)=(-?\d{1,2}\.\d+)(?:,|%2C)(-?\d{1,3}\.\d+)"#, // maps.apple.com/?ll=50.85,4.35
    ]

    /// The first coordinate written in the text, if any.
    static func coordinate(in text: String) -> CLLocationCoordinate2D? {
        let range = NSRange(text.startIndex..., in: text)
        for p in patterns {
            guard let re = try? NSRegularExpression(pattern: p, options: [.caseInsensitive]),
                  let m = re.firstMatch(in: text, range: range),
                  let r1 = Range(m.range(at: 1), in: text), let r2 = Range(m.range(at: 2), in: text),
                  let lat = Double(text[r1]), let lon = Double(text[r2]),
                  (-90...90).contains(lat), (-180...180).contains(lon) else { continue }
            return CLLocationCoordinate2D(latitude: lat, longitude: lon)
        }
        return nil
    }
}

// MARK: - API

enum VikunjaError: LocalizedError {
    case notSetUp, rejected, unreachable(String), server(Int)

    var errorDescription: String? {
        switch self {
        case .notSetUp: return "ADD YOUR VIKUNJA ADDRESS AND API TOKEN IN [SETUP]."
        case .rejected: return "VIKUNJA REFUSED THE TOKEN. MAKE A NEW ONE WITH TASK ACCESS."
        case .unreachable(let why): return why
        case .server(let code): return "VIKUNJA ERROR \(code)"
        }
    }
}

struct VikunjaClient {
    let base: String
    let token: String

    static var tokenKey: String { "vikunja-token" }

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private func url(_ path: String, query: [URLQueryItem] = []) throws -> URL {
        let trimmed = base.trimmingCharacters(in: CharacterSet(charactersIn: "/ "))
        guard var c = URLComponents(string: trimmed + "/api/v1" + path) else { throw VikunjaError.notSetUp }
        if !query.isEmpty { c.queryItems = query }
        guard let u = c.url else { throw VikunjaError.notSetUp }
        return u
    }

    private func send(_ req: URLRequest) async throws -> (Data, Int) {
        var req = req
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.timeoutInterval = 10
        do {
            let (data, response) = try await URLSession.shared.data(for: req)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            if code == 401 || code == 403 { throw VikunjaError.rejected }
            return (data, code)
        } catch let e as URLError {
            switch e.code {
            case .timedOut, .cannotConnectToHost, .cannotFindHost:
                throw VikunjaError.unreachable("CAN'T REACH VIKUNJA. IS TAILSCALE ON?")
            case .notConnectedToInternet:
                throw VikunjaError.unreachable("NO NETWORK ON THIS PHONE")
            default:
                throw VikunjaError.unreachable("VIKUNJA: \(e.localizedDescription.uppercased())")
            }
        }
    }

    /// All open tasks, soonest due first. Newer Vikunja uses /tasks, older versions /tasks/all.
    /// Vikunja pages its answers (50 per page by default), so keep asking until a page comes back short.
    func openTasks(project: Int) async throws -> [VikunjaTask] {
        guard !base.isEmpty, !token.isEmpty else { throw VikunjaError.notSetUp }
        let pageSize = 50
        for path in ["/tasks", "/tasks/all"] {
            var all: [VikunjaTask] = []
            var page = 1
            var found = true
            while page <= 40 {
                let query = [URLQueryItem(name: "filter", value: "done = false"),
                             URLQueryItem(name: "per_page", value: String(pageSize)),
                             URLQueryItem(name: "page", value: String(page)),
                             URLQueryItem(name: "sort_by", value: "due_date"), URLQueryItem(name: "order_by", value: "asc")]
                let (data, code) = try await send(URLRequest(url: try url(path, query: query)))
                if code == 404 || code == 405 {
                    found = false
                    break
                }
                guard code == 200 else { throw VikunjaError.server(code) }
                let batch = try Self.decoder.decode([VikunjaTask].self, from: data)
                all += batch
                if batch.count < pageSize { break }
                page += 1
            }
            guard found else { continue }
            // filter here as well: older servers ignore the filter, and the project is matched on the phone
            var seen = Set<Int>()
            return all.filter { !$0.done && (project == 0 || $0.projectId == project) && seen.insert($0.id).inserted }
        }
        throw VikunjaError.server(404)
    }

    func projects() async throws -> [VikunjaProject] {
        let (data, code) = try await send(URLRequest(url: try url("/projects", query: [URLQueryItem(name: "per_page", value: "200")])))
        guard code == 200 else { throw VikunjaError.server(code) }
        return (try? Self.decoder.decode([VikunjaProject].self, from: data)) ?? []
    }

    /// Vikunja's update replaces the whole task, so read it, flip "done", and send everything back.
    func markDone(_ id: Int) async throws {
        let taskURL = try url("/tasks/\(id)")
        let (data, code) = try await send(URLRequest(url: taskURL))
        guard code == 200, var task = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw VikunjaError.server(code)
        }
        task["done"] = true
        var post = URLRequest(url: taskURL)
        post.httpMethod = "POST"
        post.setValue("application/json", forHTTPHeaderField: "Content-Type")
        post.httpBody = try JSONSerialization.data(withJSONObject: task)
        let (_, postCode) = try await send(post)
        guard postCode == 200 || postCode == 201 else { throw VikunjaError.server(postCode) }
    }

    func webURL(task id: Int) -> URL? {
        URL(string: base.trimmingCharacters(in: CharacterSet(charactersIn: "/ ")) + "/tasks/\(id)")
    }
}
