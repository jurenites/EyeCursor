// Native macOS interface. Sampling, stability checks and mapping live in Python.
import AppKit
import ApplicationServices
import AVFoundation

struct CalibrationStep: Decodable {
    let phase: String
    let step: Int
    let target: [Double]?
    let progress: Double
    let message: String
}
struct TrackerState: Decodable {
    let source: String
    let eye_camera_id: String?
    let eye_cameras: EyeCamerasState?
    let mode: String?
    let head_camera: HeadCameraState?
    let camera_connected: Bool
    let valid: Bool
    let display_valid: Bool?
    let detection_threshold: Double?
    let confidence: Double?
    let pupil_center: [Double]?
    let detection_evidence: DetectionEvidence?
    let eye_region: [Double]?
    let calibrated: Bool
    let cursor_message: String?
    let desktop_cursor: Bool
    let desktop_gaze: [Double]?
    let gaze: [Double]?
    let unclamped_gaze: [Double]?
    let calibration: CalibrationStep?
    let blink_click_enabled: Bool
    let click_event: EyeClick?
    let eye_model: EyeModelState
    let onboarding: OnboardingState?
    let performance: TrackerPerformance?
    let eye_direction: DebugEyeDirection?
}
struct EyeCameraDevice: Decodable {
    let id: String
    let name: String
}
struct EyeCameraSlot: Decodable {
    let device_id: String?
    let rotation: Int
    let connected: Bool
    let fps: Double
    let status: String
    let error: String?
    var tracking: String? = nil
    var tracking_fps: Double? = nil
    var confidence: Double? = nil
}
struct EyeCamerasState: Decodable {
    let active_eye: String
    let eyes: [String: EyeCameraSlot]
    let devices: [EyeCameraDevice]
    let error: String?
}
struct DetectionEvidence: Decodable {
    let shape_source: String?
}
struct HeadCameraState: Decodable {
    let image_aspect: Double?
    let name: String
    let connected: Bool
    let face_visible: Bool
    let fps: Double
    let preview_irises: [[Double]]?
    let error: String?
    let features: [Double]?
    let eye_rays: [[Double]?]?
}
struct GeometryCalibrationState: Decodable {
    let motion_hint: String?
    let phase: String
    let message: String
    let remaining_seconds: Double
    let validation_error_uv: Double?
    let baseline_error_uv: Double?
    let applied: Bool
}
struct GazeGeometryModel: Decodable {
    let checked_motion: [String: Bool]?
    let depth_screen_widths: Double
    let reference_log_face_width: Double
    let camera_aspect: Double
    let eye_separation_screen_widths: Double
}
struct CursorCalibrationState: Decodable {
    let active: Bool
    let positions: Int
    let remaining_seconds: Double?
    let ready: Bool
    let message: String
    let stage: String?
    let head_cue: String?
    let progress: Double?
    let live_preview: Bool?
    let sample_accepted: Bool?
    let saved_anchors: Int?
    let fixed_target: [Double]?
    let target_complete: Bool?
    let target_position: [Double]?
}
struct TrackerPerformance: Decodable {
    let tracking_fps: Double
    let preview_fps: Double
}
struct AccuracyRow: Decodable {
    let target: [Double]
    let measured: [Double]?
    let error_points: Double?
    let precision_points: Double?
    let samples: Int
}
struct AccuracyCheckState: Decodable {
    let status: String
    let target_index: Int
    let target_count: Int
    let targets: [[Double]]?
    let rows: [AccuracyRow]
    let mean_error_points: Double?
    let worst_error_points: Double?
    let viewport_size: [Double]
    let remaining_seconds: Double
}

struct OnboardingState: Decodable {
    let accuracy_check: AccuracyCheckState?
    let screen_path: String?
    let screen_path_started_at: Double?
    let cursor_calibration: CursorCalibrationState?
    let calibration_rays: [CalibrationRay]?
    let calibration_session_id: String?
    let head_correction_rank: Int?
    let head_correction_status: String?
    let geometry_calibration: GeometryCalibrationState?
    let geometry_model: GazeGeometryModel?
    let phase: String
    let display_id: String?
    let display_index: Int
    let display_count: Int
    let target: [Double]?
    let progress: Double
    let message: String
    let elapsed: Double
    let fast_path: Bool
    let sample_accepted: Bool?
    let head_cue: String?
    let head_ready: Bool?
    let head_mode: String?
    let screen_fit_status: String?
    let screen_fit_error: Double?
    let screen_target_index: Int?
    let screen_sectors: Int?
    let screen_points: Int?
    let screen_point: Int?
    let blocker: String?
    let stopped_stage: String?
    let remaining_seconds: Double?
    let step_remaining_seconds: Double?
}
struct EyeModelState: Decodable {
    let phase: String
    let can_freeze: Bool
    let message: String
}
struct EyeClick: Decodable {
    let id: Int
    let point: [Double]
    let age_ms: Double
}

final class CalibrationStepsView: NSView {
    let heading = NSTextField(labelWithString: "Calibration")
    let countdown = NSTextField(wrappingLabelWithString: "Waiting for cameras")
    let actionButton = NSButton(title: "Start calibration", target: nil, action: nil)
    let manualButton = NSButton(title: "Calibrate with system cursor", target: nil, action: nil)
    let accuracyButton = NSButton(title: "Check accuracy", target: nil, action: nil)
    let accuracySummary = NSTextField(wrappingLabelWithString: "Accuracy not checked for this mapping.")
    let rows = (0..<4).map { _ in NSTextField(wrappingLabelWithString: "") }
    let descriptions = ["Look at center for about two seconds; keep your head comfortable and still",
                        "Follow the four dots; keep your head still",
                        "Check five new dots; these samples only measure accuracy"]

