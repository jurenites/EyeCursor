import Foundation

/// Project visual feedback onto the connected display union, with open seams.
/// Applied after smoothing as well, so a path across a desktop gap stays visible.
func desktopFence(_ point: CGPoint, frames: [CGRect], inset: CGFloat = 8) -> CGPoint? {
    guard point.x.isFinite, point.y.isFinite, !frames.isEmpty else { return nil }
    func covered(_ x: CGFloat, _ y: CGFloat) -> Bool {
        frames.contains { x >= $0.minX && x <= $0.maxX && y >= $0.minY && y <= $0.maxY }
    }
    let candidates = frames.map { f -> CGPoint in
        let x = min(f.maxX,max(f.minX,point.x)), y = min(f.maxY,max(f.minY,point.y))
        let mx = min(inset,f.width/2), my = min(inset,f.height/2)
        let left = covered(f.minX-0.01,y) ? f.minX : f.minX+mx
        let right = covered(f.maxX+0.01,y) ? f.maxX : f.maxX-mx
        let bottom = covered(x,f.minY-0.01) ? f.minY : f.minY+my
        let top = covered(x,f.maxY+0.01) ? f.maxY : f.maxY-my
        return CGPoint(x:min(right,max(left,point.x)),y:min(top,max(bottom,point.y)))
    }
    return candidates.min { hypot($0.x-point.x,$0.y-point.y) < hypot($1.x-point.x,$1.y-point.y) }
}
import CoreGraphics

/// Display feedback only; holding the ring never adds calibration samples.
struct CalibrationFeedback {
    private var key: String?
    private(set) var progress = 0.0
    private(set) var accepted = false

    mutating func update(key nextKey: String, progress value: Double, accepted good: Bool) {
        if key != nextKey { reset(); key = nextKey }
        if good && value.isFinite { progress = max(progress, min(1, max(0, value))) }
        accepted = good
    }

    mutating func reset() { key = nil; progress = 0; accepted = false }
}

/// Critically damped motion: preserve position and velocity when a new target
/// arrives. Exact integration makes the response independent of render cadence.
/// Raw observations and calibration acceptance are never altered by this filter.
struct MeasurementMotion {
    private var position: [Double]?
    private var velocity: [Double] = []
    private var target: [Double] = []
    private var lastTick = 0.0
    private var lastTarget = -Double.infinity
    private let responseTime: Double
    private let preventsOvershoot: Bool

    init(responseTime: Double = 0.07, preventsOvershoot: Bool = false) {
        self.responseTime = responseTime
        self.preventsOvershoot = preventsOvershoot
    }

    mutating func reset() { position = nil; velocity = []; target = []; lastTarget = -.infinity }

    mutating func updateTarget(_ values: [Double], at time: Double) {
        guard !values.isEmpty, values.allSatisfy({ $0.isFinite }), time.isFinite else { reset(); return }
        if position?.count != values.count || time < lastTick || time - lastTarget > 0.5 {
            position = values
            velocity = Array(repeating: 0, count: values.count)
            lastTick = time
        } else {
            // Finish the old trajectory up to this sample's arrival, then redirect
            // it without jumping position or restarting its velocity from zero.
            _ = sample(at: time)
        }
        target = values
        lastTarget = time
    }

    mutating func sample(at time: Double) -> [Double]? {
        guard time.isFinite, time >= lastTick, time - lastTarget <= 0.5,
              var current = position else { reset(); return nil }
        let dt = time - lastTick
        let omega = 1 / responseTime
        let decay = exp(-omega * dt)
        for i in current.indices {
            let previous = current[i]
            let offset = current[i] - target[i]
            let impulse = velocity[i] + omega * offset
            current[i] = target[i] + (offset + impulse * dt) * decay
            velocity[i] = (velocity[i] - omega * impulse * dt) * decay
            if preventsOvershoot {
                let bounded = min(max(previous, target[i]), max(min(previous, target[i]), current[i]))
                if bounded != current[i] { current[i] = bounded; velocity[i] = 0 }
            }
        }
        lastTick = time
        position = current
        return current
    }
}

