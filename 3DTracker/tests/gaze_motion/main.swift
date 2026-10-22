import Foundation
import CoreGraphics

var motion = GazeMotion()
precondition(motion.sample(at: 0) == nil)
motion.updateTarget(CGPoint(x: 10, y: 20), at: 0)
precondition(motion.sample(at: 0) == CGPoint(x: 10, y: 20))
motion.updateTarget(CGPoint(x: 110, y: -80), at: 0)
var previous = CGPoint(x: 10, y: 20)
for frame in 1...15 {
    let next = motion.sample(at: Double(frame) / 60)!
    precondition(next.x > previous.x && next.x < 110)
    precondition(next.y < previous.y && next.y > -80)
    previous = next
}
precondition(previous.x > 95, "Cursor should cover most of a sustained move within a quarter second")

var snappy = GazeMotion()
snappy.updateTarget(.zero, at: 0)
snappy.updateTarget(CGPoint(x: 500,y: 0), at: 0)
precondition(snappy.sample(at: 0.1)!.x > 450,
             "A purposeful cursor move must cover 90 percent within 100 ms")

func position(fps: Int) -> CGPoint {
    var easing = GazeMotion()
    easing.updateTarget(.zero, at: 0)
    easing.updateTarget(CGPoint(x: 100, y: 100), at: 0)
    for frame in 1...(fps * 3 / 10) { _ = easing.sample(at: Double(frame) / Double(fps)) }
    return easing.sample(at: 0.3)!
}
precondition(abs(position(fps: 30).x - position(fps: 60).x) < 0.000001)
precondition(motion.sample(at: 0.51) != nil, "Stale gaze starts fading instead of disappearing")
let predicted = motion.sample(at: 0.6)!
let fadedOpacity = motion.opacity
motion.updateTarget(CGPoint(x: 800, y: 300), at: 0.6)
precondition(motion.sample(at: 0.6) == predicted, "Reacquisition preserves the visible position")
precondition(motion.opacity == fadedOpacity, "Reacquisition preserves opacity")
motion.reset()
precondition(motion.sample(at: 0.61) == nil)
motion.updateTarget(CGPoint(x: CGFloat.nan, y: 0), at: 0.7)
precondition(motion.sample(at: 0.7) == nil)

func movingCursor() -> GazeMotion {
    var result = GazeMotion()
    result.updateTarget(CGPoint(x: 100, y: 200), at: 0)
    result.updateTarget(CGPoint(x: 200, y: 250), at: 0.05)
    _ = result.sample(at: 0.1)
    return result
}
var coast = movingCursor()
let beforeLoss = coast.sample(at: 0.1)!
coast.loseTracking(at: 0.1)
precondition(coast.sample(at: 0.1) == beforeLoss && coast.opacity == 1)
let coast1 = coast.sample(at: 0.2)!
let coast2 = coast.sample(at: 0.3)!
precondition(coast1.x > beforeLoss.x && coast1.y > beforeLoss.y)
precondition(abs((coast2.x-coast1.x) - (coast1.x-beforeLoss.x)) < 0.000001,
             "Loss preserves constant velocity, including its direction")
coast.loseTracking(at: 0.3)
_ = coast.sample(at: 0.85)
precondition(abs(coast.opacity - 0.5) < 0.000001, "Repeated loss must not restart the fade")
precondition(coast.sample(at: 1.599) != nil && coast.opacity > 0)
precondition(coast.sample(at: 1.6) == nil && coast.opacity == 0)
coast.updateTarget(CGPoint(x: -500, y: -200), at: 2)
precondition(coast.sample(at: 2) == CGPoint(x: -500, y: -200) && coast.opacity == 0,
             "After a completed fade, reappear at the fresh position without a stale sweep")
_ = coast.sample(at: 2.1)
precondition(coast.opacity > 0 && coast.opacity < 1)

