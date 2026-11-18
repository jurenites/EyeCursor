// Native macOS interface. Sampling, stability checks and mapping live in Python.
import AppKit
import ApplicationServices
import AVFoundation
import Carbon
import Darwin

// A different local service may own the preferred port (for example Docker).
// Probe only loopback and pass the chosen port to the child tracker.
func availableTrackerPort(preferred: UInt16 = 8765) -> Int {
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    guard fd >= 0 else { return 0 }
    defer { close(fd) }
    var address = sockaddr_in()
    address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
    address.sin_family = sa_family_t(AF_INET)
    address.sin_addr.s_addr = inet_addr("127.0.0.1")
    func tryBind(_ port: UInt16) -> Bool {
        address.sin_port = port.bigEndian
        return withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
            }
        }
    }
    guard tryBind(preferred) || tryBind(0) else { return 0 }
    var size = socklen_t(MemoryLayout<sockaddr_in>.size)
    let result = withUnsafeMutablePointer(to: &address) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &size) }
    }
    return result == 0 ? Int(UInt16(bigEndian: address.sin_port)) : 0
}

struct CalibrationStep: Decodable {
    let phase: String
    let step: Int
    let target: [Double]?
    let progress: Double
    let message: String
}
struct DotLearningState: Decodable {
    let target_index: Int
    let target_count: Int
    let remaining_seconds: Double
    let message: String
}
struct TrackerState: Decodable {
    let source: String
    let eye_camera_id: String?
    let eye_cameras: EyeCamerasState?
    var eye_predictions: [String: EyeScreenPrediction]? = nil
    let binocular_status: String?
    let gaze_eye_mode: String?
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
struct EyeScreenPrediction: Decodable {
    let uv: [Double]
    let desktop: [Double]
    let head_features: [Double]
    let confidence: Double
    let identity: String
}
struct EyeCameraDevice: Decodable {
    let id: String
    let name: String
}
struct EyeCameraDirection: Decodable {
    var captured_at: Double? = nil
    let vector: [Double]
    let head_features: [Double]
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
    var scene_direction: EyeCameraDirection? = nil
    var tracking_epoch: String? = nil
    var fixed_eye_sphere: Bool? = nil
    var pupil_center: [Double]? = nil
    var measurement_valid: Bool? = nil
    var eyeball_model_status: String? = nil
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
struct SecondWebcamState: Decodable {
    let connected: Bool
    let face_visible: Bool
    let fps: Double
    let error: String?
}
struct HeadAssistanceState: Decodable {
    let reason: String
    let weight: Double
}
struct SecondHeadState: Decodable {
    let camera_id: String?
    let camera: SecondWebcamState?
    let devices: [EyeCameraDevice]
    let error: String?
    let collecting: Bool
    let aligned: Bool
    let samples: Int
    let message: String
    let assistance: HeadAssistanceState
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
    var second_view: SecondHeadState? = nil
}
struct GeometryCalibrationState: Decodable {
    let continuous: Bool?
    let total_samples: Int?
    let applied_updates: Int?
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

struct PreviewReferenceState: Decodable {
    let eye: String?
    let target: [Double]?
    let completed: [String]
}

struct OnboardingState: Decodable {
    var preview_alignment: PreviewReferenceState? = nil
    let two_view_guided: Bool?
    let eye_scan_enabled: Bool?
    let guided_head_outcome: String?
    let second_view_fallback_reason: String?
    let dot_learning: DotLearningState?
    let eye_map_status: [String:String]?
    let accuracy_check: AccuracyCheckState?
    let screen_path: String?
    let screen_path_started_at: Double?
    let cursor_calibration: CursorCalibrationState?
    let calibration_rays: [CalibrationRay]?
    let calibration_session_id: String?
    let head_correction_rank: Int?
    let head_correction_status: String?
    let head_reference: [Double]?
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

final class CalibrationVoiceGuide {
    private let synthesizer = AVSpeechSynthesizer()
    var enabled = true
    var output: ((String) -> Void)?
    private var lastKey: String?
    func silence(reset: Bool = true) { synthesizer.stopSpeaking(at: .immediate); if reset { lastKey = nil } }
    static func instruction(_ flow: OnboardingState) -> (String,String)? {
        let phase = flow.phase
        let key = "\(flow.calibration_session_id ?? "")|\(phase)"
        switch phase {
        case "preview":
            let eye=flow.preview_alignment?.eye ?? "left"
            return (key+"|"+eye,"Look at your " + eye + " pupil in its camera preview. Gently align your head with the fixed marker, then hold still.")
        case "head": return (key,"Keep your head still. Look at the center dot.")
        case "screen":
            let index = max(0,min(3,(flow.screen_target_index ?? 2)-2))
            return (key + "|\(index)",["Top left.","Top right.","Bottom right.","Bottom left."][index])
        case "fitting": return (key,"Keep your head still. Look around slowly in comfortable circles.")
        case "views", "motion":
            let cue = phase == "views" ? flow.head_cue : flow.cursor_calibration?.head_cue
            guard let cue = cue else { return (key,"Look at the center dot.") }
            let action = ["shift":"Slide your head gently left and right.","depth":"Move gently closer, then farther away.","pitch":"Gently nod your head up and down.","yaw":"Gently turn your head left and right."][cue] ?? "Move your head gently."
            let checking = (flow.remaining_seconds ?? 64) <= 32
            return (key + "|\(cue)|\(checking)","Keep watching the center. " + action)
        case "views_fit": return (key,flow.two_view_guided == true ? "Movement recorded. Checking the measurements, then continuing to the check dots." : "Movement recorded. Checking the measurements.")
        case "verify": return (key,"Keep your head still and follow the check dots.")
        case "paused": return (key,"Calibration paused. Use Retry step in diagnostics to continue.")
        case "complete": return (key,"Calibration finished. The results are in diagnostics.")
        default: return nil
        }
    }
    func update(_ flow: OnboardingState?) {
        guard enabled,let flow = flow,let (key,text) = Self.instruction(flow) else { silence();return }
        guard key != lastKey else { return }
        // Do not queue old directions behind a new target or a Stop action.
        synthesizer.stopSpeaking(at: .immediate);lastKey=key
        if let output = output { output(text) }
        else {
            let utterance = AVSpeechUtterance(string:text)
            utterance.voice = AVSpeechSynthesisVoice(language:"en-US")
            utterance.rate = AVSpeechUtteranceDefaultSpeechRate
            synthesizer.speak(utterance)
        }
    }
}

final class CalibrationStepsView: NSView {
    let heading = NSTextField(labelWithString: "Calibration")
    let muteButton = NSButton(title: "Mute", target: nil, action: nil)
    let countdown = NSTextField(wrappingLabelWithString: "Waiting for cameras")
    let actionButton = NSButton(title: "Start calibration", target: nil, action: nil)
    let manualButton = NSButton(title: "Learn at cursor", target: nil, action: nil)
    let headButton = NSButton(title: "Calibrate head movement", target: nil, action: nil)
    let accuracyButton = NSButton(title: "Check Accuracy", target: nil, action: nil)
    let rows = (0..<5).map { _ in NSTextField(wrappingLabelWithString: "") }
    let descriptions = ["Follow five dots; keep your head comfortably still",
                        "Watch the fixed center; gently turn and shift your head",
                        "Follow the check dots; accuracy is measured automatically"]