    override init(frame: NSRect) {
        super.init(frame: frame)
        heading.font = .systemFont(ofSize: 13, weight: .semibold)
        countdown.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
        countdown.textColor = .secondaryLabelColor
        countdown.alignment = .left
        actionButton.bezelStyle = .rounded
        manualButton.bezelStyle = .rounded
        accuracyButton.bezelStyle = .rounded
        accuracySummary.font = .systemFont(ofSize: 11)
        accuracySummary.textColor = .secondaryLabelColor
        addSubview(accuracyButton); addSubview(accuracySummary)
        addSubview(manualButton)
        addSubview(heading); addSubview(countdown); addSubview(actionButton)
        for row in rows { addSubview(row) }
        update(nil)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override var intrinsicContentSize: NSSize {
        NSSize(width: NSView.noIntrinsicMetric, height: (accuracyButton.isHidden ? 0 : 126) + (manualButton.isHidden ? 130 : 166) + CGFloat(rows.filter { !$0.isHidden }.count) * 58)
    }
    override func layout() {
        super.layout()
        heading.frame = NSRect(x: 0, y: bounds.height - 20, width: bounds.width, height: 20)
        countdown.frame = NSRect(x: 0, y: bounds.height - 90, width: bounds.width, height: 64)
        let footer: CGFloat = accuracyButton.isHidden ? 0 : 126
        accuracyButton.frame = NSRect(x: 0, y: 90, width: bounds.width, height: 30)
        accuracySummary.frame = NSRect(x: 0, y: 0, width: bounds.width, height: 84)
        actionButton.frame = NSRect(x: 0, y: footer + (manualButton.isHidden ? 0 : 36), width: bounds.width, height: 30)
        manualButton.frame = NSRect(x: 0, y: footer, width: bounds.width, height: 30)
        for (index, row) in rows.enumerated() {
            row.frame = NSRect(x: 0, y: bounds.height - 150 - CGFloat(index) * 58, width: bounds.width, height: 54)
        }
    }
    func update(_ flow: OnboardingState?, stale: Bool = false) {
        let phase = flow?.phase ?? "no_displays"
        manualButton.isHidden = flow?.cursor_calibration?.active == true || phase == "complete"
        accuracyButton.isHidden = !["complete", "verify"].contains(phase)
        accuracySummary.isHidden = accuracyButton.isHidden
        let phases = ["head", "screen", "verify"]
        let paused = phase == "paused"
        let current = phases.firstIndex(of: paused ? (flow?.stopped_stage ?? "") : phase)
        let running = ["waiting", "fitting", "head", "screen", "verify"].contains(phase)
        actionButton.title = phase == "complete" ? "Align with system cursor" :
            running ? "Stop calibration" : paused ? "Retry step \((current ?? 0) + 1)" : "Start calibration"
        for (index, row) in rows.enumerated() {
            row.isHidden = index >= descriptions.count
            guard !row.isHidden else { row.stringValue = ""; continue }
            let done = phase == "complete" || current.map { index < $0 } == true
            let selected = current == index
            let suffix = done ? "  ✓" : selected ? (paused ? "  · Ready to retry" : "  · Active") : ""
            row.stringValue = "\(index + 1). \(descriptions[index])\(suffix)"
            row.font = .systemFont(ofSize: 13, weight: selected ? .semibold : .regular)
            row.textColor = stale ? .secondaryLabelColor : selected ? (paused ? .systemOrange : .systemBlue) : done ? .labelColor : .secondaryLabelColor
        }
        heading.stringValue = "Calibration"
        if let cursor = flow?.cursor_calibration, cursor.active {
            heading.stringValue = "Cursor alignment"
            actionButton.title = cursor.ready ? "Finish cursor alignment" : "Stop cursor alignment"
            let practice = cursor.stage == "geometry"
            if practice { heading.stringValue = "Fixed-target head calibration"; actionButton.title = "Stop head calibration" }
            let previewAlignment = cursor.fixed_target != nil && !practice
            if previewAlignment {
                heading.stringValue = "IR preview alignment"
                actionButton.title = cursor.ready ? "Finish preview alignment" : "Stop preview alignment"
            }
            let steps = previewAlignment ? ["Look at the fixed marker over the IR preview",
                         "Hold still for one second to save a reference",
                         "Keep watching it; move your head slightly and pause", cursor.message] : practice ? ["Keep looking at the fixed center dot",
                         flow?.geometry_calibration?.motion_hint == "shift" ? "Slide your head sideways; keep your face forward" : "Turn your head gently left and right",
                         "Keep watching the dot as your head moves", cursor.message] :
                        ["Look at the mouse; hold it still until the checkmark",
                         cursor.positions < 6 && cursor.ready == false ? "Save six positions across the screen; keep your head still" : "Move the pointer or your head to add measurements",
                         "When ready, press Finish cursor alignment", cursor.message]
            for (i,row) in rows.enumerated() {
                row.isHidden = false
                row.stringValue = "\(i+1). \(steps[i])"; row.textColor = .labelColor
            }
            invalidateIntrinsicContentSize(); needsLayout = true
            countdown.stringValue = stale ? "Waiting for tracker response" : practice
                ? "\(Int(ceil(cursor.remaining_seconds ?? 15)))s left · \(flow?.geometry_calibration?.phase == "validate" ? "Checking" : "Learning")"
                : cursor.stage == "center" ? "Hold a comfortable center position"
                : "\(cursor.saved_anchors ?? cursor.positions) saved fixations · \(cursor.live_preview == true ? "Live adjustment" : "Collecting screen fit")"
            return
        }
        invalidateIntrinsicContentSize(); needsLayout = true
        if stale { countdown.stringValue = "Waiting for tracker response" }
        else if phase == "complete" { countdown.stringValue = flow?.geometry_calibration?.message ?? flow?.message ?? "Ready" }
        else if paused { countdown.stringValue = flow?.blocker == "Stopped by user" ? "Stopped · Completed steps saved" : (flow?.blocker ?? "Stopped · Retry this step") }
        else if phase == "cancelled" { countdown.stringValue = "Calibration cancelled" }
        else if phase == "verify", let check = flow?.accuracy_check {
            countdown.stringValue = "Accuracy check \(check.target_index)/\(check.target_count) · \(Int(ceil(check.remaining_seconds)))s available\n\(flow?.blocker ?? "Look at the dot")"
        }
        else if flow?.screen_path == "quick" {
            let feedback = flow?.sample_accepted == true ? "Collecting paired eye and head samples" : (flow?.blocker ?? "Hold at the dot")
            countdown.stringValue = "Target \(flow?.screen_target_index ?? 2)/5 · \(Int(ceil(flow?.remaining_seconds ?? 0)))s available\n\(feedback)"
        }
        else if let remaining = flow?.remaining_seconds, remaining.isFinite {
            let total = max(0, Int(ceil(remaining)))
            if let step = flow?.step_remaining_seconds, step.isFinite {
                countdown.stringValue = "\(total)s total · \(max(0, Int(ceil(step))))s for this step (time limits)"
            } else { countdown.stringValue = "\(total)s remaining before timeout" }
        } else { countdown.stringValue = "Waiting for the tracking eye and head webcam" }
    }
}

final class DotView: NSView {
    override func draw(_ dirtyRect: NSRect) {
        NSColor.white.withAlphaComponent(0.55).setFill()
        NSBezierPath(ovalIn: bounds).fill()
    }
}
final class DotPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}
final class CalibrationView: NSView {
    var monochrome = false { didSet { needsDisplay = true } }
    var progress = 0.0 { didSet { needsDisplay = true } }
    var accepted = false { didSet { needsDisplay = true } }
    var hollow = false { didSet { needsDisplay = true } }
    var completed = false { didSet { needsDisplay = true } }
    var headCue: String? { didSet { needsDisplay = true } }
    override var isOpaque: Bool { false }
    override func draw(_ dirtyRect: NSRect) {
        // Only the target and its progress ring are drawn. The desktop remains
        // visible through this small, nonactivating, click-through panel.
        NSColor.clear.setFill()
        bounds.fill(using: .copy)
        let center = NSPoint(x: bounds.midX, y: bounds.midY)
        let pupil = NSBezierPath(ovalIn: NSRect(x: center.x - 10, y: center.y - 10, width: 20, height: 20))
        NSColor.white.withAlphaComponent(0.55).setFill()
        if !hollow && !completed { pupil.fill() }
        NSColor.black.withAlphaComponent(0.45).setStroke()
        pupil.lineWidth = 1
        if !hollow && !completed { pupil.stroke() }
        if hollow && !completed {
            NSColor.white.setFill()
            NSBezierPath(ovalIn: NSRect(x: center.x - 1, y: center.y - 1, width: 2, height: 2)).fill()
        }
        let ring = NSBezierPath(ovalIn: NSRect(x: center.x - 20, y: center.y - 20, width: 40, height: 40))
        ring.lineWidth = 4
        NSColor.black.withAlphaComponent(0.3).setStroke()
        ring.stroke()
        ring.lineWidth = 2
        let feedbackColor: NSColor = completed ? .systemGreen : monochrome ? (accepted ? .white : .gray) : (accepted ? .systemGreen : .systemRed)
        feedbackColor.withAlphaComponent(0.45).setStroke()
        ring.stroke()
        let amount = completed ? 1 : progress.isFinite ? min(1, max(0, progress)) : 0
        if amount > 0 {
            let arc = NSBezierPath()
            arc.lineWidth = 2
            arc.lineCapStyle = .round
            arc.appendArc(withCenter: center, radius: 20, startAngle: 90,
                          endAngle: 90 - CGFloat(amount) * 360, clockwise: true)
            feedbackColor.withAlphaComponent(0.95).setStroke()
            arc.stroke()
        }
        if completed {
            let check = NSBezierPath()
            check.move(to: NSPoint(x: center.x - 7, y: center.y))
            check.line(to: NSPoint(x: center.x - 2, y: center.y - 5))
            check.line(to: NSPoint(x: center.x + 8, y: center.y + 6))
            check.lineWidth = 2.5; check.lineCapStyle = .round; check.lineJoinStyle = .round
            NSColor.systemGreen.setStroke(); check.stroke()
        }
        if let cue = headCue {
            let head = NSPoint(x: center.x, y: center.y - 42)
            NSColor.black.withAlphaComponent(0.55).setFill()
            NSBezierPath(roundedRect: NSRect(x: head.x - 36, y: head.y - 24, width: 72, height: 48),
                         xRadius: 12, yRadius: 12).fill()
            NSColor.white.withAlphaComponent(0.85).setStroke()
            let face = NSBezierPath(ovalIn: NSRect(x: head.x - 7, y: head.y - 9, width: 14, height: 18))
            face.lineWidth = 1.5; face.stroke()
            NSColor.white.withAlphaComponent(0.85).setFill()
            for dx in [-3.0, 3.0] {
                NSBezierPath(ovalIn: NSRect(x: head.x + dx - 1, y: head.y + 1, width: 2, height: 2)).fill()
            }
            func arrow(_ from: CGPoint, _ to: CGPoint) {
                let line = NSBezierPath(); line.lineWidth = 1.5
                line.move(to: from); line.line(to: to)
                let dx = to.x - from.x, dy = to.y - from.y, length = hypot(dx,dy)
                let ux = dx/length, uy = dy/length
                line.move(to: CGPoint(x: to.x - 4*ux + 3*uy, y: to.y - 4*uy - 3*ux))
                line.line(to: to)
                line.line(to: CGPoint(x: to.x - 4*ux - 3*uy, y: to.y - 4*uy + 3*ux))
                line.stroke()
            }
            if cue == "yaw" || cue == "both" {
                for side in [-1.0, 1.0] {
                    arrow(CGPoint(x: head.x + 13*side, y: head.y), CGPoint(x: head.x + 29*side, y: head.y))
                }
            }
            if cue == "pitch" || cue == "both" {
                for side in [-1.0, 1.0] {
                    arrow(CGPoint(x: head.x, y: head.y + 12*side), CGPoint(x: head.x, y: head.y + 21*side))
                }
            }
            if cue == "left" || cue == "right" {
                let sign = cue == "left" ? -1.0 : 1.0
                arrow(CGPoint(x: head.x + 13*sign, y: head.y), CGPoint(x: head.x + 29*sign, y: head.y))
            }
            if cue == "up" || cue == "down" {
                let sign = cue == "up" ? 1.0 : -1.0
                arrow(CGPoint(x: head.x, y: head.y + 12*sign), CGPoint(x: head.x, y: head.y + 21*sign))
            }
            for (name, dx, dy) in [("top-left", -1.0, 1.0), ("top-right", 1.0, 1.0),
                                   ("bottom-right", 1.0, -1.0), ("bottom-left", -1.0, -1.0)] {
                if cue == name || cue == "cone" {
                    arrow(CGPoint(x: head.x + 12*dx, y: head.y + 9*dy),
                          CGPoint(x: head.x + 28*dx, y: head.y + 20*dy))
                }
            }
        }

    }
}

class CameraPreviewView: NSView {
    var image: NSImage? { didSet { needsDisplay = true } }
    var selection: (([Double]) -> Void)?
    private var start: NSPoint?
    private var end: NSPoint?

    override func draw(_ dirtyRect: NSRect) {
        NSColor.black.setFill()
        bounds.fill()
        image?.draw(in: bounds)
        if let start = start, let end = end {
            let rect = NSRect(x: min(start.x, end.x), y: min(start.y, end.y),
                              width: abs(start.x - end.x), height: abs(start.y - end.y))
            NSColor.systemYellow.withAlphaComponent(0.18).setFill()
            rect.fill()
            NSColor.systemYellow.setStroke()
            let border = NSBezierPath(rect: rect)
            border.lineWidth = 2
            border.stroke()
        }
    }
    private func clipped(_ event: NSEvent) -> NSPoint {
        let point = convert(event.locationInWindow, from: nil)
        return NSPoint(x: min(max(point.x, 0), bounds.width),
                       y: min(max(point.y, 0), bounds.height))
    }
    override func mouseDown(with event: NSEvent) {
        guard selection != nil else { return }
        start = clipped(event)
        end = start
        needsDisplay = true
    }
    override func mouseDragged(with event: NSEvent) {
        end = clipped(event)
        needsDisplay = true
    }
    override func mouseUp(with event: NSEvent) {
        defer { start = nil; end = nil; needsDisplay = true }
        guard let start = start else { return }
        let end = clipped(event)
        let left = min(start.x, end.x) / bounds.width
        let right = max(start.x, end.x) / bounds.width
        let top = 1 - max(start.y, end.y) / bounds.height
        let bottom = 1 - min(start.y, end.y) / bounds.height
        if right - left >= 0.125 && bottom - top >= 0.125 {
            selection?([left, top, right, bottom].map(Double.init))
        }
    }
}

final class DiagnosticsClipView: NSClipView {
    override var isFlipped: Bool { true }
}

final class CameraSidebarDivider: NSView {
    var resize: ((CGFloat) -> Void)?
    private var grabOffset: CGFloat = 0
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func resetCursorRects() { addCursorRect(bounds, cursor: .resizeLeftRight) }
    override func draw(_ rect: NSRect) {
        NSColor.white.withAlphaComponent(0.15).setFill()
        NSRect(x: bounds.midX - 0.5, y: 0, width: 1, height: bounds.height).fill()
        NSColor.white.withAlphaComponent(0.55).setFill()
        NSBezierPath(roundedRect: NSRect(x: bounds.midX - 1.5, y: bounds.midY - 18, width: 3, height: 36),
                     xRadius: 1.5, yRadius: 1.5).fill()
    }
    override func mouseDown(with event: NSEvent) {
        grabOffset = convert(event.locationInWindow, from: nil).x
    }
    override func mouseDragged(with event: NSEvent) {
        guard let parent = superview else { return }
        resize?(parent.convert(event.locationInWindow, from: nil).x - grabOffset)
    }
}