/// Independent channels share the same response without mixing units or samples.
struct MeasurementChannels {
    private var channels: [String: MeasurementMotion] = [:]
    mutating func reset() { channels.removeAll() }
    mutating func update(_ key: String, _ values: [Double]?, at time: Double) {
        guard let values = values else { channels.removeValue(forKey: key); return }
        channels[key, default: MeasurementMotion(preventsOvershoot: key == "gaze")].updateTarget(values, at: time)
    }
    mutating func sample(_ key: String, at time: Double) -> [Double]? {
        channels[key]?.sample(at: time)
    }
}

/// Visual dead reckoning only. Continue the displayed velocity through loss,
/// then reconcile with a critically damped spring when measurements resume.
/// Calibration, diagnostics and click coordinates never consume this prediction.
struct GazeMotion {
    static let fadeDuration = 1.5
    static let silenceTimeout = 0.5
    private var position: CGPoint?
    private var velocity = CGPoint.zero
    private var target = CGPoint.zero
    private var lastTick = 0.0
    private var lastTarget = 0.0
    private var lossStarted: Double?
    private var lossOpacity = 1.0
    private var hasAppeared = false
    private(set) var opacity = 0.0

    mutating func reset() { self = GazeMotion() }

    mutating func updateTarget(_ point: CGPoint, at time: Double) {
        guard point.x.isFinite, point.y.isFinite, time.isFinite else {
            if time.isFinite { loseTracking(at: time) }
            return
        }
        guard position == nil || time >= lastTick else { return }
        _ = sample(at: time)
        if position == nil {
            position = point
            velocity = .zero
            opacity = hasAppeared ? 0 : 1
            hasAppeared = true
        }
        target = point
        lastTarget = time
        lastTick = time
        lossStarted = nil
    }

    mutating func loseTracking(at time: Double) {
        guard time.isFinite, time >= lastTick else { return }
        _ = sample(at: time)
        guard position != nil, lossStarted == nil else { return }
        lossStarted = time
        lossOpacity = opacity
    }

    private mutating func follow(until time: Double) {
        guard let current = position else { return }
        let dt = time - lastTick
        let omega = 1.0 / 0.07
        let decay = exp(-omega * dt)
        func axis(_ value: CGFloat, _ speed: CGFloat, _ goal: CGFloat) -> (CGFloat, CGFloat) {
            let offset = Double(value - goal)
            let impulse = Double(speed) + omega * offset
            return (goal + CGFloat((offset + impulse * dt) * decay),
                    CGFloat((Double(speed) - omega * impulse * dt) * decay))
        }
        let x = axis(current.x, velocity.x, target.x)
        let y = axis(current.y, velocity.y, target.y)
        position = CGPoint(x: x.0, y: y.0)
        velocity = CGPoint(x: x.1, y: y.1)
        opacity = 1 - (1 - opacity) * exp(-dt / 0.1)
        lastTick = time
    }

    mutating func sample(at time: Double) -> CGPoint? {
        guard time.isFinite, time >= lastTick, position != nil else { return nil }
        // Split exactly at expiry so a slow render tick does not change the path.
        if lossStarted == nil {
            let expiry = lastTarget + Self.silenceTimeout
            follow(until: min(time, expiry))
            if time >= expiry { lossStarted = expiry; lossOpacity = opacity }
        }
        if let loss = lossStarted, let current = position {
            let end = loss + Self.fadeDuration
            let dt = max(0, min(time, end) - lastTick)
            position = CGPoint(x: current.x + velocity.x * dt, y: current.y + velocity.y * dt)
            let t = min(1, max(0, (time - loss) / Self.fadeDuration))
            opacity = lossOpacity * (1 - t * t * (3 - 2 * t))
            if time >= end { position = nil; velocity = .zero; opacity = 0 }
        }
        lastTick = time
        return position
    }
}