    override init(frame: NSRect) {
        super.init(frame: frame)
        heading.font = .systemFont(ofSize: 13, weight: .semibold)
        muteButton.bezelStyle = .rounded
        muteButton.controlSize = .small
        muteButton.imagePosition = .imageLeading
        addSubview(muteButton)
        countdown.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
        countdown.textColor = .secondaryLabelColor
        countdown.alignment = .left
        actionButton.bezelStyle = .rounded
        manualButton.bezelStyle = .rounded
        headButton.bezelStyle = .rounded
        accuracyButton.bezelStyle = .rounded
        accuracyButton.toolTip = "Check dots measure error without changing your calibration."
        addSubview(accuracyButton)
        addSubview(manualButton)
        addSubview(headButton)
        addSubview(heading); addSubview(countdown); addSubview(actionButton)
        for row in rows { addSubview(row) }
        update(nil)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override var intrinsicContentSize: NSSize {
        NSSize(width: NSView.noIntrinsicMetric, height: CGFloat(130 + (manualButton.isHidden ? 0 : 36) + (accuracyButton.isHidden ? 0 : 36)) + CGFloat(rows.filter { !$0.isHidden }.count) * 58)
    }
    override func layout() {
        super.layout()
        heading.frame = NSRect(x: 0, y: bounds.height - 20, width: max(0, bounds.width - 92), height: 20)
        heading.lineBreakMode = .byTruncatingTail
        muteButton.frame = NSRect(x: max(0, bounds.width - 86), y: bounds.height - 24, width: 86, height: 24)
        countdown.frame = NSRect(x: 0, y: bounds.height - 90, width: bounds.width, height: 64)
        headButton.frame = NSRect(x: 0, y: bounds.height - 126, width: bounds.width, height: 30)
        let footer: CGFloat = accuracyButton.isHidden ? 0 : 36
        accuracyButton.frame = NSRect(x: 0, y: 0, width: bounds.width, height: 30)
        actionButton.frame = NSRect(x: 0, y: footer + (manualButton.isHidden ? 0 : 36), width: bounds.width, height: 30)
        manualButton.frame = NSRect(x: 0, y: footer, width: bounds.width, height: 30)
        for (index, row) in rows.enumerated() {
            row.frame = NSRect(x: 0, y: bounds.height - 150 - CGFloat(index) * 58, width: bounds.width, height: 54)
        }
    }
    func update(_ flow: OnboardingState?, stale: Bool = false) {
        let phase = flow?.phase ?? "no_displays"
        manualButton.isHidden = flow?.cursor_calibration?.active == true || phase == "complete"
        let paused = phase == "paused"
        let stage = paused ? (flow?.stopped_stage ?? "") : phase
        let scan = flow?.eye_scan_enabled == true
        let views = flow?.two_view_guided == true
        let previews = flow?.preview_alignment != nil
        let offset = previews ? 2 : scan ? 1 : 0
        let descriptions = (previews ? ["Look at the left pupil preview; align and hold", "Look at the right pupil preview; align and hold"] : scan ? ["Look around slowly in circles; keep your head still"] : []) + self.descriptions
        let current: Int? = stage == "preview" ? (flow?.preview_alignment?.eye == "right" ? 1 : 0) : ["waiting","fitting"].contains(stage) ? 0 : ["head","screen"].contains(stage) ? offset : ["views","views_fit","motion"].contains(stage) ? 1 + offset : stage == "verify" ? 2 + offset : nil
        let running = ["preview", "views_fit", "views", "waiting", "fitting", "head", "screen", "motion", "verify", "refine"].contains(phase)
        manualButton.isHidden = running || flow?.cursor_calibration?.active == true || phase == "no_displays"
        manualButton.title = phase == "complete" ? "Learn at cursor" : "Learn at cursor"
        headButton.isHidden = true
        accuracyButton.isHidden = phase != "complete" || flow?.cursor_calibration?.active == true
        let headRetry = ["previous_fit_kept", "partial"].contains(flow?.guided_head_outcome ?? "")
        actionButton.title = phase == "complete" ? (headRetry ? "Retry head movement" : "Restart calibration") :
            running ? "Stop calibration" : paused ? "Retry step \((current ?? 0) + 1)" : "Start calibration"
        for (index, row) in rows.enumerated() {
            row.isHidden = index >= ((views || phase == "verify") ? descriptions.count : 2 + offset)
            guard !row.isHidden else { row.stringValue = ""; continue }
            let done = phase == "complete" || current.map { index < $0 } == true
            let selected = current == index
            let unchangedHead = index == 1 + offset && done && flow?.guided_head_outcome == "previous_fit_kept"
            let partialHead = index == 1 + offset && done && flow?.guided_head_outcome == "partial"
            let suffix = unchangedHead ? "  · No correction learned" : partialHead ? "  · One eye corrected" : done ? "  ✓" : selected ? (paused ? "  · Ready to retry" : "  · Active") : ""
            row.stringValue = "\(index + 1). \(descriptions[index])\(suffix)"
            row.font = .systemFont(ofSize: 13, weight: selected ? .semibold : .regular)
            row.textColor = stale ? .secondaryLabelColor : selected ? (paused ? .systemOrange : .systemBlue) : done ? .labelColor : .secondaryLabelColor
        }
        heading.stringValue = "Calibration"
        if stage == "refine" {
            heading.stringValue = "Learn from dots"
            for (i,row) in rows.enumerated() {
                row.isHidden = i > 0
                row.stringValue = "Follow five dots; each target teaches both eye maps"
            }
            if paused { actionButton.title = "Retry dot learning" }
        }
        if let cursor = flow?.cursor_calibration, cursor.active, phase != "motion" {
            heading.stringValue = "Cursor learning · On"
            actionButton.title = "Stop learning"
            let practice = cursor.stage == "geometry"
            let continuous = practice && flow?.geometry_calibration?.continuous == true
            if practice { heading.stringValue = continuous ? "Continuous head calibration" : "Fixed-target head calibration"; actionButton.title = continuous ? "Finish head calibration" : "Stop head calibration" }
            let previewAlignment = cursor.fixed_target != nil && !practice
            if previewAlignment {
                heading.stringValue = "IR preview alignment"
                actionButton.title = cursor.ready ? "Finish preview alignment" : "Stop preview alignment"
            }
            let steps = previewAlignment ? ["Look at the fixed marker over the IR preview",
                         "Hold still for one second to save a reference",
                         "Keep watching it; move your head slightly and pause", cursor.message] : practice ? ["Keep looking at the fixed center dot",
                         continuous ? "Turn and shift your head naturally; no required pattern" : flow?.geometry_calibration?.motion_hint == "shift" ? "Slide your head sideways; keep your face forward" : "Turn your head gently left and right",
                         continuous ? "Finish whenever ready; only checked improvements are kept" : "Keep watching the dot as your head moves", cursor.message] :
                        ["Look at the mouse; hold it still until the checkmark",
                         cursor.positions < 6 && cursor.ready == false ? "Save six positions across the screen; keep your head still" : "Keep watching the stationary pointer while nodding or shifting",
                         "Stop learning before looking away; saved corrections stay", cursor.message]
            for (i,row) in rows.enumerated() {
                row.isHidden = i >= steps.count
                guard i < steps.count else { row.stringValue = ""; continue }
                row.stringValue = "\(i+1). \(steps[i])"; row.textColor = .labelColor
            }
            invalidateIntrinsicContentSize(); needsLayout = true
            countdown.stringValue = stale ? "Waiting for tracker response" : continuous
                ? "\(flow?.geometry_calibration?.total_samples ?? 0) measurements · \(flow?.geometry_calibration?.applied_updates ?? 0) checked updates"
                : practice
                ? "\(Int(ceil(cursor.remaining_seconds ?? 15)))s left · \(flow?.geometry_calibration?.phase == "validate" ? "Checking" : "Learning")"
                : cursor.stage == "center" ? "Hold a comfortable center position"
                : "\(cursor.saved_anchors ?? cursor.positions) saved fixations · \(cursor.live_preview == true ? "Live adjustment" : "Collecting screen fit")"
            return
        }
        invalidateIntrinsicContentSize(); needsLayout = true
        if stale { countdown.stringValue = "Waiting for tracker response" }
        else if phase == "idle" { countdown.stringValue = "Ready. Start calibration when you are prepared." }
        else if phase == "complete" {
            countdown.stringValue = flow?.message ?? "Ready"
            if flow?.second_view_fallback_reason != nil {
                countdown.stringValue += "\nLaptop webcam used; second view not aligned."
            }
        }
        else if paused { countdown.stringValue = flow?.blocker == "Stopped by user" ? "Stopped · Completed steps saved" : (flow?.blocker ?? "Stopped · Retry this step") }
        else if phase == "cancelled" { countdown.stringValue = "Calibration cancelled" }
        else if phase == "refine", let learning = flow?.dot_learning {
            countdown.stringValue = "Target \(learning.target_index)/\(learning.target_count) · \(Int(ceil(learning.remaining_seconds)))s available\n\(learning.message)"
        }
        else if phase == "fitting" && scan {
            countdown.stringValue = "\(Int(ceil(flow?.remaining_seconds ?? 0)))s until the first dot\nUse a comfortable range; no target to follow"
        }
        else if phase == "preview" { countdown.stringValue = flow?.message ?? "Align with the pupil preview" }
        else if phase == "views_fit" { countdown.stringValue = flow?.message ?? "Movement captured. Checking the eye models." }
        else if phase == "views" {
            countdown.stringValue = "\(Int(ceil(flow?.remaining_seconds ?? 64)))s left · Eye and head movement\n\(flow?.message ?? "Keep both faces visible")"
        }
        else if phase == "motion" {
            let checking = flow?.geometry_calibration?.phase == "validate"
            countdown.stringValue = "\(Int(ceil(flow?.remaining_seconds ?? 0)))s left · \(checking ? "Checking movement" : "Learning movement")\n\(checking ? "Repeat the same small turns and shifts" : "Small turns and shifts; return to your starting position")"
        }
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
    var color = NSColor.white
    var ring = false
    override func draw(_ dirtyRect: NSRect) {
        color.withAlphaComponent(0.75).setFill()
        color.setStroke()
        let shape = NSBezierPath(ovalIn: bounds.insetBy(dx: 1, dy: 1))
        if ring { shape.lineWidth = 2; shape.stroke() } else { shape.fill() }
    }
}
final class DotPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}
final class CalibrationView: NSView {
    var freeEyeInstruction: String? { didSet { needsDisplay = true } }
    var monochrome = false { didSet { needsDisplay = true } }
    var progress = 0.0 { didSet { needsDisplay = true } }
    var accepted = false { didSet { needsDisplay = true } }
    var hollow = false { didSet { needsDisplay = true } }
    var completed = false { didSet { needsDisplay = true } }
    var collecting = false { didSet { needsDisplay = true } }
    var headCueStarted = ProcessInfo.processInfo.systemUptime
    var headCue: String? { didSet { if headCue != oldValue { headCueStarted=ProcessInfo.processInfo.systemUptime }; needsDisplay = true } }
    override var isOpaque: Bool { false }
    override func draw(_ dirtyRect: NSRect) {
        // Only the target and its progress ring are drawn. The desktop remains
        // visible through this small, nonactivating, click-through panel.
        NSColor.clear.setFill()
        bounds.fill(using: .copy)
        if let instruction = freeEyeInstruction {
            NSColor.black.withAlphaComponent(0.72).setFill()
            NSBezierPath(roundedRect: bounds.insetBy(dx: 2, dy: 2), xRadius: 14, yRadius: 14).fill()
            let paragraph = NSMutableParagraphStyle(); paragraph.alignment = .center
            (instruction as NSString).draw(in: bounds.insetBy(dx: 16, dy: 16), withAttributes: [
                .font: NSFont.systemFont(ofSize: 15, weight: .medium), .foregroundColor: NSColor.white,
                .paragraphStyle: paragraph])
            return // Preparation instructions only: no fixation dot or progress ring.
        }
        let center = NSPoint(x: bounds.midX, y: bounds.midY)
        let ringRadius: CGFloat = 20
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
        let ring = NSBezierPath(ovalIn: NSRect(x: center.x - ringRadius, y: center.y - ringRadius, width: 2*ringRadius, height: 2*ringRadius))
        ring.lineWidth = 4
        NSColor.black.withAlphaComponent(0.3).setStroke()
        ring.stroke()
        ring.lineWidth = 2
        let feedbackColor: NSColor = completed ? .systemGreen : monochrome ? (accepted ? .white : .gray) : (accepted ? .systemGreen : .systemRed)
        feedbackColor.withAlphaComponent(0.45).setStroke()
        ring.stroke()
        let amount = completed ? 1 : collecting ? 0.22 : progress.isFinite ? min(1, max(0, progress)) : 0
        if amount > 0 {
            let arc = NSBezierPath()
            arc.lineWidth = 2
            arc.lineCapStyle = .round
            let start: CGFloat = collecting && !completed ? 90-CGFloat(ProcessInfo.processInfo.systemUptime.truncatingRemainder(dividingBy:2))*180 : 90
            arc.appendArc(withCenter: center, radius: ringRadius, startAngle: start,
                          endAngle: start - CGFloat(amount) * 360, clockwise: true)
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
            // The fixation stays at the panel center with the same ring in every
            // phase. Instructions sit immediately below, outside that ring.
            let head = NSPoint(x: center.x, y: center.y - 43)
            NSColor.black.withAlphaComponent(0.78).setFill()
            NSBezierPath(roundedRect: NSRect(x:center.x-47,y:center.y-70,width:94,height:47),
                         xRadius:8,yRadius:8).fill()
            if let title = ["shift":"Slide sideways", "depth":"Closer / farther",
                            "pitch":"Nod up / down", "yaw":"Turn left / right"][cue] {
                let attributes: [NSAttributedString.Key:Any] = [.font:NSFont.systemFont(ofSize:11,weight:.semibold),
                    .foregroundColor:NSColor.white]
                let size = (title as NSString).size(withAttributes:attributes)
                (title as NSString).draw(at:NSPoint(x:center.x-size.width/2,y:center.y-69),withAttributes:attributes)
            }
            let phase = (ProcessInfo.processInfo.systemUptime-headCueStarted) * .pi/2
            let motion = sin(phase)
            let forward = cos(phase) >= 0
            NSColor.white.setStroke(); NSColor.white.setFill()
            let scale: CGFloat = cue == "depth" ? 1 + 0.25*motion : 1
            let dx: CGFloat = cue == "shift" ? -8*motion : 0
            if cue == "pitch" {
                // Rear view throughout: pitch foreshortens the round head around
                // a fixed ear-to-ear axle, without switching to a face profile.
                let height: CGFloat = 18 + 4*motion
                let face=NSBezierPath(ovalIn:NSRect(x:head.x-8,y:head.y-height/2,width:16,height:height))
                face.lineWidth=2; face.stroke()
                let axle=NSBezierPath()
                axle.move(to:NSPoint(x:head.x-14,y:head.y))
                axle.line(to:NSPoint(x:head.x+14,y:head.y))
                axle.lineWidth=1.5; axle.stroke()
                for side in [-1.0,1.0] {
                    NSBezierPath(ovalIn:NSRect(x:head.x+9*side-2,y:head.y-3,width:4,height:6)).fill()
                }
            } else {
                let face = NSBezierPath(ovalIn: NSRect(x: head.x + dx - 7*scale, y: head.y - 9*scale,
                                                      width: 14*scale, height: 18*scale))
                face.lineWidth = 2; face.stroke()
                // Consistent rear view: ears, no facial features that imply mirroring.
                let turn: CGFloat = cue == "yaw" ? -3*motion : 0
                for side in [-1.0,1.0] {
                    NSBezierPath(ovalIn:NSRect(x:head.x+dx+side*8*scale+turn-1.5,
                                              y:head.y-2,width:3,height:5)).fill()
                }
            }
            func arrowTip(_ tip: CGPoint, tangent: CGPoint) {
                let length = hypot(tangent.x,tangent.y)
                guard length > 0 else { return }
                let ux=tangent.x/length, uy=tangent.y/length
                let path=NSBezierPath()
                path.move(to:CGPoint(x:tip.x-5*ux+3*uy,y:tip.y-5*uy-3*ux))
                path.line(to:tip)
                path.line(to:CGPoint(x:tip.x-5*ux-3*uy,y:tip.y-5*uy+3*ux))
                path.lineWidth=2.2; path.lineCapStyle = .round; path.lineJoinStyle = .round; path.stroke()
            }
            func arrow(_ from: CGPoint, _ to: CGPoint) {
                let line=NSBezierPath(); line.lineWidth=2.2; line.lineCapStyle = .round
                line.move(to:from); line.line(to:to); line.stroke()
                arrowTip(to,tangent:CGPoint(x:to.x-from.x,y:to.y-from.y))
            }
            func rotationArrow(origin: CGPoint, rx: CGFloat, ry: CGFloat, start: CGFloat, end: CGFloat) {
                let arc=NSBezierPath()
                for i in 0...32 {
                    let angle=start+(end-start)*CGFloat(i)/32
                    let point=CGPoint(x:origin.x+rx*cos(angle),y:origin.y+ry*sin(angle))
                    if i == 0 { arc.move(to:point) } else { arc.line(to:point) }
                }
                arc.lineWidth=2.2; arc.lineCapStyle = .round; arc.stroke()
                let direction: CGFloat = end > start ? 1 : -1
                arrowTip(CGPoint(x:origin.x+rx*cos(end),y:origin.y+ry*sin(end)),
                         tangent:CGPoint(x:-rx*sin(end)*direction,y:ry*cos(end)*direction))
            }
            if cue == "pitch" || cue == "both" {
                // Vertical half-circle: tilt around the horizontal ear-to-ear axis.
                rotationArrow(origin:CGPoint(x:head.x+9,y:head.y+3),rx:12,ry:12,
                              start:forward ? -.pi/2 : .pi/2,end:forward ? .pi/2 : -.pi/2)
            }
            if cue == "yaw" || cue == "both" {
                // Horizontal half-circle: turn around the upright neck axis.
                rotationArrow(origin:CGPoint(x:head.x,y:head.y+2),rx:25,ry:14,
                              start:forward ? .pi : 0,end:forward ? 0 : .pi)
            }
            if cue == "depth" {
                let monitor=NSBezierPath(rect:NSRect(x:head.x-30,y:head.y-11,width:3,height:23))
                monitor.lineWidth=2; monitor.stroke()
                arrow(CGPoint(x:head.x-12,y:head.y),CGPoint(x:head.x-23,y:head.y))
                arrow(CGPoint(x:head.x+12,y:head.y),CGPoint(x:head.x+28,y:head.y))
            }
            if cue == "shift" {
                for side in [-1.0,1.0] {
                    arrow(CGPoint(x:head.x+18*side,y:head.y),CGPoint(x:head.x+33*side,y:head.y))
                }
            }
            if cue == "left" || cue == "right" {
                let sign = cue == "left" ? -1.0 : 1.0
                arrow(CGPoint(x:head.x+13*sign,y:head.y),CGPoint(x:head.x+29*sign,y:head.y))
            }
            if cue == "up" || cue == "down" {
                let sign = cue == "up" ? 1.0 : -1.0
                arrow(CGPoint(x:head.x+12,y:head.y),CGPoint(x:head.x+12,y:head.y+15*sign))
            }
            for (name, dx, dy) in [("top-left", -1.0, 1.0), ("top-right", 1.0, 1.0),
                                   ("bottom-right", 1.0, -1.0), ("bottom-left", -1.0, -1.0)] {
                if cue == name || cue == "cone" {
                    arrow(CGPoint(x:head.x+12*dx,y:head.y+5*dy),
                          CGPoint(x:head.x+28*dx,y:head.y+13*dy))
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

final class RecordCaptureButton:NSButton {
    override func draw(_ dirtyRect:NSRect) {
        NSColor.systemRed.withAlphaComponent(isEnabled ? 1 : 0.5).setFill()
        NSColor.systemRed.withAlphaComponent(isEnabled ? 1 : 0.5).setStroke()
        let center=NSPoint(x:bounds.midX,y:bounds.midY)
        NSBezierPath(ovalIn:NSRect(x:center.x-5,y:center.y-5,width:10,height:10)).fill()
        let rim=NSBezierPath(ovalIn:NSRect(x:center.x-9,y:center.y-9,width:18,height:18))
        rim.lineWidth=1.5;rim.stroke()
    }
}
struct ReplayCursor: Codable {
    let point: [Double]
    let opacity: Double
}
struct ReplayTimeline: Decodable {
    let id: String
    let duration_ms: Double
    let frames: [Double]
    let has_scene: Bool
}
struct ReplayFrame: Decodable {
    let t_ms: Double
    let images: [String:String]
    let camera_times: [String:Double]
    let state: TrackerState?
    let cursors: [String:ReplayCursor]
    let scene: [String:Double]?
}
final class DiagnosticRecordingController: NSObject {
    let view=NSStackView()
    let record=RecordCaptureButton()
    let play=NSButton(), stop=NSButton(), previous=NSButton(), next=NSButton()
    let slider=NSSlider(value:0,minValue:0,maxValue:1,target:nil,action:nil)
    let status=NSTextField(labelWithString:"Live")
    var ensureService: ((@escaping (String?)->Void)->Void)?
    var canReplay: ()->Bool = { true }
    var modeChanged: ((Bool)->Void)?
    var frameReady: ((ReplayFrame,[String:NSImage])->Void)?
    var initialized=false, connecting=false, busy=false
    var activeID: String?, recordingPaused=false
    var timeline: ReplayTimeline?
    private(set) var replaying=false
    private(set) var playing=false
    private(set) var playhead=0.0
    private var framePending=false, frameGeneration=0, commandRevision=0
    private var frameWanted=false, lastTick=ProcessInfo.processInfo.systemUptime
    private var lastPoll=0.0, statusPending=false, presentationPending=false, lastPresentation=0.0
    private var clock:Timer?
    override init() {
        super.init()
        view.orientation = .vertical;view.alignment = .leading;view.spacing=5
        view.edgeInsets=NSEdgeInsets(top:8,left:12,bottom:8,right:12)
        let buttons=NSStackView();buttons.spacing=5
        for (button,symbol,label,action) in [
            (record,"record.circle.fill","Record (replaces previous recording)",#selector(startRecording)),
            (play,"play.fill","Play recording",#selector(togglePlay)),
            (stop,"stop.fill","Stop recording / return to live",#selector(stopAction)),
            (previous,"backward.end.fill","Previous camera frame",#selector(stepBack)),
            (next,"forward.end.fill","Next camera frame",#selector(stepForward))] {
            button.image=NSImage(systemSymbolName:symbol,accessibilityDescription:label)
            button.imagePosition = .imageOnly;button.bezelStyle = .texturedRounded
            button.toolTip=label;button.setAccessibilityLabel(label)
            button.target=self;button.action=action
            button.widthAnchor.constraint(equalToConstant:30).isActive=true
            button.heightAnchor.constraint(equalToConstant:26).isActive=true
            buttons.addArrangedSubview(button)
        }
        buttons.addArrangedSubview(NSView())
        record.contentTintColor = .systemRed
        slider.target=self;slider.action=#selector(scrub);slider.isContinuous=true
        slider.setAccessibilityLabel("Recording timeline")
        status.font = .monospacedDigitSystemFont(ofSize:10,weight:.regular)
        status.lineBreakMode = .byTruncatingTail
        for item in [buttons,slider,status] as [NSView] {
            view.addArrangedSubview(item)
            item.translatesAutoresizingMaskIntoConstraints=false
            item.widthAnchor.constraint(equalTo:view.widthAnchor,constant:-24).isActive=true
        }
        refreshControls()
        let timer=Timer(timeInterval:1.0/30,repeats:true) { [weak self] _ in self?.tick() }
        clock=timer;RunLoop.main.add(timer,forMode:.common)
    }
    deinit { clock?.invalidate() }
    func call(_ path:String, body:[String:Any]?=nil, completion:@escaping (Data?,String?)->Void) {
        var req=URLRequest(url:URL(string:"http://127.0.0.1:8766"+path)!,cachePolicy:.reloadIgnoringLocalCacheData,timeoutInterval:30)
        if let body=body {
            req.httpMethod="POST";req.setValue("application/json",forHTTPHeaderField:"Content-Type")
            req.httpBody=try? JSONSerialization.data(withJSONObject:body)
        }
        URLSession.shared.dataTask(with:req) { data,response,error in
            var message=error?.localizedDescription
            if (response as? HTTPURLResponse)?.statusCode != 200 {
                let json=data.flatMap { try? JSONSerialization.jsonObject(with:$0) as? [String:Any] }
                message=json?["error"] as? String ?? message ?? "Recorder unavailable"
            }
            DispatchQueue.main.async { completion(data,message) }
        }.resume()
    }
    func message(_ text:String) { status.stringValue=text;status.toolTip=text }
    func connect(_ completion:((Bool)->Void)?=nil) {
        if initialized { completion?(true);return }
        guard !connecting else { completion?(false);return }
        connecting=true
        ensureService? { [weak self] error in
            guard let self=self else { return }
            self.connecting=false
            if let error=error { self.message(error);completion?(false);return }
            self.initialized=true;self.loadLatest();completion?(true)
        }
    }
    func loadLatest() {
        call("/api/sessions") { [weak self] data,error in
            guard let self=self,error == nil,let data=data,
                  let rows=try? JSONSerialization.jsonObject(with:data) as? [[String:Any]],
                  let row=rows.first,let id=row["id"] as? String,
                  row["status"] as? String != "recording" else { return }
            self.loadTimeline(id,show:false)
        }
    }
    func loadTimeline(_ id:String,show:Bool) {
        let revision=commandRevision
        call("/api/sessions/\(id)/timeline") { [weak self] data,error in
            guard let self=self else { return }
            if let error=error { self.message(error);return }
            guard let data=data,let timeline=try? JSONDecoder().decode(ReplayTimeline.self,from:data) else {
                self.message("Recording timeline unavailable");return
            }
            guard self.activeID == nil,self.commandRevision == revision else { return }
            self.timeline=timeline;self.slider.maxValue=max(1,timeline.duration_ms)
            self.refreshControls()
            if show { self.seek(0) }
            else if !self.replaying { self.message("Saved · press Play to review") }
        }
    }
    func refreshControls() {
        record.isEnabled = !busy && activeID == nil
        play.isEnabled = !busy && (activeID != nil || timeline != nil)
        stop.isEnabled = !busy && (activeID != nil || replaying)
        previous.isEnabled = !busy && activeID == nil && timeline != nil
        next.isEnabled=previous.isEnabled;slider.isEnabled=previous.isEnabled
        let pausing = activeID != nil ? !recordingPaused : playing
        play.image=NSImage(systemSymbolName:pausing ? "pause.fill" : "play.fill",accessibilityDescription:pausing ? "Pause" : "Play")
        play.toolTip=activeID != nil ? (recordingPaused ? "Resume recording" : "Pause recording") : (playing ? "Pause replay" : "Play recording")
        play.setAccessibilityLabel(play.toolTip)
    }
    func enterReplay()->Bool {
        if replaying { return true }
        guard canReplay() else { message("Finish calibration before replay");return false }
        guard timeline != nil else { return false }
        replaying=true;modeChanged?(true);return true
    }
    func returnLive() {
        playing=false;replaying=false;frameGeneration+=1;frameWanted=false
        modeChanged?(false);message("Live");refreshControls()
    }
    @objc func startRecording() {
        guard !busy,activeID == nil else { return }
        connect { [weak self] ok in
            guard let self=self,ok else { return }
            self.commandRevision+=1;self.busy=true;self.refreshControls();self.message("Starting recording…")
            self.call("/api/start",body:["display_id":0]) { data,error in
                self.busy=false
                if let error=error { self.message(error);self.refreshControls();return }
                let row=data.flatMap { try? JSONSerialization.jsonObject(with:$0) as? [String:Any] }
                self.activeID=row?["id"] as? String;self.timeline=nil;self.recordingPaused=false
                self.returnLive();self.message("Recording 00:00 / 01:00");self.refreshControls()
            }
        }
    }
    @objc func togglePlay() {
        guard !busy else { return }
        if activeID != nil {
            commandRevision+=1;busy=true;refreshControls()
            call("/api/pause",body:["paused":!recordingPaused]) { [weak self] data,error in
                guard let self=self else { return };self.busy=false
                if let error=error { self.message(error) }
                else { self.recordingPaused.toggle() }
                self.refreshControls();self.pollStatus()
            };return
        }
        guard enterReplay() else { return }
        if playing { playing=false;seek(playhead) }
        else {
            if playhead >= (timeline?.duration_ms ?? 0) { playhead=0 }
            playing=true;lastTick=ProcessInfo.processInfo.systemUptime;frameWanted=true;requestFrame()
        }
        refreshControls()
    }
    @objc func stopAction() {
        guard !busy else { return }
        if activeID == nil { returnLive();return }
        commandRevision+=1;busy=true;refreshControls();message("Saving recording…")
        call("/api/stop",body:[:]) { [weak self] data,error in
            guard let self=self else { return };self.busy=false
            if let error=error { self.message(error);self.refreshControls();return }
            let row=data.flatMap { try? JSONSerialization.jsonObject(with:$0) as? [String:Any] }
            let id=self.activeID;self.activeID=nil;self.recordingPaused=false
            self.refreshControls()
            if let id=row?["id"] as? String ?? id { self.loadTimeline(id,show:false) }
        }
    }
    func seek(_ ms:Double) {
        guard activeID == nil,enterReplay() else { return }
        playing=false;playhead=max(0,min(timeline?.duration_ms ?? 0,ms));slider.doubleValue=playhead
        frameGeneration+=1;frameWanted=true;message("Seeking \(Self.time(playhead))")
        refreshControls();requestFrame()
    }
    @objc func scrub() { seek(slider.doubleValue) }
    @objc func stepBack() { step(-1) }
    @objc func stepForward() { step(1) }
    func step(_ direction:Int) {
        guard let times=timeline?.frames,!times.isEmpty else { return }
        let next=direction > 0 ? times.first { $0 > playhead+0.01 } : times.last { $0 < playhead-0.01 }
        seek(next ?? (direction > 0 ? times.last! : times.first!))
    }
    static func time(_ ms:Double)->String {
        String(format:"%02d:%02d.%03d",Int(ms)/60000,(Int(ms)/1000)%60,Int(ms)%1000)
    }
    func requestFrame() {
        guard replaying,frameWanted,!framePending,let timeline=timeline else { return }
        framePending=true;frameWanted=false
        let generation=frameGeneration
        call("/api/replay",body:["session_id":timeline.id,"t_ms":playhead]) { [weak self] data,error in
            guard let self=self else { return };self.framePending=false
            guard self.replaying,self.frameGeneration == generation else { self.requestFrame();return }
            if let error=error { self.playing=false;self.message(error);self.refreshControls();return }
            guard let data=data,let frame=try? JSONDecoder().decode(ReplayFrame.self,from:data) else {
                self.playing=false;self.message("Could not read recorded frame");self.refreshControls();return
            }
            let images=frame.images.compactMapValues { Data(base64Encoded:$0).flatMap(NSImage.init(data:)) }
            self.frameReady?(frame,images);self.slider.doubleValue=frame.t_ms
            self.message("\(self.playing ? "Replay" : "Paused") \(Self.time(frame.t_ms)) / \(Self.time(timeline.duration_ms))")
        }
    }
    func tick() {
        let now=ProcessInfo.processInfo.systemUptime
        if initialized,now-lastPoll>=1 { lastPoll=now;pollStatus() }
        if playing,replaying {
            playhead=min(timeline?.duration_ms ?? 0,playhead+(now-lastTick)*1000)
            frameWanted=true;requestFrame()
            if playhead >= (timeline?.duration_ms ?? 0) { playing=false;refreshControls() }
        }
        lastTick=now
    }
    func pollStatus() {
        guard initialized,!statusPending,!busy else { return }
        statusPending=true
        let revision=commandRevision
        call("/api/status") { [weak self] data,error in
            guard let self=self else { return };self.statusPending=false
            guard !self.busy,self.commandRevision == revision,error == nil,let data=data,let row=try? JSONSerialization.jsonObject(with:data) as? [String:Any] else { return }
            let old=self.activeID
            self.activeID=row["active"] as? String;self.recordingPaused=row["paused"] as? Bool ?? false
            if self.activeID != nil {
                if self.replaying { self.returnLive() }
                self.message("\(self.recordingPaused ? "Record paused" : "Recording") \(Self.time((row["elapsed_seconds"] as? Double ?? 0)*1000)) / 01:00")
            } else if old != nil,let id=row["last_finished"] as? String { self.loadTimeline(id,show:false) }
            self.refreshControls()
        }
    }
    func capture(_ cursors:[String:ReplayCursor], scene:[String:Double], at stamp:Double) {
        guard let id=activeID,!recordingPaused,!presentationPending,stamp-lastPresentation>=1.0/30 else { return }
        presentationPending=true;lastPresentation=stamp
        let points=cursors.mapValues { ["point":$0.point,"opacity":$0.opacity] as [String:Any] }
        call("/api/presentation",body:["session_id":id,"captured_at":stamp,"cursors":points,"scene":scene]) { [weak self] _,_ in self?.presentationPending=false }
    }
}

final class CalibrationApp: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuDelegate {
    enum PreviewAlignmentAction { case start, finish }
    let port: Int
    let hybrid: Bool
    let parentPID = getppid()
    let recording=DiagnosticRecordingController()
    var replaying:Bool { recording.replaying }
    var presentedCursors:[String:ReplayCursor]=[:]
    var liveSceneConfiguration:[String:Double]?
    // Calibration uses the same kind of desktop overlay as the gaze cursor.
    let window = DotPanel(contentRect: NSRect(x: 0, y: 0, width: 96, height: 140),
                          styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
    let surface = CalibrationView()
    let cursorReference = DotPanel(contentRect: NSRect(x: 0, y: 0, width: 96, height: 140),
                                  styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
    let cursorReferenceSurface = CalibrationView()

    let statusMenu = NSMenuItem(title: "Connecting to eye camera", action: nil, keyEquivalent: "")
    let calibrateMenu = NSMenuItem(title: "Restart calibration", action: nil, keyEquivalent: "")
    let cursorAlignMenu = NSMenuItem(title: "Learn at cursor", action: nil, keyEquivalent: "")
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
    let gazeEyes = NSPopUpButton()
    var gazeEyesPending = false
    let eyeSetupToggle = NSButton(title: "Camera setup ▾", target: nil, action: nil)
    let leftCameraChoice = NSPopUpButton(frame: .zero, pullsDown: false)
    let rightCameraChoice = NSPopUpButton(frame: .zero, pullsDown: false)
    let leftRotation = NSButton(checkboxWithTitle: "Rotate left 180°", target: nil, action: nil)
    let rightRotation = NSButton(checkboxWithTitle: "Rotate right 180°", target: nil, action: nil)
    let leftFixedSphere = NSButton(checkboxWithTitle: "Fixed eye sphere", target: nil, action: nil)
    let rightFixedSphere = NSButton(checkboxWithTitle: "Fixed eye sphere", target: nil, action: nil)
    let eyeSetupStatus = NSTextField(wrappingLabelWithString: "Both eyes track together. Assign a different camera to each eye. Left defaults to 180°.")
    let calibrationEyeStatus = NSTextField(wrappingLabelWithString: "")
    var eyeSetupPending = false
    var eyeCameraMenuOpen = false
    var deferredEyeSetup: EyeCamerasState?
    var eyeSetupSignature = ""
    let calibrationVoice = CalibrationVoiceGuide()
    let voiceGuidance = NSButton(checkboxWithTitle: "Spoken guidance", target: nil, action: nil)
    let previewAlignButton = NSButton(title: "Align with IR preview", target: nil, action: nil)
    var previewReferencePending = false
    var pendingPreviewAlignment: PreviewAlignmentAction?
    let diagnosticText = NSTextField(wrappingLabelWithString:
        "Waiting for eye camera. Drag around the eye to exclude a dark corner. Green: accepted pupil/ray · Cyan: modeled eye center · Magenta: seed · Red: rejected")
    let facePreview = CameraPreviewView()
    let secondHeadPreview = CameraPreviewView()
    let secondHeadPanel = NSStackView()
    var secondHeadWidthConstraint: NSLayoutConstraint?
    let secondHeadRate = NSTextField(labelWithString: "")
    let secondHeadChoice = NSPopUpButton(frame: .zero, pullsDown: false)
    let secondHeadLearn = NSButton(title: "Learn second view", target: nil, action: nil)
    let secondHeadMessage = NSTextField(wrappingLabelWithString: "")
    var headSetupPending = false
    var headSetupSignature = ""
    var headSetupError: String?
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
    var accuracyButton: NSButton { calibrationSteps.accuracyButton }
    let calibrationSteps = CalibrationStepsView()
    let dot = DotPanel(contentRect: NSRect(x: 0, y: 0, width: 16, height: 16),
                       styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
    var timer: Timer?
    var animationTimer: Timer?
    var motion = GazeMotion()
    var eyeMotions = ["left": GazeMotion(), "right": GazeMotion()]
    var eyeDots: [String: DotPanel] = [:]
    var eyeIdentities: [String: String] = [:]
    var readoutMotion = MeasurementChannels()
    private var readoutContext = ""
    var calibrationOrbit = CalibrationOrbit()
    var calibrationTravel = CalibrationTravel()
    var calibrationFeedback = CalibrationFeedback()
    var cursorReferenceFeedback = CalibrationFeedback()
    var pending = false
    var cursorLearningKeyDown = false
    var cursorLearningHotKey: EventHotKeyRef?
    var cursorLearningKeyHandler: EventHandlerRef?
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
        calibrationSteps.muteButton.target = self
        calibrationSteps.muteButton.action = #selector(toggleVoiceMute)
        calibrationSteps.actionButton.action = #selector(continueCalibration)
        calibrationSteps.manualButton.target = self
        calibrationSteps.manualButton.action = #selector(alignWithCursor)
        calibrationSteps.headButton.target = self
        calibrationSteps.headButton.action = #selector(practiceHeadMovement)
        accuracyButton.target = self; accuracyButton.action = #selector(checkAccuracy)
        previewAlignButton.target = self
        previewAlignButton.action = #selector(alignWithPreview)
        previewAlignButton.isHidden = true
        configureDiagnosticsLayout()
        dot.isOpaque = false
        dot.backgroundColor = .clear
        dot.hasShadow = false
        dot.ignoresMouseEvents = true
        dot.hidesOnDeactivate = false
        dot.level = .screenSaver
        dot.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        let combinedDot = DotView(frame: NSRect(x: 0, y: 0, width: 16, height: 16))
        dot.contentView = combinedDot
        for (side,color) in [("left",NSColor.systemPink),("right",NSColor.systemOrange)] {
            let panel = DotPanel(contentRect:NSRect(x:0,y:0,width:24,height:24),
                styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
            panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false
            panel.ignoresMouseEvents = true; panel.hidesOnDeactivate = false; panel.level = .screenSaver
            panel.collectionBehavior = [.canJoinAllSpaces,.fullScreenAuxiliary,.ignoresCycle]
            let view = DotView(frame:NSRect(origin:.zero,size:panel.frame.size));view.color = color;view.ring = true
            panel.contentView = view;eyeDots[side] = panel
        }
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
        let review = NSMenuItem(title:"Record & replay…",action:#selector(openRecordingReview),keyEquivalent:"")
        review.target = self; trayMenu.addItem(review)
        trayMenu.addItem(calibrateMenu)
        cursorAlignMenu.toolTip = "Turn learning on only while watching the stationary pointer. Move your head gently; stop before looking elsewhere."
        cursorAlignMenu.target = self
        cursorAlignMenu.action = #selector(alignWithCursor)
        trayMenu.addItem(cursorAlignMenu)
        headPracticeMenu.target = self
        headPracticeMenu.action = #selector(practiceHeadMovement)
        headPracticeMenu.isHidden = true
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
        defer {
            if replaying {
                for item in [calibrateMenu,cursorAlignMenu,headPracticeMenu,cancelMenu,blinkMenu] { item.isEnabled=false }
                for button in [calibrationSteps.actionButton,calibrationSteps.manualButton,calibrationSteps.headButton,accuracyButton] { button.isEnabled=false }
            }
        }
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
        calibrateMenu.title = lastState?.onboarding?.phase == "idle" ? "Start calibration" : "Restart calibration"
        cursorAlignMenu.isEnabled = fresh && !changing && hybrid && !["no_displays","preview","views_fit","views","waiting","fitting","head","screen","motion","verify","refine"].contains(lastState?.onboarding?.phase ?? "")
        let practicing = lastState?.onboarding?.phase != "motion" && lastState?.onboarding?.cursor_calibration?.active == true && lastState?.onboarding?.cursor_calibration?.stage == "geometry"
        let continuousHead = practicing && lastState?.onboarding?.geometry_calibration?.continuous == true
        headPracticeMenu.isHidden = !practicing
        headPracticeMenu.title = practicing ? (continuousHead ? "Finish head calibration" : "Stop head calibration") : "Calibrate head movement"
        headPracticeMenu.isEnabled = fresh && !changing && !active && hybrid && lastState?.calibrated == true &&
            (lastState?.onboarding?.cursor_calibration?.active != true || practicing)
        calibrationSteps.headButton.title = headPracticeMenu.title
        calibrationSteps.headButton.isEnabled = headPracticeMenu.isEnabled
        cursorAlignMenu.title = practicing ? headPracticeMenu.title : lastState?.onboarding?.phase != "motion" && lastState?.onboarding?.cursor_calibration?.active == true ? "Stop learning" : "Learn at cursor"
        calibrationSteps.actionButton.isEnabled = fresh && !changing && lastState?.onboarding != nil &&
            lastState?.onboarding?.phase != "no_displays"
        cursorAlignMenu.state = lastState?.onboarding?.cursor_calibration?.active == true ? .on : .off
        calibrationSteps.manualButton.isEnabled = cursorAlignMenu.isEnabled
        accuracyButton.isEnabled = fresh && !changing && cursorSession?.active != true &&
            ["complete", "verify"].contains(lastState?.onboarding?.phase ?? "")
        accuracyButton.title = lastState?.onboarding?.phase == "verify" ? "Stop accuracy check" : "Check Accuracy"
        let report = lastState?.onboarding?.accuracy_check
        if let report = report {
            let result = report.mean_error_points.map { String(format: "Mean %.0f pt · Worst %.0f pt", $0, report.worst_error_points ?? $0) } ?? "No measurements yet"
            accuracyButton.toolTip = "\(report.status.capitalized) · \(report.rows.filter { $0.samples > 0 }.count)/\(report.target_count) measured\n\(result)\nOn laptop: filled = measured, ring = pending, cross = missing. Orange = estimate.\nErrors in screen points."
        } else { accuracyButton.toolTip = "Check dots measure error without changing your calibration." }

        calibrateMenu.toolTip = nil
        clearEyeRegion.isHidden = active || changing || lastState?.eye_region == nil
        clearEyeRegion.isEnabled = !changing
        diagnosticMenu.isEnabled = true
        cancelMenu.isHidden = !active && lastState?.onboarding?.phase != "waiting"
        cancelMenu.isEnabled = !changing
        blinkMenu.isEnabled = fresh && !active && !changing
        var menuStatus: String
        if let error = localError {
            menuStatus = error
        } else {
            if !fresh { menuStatus = "Waiting for tracker" }
            else if lastState?.source == "video demo" { menuStatus = "Sample video · Calibration unavailable" }
            else if !ready { menuStatus = "Waiting for eye camera" }
            else if active {
                let progress = calibrationFeedback.progress
                menuStatus = lastState?.onboarding?.screen_path == "quick"
                    ? "Initial calibration · Target \(lastState?.onboarding?.screen_target_index ?? 2)/5"
                    : "Calibrating · \(Int(progress * 100))%"
            }
            else if let flow = lastState?.onboarding, flow.phase != "complete" {
                menuStatus = lastState?.cursor_message ?? flow.message
            }
            else if lastState?.calibration?.phase == "retry" {
                menuStatus = "Calibration needs retry"
            }
            else if lastState?.calibrated == true { menuStatus = "Calibration complete" }
            else { menuStatus = lastState?.cursor_message ?? "Eye camera connected" }
            if menuStatus.hasPrefix("Calibration incomplete") {
                menuStatus = "Calibration incomplete"
            }
        }
        fitMenuStatusToActions(menuStatus)
    }

    func fitMenuStatusToActions(_ fullStatus: String) {
        // Truncate BEFORE assigning NSMenuItem.title. AppKit can lay out an open
        // menu on each title mutation and retain the widest intermediate title.
        // Keep the complete message only in the tooltip.
        let attributes: [NSAttributedString.Key: Any] = [
            .font: statusItem?.menu?.font ?? NSFont.menuFont(ofSize: 0)
        ]
        func width(_ text: String) -> CGFloat {
            (text as NSString).size(withAttributes: attributes).width
        }
        let actions = [diagnosticMenu, calibrateMenu, cursorAlignMenu, headPracticeMenu, cancelMenu]
        let availableWidth = actions.filter { !$0.isHidden }.map { width($0.title) }.max() ?? 0
        guard width(fullStatus) > availableWidth else {
            statusMenu.title = fullStatus
            statusMenu.toolTip = nil
            return
        }
        var shortened = fullStatus
        while !shortened.isEmpty && width(shortened + "…") > availableWidth {
            shortened.removeLast()
        }
        statusMenu.title = shortened.trimmingCharacters(in: .whitespacesAndNewlines) + "…"
        statusMenu.toolTip = fullStatus
    }

    func request(_ path: String, body: [String: Any], completion: @escaping (String?) -> Void) {
        if replaying && path != "/recordings/open" { completion("Stop replay to change tracking");return }
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
        showDiagnostics()
        if let screen=calibrationScreen() { diagnosticWindow.setFrame(screen.visibleFrame,display:true) }
        request("/onboarding/start", body: ["preview_alignment":true]) { [weak self] error in
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
        if flow.cursor_calibration?.active == true && flow.phase != "motion" {
            alignWithCursor(); return
        }
        if flow.phase == "complete" {
            if ["previous_fit_kept", "partial"].contains(flow.guided_head_outcome ?? "") {
                changing = true; localError = nil
                request("/onboarding/head-retry", body: [:]) { [weak self] error in
                    self?.changing = false; self?.localError = error
                }
                updateMenu()
            } else { restartOnboarding() }
            return
        }
        if ["preview", "views_fit", "views", "waiting", "fitting", "head", "screen", "motion", "verify", "refine"].contains(flow.phase) {
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

    func registerCursorLearningHotKey() {
        guard cursorLearningHotKey == nil, cursorLearningKeyHandler == nil else { return }
        var eventTypes = [EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
                          EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased))]
        let status = InstallEventHandler(GetApplicationEventTarget(), { _, event, context in
            guard let context = context, let event = event else { return OSStatus(eventNotHandledErr) }
            let owner = Unmanaged<CalibrationApp>.fromOpaque(context).takeUnretainedValue()
            if GetEventKind(event) == UInt32(kEventHotKeyReleased) { owner.cursorLearningKeyDown = false; return noErr }
            guard !owner.cursorLearningKeyDown else { return noErr }
            owner.cursorLearningKeyDown = true
            // The shortcut toggles the same explicit learning mode, without
            // moving the pointer or asking the wearer to read another corner.
            if owner.cursorAlignMenu.isEnabled { owner.alignWithCursor() }
            return noErr
        }, 2, &eventTypes, Unmanaged.passUnretained(self).toOpaque(), &cursorLearningKeyHandler)
        guard status == noErr else { return }
        let result = RegisterEventHotKey(UInt32(kVK_ANSI_L), UInt32(controlKey | optionKey),
            EventHotKeyID(signature: 0x45594355, id: 1), GetApplicationEventTarget(), 0, &cursorLearningHotKey)
        let hint = result == noErr ? " Toggle without looking away: Control–Option–L." : " Keyboard shortcut unavailable; use this menu."
        cursorAlignMenu.toolTip = (cursorAlignMenu.toolTip ?? "") + hint
        if result != noErr, let handler = cursorLearningKeyHandler {
            RemoveEventHandler(handler); cursorLearningKeyHandler = nil
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
        guard state.onboarding?.phase != "motion", state.onboarding?.cursor_calibration?.active == true, !changing, !cursorSamplePending,
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

    func preparePreviewReference(_ flow: OnboardingState) {
        guard flow.phase == "preview", let step=flow.preview_alignment, step.target == nil,
              let side=step.eye, !previewReferencePending,
              let eye=lastState?.eye_cameras?.eyes[side], eye.measurement_valid == true,
              let pupil=eye.pupil_center, pupil.count == 2, pupil.allSatisfy({ $0.isFinite }),
              let screen=calibrationScreen() else { return }
        let image=side == "left" ? preview : secondaryEyePreview
        image.scrollToVisible(image.bounds)
        diagnosticWindow.contentView?.layoutSubtreeIfNeeded()
        let local=NSPoint(x:pupil[0]/640*image.bounds.width,y:(1-pupil[1]/480)*image.bounds.height)
        guard image.visibleRect.contains(local) else { return }
        let point=diagnosticWindow.convertPoint(toScreen:image.convert(local,to:nil))
        guard screen.frame.contains(point) else { return }
        let uv=[(point.x-screen.frame.minX)/screen.frame.width,(screen.frame.maxY-point.y)/screen.frame.height]
        previewReferencePending=true
        request("/onboarding/preview-target",body:["eye":side,"target":uv]) { [weak self] error in
            self?.previewReferencePending=false;self?.localError=error
        }
    }

    func renderOnboarding(_ flow: OnboardingState) {
        if flow.phase == "preview" {
            preparePreviewReference(flow)
            if flow.target == nil { window.orderOut(nil);return }
        }
        let showing = ["preview", "views_fit", "views", "fitting", "head", "screen", "motion", "verify", "refine"].contains(flow.phase)
        guard showing, let screen = NSScreen.screens.first(where: {
            ($0.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.stringValue == flow.display_id
        }) else {
            if active { restore() }
            return
        }
        active = true
        displayFrame = screen.frame
        hideCursor()
        if flow.phase == "fitting" && flow.eye_scan_enabled == true {
            calibrationTravel.reset(); calibrationOrbit.reset()
            surface.headCue = nil
            surface.freeEyeInstruction = "Look around slowly in circles\nKeep your head still; use a comfortable range\n\(Int(ceil(flow.remaining_seconds ?? 0)))s until the first dot"
            window.setContentSize(NSSize(width: 430, height: 112))
            placeCalibrationTarget(CGPoint(x: 0.5, y: 0.5))
            return
        }
        if surface.freeEyeInstruction != nil {
            surface.freeEyeInstruction = nil
            window.setContentSize(NSSize(width: 96, height: 140))
        }
        let key = flow.screen_path == "quick"
            ? "\(flow.calibration_session_id ?? "")|\(flow.display_id ?? "")|quick|\(flow.screen_path_started_at ?? 0)|\(flow.screen_target_index ?? 0)"
            : "\(flow.calibration_session_id ?? "")|\(flow.display_id ?? "")|\(flow.phase)|\(flow.target ?? [])"
        // Keep earned visual progress during rejection; only a new target or
        // calibration session starts a fresh ring. Sampling still validates each fixation.
        calibrationFeedback.update(key: key, progress: flow.progress,
                                   accepted: flow.sample_accepted ?? (lastState?.valid ?? false))
        surface.headCue = flow.phase == "motion" ? flow.cursor_calibration?.head_cue : ["head", "views"].contains(flow.phase) ? flow.head_cue : nil
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
        surface.freeEyeInstruction = nil
        window.setContentSize(NSSize(width: 96, height: 140))
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
    @objc func changeGazeEyes() {
        guard !gazeEyesPending else { return }
        gazeEyesPending = true; gazeEyes.isEnabled = false
        hideCursor()
        let mode = ["both", "left", "right"][max(0,min(2,gazeEyes.indexOfSelectedItem))]
        request("/gaze-eyes", body: ["mode":mode]) { [weak self] error in
            self?.gazeEyesPending = false; self?.localError = error
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
        case "idle": return "Ready to calibrate"
        case "paused": return "Calibration incomplete"
        case "cancelled": return "Calibration cancelled"
        case "preview", "views_fit", "views", "fitting", "head", "screen", "motion", "verify", "refine", "cursor": return "Calibrating"
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
        let eyeOutlineHelp = "White: detected iris. Blue: estimated eyeball projection, shown only with a supported fit. Pixel sizes can differ between cameras."
        preview.toolTip = eyeOutlineHelp
        secondaryEyePreview.toolTip = eyeOutlineHelp
        versionLabel.stringValue = buildVersion
        versionLabel.font = .monospacedDigitSystemFont(ofSize: 11, weight: .regular)
        versionLabel.textColor = .white
        versionLabel.alignment = .right
        versionLabel.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(versionLabel)
        let recordingControls=recording.view
        recordingControls.translatesAutoresizingMaskIntoConstraints=false
        root.addSubview(recordingControls)
        recording.ensureService = { [weak self] completion in
            self?.request("/recordings/open",body:[:],completion:completion)
        }
        recording.canReplay = { [weak self] in
            guard let self=self else { return false }
            return !self.active && self.lastState?.onboarding?.cursor_calibration?.active != true
        }
        recording.modeChanged = { [weak self] enabled in self?.setReplayMode(enabled) }
        recording.frameReady = { [weak self] frame,images in self?.renderReplay(frame,images:images) }
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
            cameras.bottomAnchor.constraint(equalTo:recordingControls.topAnchor),
            recordingControls.leadingAnchor.constraint(equalTo:cameras.leadingAnchor),
            recordingControls.trailingAnchor.constraint(equalTo:cameras.trailingAnchor),
            recordingControls.bottomAnchor.constraint(equalTo:root.bottomAnchor),
            recordingControls.heightAnchor.constraint(equalToConstant:86),
            versionLabel.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -12),
            versionLabel.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -6),
            versionLabel.heightAnchor.constraint(equalToConstant: 16),
            cameraWidthConstraint,
            cameras.widthAnchor.constraint(greaterThanOrEqualToConstant: 220),
            cameraDivider.leadingAnchor.constraint(equalTo: cameras.trailingAnchor),
            cameraDivider.topAnchor.constraint(equalTo: cameras.topAnchor),
            cameraDivider.bottomAnchor.constraint(equalTo:root.bottomAnchor),
            cameraDivider.widthAnchor.constraint(equalToConstant: 8),
            stack.leadingAnchor.constraint(equalTo: cameras.contentView.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: cameras.contentView.trailingAnchor),
            stack.topAnchor.constraint(equalTo: cameras.contentView.topAnchor),
            angles.leadingAnchor.constraint(equalTo: cameraDivider.trailingAnchor),
            angles.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            angles.topAnchor.constraint(equalTo: root.topAnchor),
            angles.bottomAnchor.constraint(equalTo: versionLabel.topAnchor,constant:-6)
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
            secondHeadPanel.orientation = .vertical
            secondHeadPanel.alignment = .leading
            secondHeadPanel.spacing = 6
            secondHeadPanel.translatesAutoresizingMaskIntoConstraints = false
            stack.addArrangedSubview(secondHeadPanel)
            secondHeadWidthConstraint = secondHeadPanel.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -24)
            for view in [NSTextField(labelWithString: "Second webcam · face"), secondHeadPreview, secondHeadRate] as [NSView] {
                view.translatesAutoresizingMaskIntoConstraints = false
                secondHeadPanel.addArrangedSubview(view)
                view.widthAnchor.constraint(equalTo: secondHeadPanel.widthAnchor).isActive = true
            }
            secondHeadPreview.heightAnchor.constraint(equalTo: secondHeadPreview.widthAnchor, multiplier: 0.75).isActive = true
            secondHeadRate.font = .monospacedDigitSystemFont(ofSize: 11, weight: .regular)
            secondHeadRate.lineBreakMode = .byTruncatingTail
            secondHeadRate.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
            setSecondHeadVisible(false)
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
        for (label, choice, rotation, fixedSphere) in [("Left camera", leftCameraChoice, leftRotation, leftFixedSphere),
                                           ("Right camera", rightCameraChoice, rightRotation, rightFixedSphere)] {
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
            fixedSphere.target = self; fixedSphere.action = #selector(changeFixedSphere(_:))
            fixedSphere.toolTip = "Hold the current eye center and radius. Clear to resume automatic adjustment. Pupil detection continues."
            addSetup(fixedSphere, height: 22)
        }
        if hybrid {
            addSetup(NSTextField(labelWithString: "Second face webcam"), height: 18)
            secondHeadChoice.addItem(withTitle: "Disabled")
            secondHeadChoice.target = self; secondHeadChoice.action = #selector(changeSecondHead)
            secondHeadChoice.menu?.delegate = self
            secondHeadChoice.cell?.lineBreakMode = .byTruncatingMiddle
            secondHeadChoice.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
            addSetup(secondHeadChoice, height: 26)
            secondHeadLearn.bezelStyle = .rounded
            secondHeadLearn.target = self; secondHeadLearn.action = #selector(learnSecondHead)
            addSetup(secondHeadLearn, height: 28)
            secondHeadMessage.font = .systemFont(ofSize: 11)
            secondHeadMessage.textColor = .secondaryLabelColor
            addSetup(secondHeadMessage, height: 112)
        }
        setVoiceGuidance(UserDefaults.standard.object(forKey: "spokenCalibrationGuidance") as? Bool ?? true, persist: false)
        voiceGuidance.target=self;voiceGuidance.action=#selector(toggleVoiceGuidance)
        addSetup(voiceGuidance,height:22)
        leftRotation.state = .on
        eyeSetupStatus.font = .systemFont(ofSize: 11)
        eyeSetupStatus.textColor = .secondaryLabelColor
        addSetup(eyeSetupStatus, height: 64)
        thresholdLabel.textColor = .secondaryLabelColor
        addSetup(thresholdLabel, height: 18)
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
        addSetup(thresholdRow, height: 24)
        calibrationEyeStatus.font = .systemFont(ofSize: 11)
        calibrationEyeStatus.textColor = .secondaryLabelColor
        add(calibrationEyeStatus, height: 44)
        // Reserve status space so live text never shifts the webcam below it.
        title("Cursor eyes")
        gazeEyes.addItems(withTitles: ["Both eyes", "Left eye only", "Right eye only"])
        gazeEyes.target = self; gazeEyes.action = #selector(changeGazeEyes)
        add(gazeEyes, height: 26)
        title("Tracking controls")
        add(diagnosticText, height: 20)
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
    func setSecondHeadVisible(_ visible: Bool) {
        secondHeadPanel.isHidden = !visible
        cameraStack?.setVisibilityPriority(visible ? .mustHold : .notVisible, for: secondHeadPanel)
        // Detaching removes constraints to the parent; restore the sidebar
        // width when the optional preview returns to the stack.
        secondHeadWidthConstraint?.isActive = visible
    }
    func renderSecondHead(_ state: SecondHeadState?) {
        guard !eyeCameraMenuOpen, !headSetupPending else { return }
        let busy = active || lastState?.onboarding?.cursor_calibration?.active == true
        secondHeadChoice.isEnabled = state != nil && !busy
        secondHeadLearn.isEnabled = state?.camera_id != nil && !busy
        setSecondHeadVisible(state?.camera_id != nil)
        secondHeadLearn.title = state?.collecting == true ? "Finish alignment" : "Learn second view"
        guard let state = state else { return }
        secondHeadMessage.stringValue = headSetupError ?? state.error ?? state.message
        if headSetupError == nil, state.camera?.connected == true, state.camera?.face_visible != true {
            secondHeadMessage.stringValue = "Face not visible. Aim this webcam at your whole face.\n" + state.message
        }
        secondHeadMessage.toolTip = secondHeadMessage.stringValue
        let mode = state.camera?.connected != true ? "Disconnected" :
            state.camera?.face_visible != true ? "Face not visible" :
            state.collecting ? "\(state.samples) paired frames" :
            state.assistance.weight > 0 ? "Assisting \(Int(state.assistance.weight * 100))%" :
            state.aligned ? "Primary only · \(state.assistance.reason.replacingOccurrences(of: "_", with: " "))" : "Needs alignment"
        secondHeadRate.stringValue = String(format: "%.0f FPS · ", state.camera?.fps ?? 0) + mode
        secondHeadRate.toolTip = state.camera?.error ?? secondHeadRate.stringValue
        if state.camera?.connected != true { secondHeadPreview.image = nil }
        let signature = state.devices.map { $0.id + $0.name }.joined(separator: "|") + (state.camera_id ?? "")
        if signature != headSetupSignature {
            headSetupSignature = signature
            secondHeadChoice.removeAllItems(); secondHeadChoice.addItem(withTitle: "Disabled")
            var options = state.devices
            if let selected = state.camera_id, !options.contains(where: { $0.id == selected }) {
                options.append(EyeCameraDevice(id: selected, name: "Disconnected camera"))
            }
            for (index, device) in options.enumerated() {
                let label = device.name == "USB Camera" && device.id.hasPrefix("0x") ? "USB · " + String(device.id.dropFirst(2).prefix(8)) : device.name
                    let name = label.count > 22 ? String(label.prefix(21)) + "…" : label
                let item = NSMenuItem(title: "\(index + 1) · \(name)", action: nil, keyEquivalent: "")
                item.representedObject = device.id
                item.toolTip = "\(device.name) [\(device.id)]"
                secondHeadChoice.menu?.addItem(item)
            }
            secondHeadChoice.selectItem(at: secondHeadChoice.itemArray.firstIndex {
                ($0.representedObject as? String) == state.camera_id
            } ?? 0)
            secondHeadChoice.toolTip = secondHeadChoice.selectedItem?.toolTip
        }
    }
    func sendSecondHead(_ body: [String: Any]) {
        guard !headSetupPending else { return }
        headSetupPending = true; headSetupError = nil
        hideCursor()
        secondHeadChoice.isEnabled = false; secondHeadLearn.isEnabled = false
        request("/head-camera", body: body) { [weak self] error in
            guard let self = self else { return }
            self.headSetupPending = false; self.headSetupError = error
            self.headSetupSignature = ""
        }
    }
    @objc func changeSecondHead() {
        sendSecondHead(["action": "select", "camera_id": secondHeadChoice.selectedItem?.representedObject ?? NSNull()])
    }
    @objc func learnSecondHead() {
        sendSecondHead(["action": lastState?.head_camera?.second_view?.collecting == true ? "finish" : "learn"])
    }
    func renderEyeSetup(_ rig: EyeCamerasState?) {
        // AppKit runs the polling timer inside menu tracking. Never mutate a
        // popup or its items until that interaction has finished.
        if eyeCameraMenuOpen { deferredEyeSetup = rig; return }
        let controls: [NSControl] = [leftCameraChoice, rightCameraChoice, leftRotation, rightRotation, leftFixedSphere, rightFixedSphere]
        controls.forEach { $0.isEnabled = rig != nil && !eyeSetupPending }
        guard let rig = rig else {
            trackingEyeTitle.stringValue = "Eye camera · Tracking"
            secondaryEyeStatus.stringValue = "Two-eye setup needs native USB mode"
            return
        }
        trackingEyeTitle.stringValue = "Left eye · \(rig.eyes["left"]?.rotation ?? 0)°"
        secondaryEyeTitle.stringValue = "Right eye · \(rig.eyes["right"]?.rotation ?? 0)°"
        for (side,label) in [("left",trackingEyeTitle),("right",secondaryEyeTitle)] {
            if let model=rig.eyes[side]?.eyeball_model_status {
                label.stringValue += model == "estimated" ? " · Model fitted" : " · Model pending"
                label.lineBreakMode = .byTruncatingTail
            }
        }
        diagnosticRate.stringValue = Self.eyeRate(rig.eyes["left"])
        secondaryEyeStatus.stringValue = Self.eyeRate(rig.eyes["right"])
        diagnosticRate.toolTip = rig.eyes["left"]?.error ?? diagnosticRate.stringValue
        secondaryEyeStatus.toolTip = rig.eyes["right"]?.error ?? secondaryEyeStatus.stringValue
        if rig.eyes["left"]?.connected != true { preview.image = nil }
        if rig.eyes["right"]?.connected != true { secondaryEyePreview.image = nil }
        calibrationEyeStatus.stringValue = "Both eyes are detected independently. Coloured beams follow their calibrated screen dots."
        if !gazeEyesPending {
            gazeEyes.selectItem(at: ["both","left","right"].firstIndex(of:lastState?.gaze_eye_mode ?? "both") ?? 0)
            gazeEyes.isEnabled = !active && lastState?.onboarding?.cursor_calibration?.active != true
        }
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
                    let label = device.name == "USB Camera" && device.id.hasPrefix("0x") ? "USB · " + String(device.id.dropFirst(2).prefix(8)) : device.name
                    let name = label.count > 22 ? String(label.prefix(21)) + "…" : label
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
        leftFixedSphere.state = rig.eyes["left"]?.fixed_eye_sphere == true ? .on : .off
        rightFixedSphere.state = rig.eyes["right"]?.fixed_eye_sphere == true ? .on : .off
        if let error = rig.error { eyeSetupStatus.stringValue = error }
    }
    @objc func toggleVoiceGuidance() {
        setVoiceGuidance(voiceGuidance.state == .on)
    }
    @objc func toggleVoiceMute() {
        setVoiceGuidance(!calibrationVoice.enabled)
    }
    func setVoiceGuidance(_ enabled: Bool, persist: Bool = true) {
        calibrationVoice.enabled = enabled
        voiceGuidance.state = enabled ? .on : .off
        let button = calibrationSteps.muteButton
        button.title = enabled ? "Mute" : "Unmute"
        button.image = NSImage(systemSymbolName: enabled ? "speaker.wave.2.fill" : "speaker.slash.fill",
                               accessibilityDescription: nil)
        button.setAccessibilityLabel(enabled ? "Mute spoken instructions" : "Unmute spoken instructions")
        button.toolTip = enabled ? "Mute spoken instructions" : "Unmute spoken instructions"
        if persist { UserDefaults.standard.set(enabled, forKey: "spokenCalibrationGuidance") }
        if !enabled { calibrationVoice.silence() }
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
    @objc func changeFixedSphere(_ sender: NSButton) {
        guard !eyeSetupPending else { return }
        eyeSetupPending = true
        let eye = sender === leftFixedSphere ? "left" : "right"
        let fixed = sender.state == .on
        request("/eye-sphere", body: ["eye": eye, "fixed_eye_sphere": fixed]) { [weak self] error in
            guard let self = self else { return }
            self.eyeSetupPending = false
            self.eyeSetupStatus.stringValue = error ?? "\(eye.capitalized) eye sphere \(fixed ? "fixed" : "adjusting automatically")."
        }
    }
    func refreshDiagnosticFrame() {
        guard !replaying,diagnosticWindow.isVisible else { return }
        if let rig = lastState?.eye_cameras {
            for (eye, view) in [("left", preview), ("right", secondaryEyePreview)] {
                if rig.eyes[eye]?.connected == true { fetchPreview("\(eye).jpg", into: view) }
                else { view.image = nil }
            }
        } else { fetchPreview("frame.jpg", into: preview) }
        if hybrid {
            fetchPreview("head.jpg", into: facePreview)
            if lastState?.head_camera?.second_view?.camera?.connected == true {
                fetchPreview("head-secondary.jpg", into: secondHeadPreview)
            } else { secondHeadPreview.image = nil }
        }
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
                if self?.generation == frameGeneration && self?.replaying == false { view?.image = image }
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
    @objc func openRecordingReview() {
        showDiagnostics();recording.connect()
    }
    func setReplayMode(_ enabled:Bool) {
        calibrationVoice.silence()
        func editable(_ view:NSView) {
            (view as? NSControl)?.isEnabled = !enabled
            for child in view.subviews { editable(child) }
        }
        editable(eyeSetupStack)
        for control in [thresholdSlider,gazeEyes,clearEyeRegion] as [NSControl] { control.isEnabled = !enabled }
        for slider in angleDebugger.sliders.values { slider.isEnabled = !enabled }
        if enabled { liveSceneConfiguration=angleDebugger.replayConfiguration }
        else {
            angleDebugger.replayTime=nil
            if let saved=liveSceneConfiguration { angleDebugger.applyReplayConfiguration(saved,cameraName:lastState?.head_camera?.name) }
            liveSceneConfiguration=nil
        }
        generation+=1;clicksSuppressedUntil=Date().addingTimeInterval(1)
        motion.reset();for side in ["left","right"] { eyeMotions[side]?.reset();eyeDots[side]?.orderOut(nil) }
        dot.orderOut(nil);window.orderOut(nil);cursorReference.orderOut(nil)
        preview.image=nil;secondaryEyePreview.image=nil;facePreview.image=nil;secondHeadPreview.image=nil
        angleDebugger.resetReplayMeasurements()
        if enabled {
            diagnosticWindow.title="EyeCursor · Eye camera diagnostics · Replay"
        } else {
            diagnosticWindow.title="EyeCursor · Eye camera diagnostics"
            if let state=lastState { render(state) };refreshDiagnosticFrame()
        }
        updateMenu()
    }
    func renderReplay(_ frame:ReplayFrame,images:[String:NSImage]) {
        guard replaying else { return }
        preview.image=images["left"];secondaryEyePreview.image=images["right"];facePreview.image=images["face"]
        secondHeadPreview.image=images["face_secondary"]
        setSecondHeadVisible(images["face_secondary"] != nil || frame.state?.head_camera?.second_view?.camera_id != nil)
        func stamp(_ side:String)->String {
            frame.camera_times[side].map { "Replay · \(DiagnosticRecordingController.time($0))" } ?? "No frame at this time"
        }
        secondHeadRate.stringValue=stamp("face_secondary")
        diagnosticRate.stringValue=stamp("left");secondaryEyeStatus.stringValue=stamp("right");webcamRate.stringValue=stamp("face")
        angleDebugger.resetReplayMeasurements()
        angleDebugger.replayTime=frame.t_ms/1000
        if let scene=frame.scene,!scene.isEmpty { angleDebugger.applyReplayConfiguration(scene,cameraName:frame.state?.head_camera?.name) }
        trackingEyeTitle.stringValue=frame.state?.eye_cameras?.eyes["left"].map { "Left eye · \($0.rotation)°" } ?? "Left eye · Replay"
        secondaryEyeTitle.stringValue=frame.state?.eye_cameras?.eyes["right"].map { "Right eye · \($0.rotation)°" } ?? "Right eye · Replay"
        if let state=frame.state {
            angleDebugger.update(state,at:frame.t_ms/1000)
            calibrationSteps.update(state.onboarding)
        }
        var eyes:[String:([Double],Double)]=[:]
        for side in ["left","right","combined"] {
            let panel=side == "combined" ? dot : eyeDots[side]
            guard let panel=panel else { continue }
            guard let sample=frame.cursors[side],sample.point.count == 2,sample.point.allSatisfy({$0.isFinite}),
                  sample.opacity>0,let primary=NSScreen.screens.first else { panel.orderOut(nil);continue }
            let point=NSPoint(x:sample.point[0],y:primary.frame.maxY-sample.point[1])
            // Recorded desktop coordinates are already fenced and eased. Do not
            // infer a new gaze, smooth again, or move the operating-system cursor.
            guard NSScreen.screens.contains(where:{$0.frame.contains(point)}) else { panel.orderOut(nil);continue }
            panel.alphaValue=sample.opacity
            panel.setFrameOrigin(NSPoint(x:point.x-panel.frame.width/2,y:point.y-panel.frame.height/2))
            panel.orderFrontRegardless()
            if side != "combined" { eyes[side]=(sample.point,sample.opacity) }
        }
        angleDebugger.followDisplayedEyes(eyes)
        angleDebugger.followDisplayedCursor(frame.cursors["combined"]?.point,opacity:frame.cursors["combined"]?.opacity ?? 0)
        angleDebugger.rebuild(at:frame.t_ms/1000)
        if frame.state == nil { diagnosticText.stringValue="No saved scene at this time" }
        updateMenu()
    }
    @objc func quitEyeCursor() { NSApp.terminate(nil) }
    func menuWillOpen(_ menu: NSMenu) {
        if menu === leftCameraChoice.menu || menu === rightCameraChoice.menu || menu === secondHeadChoice.menu {
            eyeCameraMenuOpen = true
            clicksSuppressedUntil = Date().addingTimeInterval(1)
            return
        }
        menuOpen = true; updateMenu()
    }
    func menuDidClose(_ menu: NSMenu) {
        if menu === leftCameraChoice.menu || menu === rightCameraChoice.menu || menu === secondHeadChoice.menu {
            eyeCameraMenuOpen = false
            // The selected item's action is dispatched after menuDidClose.
            DispatchQueue.main.async { [weak self] in
                guard let self = self else { return }
                if let rig = self.deferredEyeSetup, !self.eyeSetupPending { self.renderEyeSetup(rig) }
                self.deferredEyeSetup = nil
                self.renderSecondHead(self.lastState?.head_camera?.second_view)
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
            if replaying { recording.returnLive() }
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
        calibrationVoice.silence()
        quitting = true
        if let hotKey = cursorLearningHotKey { UnregisterEventHotKey(hotKey) }
        if let handler = cursorLearningKeyHandler { RemoveEventHandler(handler) }
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
            process.arguments = ["-u", script.path, "--port", String(port), "--native-host-pid", String(ProcessInfo.processInfo.processIdentifier)]
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
        angleDebugger.followDisplayedCursor(nil)
    }

    func loseCursorTracking() {
        if Date().timeIntervalSince(lastReply) > 0.6 {
            for side in ["left","right"] { eyeMotions[side]?.loseTracking(at:ProcessInfo.processInfo.systemUptime) }
        }
        motion.loseTracking(at: ProcessInfo.processInfo.systemUptime)
        animateCursor()
    }

    func animateCursor(at time: Double = ProcessInfo.processInfo.systemUptime) {
        guard !replaying else { return }
        presentedCursors=[:]
        defer { recording.capture(presentedCursors,scene:angleDebugger.replayConfiguration,at:time) }
        // Draw the scene after publishing this frame's displayed cursor point.
        defer { angleDebugger.animate(at:time) }
        let combinedSample = motion.sample(at:time)
        var displayedEyes: [String: ([Double],Double)] = [:]
        for side in ["left","right"] {
            let eyeSample = eyeMotions[side]?.sample(at:time)
            guard eyeSample != nil, let sample = eyeSample,
                  let center = desktopFence(sample,frames:NSScreen.screens.map { $0.frame }),
                  let primary = NSScreen.screens.first else { eyeDots[side]?.orderOut(nil); continue }
            let opacity = eyeMotions[side]?.opacity ?? 0
            displayedEyes[side] = ([Double(center.x),Double(primary.frame.maxY-center.y)],opacity)
            presentedCursors[side]=ReplayCursor(point:[Double(center.x),Double(primary.frame.maxY-center.y)],opacity:opacity)
            if angleDebugger.separateEyes.state == .on && !active && !eyeSetupPending && lastState?.calibrated == true && lastState?.desktop_cursor == true {
                eyeDots[side]?.alphaValue = opacity
                let radius = (eyeDots[side]?.frame.width ?? 18)/2
                eyeDots[side]?.setFrameOrigin(NSPoint(x:center.x-radius,y:center.y-radius))
                eyeDots[side]?.orderFrontRegardless()
            } else { eyeDots[side]?.orderOut(nil) }
        }
        angleDebugger.followDisplayedEyes(displayedEyes)
        var combinedPoint = combinedSample
        // Share the per-eye easing rather than applying a third, lagging path.
        // A live combined sample still governs loss/fade and calibration visibility.
        if combinedSample != nil, (lastState?.gaze_eye_mode ?? "both") == "both",
           ["binocular", "disagreement"].contains(lastState?.binocular_status ?? ""),
           let left = displayedEyes["left"], let right = displayedEyes["right"],
           let primary = NSScreen.screens.first {
            combinedPoint = NSPoint(x:(left.0[0]+right.0[0])/2,
                y:primary.frame.maxY-(left.0[1]+right.0[1])/2)
        }
        guard let sample = combinedPoint,
              let center = desktopFence(sample, frames: NSScreen.screens.map { $0.frame }) else {
            dot.orderOut(nil)
            angleDebugger.followDisplayedCursor(nil)
            return
        }
        if let primary = NSScreen.screens.first {
            angleDebugger.followDisplayedCursor([Double(center.x),Double(primary.frame.maxY-center.y)],opacity:motion.opacity)
            presentedCursors["combined"]=ReplayCursor(point:[Double(center.x),Double(primary.frame.maxY-center.y)],opacity:motion.opacity)
        }
        dot.alphaValue = motion.opacity
        dot.setFrameOrigin(NSPoint(x: center.x - 8, y: center.y - 8))
        if !dot.isVisible { dot.orderFrontRegardless() }
    }

    func animateCursorReference(mouse: NSPoint = NSEvent.mouseLocation) {
        guard !replaying else { return }
        guard Date().timeIntervalSince(lastReply) <= 0.6 else {
            cursorReference.orderOut(nil); return
        }
        guard lastState?.onboarding?.phase != "motion", let session = lastState?.onboarding?.cursor_calibration, session.active,
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
        let continuous = session.stage == "geometry" && lastState?.onboarding?.geometry_calibration?.continuous == true
        cursorReferenceSurface.collecting = continuous
        cursorReferenceSurface.completed = continuous ? lastState?.onboarding?.geometry_calibration?.applied == true : session.target_complete == true && !moved
        if continuous {
            cursorReferenceFeedback.reset()
        } else if moved {
            cursorReferenceFeedback.reset()
        } else {
            let key = "\(lastState?.onboarding?.calibration_session_id ?? "")|\(lastState?.onboarding?.display_id ?? "")|\(session.stage ?? "")|\(session.fixed_target ?? session.target_position ?? [])"
            cursorReferenceFeedback.update(key: key, progress: session.progress ?? 0,
                                           accepted: session.sample_accepted ?? (lastState?.valid == true))
        }
        cursorReferenceSurface.progress = cursorReferenceFeedback.progress
        cursorReferenceSurface.accepted = continuous ? session.sample_accepted == true : cursorReferenceFeedback.accepted
        cursorReference.setFrameOrigin(NSPoint(x: target.x - 48, y: target.y - 70))
        if !cursorReference.isVisible { cursorReference.orderFrontRegardless() }
    }

    func animateCalibration() {
        guard !replaying,active, Date().timeIntervalSince(lastReply) <= 0.6 else { return }
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
        if !replaying,Date().timeIntervalSince(lastReply) > 0.6 {
            calibrationVoice.silence(reset:false)
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
                guard let state = state else { if !self.replaying { self.loseCursorTracking() }; return }
                self.lastReply = Date()
                self.lastState = state
                if state.onboarding != nil && !self.displaysRegistered { self.registerDisplays() }
                if !self.replaying && !self.changing && self.generation == generation { self.render(state) }
                if !self.recording.initialized && !self.recording.connecting { self.recording.connect() }
                if !self.replaying { self.processPendingPreviewAlignment() }
            }
        }.resume()
    }

    func animateMeasurements() {
        guard !replaying,diagnosticWindow.isVisible, Date().timeIntervalSince(lastReply) <= 0.6,
              let state = lastState else { return }
        let time = ProcessInfo.processInfo.systemUptime
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
        guard !replaying else { return }
        calibrationVoice.update(state.onboarding)
        renderEyeSetup(state.eye_cameras)
        renderSecondHead(state.head_camera?.second_view)
        sampleSystemCursor(state)
        calibrationSteps.update(state.onboarding)
        let eyeTime = ProcessInfo.processInfo.systemUptime
        angleDebugger.update(state)
        for side in ["left","right"] {
            if let prediction = state.eye_predictions?[side],prediction.desktop.count == 2,
               prediction.desktop.allSatisfy({ $0.isFinite }),let primary = NSScreen.screens.first {
                if eyeIdentities[side] != prediction.identity { eyeMotions[side]?.reset();eyeIdentities[side] = prediction.identity }
                eyeMotions[side]?.updateTarget(NSPoint(x:prediction.desktop[0],y:primary.frame.maxY-prediction.desktop[1]),at:eyeTime)
            } else { eyeMotions[side]?.loseTracking(at:eyeTime) }
        }
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
                    let correction = state.onboarding?.head_correction_status == "empirical" ? "measured head correction active" : state.onboarding?.geometry_model != nil ? "head rotation and position model active" : state.onboarding?.head_mode == "steady" ? "steady-head mode; use fixed-dot head calibration" :
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
        guard !eyeSetupPending, !headSetupPending, !active, state.calibrated, state.desktop_cursor else { hideCursor(); return }
        guard (state.display_valid ?? state.valid), let point = state.desktop_gaze,
              point.count == 2, point.allSatisfy({ $0.isFinite }), let primary = NSScreen.screens.first else {
            loseCursorTracking(); return
        }
        let center = NSPoint(x: point[0], y: primary.frame.maxY - point[1])
        guard NSScreen.screens.contains(where: { $0.frame.contains(center) }) else { loseCursorTracking(); return }
        motion.updateTarget(center, at:time)
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
let port = standalone ? availableTrackerPort() : (Int(arguments[0]) ?? 0)
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
controller.registerCursorLearningHotKey()
if standalone {
    controller.showDiagnostics()
    controller.startTracker()
}
app.run()