final class CalibrationApp: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuDelegate {
    enum PreviewAlignmentAction { case start, finish }
    let port: Int
    let hybrid: Bool
    let parentPID = getppid()
    // Calibration uses the same kind of desktop overlay as the gaze cursor.
    let window = DotPanel(contentRect: NSRect(x: 0, y: 0, width: 96, height: 140),
                          styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
    let surface = CalibrationView()
    let cursorReference = DotPanel(contentRect: NSRect(x: 0, y: 0, width: 96, height: 140),
                                  styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
    let cursorReferenceSurface = CalibrationView()

    let statusMenu = NSMenuItem(title: "Connecting to eye camera", action: nil, keyEquivalent: "")
    let calibrateMenu = NSMenuItem(title: "Restart calibration", action: nil, keyEquivalent: "")
    let cursorAlignMenu = NSMenuItem(title: "Align with cursor", action: nil, keyEquivalent: "")
    let headPracticeMenu = NSMenuItem(title: "Calibrate head movement", action: nil, keyEquivalent: "")
    let cancelMenu = NSMenuItem(title: "Cancel calibration", action: nil, keyEquivalent: "\u{1b}")
    let diagnosticMenu = NSMenuItem(title: "Diagnostics", action: nil, keyEquivalent: "")
    let diagnosticWindow = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 680, height: 630),
                                    styleMask: [.titled, .closable, .resizable, .miniaturizable],
                                    backing: .buffered, defer: false)
    let preview = CameraPreviewView(frame: NSRect(x: 20, y: 130, width: 640, height: 480))
    let secondaryEyePreview = CameraPreviewView()
    let trackingEyeTitle = NSTextField(labelWithString: "Left eye")
    let secondaryEyeTitle = NSTextField(labelWithString: "Right eye")
    let secondaryEyeStatus = NSTextField(labelWithString: "Not assigned")
    let eyeSetupStack = NSStackView()
    var cameraStack: NSStackView?
    var eyeSetupExpanded = true
    let eyeSetupToggle = NSButton(title: "Camera setup ▾", target: nil, action: nil)
    let leftCameraChoice = NSPopUpButton(frame: .zero, pullsDown: false)
    let rightCameraChoice = NSPopUpButton(frame: .zero, pullsDown: false)
    let leftRotation = NSButton(checkboxWithTitle: "Rotate left 180°", target: nil, action: nil)
    let rightRotation = NSButton(checkboxWithTitle: "Rotate right 180°", target: nil, action: nil)
    let eyeSetupStatus = NSTextField(wrappingLabelWithString: "Both eyes track together. Assign a different camera to each eye. Left defaults to 180°.")
    let calibrationEyeStatus = NSTextField(wrappingLabelWithString: "")
    var eyeSetupPending = false
    var eyeCameraMenuOpen = false
    var deferredEyeSetup: EyeCamerasState?
    var eyeSetupSignature = ""
    let previewAlignButton = NSButton(title: "Align with IR preview", target: nil, action: nil)
    var pendingPreviewAlignment: PreviewAlignmentAction?
    let diagnosticText = NSTextField(wrappingLabelWithString:
        "Waiting for eye camera. Drag around the eye to exclude a dark corner. Green: accepted pupil/ray · Cyan: modeled eye center · Magenta: seed · Red: rejected")
    let facePreview = CameraPreviewView()
    let faceText = NSTextField(wrappingLabelWithString: "Waiting for the laptop webcam.")
    let clearEyeRegion = NSButton(title: "Clear eye area", target: nil, action: nil)
    let thresholdLabel = NSTextField(labelWithString: "Detection threshold")
    let thresholdSlider = NSSlider(value: 0.5, minValue: 0.2, maxValue: 0.95, target: nil, action: nil)
    let thresholdValue = NSTextField(labelWithString: "0.50")
    var thresholdPending = false
    var cursorSamplePending = false
    var lastCursorSample = Date.distantPast
    var serverThreshold: Double?
    let diagnosticRate = NSTextField(labelWithString: "")
    let cameraDivider = CameraSidebarDivider()
    var cameraWidthConstraint: NSLayoutConstraint!
    let webcamRate = NSTextField(labelWithString: "")
    var accuracySummary: NSTextField { calibrationSteps.accuracySummary }
    var accuracyButton: NSButton { calibrationSteps.accuracyButton }
    let calibrationSteps = CalibrationStepsView()
    let dot = DotPanel(contentRect: NSRect(x: 0, y: 0, width: 16, height: 16),
                       styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
    var timer: Timer?
    var animationTimer: Timer?
    var motion = GazeMotion()
    var readoutMotion = MeasurementChannels()
    private var readoutContext = ""
    var calibrationOrbit = CalibrationOrbit()
    var calibrationTravel = CalibrationTravel()
    var calibrationFeedback = CalibrationFeedback()
    var cursorReferenceFeedback = CalibrationFeedback()
    var pending = false
    var changing = false
    var lastReply = Date.distantPast
    var active = false
    var displayFrame: NSRect?
    var lastState: TrackerState?
    var localError: String?
    var generation = 0
    var launched = false
    var statusItem: NSStatusItem?
    let blinkMenu = NSMenuItem(title: "Double-blink to click (experimental)", action: nil, keyEquivalent: "")
    var menuOpen = false
    var lastClickID = 0
    var clicksSuppressedUntil = Date.distantPast
    var diagnosticTimer: Timer?
    var diagnosticPending: Set<String> = []
    var displaysRegistered = false
    var registeringDisplays = false
    var trackerProcess: Process?
    var trackerLog: URL?
    var quitting = false
    let angleDebugger = AngleDebugger()
    // Capture once at launch: replacing the installed bundle must not relabel a
    // process that is still running the previous implementation.
    let buildVersion = "v" + (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "development")
    let versionLabel = NSTextField(labelWithString: "")
    let versionMenu = NSMenuItem(title: "", action: nil, keyEquivalent: "")

    init(port: Int, hybrid: Bool = false) { self.port = port; self.hybrid = hybrid; super.init() }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard !launched else { return }
        launched = true
        window.title = "EyeCursor calibration target"
        window.appearance = NSAppearance(named: .darkAqua)
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.contentView = surface
        surface.wantsLayer = true
        window.hasShadow = false
        window.isOpaque = false
        window.backgroundColor = .clear
        window.ignoresMouseEvents = true
        window.hidesOnDeactivate = false
        window.level = .screenSaver
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        diagnosticWindow.title = "EyeCursor · Eye camera diagnostics"
        diagnosticWindow.appearance = NSAppearance(named: .darkAqua)
        diagnosticWindow.isReleasedWhenClosed = false
        diagnosticWindow.delegate = self
        diagnosticWindow.center()
        updateEyeSelection(primary: "left")
        clearEyeRegion.isHidden = true
        clearEyeRegion.target = self
        clearEyeRegion.action = #selector(clearRegion)
        diagnosticText.textColor = NSColor.white.withAlphaComponent(0.75)
        diagnosticText.font = .systemFont(ofSize: 12)
        calibrationSteps.actionButton.target = self
        calibrationSteps.actionButton.action = #selector(continueCalibration)
        calibrationSteps.manualButton.target = self
        calibrationSteps.manualButton.action = #selector(alignWithCursor)
        accuracyButton.target = self; accuracyButton.action = #selector(checkAccuracy)
        previewAlignButton.target = self
        previewAlignButton.action = #selector(alignWithPreview)
        configureDiagnosticsLayout()
        dot.isOpaque = false
        dot.backgroundColor = .clear
        dot.hasShadow = false
        dot.ignoresMouseEvents = true
        dot.hidesOnDeactivate = false
        dot.level = .screenSaver
        dot.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        dot.contentView = DotView(frame: NSRect(x: 0, y: 0, width: 16, height: 16))
        cursorReference.isOpaque = false
        cursorReference.backgroundColor = .clear
        cursorReference.hasShadow = false
        cursorReference.ignoresMouseEvents = true
        cursorReference.hidesOnDeactivate = false
        cursorReference.level = .screenSaver
        cursorReference.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        cursorReference.contentView = cursorReferenceSurface
        let menu = NSMenu()
        let appItem = NSMenuItem()
        menu.addItem(appItem)
        appItem.submenu = NSMenu()
        let diagnosticShortcut = appItem.submenu?.addItem(withTitle: diagnosticMenu.title, action: #selector(showDiagnostics), keyEquivalent: "d")
        diagnosticShortcut?.target = self
        appItem.submenu?.autoenablesItems = false
        appItem.submenu?.addItem(.separator())
        appItem.submenu?.addItem(withTitle: "Quit EyeCursor", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        NSApp.mainMenu = menu
        let tray = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem = tray
        let symbol = Bundle.main.url(forResource: "EyeCursorMenuBar", withExtension: "svg")
            .flatMap { NSImage(contentsOf: $0) } ?? NSImage(systemSymbolName: "eye", accessibilityDescription: "EyeCursor")
        symbol?.size = NSSize(width: 18, height: 18)
        // Preserve the white eyeball and cursor instead of letting macOS invert them.
        symbol?.isTemplate = false
        tray.button?.image = symbol
        tray.button?.toolTip = "EyeCursor"
        tray.button?.setAccessibilityLabel("EyeCursor")
        let trayMenu = NSMenu()
        trayMenu.delegate = self
        trayMenu.autoenablesItems = false
        versionMenu.title = "EyeCursor \(buildVersion)"
        versionMenu.isEnabled = false
        trayMenu.addItem(versionMenu)
        statusMenu.isEnabled = false
        trayMenu.addItem(statusMenu)
        trayMenu.addItem(.separator())
        calibrateMenu.target = self
        calibrateMenu.action = #selector(restartOnboarding)
        diagnosticMenu.target = self
        diagnosticMenu.action = #selector(showDiagnostics)
        trayMenu.addItem(diagnosticMenu)
        trayMenu.addItem(calibrateMenu)
        cursorAlignMenu.target = self
        cursorAlignMenu.action = #selector(alignWithCursor)
        trayMenu.addItem(cursorAlignMenu)
        headPracticeMenu.target = self
        headPracticeMenu.action = #selector(practiceHeadMovement)
        trayMenu.addItem(headPracticeMenu)
        cancelMenu.target = self
        cancelMenu.action = #selector(cancelCalibration)
        cancelMenu.isHidden = true
        trayMenu.addItem(cancelMenu)
        blinkMenu.target = self
        blinkMenu.action = #selector(toggleBlinkClick)
        // Keep the experimental double-blink option out of the menu for now.
        trayMenu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit", action: #selector(quitEyeCursor), keyEquivalent: "q")
        quit.target = self
        trayMenu.addItem(quit)
        tray.menu = trayMenu
        updateMenu()
        NotificationCenter.default.addObserver(self, selector: #selector(screensChanged),
                                               name: NSApplication.didChangeScreenParametersNotification, object: nil)
        let polling = Timer(timeInterval: 0.05, repeats: true) { [weak self] _ in self?.refresh() }
        timer = polling
        RunLoop.main.add(polling, forMode: .common)
        let animation = Timer(timeInterval: 1.0 / 60, repeats: true) { [weak self] _ in
            self?.animateCursor()
            self?.animateCalibration()
            self?.animateMeasurements()
            self?.animateCursorReference()
        }
        animationTimer = animation
        RunLoop.main.add(animation, forMode: .common)
        let diagnosticPolling = Timer(timeInterval: 1.0 / 30, repeats: true) { [weak self] _ in
            self?.refreshDiagnosticFrame()
        }
        diagnosticTimer = diagnosticPolling
        RunLoop.main.add(diagnosticPolling, forMode: .common)
    }

    func registerDisplays() {
        guard !registeringDisplays, let primary = NSScreen.screens.first else { return }
        registeringDisplays = true
        let laptop = NSScreen.screens.first { screen in
            guard let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else { return false }
            return CGDisplayIsBuiltin(id.uint32Value) != 0
        }
        guard !hybrid || laptop != nil else {
            registeringDisplays = false
            localError = "Open the laptop display to use its webcam calibration."
            return
        }
        let chosen = hybrid ? laptop! : primary
        // Keep the calibration anchor first, then use System Settings geometry.
        let screens = [chosen] + NSScreen.screens.filter { $0 !== chosen }
        let displays: [[String: Any]] = screens.compactMap { screen in
            guard let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else { return nil }
            return ["id": id.stringValue, "viewport": [screen.frame.minX,
                primary.frame.maxY - screen.frame.maxY, screen.frame.width, screen.frame.height]]
        }
        func topology() -> [String] {
            NSScreen.screens.map { "\($0.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] ?? ""):\($0.frame)" }
        }
        let submittedTopology = topology()
        request("/onboarding/displays", body: ["displays": displays]) { [weak self] error in
            self?.registeringDisplays = false
            self?.displaysRegistered = error == nil && submittedTopology == topology()
            self?.localError = error
        }
    }

    func updateMenu() {
        let fresh = Date().timeIntervalSince(lastReply) <= 0.6
        let ready = fresh && lastState?.camera_connected == true && lastState?.source != "video demo"
        let cursorSession = lastState?.onboarding?.cursor_calibration
        let aligningPreview = cursorSession?.active == true && cursorSession?.fixed_target != nil && cursorSession?.stage != "geometry"
        previewAlignButton.title = pendingPreviewAlignment == .start ? "Align with IR preview · queued" :
            pendingPreviewAlignment == .finish ? "Finish preview alignment · queued" :
            aligningPreview ? (cursorSession?.ready == true ? "Finish preview alignment" : "Stop preview alignment") : "Align with IR preview"
        // A momentary tracking gap should never make a button jump between
        // enabled and disabled. The action waits for a usable state below.
        previewAlignButton.isEnabled = true
        calibrateMenu.isEnabled = ready && !changing
        cursorAlignMenu.isEnabled = fresh && !changing && hybrid && lastState?.onboarding?.phase != "no_displays"
        let practicing = lastState?.onboarding?.cursor_calibration?.active == true && lastState?.onboarding?.cursor_calibration?.stage == "geometry"
        headPracticeMenu.title = practicing ? "Stop head calibration" : "Calibrate head movement"
        headPracticeMenu.isEnabled = fresh && !changing && !active && hybrid && lastState?.calibrated == true &&
            (lastState?.onboarding?.cursor_calibration?.active != true || practicing)
        cursorAlignMenu.title = practicing ? "Stop head calibration" : lastState?.onboarding?.cursor_calibration?.active == true ? "Finish cursor alignment" : "Align with cursor"
        calibrationSteps.actionButton.isEnabled = fresh && !changing && lastState?.onboarding != nil &&
            lastState?.onboarding?.phase != "no_displays"
        calibrationSteps.manualButton.isEnabled = cursorAlignMenu.isEnabled
        accuracyButton.isEnabled = fresh && !changing && cursorSession?.active != true &&
            ["complete", "verify"].contains(lastState?.onboarding?.phase ?? "")
        accuracyButton.title = lastState?.onboarding?.phase == "verify" ? "Stop accuracy check" : "Check accuracy"
        let report = lastState?.onboarding?.accuracy_check
        if let report = report {
            let result = report.mean_error_points.map { String(format: "Mean %.0f pt · Worst %.0f pt", $0, report.worst_error_points ?? $0) } ?? "No measurements yet"
            accuracySummary.stringValue = "\(report.status.capitalized) · \(report.rows.filter { $0.samples > 0 }.count)/\(report.target_count) measured\n\(result)\nOn laptop: filled = measured, ring = pending, cross = missing. Orange = estimate.\nErrors in screen points."
        } else { accuracySummary.stringValue = "Accuracy not checked for this mapping.\nCheck again after alignment." }

        calibrateMenu.toolTip = nil
        clearEyeRegion.isHidden = active || changing || lastState?.eye_region == nil
        clearEyeRegion.isEnabled = !changing
        diagnosticMenu.isEnabled = true
        cancelMenu.isHidden = !active && lastState?.onboarding?.phase != "waiting"
        cancelMenu.isEnabled = !changing
        blinkMenu.isEnabled = fresh && !active && !changing
        if let error = localError {
            statusMenu.title = error
            statusMenu.toolTip = nil
        } else {
            statusMenu.toolTip = nil
            if !fresh { statusMenu.title = "Waiting for tracker" }
            else if lastState?.source == "video demo" { statusMenu.title = "Sample video · Calibration unavailable" }
            else if !ready { statusMenu.title = "Waiting for eye camera" }
            else if active {
                let progress = calibrationFeedback.progress
                statusMenu.title = lastState?.onboarding?.screen_path == "quick"
                    ? "Initial calibration · Target \(lastState?.onboarding?.screen_target_index ?? 2)/5"
                    : "Calibrating · \(Int(progress * 100))%"
                statusMenu.toolTip = nil
            }
            else if let flow = lastState?.onboarding, flow.phase != "complete" {
                statusMenu.title = lastState?.cursor_message ?? flow.message
            }
            else if lastState?.calibration?.phase == "retry" {
                statusMenu.title = "Calibration needs retry"
                statusMenu.toolTip = nil
            }
            else if lastState?.calibrated == true { statusMenu.title = "Calibration complete" }
            else { statusMenu.title = lastState?.cursor_message ?? "Eye camera connected" }
            if statusMenu.title.hasPrefix("Calibration incomplete") {
                statusMenu.title = "Calibration incomplete"
            }
        }
        fitMenuStatusToActions()
    }

    func fitMenuStatusToActions() {
        // Let AppKit hug the action labels. Transient tracker messages must not
        // expand the dropdown; their full text remains available on hover.
        let attributes: [NSAttributedString.Key: Any] = [
            .font: statusItem?.menu?.font ?? NSFont.menuFont(ofSize: 0)
        ]
        func width(_ text: String) -> CGFloat {
            (text as NSString).size(withAttributes: attributes).width
        }
        let actions = [diagnosticMenu, calibrateMenu, cursorAlignMenu, headPracticeMenu, cancelMenu]
        let availableWidth = actions.filter { !$0.isHidden }.map { width($0.title) }.max() ?? 0
        let fullStatus = statusMenu.title
        guard width(fullStatus) > availableWidth else { return }
        var shortened = fullStatus
        while !shortened.isEmpty && width(shortened + "…") > availableWidth {
            shortened.removeLast()
        }
        statusMenu.title = shortened.trimmingCharacters(in: .whitespacesAndNewlines) + "…"
        statusMenu.toolTip = fullStatus
    }

    func request(_ path: String, body: [String: Any], completion: @escaping (String?) -> Void) {
        generation += 1
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)\(path)")!, timeoutInterval: 2)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: request) { data, response, error in
            var message = error?.localizedDescription
            if (response as? HTTPURLResponse)?.statusCode != 200 {
                let payload = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                message = payload?["error"] as? String ?? message ?? "Could not reach the tracker. Try again."
            }
            DispatchQueue.main.async { completion(message) }
        }.resume()
    }