/// Matches quick_calibration.target_at. Python monotonic time and
/// ProcessInfo.systemUptime share macOS's boot clock, so capture and rendered
/// target positions agree without adding HTTP delivery latency to the path.
enum ScreenCalibrationPath {
    static func target(elapsed: Double, corner: Int? = nil) -> CGPoint {
        let elapsed = max(0, elapsed)
        let index = corner ?? min(3, Int(elapsed/1.95))
        let localElapsed = corner == nil ? elapsed-Double(index)*1.95 : elapsed
        let t = min(1, localElapsed/0.55)
        let eased = t*t*(3-2*t)
        let targets = [CGPoint(x: 0.5,y: 0.5), CGPoint(x: 0.08,y: 0.08),
                       CGPoint(x: 0.92,y: 0.08), CGPoint(x: 0.92,y: 0.92), CGPoint(x: 0.08,y: 0.92)]
        let start = targets[index], end = targets[index+1]
        return CGPoint(x: start.x+(end.x-start.x)*eased, y: start.y+(end.y-start.y)*eased)
    }
}

/// Animate the calibration path locally; network polling only starts/stops it.
struct CalibrationOrbit {
    private var startedAt: Double?

    mutating func reset() { startedAt = nil }

    mutating func synchronize(elapsed: Double, at time: Double) {
        guard elapsed.isFinite, elapsed >= 0, time.isFinite else { reset(); return }
        // Ignore normal network delivery jitter. A large discontinuity means a
        // new onboarding attempt, whose orbit needs a new local time origin.
        if startedAt == nil || abs(time - startedAt! - elapsed) > 1 {
            startedAt = time - elapsed
        }
    }

    func sample(at time: Double) -> CGPoint? {
        guard let origin = startedAt, time.isFinite else { return nil }
        let angle = min(4 * Double.pi, max(0, time - origin) * 0.75)
        return CGPoint(x: 0.5 + 0.36 * cos(angle), y: 0.5 + 0.34 * sin(angle))
    }
}

/// Convert the top-left normalized calibration point to an AppKit panel origin.
func calibrationTargetOrigin(_ point: CGPoint, display: CGRect, size: CGSize) -> CGPoint? {
    guard point.x.isFinite, point.y.isFinite, (0...1).contains(point.x), (0...1).contains(point.y),
          display.width > 0, display.height > 0 else { return nil }
    return CGPoint(x: display.minX + point.x * display.width - size.width / 2,
                   y: display.maxY - point.y * display.height - size.height / 2)
}

/// A continuous path from the currently visible target to the next fixation.
struct CalibrationTravel {
    private var origin: CGPoint?
    private var destination: CGPoint?
    private var startedAt = 0.0
    static let duration = 0.55

    mutating func reset() { origin = nil; destination = nil }

    mutating func move(from current: CGPoint, to next: CGPoint, at time: Double) {
        guard destination != next else { return }
        origin = current
        destination = next
        startedAt = time
    }

    func sample(at time: Double) -> CGPoint? {
        guard let origin = origin, let destination = destination else { return nil }
        let t = min(1, max(0, (time - startedAt) / Self.duration))
        let amount = t * t * (3 - 2 * t)
        return CGPoint(x: origin.x + (destination.x - origin.x) * amount,
                       y: origin.y + (destination.y - origin.y) * amount)
    }
}


/// A short history of measured screen estimates, never predicted across dropouts.
struct DiagnosticGazeTrail {
    private(set) var samples: [(point: CGPoint, time: Double)] = []
    private var display: String?
    mutating func reset() { samples.removeAll(); display = nil }
    mutating func update(_ point: CGPoint?, display key: String, at time: Double) {
        guard let point = point, time.isFinite, point.x.isFinite, point.y.isFinite,
              (0...1).contains(point.x), (0...1).contains(point.y) else { reset(); return }
        if display != key || samples.last.map({ time < $0.time || time - $0.time > 0.3 }) == true { reset() }
        display = key
        samples.removeAll { time - $0.time > 0.8 }
        samples.append((point, time))
        if samples.count > 32 { samples.removeFirst(samples.count - 32) }
    }
    mutating func expire(at time: Double) {
        if samples.last.map({ time - $0.time > 0.3 }) == true { reset() }
    }
}