var recover = movingCursor()
recover.loseTracking(at: 0.1)
let recoveryStart = recover.sample(at: 0.4)!
let recoveryAlpha = recover.opacity
let prior = recover.sample(at: 0.400001)!
let priorVelocity = (prior.x - recoveryStart.x) / 0.000001
recover.updateTarget(CGPoint(x: -200, y: -100), at: 0.400001)
precondition(recover.sample(at: 0.400001) == prior)
// Smaller derivative interval also resolves the faster response's acceleration.
let next = recover.sample(at: 0.40000101)!
precondition(abs((next.x - prior.x) / 0.00000001 - priorVelocity) < 0.1,
             "Reconciliation preserves instantaneous velocity before turning")
let corrected = recover.sample(at: 0.8)!
precondition(abs(corrected.x + 200) < 20 && recover.opacity > recoveryAlpha)
let stable = corrected
recover.updateTarget(CGPoint(x: 999, y: 999), at: 0.1)
precondition(recover.sample(at: 0.8) == stable, "Out of order updates cannot rewind the cursor")
recover.updateTarget(CGPoint(x: CGFloat.nan, y: 0), at: 0.8)
precondition(recover.sample(at: 0.8) == stable, "Invalid samples fade existing motion")

func dropoutPath(fps: Int) -> (CGPoint, Double) {
    var result = movingCursor()
    result.loseTracking(at: 0.1)
    for i in 1...fps { _ = result.sample(at: 0.1 + Double(i) / Double(fps)) }
    return (result.sample(at: 1.1)!, result.opacity)
}
let slow = dropoutPath(fps: 30), fast = dropoutPath(fps: 144)
precondition(hypot(slow.0.x-fast.0.x, slow.0.y-fast.0.y) < 0.000001 && abs(slow.1-fast.1) < 0.000001)
var silent = movingCursor()
precondition(silent.sample(at: 0.8) != nil && silent.opacity < 1)
precondition(silent.sample(at: 2.05) == nil, "Network silence must eventually expire the circle")

var jitter = GazeMotion()
jitter.updateTarget(.zero, at: 0)
var displayed: [Double] = []
for frame in 1...120 {
    let time = Double(frame) / 60
    if frame % 3 == 0 {
        jitter.updateTarget(CGPoint(x: (frame / 3) % 2 == 0 ? 3 : -3, y: 0), at: time)
    }
    let point = jitter.sample(at: time)!
    if frame > 30 { displayed.append(point.x) }
}
precondition(displayed.max()! - displayed.min()! < 4, "Smoothing should reduce a six-pixel jitter range")
precondition(displayed.max()! - displayed.min()! < 1, "Rapid alternating noise should barely move the marker")

var redirected = MeasurementMotion()
redirected.updateTarget([0, 0, 0], at: 0)
redirected.updateTarget([100, -100, 50], at: 0)
let moving = redirected.sample(at: 0.05)!
redirected.updateTarget([-20, 20, -10], at: 0.05)
precondition(redirected.sample(at: 0.05)! == moving, "Retargeting must not jump the displayed value")
let following = redirected.sample(at: 0.051)!
precondition(following[0] > moving[0] && following[0] - moving[0] < 1,
             "Retargeting must preserve velocity, then gently turn toward the new target")
precondition(redirected.sample(at: 0.35)![0] < moving[0], "New samples redirect unfinished movement")
var gazeChannel = MeasurementChannels()
gazeChannel.update("gaze", [0.5,0.5], at: 0)
gazeChannel.update("gaze", [0.9,0.9], at: 0)
let beforeGazeReversal = gazeChannel.sample("gaze", at: 0.05)!
gazeChannel.update("gaze", [0.1,0.1], at: 0.05)
precondition(gazeChannel.sample("gaze", at: 0.06)![0] <= beforeGazeReversal[0],
             "Diagnostic screen ray must remain conservative")