    @objc func restartOnboarding() {
        guard !changing else { return }
        changing = true
        localError = nil
        hideCursor()
        request("/onboarding/start", body: [:]) { [weak self] error in
            self?.changing = false
            self?.localError = error
            self?.restore()
        }
    }

    @objc func checkAccuracy() {
        guard !changing else { return }
        changing = true
        let path = lastState?.onboarding?.phase == "verify" ? "/onboarding/stop" : "/onboarding/accuracy-start"
        request(path, body: [:]) { [weak self] error in
            self?.changing = false; self?.localError = error
        }
    }

    @objc func continueCalibration() {
        guard !changing, Date().timeIntervalSince(lastReply) <= 0.6,
              let flow = lastState?.onboarding else { return }
        if flow.cursor_calibration?.active == true || flow.phase == "complete" {
            alignWithCursor(); return
        }
        if ["waiting", "fitting", "head", "screen", "verify"].contains(flow.phase) {
            changing = true; localError = nil
            request("/onboarding/stop", body: [:]) { [weak self] error in
                guard let self = self else { return }
                self.changing = false; self.localError = error
                if error == nil { self.restore() }
            }
            updateMenu()
            return
        }
        if !hybrid || ["cancelled", "complete"].contains(flow.phase) {
            restartOnboarding()
            return
        }
        changing = true
        localError = nil
        hideCursor()
        updateMenu()
        request("/onboarding/retry", body: [:]) { [weak self] error in
            guard let self = self else { return }
            self.changing = false
            self.localError = error
            self.restore()
        }
    }

    @objc func alignWithCursor() {
        guard !changing, hybrid, Date().timeIntervalSince(lastReply) <= 0.6 else { return }
        changing = true; localError = nil
        let finish = lastState?.onboarding?.cursor_calibration?.active == true
        request(finish ? "/onboarding/cursor-finish" : "/onboarding/cursor-start", body: [:]) { [weak self] error in
            self?.changing = false; self?.localError = error
            if error == nil { self?.restore() }
        }
        updateMenu()
    }

