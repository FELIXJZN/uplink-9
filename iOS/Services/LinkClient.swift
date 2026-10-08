import Foundation

/// Where the phone finds the Uplink-9 handheld. Comes from the pairing QR code.
struct LinkConfig: Codable, Equatable, Identifiable {
    var host: String
    var port: Int
    var token: String
    var name: String
    var id: String { "\(host):\(port)/\(token)" }

    /// Reads uplink9://pair?host=…&port=…&token=…&name=…
    init?(url: URL) {
        guard url.scheme == "uplink9", url.host == "pair",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems else { return nil }
        func value(_ key: String) -> String? { items.first { $0.name == key }?.value }
        guard let host = value("host"), !host.isEmpty, let token = value("token"), !token.isEmpty else { return nil }
        self.init(host: host, port: Int(value("port") ?? "") ?? 8909, token: token, name: value("name") ?? "UPLINK-9")
    }

    init(host: String, port: Int, token: String, name: String) {
        self.host = host
        self.port = port
        self.token = token
        self.name = name
    }
}

enum LinkError: LocalizedError {
    case rejected, notFound, server(String), unreachable(String)

    var errorDescription: String? {
        switch self {
        case .rejected: return "PAIRING CODE REJECTED. PAIR AGAIN."
        case .notFound: return "NOT FOUND ON THE DEVICE"
        case .server(let msg): return msg
        case .unreachable(let msg): return msg
        }
    }
}

/// Talks to the phone link API on the handheld (uplink/link.py).
struct LinkClient {
    let config: LinkConfig

    private static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 5
        c.waitsForConnectivity = false
        return URLSession(configuration: c)
    }()

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private func request(_ path: String, body: [String: String]? = nil) throws -> URLRequest {
        guard let url = URL(string: "http://\(config.host):\(config.port)\(path)") else {
            throw LinkError.unreachable("BAD ADDRESS: \(config.host)")
        }
        var req = URLRequest(url: url)
        req.setValue("Bearer \(config.token)", forHTTPHeaderField: "Authorization")
        if let body {
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        return req
    }

    private func perform(_ req: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await Self.session.data(for: req)
        } catch let error as URLError {
            switch error.code {
            case .timedOut: throw LinkError.unreachable("NO ANSWER. IS THE LINK ON AND TAILSCALE UP?")
            case .notConnectedToInternet: throw LinkError.unreachable("NO NETWORK ON THIS PHONE")
            case .cannotConnectToHost: throw LinkError.unreachable("DEVICE REFUSED. TURN ON SETTINGS > PHONE LINK.")
            default: throw LinkError.unreachable("CAN'T REACH \(config.host)")
            }
        }
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        switch code {
        case 200: return data
        case 401: throw LinkError.rejected
        case 404: throw LinkError.notFound
        default:
            let msg = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
            throw LinkError.server(msg ?? "DEVICE ERROR \(code)")
        }
    }

    func status() async throws -> DeviceStatus {
        try Self.decoder.decode(DeviceStatus.self, from: try await perform(try request("/api/status")))
    }

    func messages() async throws -> [MessageThread] {
        try Self.decoder.decode(MessagesResponse.self, from: try await perform(try request("/api/messages"))).threads
    }

    func tapes() async throws -> [Tape] {
        try Self.decoder.decode(TapesResponse.self, from: try await perform(try request("/api/tapes"))).tapes
    }

    func send(_ text: String, thread: String) async throws {
        let path = "/api/messages/" + (thread.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? thread)
        _ = try await perform(try request(path, body: ["text": text]))
    }
}
