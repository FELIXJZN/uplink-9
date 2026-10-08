import SwiftUI

// MARK: - Colours

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xff) / 255, green: Double((hex >> 8) & 0xff) / 255, blue: Double(hex & 0xff) / 255)
    }
}

enum Phosphor: String, CaseIterable, Codable {
    case green, amber, white, blue

    var bright: Color {
        switch self {
        case .green: return Color(hex: 0x3dff7a)
        case .amber: return Color(hex: 0xffb642)
        case .white: return Color(hex: 0xe8f1ff)
        case .blue: return Color(hex: 0x5ad2ff)
        }
    }

    var dim: Color {
        switch self {
        case .green: return Color(hex: 0x1f8a45)
        case .amber: return Color(hex: 0x9a6a1c)
        case .white: return Color(hex: 0x7d8796)
        case .blue: return Color(hex: 0x2a7590)
        }
    }
}

struct TermTheme: Equatable {
    var phosphor: Phosphor = .green
    /// Realism mode: green text only, no glow, no scanlines, no colours for warnings.
    var plain = false

    var bright: Color { plain ? Phosphor.green.bright : phosphor.bright }
    var dim: Color { plain ? Phosphor.green.dim : phosphor.dim }
    var warn: Color { plain ? bright : Color(hex: 0xffb642) }
    var bad: Color { plain ? bright : Color(hex: 0xff5a4a) }

    func color(_ style: LineStyle) -> Color {
        switch style {
        case .normal: return bright
        case .dim: return dim
        case .warn: return warn
        case .bad: return bad
        }
    }
}

enum LineStyle { case normal, dim, warn, bad }

private struct TermThemeKey: EnvironmentKey { static let defaultValue = TermTheme() }

extension EnvironmentValues {
    var termTheme: TermTheme {
        get { self[TermThemeKey.self] }
        set { self[TermThemeKey.self] = newValue }
    }
}

// MARK: - Text

#if os(watchOS)
let termFontSize: CGFloat = 13
#else
let termFontSize: CGFloat = 14
#endif

/// One line of terminal text.
struct TermText: View {
    @Environment(\.termTheme) private var theme
    let text: String
    var style: LineStyle = .normal
    var bold = false

    init(_ text: String, _ style: LineStyle = .normal, bold: Bool = false) {
        self.text = text
        self.style = style
        self.bold = bold
    }

    var body: some View {
        let color = theme.color(style)
        Text(text.uppercased())
            .font(.system(size: termFontSize, weight: bold ? .bold : .regular, design: .monospaced))
            .foregroundStyle(color)
            .shadow(color: theme.plain || style == .dim ? .clear : color.opacity(0.55), radius: 3)
            .frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
    }
}

/// A thin line in the dim colour.
struct TermRule: View {
    @Environment(\.termTheme) private var theme
    var body: some View { Rectangle().fill(theme.dim).frame(height: 1).padding(.vertical, 4) }
}

/// Faint horizontal lines over the screen, like an old monitor.
struct Scanlines: View {
    var body: some View {
        Canvas { ctx, size in
            var y: CGFloat = 0
            while y < size.height {
                ctx.fill(Path(CGRect(x: 0, y: y, width: size.width, height: 1)), with: .color(.black.opacity(0.28)))
                y += 3
            }
        }
        .allowsHitTesting(false)
    }
}

// MARK: - Formatting helpers (same output as the handheld)

func bar(_ percent: Double, width: Int = 10) -> String {
    let n = max(0, min(width, Int((percent / 100 * Double(width)).rounded())))
    return String(repeating: "█", count: n) + String(repeating: "░", count: width - n)
}

func human(_ bytes: Int64) -> String {
    var n = Double(bytes)
    let units = ["B", "K", "M", "G", "T"]
    var i = 0
    while n >= 1024 && i < units.count - 1 {
        n /= 1024
        i += 1
    }
    return i == 0 ? "\(Int(n))B" : String(format: "%.1f%@", n, units[i])
}

func clockString(_ secs: Int) -> String {
    String(format: "%02d:%02d", secs / 60, secs % 60)
}

func uptimeString(_ secs: Int) -> String {
    String(format: "%dD %02d:%02d", secs / 86400, secs % 86400 / 3600, secs % 3600 / 60)
}

/// Signal bars from a ping time, like the handheld's SIGNAL tab.
func signalBars(_ ms: Double?) -> String {
    guard let ms else { return "----" }
    let n = ms < 10 ? 4 : ms < 40 ? 3 : ms < 100 ? 2 : 1
    let glyphs = Array("▂▄▆█")
    return (0..<4).map { $0 < n ? String(glyphs[$0]) : " " }.joined()
}

/// A gauge line: "LABEL     [████░░░░░░] VALUE"
func gaugeLine(_ label: String, _ percent: Double?, _ value: String) -> (String, LineStyle) {
    let padded = label.padding(toLength: 9, withPad: " ", startingAt: 0)
    guard let percent else { return ("\(padded) NO SENSOR", .dim) }
    let style: LineStyle = percent >= 90 ? .bad : percent >= 75 ? .warn : .normal
    return ("\(padded) [\(bar(percent))] \(value)", style)
}

/// Battery is the other way round: low is the problem, not high.
func batteryLine(_ label: String, _ percent: Int?, charging: Bool) -> (String, LineStyle) {
    let padded = label.padding(toLength: 9, withPad: " ", startingAt: 0)
    guard let percent else { return ("\(padded) NO SENSOR", .dim) }
    let style: LineStyle = charging ? .normal : (percent < 15 ? .bad : (percent < 25 ? .warn : .normal))
    return ("\(padded) [\(bar(Double(percent)))] \(percent)%" + (charging ? " +" : ""), style)
}