var channels = MeasurementChannels()
channels.update("head", [1,2,3], at: 0)
channels.update("confidence", [0.8], at: 0)
channels.update("head", nil, at: 0.1)
precondition(channels.sample("head", at: 0.1) == nil, "Missing measurements must remain unavailable")
precondition(channels.sample("confidence", at: 0.1) == [0.8], "Measurement channels must stay independent")
channels.update("confidence", [.nan], at: 0.2)
precondition(channels.sample("confidence", at: 0.2) == nil)
redirected.updateTarget([0.3], at: 0.4)
precondition(redirected.sample(at: 0.4) == [0.3], "Changing dimensions must clear old motion")
print("Gaze motion checks passed: initial placement, easing, frame-rate independence, momentum, 1.5-second fade, continuous recovery, silence expiry, invalid input, jitter reduction.")

var orbit = CalibrationOrbit()
precondition(orbit.sample(at: 0) == nil)
orbit.synchronize(elapsed: 0, at: 100)
var positions: [CGPoint] = []
for frame in 0..<60 {
    let now = 100 + Double(frame) / 60
    // Simulate irregular 20 Hz status delivery while animation runs at 60 Hz.
    if frame % 3 == 0 { orbit.synchronize(elapsed: Double(frame) / 60 - (frame == 0 ? 0 : 0.02), at: now) }
    let point = orbit.sample(at: now)!
    let expected = CGPoint(x: 0.5 + 0.36 * cos(Double(frame) / 60 * 0.75),
                           y: 0.5 + 0.34 * sin(Double(frame) / 60 * 0.75))
    precondition(hypot(point.x - expected.x, point.y - expected.y) < 0.000001,
                 "Network jitter must not shift the calibration orbit")
    if let previous = positions.last { precondition(point != previous, "Every display tick must move the target") }
    positions.append(point)
}
orbit.reset()
precondition(orbit.sample(at: 102) == nil)
orbit.synchronize(elapsed: .nan, at: 103)
precondition(orbit.sample(at: 103) == nil)
print("Calibration orbit checks passed: 60 distinct updates per second, no phase jumps from network jitter, reset, invalid input.")

let overlaySize = CGSize(width: 40, height: 40)
precondition(calibrationTargetOrigin(CGPoint(x: 0.5, y: 0.5),
    display: CGRect(x: 0, y: 0, width: 1920, height: 1080), size: overlaySize) == CGPoint(x: 940, y: 520))
precondition(calibrationTargetOrigin(CGPoint(x: 0.08, y: 0.08),
    display: CGRect(x: -1600, y: -200, width: 1600, height: 900), size: overlaySize) == CGPoint(x: -1492, y: 608))
precondition(calibrationTargetOrigin(CGPoint(x: 1.1, y: 0.5), display: CGRect(x: 0, y: 0, width: 1920, height: 1080), size: overlaySize) == nil)
print("Desktop calibration overlay checks passed: target centering, offset display, top-left coordinates, invalid point rejection.")

var limitedOrbit = CalibrationOrbit()
limitedOrbit.synchronize(elapsed: 0, at: 0)
let orbitEnd = limitedOrbit.sample(at: 4 * Double.pi / 0.75)!
precondition(limitedOrbit.sample(at: 60) == orbitEnd, "Orbit cannot start a third rotation")
var travel = CalibrationTravel()
let start = CGPoint(x: 50, y: 70)
let finish = CGPoint(x: 1200, y: 900)
travel.move(from: start, to: finish, at: 0)
precondition(travel.sample(at: 0) == start, "Transition starts at the still-visible orbit target")
var last = start
for frame in 1...33 {
    let t = Double(frame) / 60
    let point = travel.sample(at: t)!
    precondition(point.x > last.x && point.x <= finish.x)
    precondition(hypot(point.x - last.x, point.y - last.y) < 70, "No jump between frames")
    // Repeated server polls must not restart the animation.
    travel.move(from: point, to: finish, at: t)
    last = point
}
precondition(travel.sample(at: 1) == finish)
travel.reset()
precondition(travel.sample(at: 2) == nil)
print("Two-orbit cap and continuous target travel checks passed.")

