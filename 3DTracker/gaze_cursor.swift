// Optional click-through desktop overlay for monitor_demo.py.
import AppKit

struct GazeState: Decodable {
    let valid: Bool
    let desktop_gaze: [Double]?
}

final class GazeDot: NSView {
    override func draw(_ dirtyRect: NSRect) {
        NSColor.white.withAlphaComponent(0.55).setFill()
        NSBezierPath(ovalIn: bounds).fill()
    }
}

final class GazePanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

final class GazeCursor {
    let panel = GazePanel(contentRect: NSRect(x: 0, y: 0, width: 16, height: 16),
                          styleMask: [.borderless, .nonactivatingPanel],
                          backing: .buffered, defer: false)
    let url: URL
    let parentPID = getppid()
    var pending = false
    var timer: Timer?
    var animationTimer: Timer?
    var motion = GazeMotion()

    init(port: Int) {
        url = URL(string: "http://127.0.0.1:\(port)/state")!
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.ignoresMouseEvents = true
        panel.hidesOnDeactivate = false
        panel.level = .screenSaver
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        panel.contentView = GazeDot(frame: NSRect(x: 0, y: 0, width: 16, height: 16))
        timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
            self?.refresh()
        }
        let animation = Timer(timeInterval: 1.0 / 60, repeats: true) { [weak self] _ in self?.animate() }
        animationTimer = animation
        RunLoop.main.add(animation, forMode: .common)
    }

    func loseTracking() {
        motion.loseTracking(at: ProcessInfo.processInfo.systemUptime)
        animate()
    }

    func animate() {
        guard let sample = motion.sample(at: ProcessInfo.processInfo.systemUptime),
              let center = desktopFence(sample, frames: NSScreen.screens.map { $0.frame }) else {
            panel.orderOut(nil)
            return
        }
        panel.alphaValue = motion.opacity
        panel.setFrameOrigin(NSPoint(x: center.x - 8, y: center.y - 8))
        if !panel.isVisible { panel.orderFrontRegardless() }
    }

    func refresh() {
        // Also exit if the tracker is killed without running its normal cleanup.
        guard getppid() == parentPID else { NSApp.terminate(nil); return }
        guard !pending else { return }
        pending = true
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 0.4)
        request.httpMethod = "GET"
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            let state: GazeState?
            if error == nil, (response as? HTTPURLResponse)?.statusCode == 200, let data = data {
                state = try? JSONDecoder().decode(GazeState.self, from: data)
            } else {
                state = nil
            }
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.pending = false
                guard let state = state, state.valid, let point = state.desktop_gaze,
                      point.count == 2, point.allSatisfy({ $0.isFinite }),
                      let primary = NSScreen.screens.first else {
                    self.loseTracking()
                    return
                }
                // Browser desktop coordinates start at the main screen's top left.
                // AppKit uses its bottom left; both are logical pixels on Retina.
                let center = NSPoint(x: point[0], y: primary.frame.maxY - point[1])
                guard NSScreen.screens.contains(where: { $0.frame.contains(center) }) else {
                    self.loseTracking()
                    return
                }
                self.motion.updateTarget(center, at: ProcessInfo.processInfo.systemUptime)
                self.animate()
            }
        }.resume()
    }
}

guard CommandLine.arguments.count == 2, let port = Int(CommandLine.arguments[1]),
      (1...65535).contains(port) else {
    fputs("Usage: gaze-cursor PORT\n", stderr)
    exit(2)
}
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let cursor = GazeCursor(port: port)
app.run()