    @objc func practiceHeadMovement() {
        guard headPracticeMenu.isEnabled else { return }
        if lastState?.onboarding?.cursor_calibration?.active == true { alignWithCursor(); return }
        changing = true; localError = nil
        request("/onboarding/head-refine", body: [:]) { [weak self] error in
            self?.changing = false; self?.localError = error
        }
        updateMenu()
    }

    @objc func alignWithPreview() {
        guard hybrid else { return }
        // A second click cancels an unfulfilled request instead of queuing a
        // start followed immediately by a stop when tracking returns.
        if pendingPreviewAlignment != nil {
            pendingPreviewAlignment = nil
            updateMenu()
            return
        }
        let session = lastState?.onboarding?.cursor_calibration
        pendingPreviewAlignment = session?.active == true && session?.fixed_target != nil && session?.stage != "geometry"
            ? .finish : .start
        processPendingPreviewAlignment()
        updateMenu()
    }

    func processPendingPreviewAlignment() {
        guard let action = pendingPreviewAlignment, !changing, !active, hybrid,
              Date().timeIntervalSince(lastReply) <= 0.6 else { return }
        let session = lastState?.onboarding?.cursor_calibration
        if action == .finish {
            // Never finish a different cursor or head calibration session.
            guard session?.active == true, session?.fixed_target != nil, session?.stage != "geometry" else {
                pendingPreviewAlignment = nil
                updateMenu()
                return
            }
            pendingPreviewAlignment = nil
            changing = true; localError = nil
            request("/onboarding/cursor-finish", body: [:]) { [weak self] error in
                self?.changing = false; self?.localError = error
            }
            updateMenu()
            return
        }
        let preview = calibrationPreview
        guard lastState?.calibrated == true, lastState?.valid == true,
              session?.active != true, let pupil = lastState?.pupil_center, pupil.count == 2,
              pupil.allSatisfy({ $0.isFinite }), let screen = calibrationScreen(),
              let window = preview.window else { return }
        // Freeze this screen location once. Following the live pupil would
        // turn a known fixation into a moving, self-referential target.
        let local = NSPoint(x: preview.bounds.minX + pupil[0] / 640 * preview.bounds.width,
                            y: preview.bounds.maxY - pupil[1] / 480 * preview.bounds.height)
        let point = window.convertPoint(toScreen: preview.convert(local, to: nil))
        guard screen.frame.contains(point) else { return }
        let uv = [(point.x-screen.frame.minX)/screen.frame.width, (screen.frame.maxY-point.y)/screen.frame.height]
        pendingPreviewAlignment = nil
        changing = true; localError = nil
        request("/onboarding/preview-start", body: ["target":uv]) { [weak self] error in
            self?.changing = false; self?.localError = error
        }
        updateMenu()
    }

    func alignmentTarget(_ session: CursorCalibrationState, screen: NSScreen, mouse: NSPoint) -> NSPoint {
        if let fixed = session.fixed_target, fixed.count == 2, fixed.allSatisfy({ $0.isFinite && (0...1).contains($0) }) {
            return NSPoint(x: screen.frame.minX + fixed[0] * screen.frame.width,
                           y: screen.frame.maxY - fixed[1] * screen.frame.height)
        }
        return session.stage == "geometry" ? NSPoint(x: screen.frame.midX, y: screen.frame.midY) : mouse
    }