var feedback = CalibrationFeedback()
feedback.update(key: "head:center", progress: 0.6, accepted: true)
precondition(feedback.progress == 0.6 && feedback.accepted)
feedback.update(key: "head:center", progress: 0.2, accepted: false)
precondition(feedback.progress == 0.6 && !feedback.accepted, "Rejected samples change color without reversing the displayed ring")
feedback.update(key: "head:center", progress: 0.9, accepted: false)
precondition(feedback.progress == 0.6, "Rejected samples cannot advance a paused progress ring")
feedback.update(key: "head:center", progress: 0.8, accepted: true)
precondition(feedback.progress == 0.8, "Progress resumes once accepted evidence exceeds the held value")
feedback.update(key: "head:center", progress: .nan, accepted: false)
precondition(feedback.progress == 0.8)
feedback.update(key: "screen:top-left", progress: 0, accepted: true)
precondition(feedback.progress == 0 && feedback.accepted, "A new target starts a new ring")
feedback.reset()
precondition(feedback.progress == 0 && !feedback.accepted)
print("Calibration feedback checks passed: monotonic display, acceptance color, target reset, invalid input.")

var trail = DiagnosticGazeTrail()
for i in 0..<100 { trail.update(CGPoint(x: 0.3, y: 0.7), display: "laptop", at: Double(i) / 60) }
precondition(trail.samples.count == 32)
trail.update(CGPoint(x: 0.4, y: 0.6), display: "external", at: 1.7)
precondition(trail.samples.count == 1, "Never join a trail across monitors")
trail.expire(at: 2.01)
precondition(trail.samples.isEmpty, "Network silence must clear stale rays")
trail.update(CGPoint(x: 0.4, y: 0.6), display: "laptop", at: 3)
trail.update(nil, display: "laptop", at: 3.1)
precondition(trail.samples.isEmpty, "Rejected frames must not invent gaze")
trail.update(CGPoint(x: CGFloat.nan, y: 0), display: "laptop", at: 3.2)
precondition(trail.samples.isEmpty)
trail.update(CGPoint(x: 1.1, y: 0), display: "laptop", at: 3.3)
precondition(trail.samples.isEmpty)
trail.update(CGPoint(x: 0.4, y: 0.6), display: "laptop", at: 4)
trail.update(CGPoint(x: 0.4, y: 0.6), display: "laptop", at: 4.4)
precondition(trail.samples.count == 1, "No line across a capture gap")
print("Diagnostic gaze trail checks passed: bounded history, monitor switch, stale expiry, invalid estimates, capture gaps.")

let screenFixtures: [(Double, CGPoint)] = [(0, CGPoint(x: 0.5,y: 0.5)),
    (0.55, CGPoint(x: 0.08,y: 0.08)), (1.95, CGPoint(x: 0.08,y: 0.08)),
    (2.5, CGPoint(x: 0.92,y: 0.08)), (3.9, CGPoint(x: 0.92,y: 0.08)),
    (4.45, CGPoint(x: 0.92,y: 0.92)), (5.85, CGPoint(x: 0.92,y: 0.92)),
    (6.4, CGPoint(x: 0.08,y: 0.92)), (100, CGPoint(x: 0.08,y: 0.92))]
for (time,expected) in screenFixtures {
    let actual = ScreenCalibrationPath.target(elapsed: time)
    precondition(hypot(actual.x-expected.x,actual.y-expected.y) < 0.00001)
}
for time in [0.55, 1.95, 2.5, 3.9, 4.45, 5.85, 6.4] {
    let before = ScreenCalibrationPath.target(elapsed: time-0.001)
    let after = ScreenCalibrationPath.target(elapsed: time+0.001)
    precondition(hypot(after.x-before.x,after.y-before.y) < 0.001)
}
print("Quick screen path passed: shared timeline, eased travel, stationary capture, finite single pass.")
