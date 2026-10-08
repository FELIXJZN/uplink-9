import AVFoundation
import Foundation

/// The handheld's terminal sounds, synthesised from the same recipes (uplink/sound.py),
/// so the phone clicks and chirps exactly like the device.
final class SoundPlayer {
    private static let rate = 44_100.0
    private var cache: [String: Data] = [:]
    private var playing: [AVAudioPlayer] = []
    private var lastSmall = Date.distantPast

    init() {
        // .ambient: mixes with music and respects the silent switch
        try? AVAudioSession.sharedInstance().setCategory(.ambient, options: [.mixWithOthers])
    }

    func play(_ name: String) {
        var key = name
        if key == "click" { key = "click_\(Int.random(in: 0...2))" }
        let small = key.hasPrefix("click") || key == "tick" || key == "type"
        if small {
            if Date().timeIntervalSince(lastSmall) < 0.03 { return }
            lastSmall = Date()
        }
        guard let data = wav(key), let player = try? AVAudioPlayer(data: data) else { return }
        playing.removeAll { !$0.isPlaying }
        playing.append(player)
        player.play()
    }

    private func wav(_ key: String) -> Data? {
        if let d = cache[key] { return d }
        guard let samples = Self.recipe(key) else { return nil }
        let d = Self.encode(samples)
        cache[key] = d
        return d
    }

    // MARK: synth (identical maths to the Python and JavaScript versions)

    private struct Rng {
        var s: UInt64
        mutating func next() -> Double {
            s = (s &* 16807) % 2_147_483_647
            return Double(s) / 2_147_483_647 * 2 - 1
        }
    }

    private static func noise(_ dur: Double, _ vol: Double, lp: Double? = nil, hp: Double? = nil, tau: Double? = nil, seed: UInt64 = 1) -> [Double] {
        let n = Int(dur * rate)
        var rng = Rng(s: seed)
        let aL = lp.map { 1 - exp(-2 * Double.pi * $0 / rate) } ?? 1
        let aH = hp.map { 1 - exp(-2 * Double.pi * $0 / rate) } ?? 0
        var lo = 0.0, lo2 = 0.0
        var out = [Double](repeating: 0, count: n)
        for i in 0..<n {
            var x = rng.next()
            if lp != nil { lo += aL * (x - lo); x = lo }
            if hp != nil { lo2 += aH * (x - lo2); x -= lo2 }
            let env = tau.map { exp(-Double(i) / rate / $0) } ?? 1
            let atk = min(1, Double(i) / (0.001 * rate))
            out[i] = x * vol * env * atk
        }
        return out
    }

    private enum Wave { case square, sine, saw }

    private static func tone(_ freq: Double, _ dur: Double, _ vol: Double, wave: Wave = .square, tau: Double? = nil,
                             attack: Double = 0.002, to: Double? = nil, trem: Double? = nil) -> [Double] {
        let n = Int(dur * rate)
        let rel = Double(Int(0.015 * rate))
        var phase = 0.0
        var out = [Double](repeating: 0, count: n)
        for i in 0..<n {
            let t = Double(i) / rate
            let f = to.map { freq * pow($0 / freq, Double(i) / Double(n)) } ?? freq
            phase += f / rate
            let x = phase.truncatingRemainder(dividingBy: 1)
            let s: Double
            switch wave {
            case .sine: s = sin(2 * Double.pi * x)
            case .saw: s = 2 * x - 1
            case .square: s = x < 0.5 ? 1 : -1
            }
            let env = tau.map { exp(-t / $0) } ?? min(1, Double(n - i) / rel)
            let atk = attack > 0 ? min(1, t / attack) : 1
            let tr = trem.map { 0.5 + 0.5 * sin(2 * Double.pi * $0 * t) } ?? 1
            out[i] = s * vol * env * atk * tr
        }
        return out
    }

    private static func mix(_ layers: [(Double, [Double])]) -> [Double] {
        let length = layers.map { Int($0.0 * rate) + $0.1.count }.max() ?? 0
        var out = [Double](repeating: 0, count: length)
        for (offset, samples) in layers {
            let o = Int(offset * rate)
            for (i, v) in samples.enumerated() { out[o + i] += v }
        }
        return out
    }

    private static func click(_ v: Int) -> [Double] {
        mix([(0, noise(0.018, 0.55, lp: 6500, hp: 1400, tau: 0.004, seed: UInt64(v + 1))),
             (0, tone(170 + Double(v) * 25, 0.03, 0.22, wave: .sine, tau: 0.008))])
    }

    private static func recipe(_ key: String) -> [Double]? {
        switch key {
        case "click_0": return click(0)
        case "click_1": return click(1)
        case "click_2": return click(2)
        case "tick": return noise(0.010, 0.32, hp: 2800, tau: 0.0025, seed: 7)
        case "type": return noise(0.006, 0.3, hp: 2200, tau: 0.0015, seed: 11)
        case "blip": return mix([(0, noise(0.03, 0.5, lp: 2600, tau: 0.008, seed: 3)), (0, tone(95, 0.07, 0.35, tau: 0.02)),
                                 (0.012, noise(0.012, 0.25, hp: 2000, tau: 0.003, seed: 5))])
        case "clack": return mix([(0, noise(0.05, 0.6, lp: 1800, tau: 0.012, seed: 13)), (0, tone(70, 0.09, 0.4, wave: .sine, tau: 0.03)),
                                  (0.065, noise(0.02, 0.35, lp: 3000, tau: 0.005, seed: 17))])
        case "ok": return tone(1050, 0.05, 0.16, tau: 0.03)
        case "chirp": return mix([(0, tone(1300, 0.06, 0.15, tau: 0.04)), (0.09, tone(1750, 0.08, 0.15, tau: 0.05))])
        case "buzz": return tone(150, 0.32, 0.2, trem: 28)
        case "hum": return mix([(0, tone(55, 0.5, 0.55, wave: .sine, tau: 0.15)), (0, noise(0.08, 0.45, lp: 400, tau: 0.03, seed: 19)),
                                (0.05, tone(80, 0.9, 0.14, wave: .sine, attack: 0.2, to: 220)),
                                (0.1, tone(15700, 1.2, 0.025, wave: .sine, attack: 0.3))])
        case "off": return mix([(0, tone(300, 0.35, 0.3, wave: .sine, to: 40)), (0.3, noise(0.02, 0.3, lp: 2000, tau: 0.005, seed: 23))])
        default: return nil
        }
    }

    /// 16-bit mono WAV in memory.
    private static func encode(_ samples: [Double]) -> Data {
        var pcm = Data(capacity: samples.count * 2)
        for v in samples {
            var s = Int16(max(-1, min(1, v)) * 32000).littleEndian
            withUnsafeBytes(of: &s) { pcm.append(contentsOf: $0) }
        }
        var d = Data()
        func put(_ str: String) { d.append(contentsOf: Array(str.utf8)) }
        func put32(_ v: UInt32) { var x = v.littleEndian; withUnsafeBytes(of: &x) { d.append(contentsOf: $0) } }
        func put16(_ v: UInt16) { var x = v.littleEndian; withUnsafeBytes(of: &x) { d.append(contentsOf: $0) } }
        put("RIFF"); put32(UInt32(36 + pcm.count)); put("WAVE")
        put("fmt "); put32(16); put16(1); put16(1); put32(UInt32(rate)); put32(UInt32(rate) * 2); put16(2); put16(16)
        put("data"); put32(UInt32(pcm.count))
        d.append(pcm)
        return d
    }
}