    func sampleSystemCursor(_ state: TrackerState) {
        guard state.onboarding?.cursor_calibration?.active == true, !changing, !cursorSamplePending,
              Date().timeIntervalSince(lastCursorSample) >= 0.1,
              let screen = calibrationScreen() else { return }
        let mouse = alignmentTarget(state.onboarding!.cursor_calibration!, screen: screen, mouse: NSEvent.mouseLocation)
        let uv = [(mouse.x-screen.frame.minX)/screen.frame.width, (screen.frame.maxY-mouse.y)/screen.frame.height]
        cursorSamplePending = true; lastCursorSample = Date()
        // Sampling must not invalidate ordinary state responses via generation.
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/onboarding/cursor-sample")!, timeoutInterval: 0.5)
        request.httpMethod = "POST"; request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["target":uv])
        URLSession.shared.dataTask(with: request) { [weak self] _,_,_ in
            DispatchQueue.main.async { self?.cursorSamplePending = false }
        }.resume()
    }

    func renderOnboarding(_ flow: OnboardingState) {
        let showing = ["fitting", "head", "screen", "verify"].contains(flow.phase)
        guard showing, let screen = NSScreen.screens.first(where: {
            ($0.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.stringValue == flow.display_id
        }) else {
            if active { restore() }
            return
        }
        active = true
        displayFrame = screen.frame
        hideCursor()
        let key = flow.screen_path == "quick"
            ? "\(flow.calibration_session_id ?? "")|\(flow.display_id ?? "")|quick|\(flow.screen_path_started_at ?? 0)|\(flow.screen_target_index ?? 0)"
            : "\(flow.calibration_session_id ?? "")|\(flow.display_id ?? "")|\(flow.phase)|\(flow.target ?? [])"
        // Keep earned visual progress during rejection; only a new target or
        // calibration session starts a fresh ring. Sampling still validates each fixation.
        calibrationFeedback.update(key: key, progress: flow.progress,
                                   accepted: flow.sample_accepted ?? (lastState?.valid ?? false))
        surface.headCue = flow.phase == "head" ? flow.head_cue : nil
        surface.progress = calibrationFeedback.progress
        surface.accepted = calibrationFeedback.accepted
        if flow.screen_path == "quick" {
            calibrationTravel.reset(); calibrationOrbit.reset()
            animateCalibration()
        } else if flow.phase == "fitting" {
            calibrationTravel.reset()
            calibrationOrbit.synchronize(elapsed: flow.elapsed, at: ProcessInfo.processInfo.systemUptime)
            animateCalibration()
        } else {
            calibrationOrbit.reset()
            if let target = flow.target, target.count == 2 {
                if let display = displayFrame,
                   let destination = calibrationTargetOrigin(CGPoint(x: target[0], y: target[1]),
                       display: display, size: window.frame.size) {
                    calibrationTravel.move(from: window.isVisible ? window.frame.origin : destination,
                                           to: destination, at: ProcessInfo.processInfo.systemUptime)
                    animateCalibration()
                }
            } else {
                window.orderOut(nil)
            }
        }
    }

    func placeCalibrationTarget(_ point: CGPoint) {
        guard let display = displayFrame,
              let origin = calibrationTargetOrigin(point, display: display, size: window.frame.size) else {
            window.orderOut(nil)
            return
        }
        window.setFrameOrigin(origin)
        if !window.isVisible { window.orderFrontRegardless() }
    }

    func restore() {
        active = false
        calibrationOrbit.reset()
        calibrationTravel.reset()
        surface.headCue = nil
        surface.progress = 0
        calibrationFeedback.reset()
        surface.accepted = false
        window.orderOut(nil)
        updateMenu()
    }

    @objc func cancelCalibration() {
        guard !changing else { return }
        changing = true
        request("/onboarding/cancel", body: [:]) { [weak self] error in
            guard let self = self else { return }
            self.changing = false
            self.localError = error
            self.restore()
        }
    }
    @objc func changeThreshold() {
        let value = (thresholdSlider.doubleValue * 100).rounded() / 100
        thresholdValue.stringValue = String(format: "%.2f", value)
        thresholdPending = true
        thresholdSlider.isEnabled = false
        request("/detection-threshold", body: ["threshold": value]) { [weak self] error in
            guard let self = self else { return }
            self.thresholdPending = false
            self.thresholdSlider.isEnabled = true
            self.serverThreshold = nil
            self.localError = error
        }
    }

    static func irCalibrationStatus(_ state: TrackerState) -> String {
        if state.calibrated { return "Calibration complete" }
        if !state.camera_connected { return "Waiting for eye camera" }
        switch state.onboarding?.phase {
        case "paused": return "Calibration incomplete"
        case "cancelled": return "Calibration cancelled"
        case "fitting", "head", "screen", "verify", "cursor": return "Calibrating"
        default: return "Waiting for calibration"
        }
    }

    func resizeCameraSidebar(to width: CGFloat) {
        guard let root = diagnosticWindow.contentView else { return }
        let controlsWidth: CGFloat = angleDebugger.sidebarCollapsed ? 0 : 330
        let maximum = max(220, root.bounds.width - controlsWidth - 320 - 8)
        cameraWidthConstraint.constant = min(maximum, max(220, width))
        root.layoutSubtreeIfNeeded()
    }

    func configureDiagnosticsLayout() {
        diagnosticWindow.minSize = NSSize(width: 1100, height: 690)
        diagnosticWindow.collectionBehavior = [.fullScreenPrimary]
        let root = diagnosticWindow.contentView!
        versionLabel.stringValue = buildVersion
        versionLabel.font = .monospacedDigitSystemFont(ofSize: 11, weight: .regular)
        versionLabel.textColor = .white
        versionLabel.alignment = .right
        versionLabel.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(versionLabel)
        let cameras = NSScrollView()
        cameras.contentView = DiagnosticsClipView()
        cameras.hasVerticalScroller = true
        cameras.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(cameras)
        let stack = NSStackView()
        cameraStack = stack
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 4
        stack.detachesHiddenViews = false
        stack.edgeInsets = NSEdgeInsets(top: 16, left: 12, bottom: 16, right: 12)
        stack.translatesAutoresizingMaskIntoConstraints = false
        cameras.documentView = stack
        let angles = angleDebugger.contentView
        angles.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(angles)
        cameraDivider.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(cameraDivider)
        cameraDivider.resize = { [weak self] width in self?.resizeCameraSidebar(to: width) }
        cameraWidthConstraint = cameras.widthAnchor.constraint(equalToConstant: 264)
        cameraWidthConstraint.priority = .defaultHigh
        NSLayoutConstraint.activate([
            cameras.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            cameras.topAnchor.constraint(equalTo: root.topAnchor),
            cameras.bottomAnchor.constraint(equalTo: versionLabel.topAnchor, constant: -6),
            versionLabel.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -12),
            versionLabel.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -6),
            versionLabel.heightAnchor.constraint(equalToConstant: 16),
            cameraWidthConstraint,
            cameras.widthAnchor.constraint(greaterThanOrEqualToConstant: 220),
            cameraDivider.leadingAnchor.constraint(equalTo: cameras.trailingAnchor),
            cameraDivider.topAnchor.constraint(equalTo: cameras.topAnchor),
            cameraDivider.bottomAnchor.constraint(equalTo: cameras.bottomAnchor),
            cameraDivider.widthAnchor.constraint(equalToConstant: 8),
            stack.leadingAnchor.constraint(equalTo: cameras.contentView.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: cameras.contentView.trailingAnchor),
            stack.topAnchor.constraint(equalTo: cameras.contentView.topAnchor),
            angles.leadingAnchor.constraint(equalTo: cameraDivider.trailingAnchor),
            angles.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            angles.topAnchor.constraint(equalTo: root.topAnchor),
            angles.bottomAnchor.constraint(equalTo: cameras.bottomAnchor)
        ])
        func add(_ view: NSView, height: CGFloat? = nil) {
            view.translatesAutoresizingMaskIntoConstraints = false
            stack.addArrangedSubview(view)
            view.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -24).isActive = true
            if let height = height { view.heightAnchor.constraint(equalToConstant: height).isActive = true }
        }
        func title(_ text: String) {
            let label = NSTextField(labelWithString: text)
            label.font = .systemFont(ofSize: 13, weight: .semibold)
            add(label)
        }
        if hybrid { angleDebugger.installCalibrationSteps(calibrationSteps) }
        trackingEyeTitle.font = .systemFont(ofSize: 13, weight: .semibold)
        add(trackingEyeTitle)
        add(preview)
        preview.heightAnchor.constraint(equalTo: preview.widthAnchor, multiplier: 0.75).isActive = true
        diagnosticRate.font = .monospacedDigitSystemFont(ofSize: 11, weight: .regular)
        diagnosticRate.textColor = .secondaryLabelColor
        diagnosticRate.lineBreakMode = .byTruncatingTail
        diagnosticRate.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        add(diagnosticRate, height: 18)
        secondaryEyeTitle.font = .systemFont(ofSize: 13, weight: .semibold)
        add(secondaryEyeTitle)
        add(secondaryEyePreview)
        secondaryEyePreview.heightAnchor.constraint(equalTo: secondaryEyePreview.widthAnchor, multiplier: 0.75).isActive = true
        secondaryEyeStatus.font = .monospacedDigitSystemFont(ofSize: 11, weight: .regular)
        secondaryEyeStatus.textColor = .secondaryLabelColor
        secondaryEyeStatus.lineBreakMode = .byTruncatingTail
        secondaryEyeStatus.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        add(secondaryEyeStatus, height: 20)
        if hybrid {
            title("Webcam · face close-up")
            add(facePreview)
            facePreview.heightAnchor.constraint(equalTo: facePreview.widthAnchor, multiplier: 0.75).isActive = true
            webcamRate.font = .monospacedDigitSystemFont(ofSize: 11, weight: .regular)
            webcamRate.textColor = .secondaryLabelColor
            add(webcamRate, height: 18)
        }
        eyeSetupToggle.bezelStyle = .rounded
        eyeSetupToggle.target = self; eyeSetupToggle.action = #selector(toggleEyeSetup)
        add(eyeSetupToggle, height: 28)
        eyeSetupStack.orientation = .vertical; eyeSetupStack.alignment = .leading; eyeSetupStack.spacing = 6
        add(eyeSetupStack)
        func addSetup(_ view: NSView, height: CGFloat) {
            view.translatesAutoresizingMaskIntoConstraints = false
            eyeSetupStack.addArrangedSubview(view)
            view.widthAnchor.constraint(equalTo: eyeSetupStack.widthAnchor).isActive = true
            view.heightAnchor.constraint(equalToConstant: height).isActive = true
        }
        for (label, choice, rotation) in [("Left camera", leftCameraChoice, leftRotation),
                                           ("Right camera", rightCameraChoice, rightRotation)] {
            let heading = NSTextField(labelWithString: label)
            heading.font = .systemFont(ofSize: 12, weight: .semibold)
            addSetup(heading, height: 18)
            choice.addItem(withTitle: "Not assigned")
            choice.target = self; choice.action = #selector(changeEyeSetup)
            choice.menu?.delegate = self
            choice.cell?.lineBreakMode = .byTruncatingMiddle
            choice.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
            addSetup(choice, height: 26)
            rotation.target = self; rotation.action = #selector(changeEyeSetup)
            addSetup(rotation, height: 22)
        }
        leftRotation.state = .on
        eyeSetupStatus.font = .systemFont(ofSize: 11)
        eyeSetupStatus.textColor = .secondaryLabelColor
        addSetup(eyeSetupStatus, height: 64)
        calibrationEyeStatus.font = .systemFont(ofSize: 11)
        calibrationEyeStatus.textColor = .secondaryLabelColor
        add(calibrationEyeStatus, height: 44)
        // Reserve status space so live text never shifts the webcam below it.
        title("Tracking controls")
        add(diagnosticText, height: 20)
        if hybrid { previewAlignButton.bezelStyle = .rounded; add(previewAlignButton, height: 28) }
        thresholdLabel.textColor = .secondaryLabelColor
        add(thresholdLabel)
        let thresholdSpace = NSView()
        let thresholdRow = NSStackView(views: [thresholdSlider, thresholdValue, thresholdSpace])
        thresholdRow.orientation = .horizontal; thresholdRow.spacing = 8
        thresholdRow.setCustomSpacing(0, after: thresholdValue)
        thresholdSpace.widthAnchor.constraint(equalTo: thresholdSlider.widthAnchor).isActive = true
        thresholdSlider.target = self
        thresholdSlider.action = #selector(changeThreshold)
        thresholdSlider.isContinuous = false
        thresholdValue.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
        thresholdValue.textColor = .secondaryLabelColor
        thresholdValue.setContentHuggingPriority(.required, for: .horizontal)
        add(thresholdRow)
        add(clearEyeRegion, height: 28)
        if hybrid {
            title("Webcam status")
            faceText.font = .systemFont(ofSize: 12)
            faceText.textColor = .secondaryLabelColor
            add(faceText, height: 84)
        }
        if let screen = calibrationScreen() {
            diagnosticWindow.setFrame(screen.visibleFrame, display: true)
        }
    }
    func calibrationScreen() -> NSScreen? {
        NSScreen.screens.first { screen in
            guard let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else { return false }
            if let selected = lastState?.onboarding?.display_id { return id.stringValue == selected }
            return CGDisplayIsBuiltin(id.uint32Value) != 0
        } ?? NSScreen.main
    }
    @objc func showDiagnostics() {
        let screen = calibrationScreen()
        if !diagnosticWindow.isVisible, let screen = screen {
            diagnosticWindow.setFrame(screen.visibleFrame, display: true)
        }
        diagnosticWindow.makeKeyAndOrderFront(nil)
        angleDebugger.activate(on: screen)
        surface.monochrome = true
        if let state = lastState { angleDebugger.update(state) }
        NSApp.activate(ignoringOtherApps: true)
        refreshDiagnosticFrame()
    }
    @objc func showAngleDebugger() { showDiagnostics() }
    @objc func clearRegion() {
        request("/eye-region", body: ["region": NSNull()]) { [weak self] error in
            self?.diagnosticText.stringValue = error ?? "Eye area cleared. Calibration was reset."
        }
    }
    @objc func toggleEyeSetup() {
        eyeSetupExpanded.toggle()
        eyeSetupStack.isHidden = !eyeSetupExpanded
        cameraStack?.setVisibilityPriority(eyeSetupExpanded ? .mustHold : .notVisible, for: eyeSetupStack)
        eyeSetupToggle.title = eyeSetupExpanded ? "Camera setup ▾" : "Camera setup ▸"
    }
    var calibrationPreview: CameraPreviewView {
        lastState?.eye_cameras?.active_eye == "right" ? secondaryEyePreview : preview
    }
    func updateEyeSelection(primary: String) {
        preview.selection = nil; secondaryEyePreview.selection = nil
        let selected = primary == "right" ? secondaryEyePreview : preview
        selected.selection = { [weak self] region in
            self?.request("/eye-region", body: ["region": region]) { error in
                self?.diagnosticText.stringValue = error ?? "Eye area set. Calibration was reset."
            }
        }
    }
    static func eyeRate(_ slot: EyeCameraSlot?) -> String {
        guard let slot = slot else { return "Not assigned" }
        guard slot.connected else { return slot.status }
        let confidence = slot.confidence.map { String(format: " · %.2f", $0) } ?? ""
        return String(format: "%.0f FPS · ", slot.tracking_fps ?? slot.fps) + (slot.tracking ?? "Detecting") + confidence
    }
    func renderEyeSetup(_ rig: EyeCamerasState?) {
        // AppKit runs the polling timer inside menu tracking. Never mutate a
        // popup or its items until that interaction has finished.
        if eyeCameraMenuOpen { deferredEyeSetup = rig; return }
        let controls: [NSControl] = [leftCameraChoice, rightCameraChoice, leftRotation, rightRotation]
        controls.forEach { $0.isEnabled = rig != nil && !eyeSetupPending }
        guard let rig = rig else {
            trackingEyeTitle.stringValue = "Eye camera · Tracking"
            secondaryEyeStatus.stringValue = "Two-eye setup needs native USB mode"
            return
        }
        trackingEyeTitle.stringValue = "Left eye · \(rig.eyes["left"]?.rotation ?? 0)°"
        secondaryEyeTitle.stringValue = "Right eye · \(rig.eyes["right"]?.rotation ?? 0)°"
        diagnosticRate.stringValue = Self.eyeRate(rig.eyes["left"])
        secondaryEyeStatus.stringValue = Self.eyeRate(rig.eyes["right"])
        diagnosticRate.toolTip = rig.eyes["left"]?.error ?? diagnosticRate.stringValue
        secondaryEyeStatus.toolTip = rig.eyes["right"]?.error ?? secondaryEyeStatus.stringValue
        if rig.eyes["left"]?.connected != true { preview.image = nil }
        if rig.eyes["right"]?.connected != true { secondaryEyePreview.image = nil }
        calibrationEyeStatus.stringValue = "Both pupils are tracked. Screen calibration and the 3D view use the \(rig.active_eye) eye."
        updateEyeSelection(primary: rig.active_eye)
        guard !eyeSetupPending else { return }
        let devices = rig.devices.sorted { $0.id < $1.id }
        let signature = devices.map { $0.id + $0.name }.joined(separator: "|") +
            ["left", "right"].map { rig.eyes[$0]?.device_id ?? "" }.joined(separator: "|")
        if signature != eyeSetupSignature {
            eyeSetupSignature = signature
            for (eye, choice) in [("left", leftCameraChoice), ("right", rightCameraChoice)] {
                choice.removeAllItems()
                choice.addItem(withTitle: "Not assigned")
                var options = devices
                if let selected = rig.eyes[eye]?.device_id, !options.contains(where: { $0.id == selected }) {
                    options.append(EyeCameraDevice(id: selected, name: "Disconnected camera"))
                }
                for (index, device) in options.enumerated() {
                    let name = device.name.count > 22 ? String(device.name.prefix(21)) + "…" : device.name
                    // Identical USB cameras often share the same ID suffix.
                    // NSPopUpButton replaces duplicate titles, so number every
                    // option and insert actual menu items with unique IDs.
                    let item = NSMenuItem(title: "\(index + 1) · \(name)", action: nil, keyEquivalent: "")
                    item.representedObject = device.id
                    item.toolTip = "\(device.name) [\(device.id)]"
                    choice.menu?.addItem(item)
                }
                let index = choice.itemArray.firstIndex { ($0.representedObject as? String) == rig.eyes[eye]?.device_id } ?? 0
                choice.selectItem(at: index)
                choice.toolTip = choice.selectedItem?.toolTip
            }
        }
        leftRotation.state = rig.eyes["left"]?.rotation == 180 ? .on : .off
        rightRotation.state = rig.eyes["right"]?.rotation == 180 ? .on : .off
        if let error = rig.error { eyeSetupStatus.stringValue = error }
    }
    @objc func changeEyeSetup() {
        guard !eyeSetupPending else { return }
        eyeSetupPending = true
        hideCursor()
        preview.image = nil; secondaryEyePreview.image = nil
        let body: [String: Any] = [
            "active_eye": lastState?.eye_cameras?.active_eye ?? "left",
            "left": ["device_id": leftCameraChoice.selectedItem?.representedObject ?? NSNull(),
                     "rotation": leftRotation.state == .on ? 180 : 0],
            "right": ["device_id": rightCameraChoice.selectedItem?.representedObject ?? NSNull(),
                      "rotation": rightRotation.state == .on ? 180 : 0]
        ]
        request("/eye-cameras", body: body) { [weak self] error in
            guard let self = self else { return }
            self.eyeSetupPending = false
            self.eyeSetupSignature = ""
            self.eyeSetupStatus.stringValue = error ?? "Camera setup saved. Both eyes are tracked independently."
        }
    }
    func refreshDiagnosticFrame() {
        guard diagnosticWindow.isVisible else { return }
        if let rig = lastState?.eye_cameras {
            for (eye, view) in [("left", preview), ("right", secondaryEyePreview)] {
                if rig.eyes[eye]?.connected == true { fetchPreview("\(eye).jpg", into: view) }
                else { view.image = nil }
            }
        } else { fetchPreview("frame.jpg", into: preview) }
        if hybrid { fetchPreview("head.jpg", into: facePreview) }
    }
    func fetchPreview(_ path: String, into view: CameraPreviewView) {
        guard !diagnosticPending.contains(path) else { return }
        diagnosticPending.insert(path)
        let frameGeneration = generation
        let request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/diagnostics/\(path)")!,
                                 cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 0.8)
        URLSession.shared.dataTask(with: request) { [weak self, weak view] data, response, error in
            let image = error == nil && (response as? HTTPURLResponse)?.statusCode == 200
                ? data.flatMap(NSImage.init(data:)) : nil
            DispatchQueue.main.async {
                self?.diagnosticPending.remove(path)
                if self?.generation == frameGeneration { view?.image = image }
            }
        }.resume()
    }
    @objc func toggleBlinkClick() {
        let enabled = !(lastState?.blink_click_enabled ?? false)
        if enabled && !AXIsProcessTrusted() {
            let alert = NSAlert()
            alert.messageText = "Allow EyeCursor to click"
            alert.informativeText = "The application to allow is EyeCursor. In Privacy & Security → Accessibility, enable EyeCursor. If it is missing, click +, press ⇧⌘G, and paste this exact path:\n\n\(Bundle.main.bundleURL.path)\n\nThen return here and turn on Double-blink to click."
            alert.addButton(withTitle: "Open Accessibility Settings")
            alert.addButton(withTitle: "Show EyeCursor in Finder")
            alert.addButton(withTitle: "Cancel")
            let choice = alert.runModal()
            if choice == .alertFirstButtonReturn {
                // Ask macOS to list this process for consent; permission remains
                // entirely under the user's control in System Settings.
                let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
                _ = AXIsProcessTrustedWithOptions(options)
                if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
                    NSWorkspace.shared.open(url)
                }
            } else if choice == .alertSecondButtonReturn {
                NSWorkspace.shared.activateFileViewerSelecting([Bundle.main.bundleURL])
            }
            return
        }
        request("/blink-click", body: ["enabled": enabled]) { [weak self] error in self?.localError = error }
    }
    @objc func quitEyeCursor() { NSApp.terminate(nil) }
    func menuWillOpen(_ menu: NSMenu) {
        if menu === leftCameraChoice.menu || menu === rightCameraChoice.menu {
            eyeCameraMenuOpen = true
            clicksSuppressedUntil = Date().addingTimeInterval(1)
            return
        }
        menuOpen = true; updateMenu()
    }
    func menuDidClose(_ menu: NSMenu) {
        if menu === leftCameraChoice.menu || menu === rightCameraChoice.menu {
            eyeCameraMenuOpen = false
            // The selected item's action is dispatched after menuDidClose.
            DispatchQueue.main.async { [weak self] in
                guard let self = self else { return }
                if let rig = self.deferredEyeSetup, !self.eyeSetupPending { self.renderEyeSetup(rig) }
                self.deferredEyeSetup = nil
            }
            return
        }
        menuOpen = false
        clicksSuppressedUntil = Date().addingTimeInterval(1)
    }
    @objc func screensChanged() {
        hideCursor()
        restore()
        angleDebugger.refreshDisplays()
        displaysRegistered = false
        registerDisplays()
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if sender === diagnosticWindow {
            angleDebugger.sceneView.isPlaying = false
            surface.monochrome = false
            diagnosticWindow.orderOut(nil)
            return false
        }
        if active { cancelCalibration() }
        window.orderOut(nil)
        return false
    }
    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        if let process = trackerProcess, process.isRunning { process.terminate() }
        hideCursor()
        if let item = statusItem { NSStatusBar.system.removeStatusItem(item) }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showDiagnostics()
        return true
    }

    func startTracker() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] allowed in
                DispatchQueue.main.async {
                    guard let self = self, !self.quitting else { return }
                    if allowed { self.launchTracker() }
                    else { self.reportLaunchFailure("Allow EyeCursor in System Settings → Privacy & Security → Camera, then reopen it.") }
                }
            }
        case .authorized:
            launchTracker()
        default:
            reportLaunchFailure("Allow EyeCursor in System Settings → Privacy & Security → Camera, then reopen it.")
        }
    }

    static func trackerRoot(bundleURL: URL, configuredPath: String?) -> URL {
        if let path = configuredPath, (path as NSString).isAbsolutePath {
            return URL(fileURLWithPath: path, isDirectory: true)
        }
        return bundleURL.deletingLastPathComponent().deletingLastPathComponent()
    }

    func launchTracker() {
        let root = Self.trackerRoot(bundleURL: Bundle.main.bundleURL,
                                    configuredPath: Bundle.main.object(forInfoDictionaryKey: "EyeCursorProjectRoot") as? String)
        let python = root.appendingPathComponent(".venv/bin/python")
        let script = root.appendingPathComponent("3DTracker/monitor_demo.py")
        let log = root.appendingPathComponent(".venv/eyecursor.log")
        trackerLog = log
        do {
            guard FileManager.default.isExecutableFile(atPath: python.path),
                  FileManager.default.fileExists(atPath: script.path) else {
                throw NSError(domain: "EyeCursor", code: 1, userInfo: [NSLocalizedDescriptionKey:
                    "The tracking runtime is missing from \(root.path). Restore the EyeTracker project and its Python environment, or rebuild EyeCursor from its new location."])
            }
            try Data().write(to: log)
            let output = try FileHandle(forWritingTo: log)
            defer { try? output.close() }
            let process = Process()
            process.executableURL = python
            process.arguments = ["-u", script.path, "--native-host-pid", String(ProcessInfo.processInfo.processIdentifier)]
            process.currentDirectoryURL = root
            process.standardOutput = output
            process.standardError = output
            process.terminationHandler = { [weak self] process in
                let status = process.terminationStatus
                DispatchQueue.main.async {
                    guard let self = self, !self.quitting else { return }
                    if status != 0 {
                        self.reportLaunchFailure("The tracker stopped (exit \(status)).")
                    } else {
                        NSApp.terminate(nil)
                    }
                }
            }
            trackerProcess = process
            try process.run()
        } catch {
            reportLaunchFailure(error.localizedDescription)
        }
    }

    func reportLaunchFailure(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "EyeCursor could not start"
        let details = trackerLog.flatMap { try? String(contentsOf: $0, encoding: .utf8) } ?? ""
        alert.informativeText = message + "\n\n" + String(details.suffix(1600))
        alert.addButton(withTitle: "Quit")
        if let log = trackerLog, FileManager.default.fileExists(atPath: log.path) {
            alert.addButton(withTitle: "Show log")
        }
        NSApp.activate(ignoringOtherApps: true)
        if alert.runModal() == .alertSecondButtonReturn, let log = trackerLog {
            NSWorkspace.shared.activateFileViewerSelecting([log])
        }
        NSApp.terminate(nil)
    }

    func hideCursor() {
        motion.reset()
        dot.orderOut(nil)
    }

    func loseCursorTracking() {
        motion.loseTracking(at: ProcessInfo.processInfo.systemUptime)
        animateCursor()
    }

    func animateCursor(at time: Double = ProcessInfo.processInfo.systemUptime) {
        guard let sample = motion.sample(at: time),
              let center = desktopFence(sample, frames: NSScreen.screens.map { $0.frame }) else {
            dot.orderOut(nil)
            return
        }
        dot.alphaValue = motion.opacity
        dot.setFrameOrigin(NSPoint(x: center.x - 8, y: center.y - 8))
        if !dot.isVisible { dot.orderFrontRegardless() }
    }

    func animateCursorReference(mouse: NSPoint = NSEvent.mouseLocation) {
        guard Date().timeIntervalSince(lastReply) <= 0.6 else {
            cursorReference.orderOut(nil); return
        }
        guard let session = lastState?.onboarding?.cursor_calibration, session.active,
              let screen = calibrationScreen() else {
            cursorReferenceFeedback.reset()
            cursorReference.orderOut(nil); return
        }
        let target = alignmentTarget(session, screen: screen, mouse: mouse)
        guard screen.frame.contains(target) else { cursorReference.orderOut(nil); return }
        cursorReferenceSurface.headCue = session.stage == "geometry" ? session.head_cue : nil
        cursorReferenceSurface.hollow = session.fixed_target != nil && session.stage != "geometry"
        var moved = false
        if let saved = session.target_position, saved.count == 2, saved.allSatisfy({ $0.isFinite }) {
            let savedPoint = NSPoint(x: screen.frame.minX + saved[0]*screen.frame.width,
                                    y: screen.frame.maxY - saved[1]*screen.frame.height)
            moved = hypot(target.x-savedPoint.x, target.y-savedPoint.y) > 5
        }
        cursorReferenceSurface.completed = session.target_complete == true && !moved
        if moved {
            cursorReferenceFeedback.reset()
        } else {
            let key = "\(lastState?.onboarding?.calibration_session_id ?? "")|\(lastState?.onboarding?.display_id ?? "")|\(session.stage ?? "")|\(session.fixed_target ?? session.target_position ?? [])"
            cursorReferenceFeedback.update(key: key, progress: session.progress ?? 0,
                                           accepted: session.sample_accepted ?? (lastState?.valid == true))
        }
        cursorReferenceSurface.progress = cursorReferenceFeedback.progress
        cursorReferenceSurface.accepted = cursorReferenceFeedback.accepted
        cursorReference.setFrameOrigin(NSPoint(x: target.x - 48, y: target.y - 70))
        if !cursorReference.isVisible { cursorReference.orderFrontRegardless() }
    }

    func animateCalibration() {
        guard active, Date().timeIntervalSince(lastReply) <= 0.6 else { return }
        let now = ProcessInfo.processInfo.systemUptime
        if let flow = lastState?.onboarding, flow.screen_path == "quick",
           let start = flow.screen_path_started_at, start.isFinite {
            placeCalibrationTarget(ScreenCalibrationPath.target(elapsed: now-start, corner: max(0, min(3, (flow.screen_target_index ?? 2)-2))))
        } else if let point = calibrationOrbit.sample(at: now) {
            placeCalibrationTarget(point)
        } else if let origin = calibrationTravel.sample(at: now) {
            window.setFrameOrigin(origin)
            if !window.isVisible { window.orderFrontRegardless() }
        }
    }

    func refresh() {
        guard getppid() == parentPID else { NSApp.terminate(nil); return }
        if Date().timeIntervalSince(lastReply) > 0.6 {
            angleDebugger.invalidate()
            readoutMotion.reset()
            clicksSuppressedUntil = Date().addingTimeInterval(1)
            loseCursorTracking()
            surface.accepted = false
            updateMenu()
            // A delayed status response must never destroy a calibration fit.
            // Hide stale output locally; the backend owns calibration validity.
            window.orderOut(nil)
            if diagnosticWindow.isVisible {
                diagnosticRate.stringValue = "IR · Waiting for tracker"
                diagnosticText.stringValue = lastState?.calibrated == true ? "Calibration complete" : "Waiting for tracker"
                calibrationSteps.update(lastState?.onboarding, stale: true)
            }
        }
        guard !pending else { return }
        pending = true
        let generation = self.generation
        let request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/state")!,
                                 cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 0.4)
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            let state = error == nil && (response as? HTTPURLResponse)?.statusCode == 200
                ? data.flatMap { try? JSONDecoder().decode(TrackerState.self, from: $0) } : nil
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.pending = false
                guard let state = state else { self.loseCursorTracking(); return }
                self.lastReply = Date()
                self.lastState = state
                if state.onboarding != nil && !self.displaysRegistered { self.registerDisplays() }
                if !self.changing && self.generation == generation { self.render(state) }
                self.processPendingPreviewAlignment()
            }
        }.resume()
    }

    func animateMeasurements() {
        guard diagnosticWindow.isVisible, Date().timeIntervalSince(lastReply) <= 0.6,
              let state = lastState else { return }
        let time = ProcessInfo.processInfo.systemUptime
        angleDebugger.animate(at: time)
        renderMeasurements(state, at: time)
    }

    func renderMeasurements(_ state: TrackerState, at time: Double) {
        let rate = readoutMotion.sample("irFPS", at: time)?.first ?? 0
        let confidence = readoutMotion.sample("confidence", at: time)?.first ?? 0
        let confidenceText = String(format: "%.2f", confidence)
        let rateText = state.camera_connected
            ? String(format: "IR %.0f FPS · Confidence ", rate) + confidenceText
            : "IR · Camera disconnected"
        let rateLabel = NSMutableAttributedString(string: rateText, attributes: [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .regular),
            .foregroundColor: NSColor.secondaryLabelColor
        ])
        if state.camera_connected, confidence > (state.detection_threshold ?? thresholdSlider.doubleValue) {
            let numberRange = NSRange(location: (rateText as NSString).length - (confidenceText as NSString).length,
                                      length: (confidenceText as NSString).length)
            rateLabel.addAttribute(.foregroundColor, value: NSColor.systemGreen, range: numberRange)
        }
        if let rig = state.eye_cameras {
            diagnosticRate.stringValue = Self.eyeRate(rig.eyes["left"])
            secondaryEyeStatus.stringValue = Self.eyeRate(rig.eyes["right"])
        } else { diagnosticRate.attributedStringValue = rateLabel }
        webcamRate.stringValue = state.head_camera.map { String(format: "Webcam %.0f FPS", readoutMotion.sample("webcamFPS", at: time)?.first ?? $0.fps) } ?? ""
    }

    func render(_ state: TrackerState) {
        renderEyeSetup(state.eye_cameras)
        sampleSystemCursor(state)
        calibrationSteps.update(state.onboarding)
        angleDebugger.update(state)
        if let threshold = state.detection_threshold, !thresholdPending, threshold != serverThreshold {
            serverThreshold = threshold
            thresholdSlider.doubleValue = threshold
            thresholdValue.stringValue = String(format: "%.2f", threshold)
        }
        blinkMenu.state = state.blink_click_enabled ? .on : .off
        let time = ProcessInfo.processInfo.systemUptime
        let context = "\(state.eye_camera_id ?? state.source):\(state.eye_cameras?.active_eye ?? "right"):\(state.eye_cameras?.eyes[state.eye_cameras?.active_eye ?? "right"]?.rotation ?? 0):\(state.head_camera?.name ?? "")"
        if readoutContext != context { readoutMotion.reset(); readoutContext = context }
        readoutMotion.update("irFPS", state.performance.map { [$0.tracking_fps] }, at: time)
        readoutMotion.update("confidence", state.confidence.map { [$0] }, at: time)
        readoutMotion.update("webcamFPS", state.head_camera.map { [$0.fps] }, at: time)
        renderMeasurements(state, at: time)
        if diagnosticWindow.isVisible {
            if let head = state.head_camera {
                faceText.stringValue = head.error ?? (!head.connected ? "Waiting for the laptop webcam. Preview paused." :
                    (!head.face_visible ? "Face not visible." : !state.calibrated ? "Head tracked · Screen estimate available after calibration." :
                     state.desktop_gaze == nil ? (state.cursor_message ?? "Waiting for a mapped gaze position.") : "Lines and trail show the combined cursor estimate on the screen map."))
                if head.connected && head.face_visible {
                    let correction = state.onboarding?.geometry_model != nil ? "head rotation and position model active" : state.onboarding?.head_mode == "steady" ? "steady-head mode; use fixed-dot head calibration" :
                        state.onboarding?.head_ready == true ? "ready" : "not calibrated"
                    faceText.stringValue = "Head correction: \(correction) · Webcam iris marks are landmarks, not screen gaze.\n" +
                        (state.calibrated ? (state.cursor_message ?? "") : "Initial anchors: \(state.onboarding?.screen_sectors ?? 0)/4 corners captured.")
                    if let cursor = state.onboarding?.cursor_calibration, cursor.active {
                        faceText.stringValue = cursor.stage == "geometry" ? cursor.message :
                            "Cursor alignment: \(cursor.positions) positions · \(cursor.live_preview == true ? "Live adjustment" : "Collecting")"
                    }
                }
            }
        }
        if diagnosticWindow.isVisible {
            diagnosticText.stringValue = Self.irCalibrationStatus(state)
        }
        if let flow = state.onboarding { renderOnboarding(flow) }
        updateMenu()
        guard !eyeSetupPending, !active, state.calibrated, state.desktop_cursor else { hideCursor(); return }
        guard (state.display_valid ?? state.valid), let point = state.desktop_gaze,
              point.count == 2, point.allSatisfy({ $0.isFinite }), let primary = NSScreen.screens.first else {
            loseCursorTracking(); return
        }
        let center = NSPoint(x: point[0], y: primary.frame.maxY - point[1])
        guard NSScreen.screens.contains(where: { $0.frame.contains(center) }) else { loseCursorTracking(); return }
        motion.updateTarget(center, at: ProcessInfo.processInfo.systemUptime)
        animateCursor()
        if let click = state.click_event, click.id > lastClickID {
            lastClickID = click.id  // Never replay an event skipped while a menu or permission is open.
            guard state.onboarding?.cursor_calibration?.active != true,
                  state.valid, !menuOpen, !eyeCameraMenuOpen, Date() > clicksSuppressedUntil, state.blink_click_enabled, AXIsProcessTrusted(),
                  !CGEventSource.buttonState(.combinedSessionState, button: .left),
                  click.age_ms >= 0 && click.age_ms < 350, click.point.count == 2,
                  click.point.allSatisfy({ $0.isFinite }),
                  hypot(click.point[0] - point[0], click.point[1] - point[1]) <= 24 else { return }
            let location = CGPoint(x: click.point[0], y: click.point[1])
            guard let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown,
                                     mouseCursorPosition: location, mouseButton: .left),
                  let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp,
                                   mouseCursorPosition: location, mouseButton: .left) else { return }
            down.setIntegerValueField(.mouseEventClickState, value: 1)
            up.setIntegerValueField(.mouseEventClickState, value: 1)
            down.post(tap: .cghidEventTap)
            up.post(tap: .cghidEventTap)
        }
    }
}

let arguments = Array(CommandLine.arguments.dropFirst()).filter { !$0.hasPrefix("-psn_") }
let standalone = arguments.isEmpty
let port = standalone ? 8765 : (Int(arguments[0]) ?? 0)
guard (1...65535).contains(port), standalone || (arguments.count <= 2 &&
      (arguments.count == 1 || arguments[1] == "--hybrid")) else {
    fputs("Usage: EyeCursor [PORT [--hybrid]]\n", stderr)
    exit(2)
}
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = CalibrationApp(port: port, hybrid: standalone || arguments.contains("--hybrid"))
app.delegate = controller
app.finishLaunching()
// A helper started directly by Python may miss AppKit's launch notification.
if !controller.launched {
    controller.applicationDidFinishLaunching(Notification(name: NSApplication.didFinishLaunchingNotification))
}
if standalone {
    controller.showDiagnostics()
    controller.startTracker()
}
app.run()
