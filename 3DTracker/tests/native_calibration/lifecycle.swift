import SceneKit

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let controller = CalibrationApp(port: 1, hybrid: true)
let runtimeRoot = "/Users/test/Projects/EyeTracker"
precondition(CalibrationApp.trackerRoot(bundleURL: URL(fileURLWithPath: "/Applications/EyeCursor.app"),
                                       configuredPath: runtimeRoot).path == runtimeRoot,
             "An installed app must resolve its configured tracking runtime")
precondition(CalibrationApp.trackerRoot(bundleURL: URL(fileURLWithPath: runtimeRoot + "/.venv/EyeCursor.app"),
                                       configuredPath: nil).path == runtimeRoot,
             "Development bundles must retain the relative runtime fallback")
precondition((25...110).contains(controller.angleDebugger.value("distance")),
             "The saved or default screen distance must stay within its control range")
let neutralHead = [0.0, 0, 0, 0.5, 0.4, log(0.3)]
let headForward = SIMD3<Float>(0,0,-1)
for yaw in [-Double.pi/6, Double.pi/6] {
    var pose = neutralHead; pose[0] = yaw
    let facing = AngleGeometry.headRotation(pose,relativeTo: neutralHead).act(headForward)
    precondition(abs(facing.x + Float(sin(yaw))) < 0.00001 && abs(facing.z + Float(cos(yaw))) < 0.00001,
                 "Head yaw must preserve turn direction, not mirror it")
    let recentered = AngleGeometry.headRotation(pose,relativeTo: pose).act(headForward)
    precondition(simd_length(recentered-headForward) < 0.00001,
                 "Captured neutral pose must cancel the current head rotation")
}
// Non-commuting turns must compose in the documented MediaPipe Euler order.
let combinedPose = [0.31,-0.22,0.17,0.58,0.39,log(0.3)]
let referencePose = [-0.12,0.13,-0.08,0.48,0.42,log(0.3)]
let basis = simd_float3x3(columns: (SIMD3<Float>(-1,0,0),SIMD3<Float>(0,1,0),SIMD3<Float>(0,0,-1)))
func mpMatrix(_ p: [Double]) -> simd_float3x3 {
    let y=Float(p[0]), x=Float(p[1]), z=Float(p[2])
    let rx=simd_float3x3(columns: ([1,0,0],[0,cos(x),sin(x)],[0,-sin(x),cos(x)]))
    let ry=simd_float3x3(columns: ([cos(y),0,-sin(y)],[0,1,0],[sin(y),0,cos(y)]))
    let rz=simd_float3x3(columns: ([cos(z),sin(z),0],[-sin(z),cos(z),0],[0,0,1]))
    return rz * ry * rx
}
let composed = basis * mpMatrix(combinedPose) * mpMatrix(referencePose).transpose * basis.transpose
let rotation = simd_float3x3(AngleGeometry.headRotation(combinedPose,relativeTo:referencePose))
for axis in 0..<3 { precondition(simd_length(rotation[axis]-composed[axis]) < 0.00001) }
precondition(abs(simd_determinant(rotation)-1) < 0.00001)
let cameraOrigin = SIMD3<Float>(0,12,0)
func eyePoint(_ uv: SIMD2<Float>, _ depth: Float = 40, _ pitch: Float = 0) -> SIMD3<Float> {
    AngleGeometry.eyeMidpoint(imageUV:uv,depth:depth,verticalFOV:.pi/4,imageAspect:16/9,
                             cameraOrigin:cameraOrigin,cameraPitch:pitch)
}
precondition(simd_length(eyePoint([0.5,0.5])-[0,12,40]) < 0.0001)
precondition(eyePoint([0.6,0.5]).x < 0 && eyePoint([0.4,0.5]).x > 0,
             "An unmirrored webcam image has opposite horizontal direction to the wearer's screen")
precondition(eyePoint([0.5,0.4]).y > cameraOrigin.y)
let mountRotation = simd_quatf(angle:0.2,axis:SIMD3<Float>(1,0,0))
precondition(simd_length(eyePoint([0.6,0.4],40,0.2)-cameraOrigin-mountRotation.act(eyePoint([0.6,0.4])-cameraOrigin)) < 0.0001)
let sameTarget = SIMD3<Float>(8,-4,0)
for a in [eyePoint([0.5,0.5]),eyePoint([0.6,0.4],50)] {
    precondition(simd_distance(AngleGeometry.hit(a,AngleGeometry.unit(sameTarget-a))!,sameTarget) < 0.0001,
                 "Different captured origins looking at B must intersect the same screen target")
}
let origin = SIMD3<Float>(3,2,60)
let expected = AngleGeometry.unit(-origin)
precondition(simd_length(AngleGeometry.hit(origin,expected)!) < 0.001)
precondition(AngleGeometry.hit(origin,[1,0,0]) == nil)
precondition(AngleGeometry.hit(origin,[0,0,1]) == nil)
precondition(simd_length(AngleGeometry.alignment(expected,expected)) < 0.001)
precondition(abs(AngleGeometry.angle([0,0,-1],[1,0,0])-90) < 0.001)
precondition(simd_length(AngleGeometry.cameraRay(pupil: [320,240],center: [320,240])-[0,0,1]) < 0.001)
precondition(AngleGeometry.cameraRay(pupil: [320,240],center: [340,240]).x < 0)
precondition(simd_length(AngleGeometry.cameraRay(pupil: [350,230],center: [320,240])-[0.11167991,0.03722664,0.99304671]) < 0.00001)
precondition(simd_length(AngleGeometry.cameraRay(pupil: [180,150],center: [340,220])-[-0.69770269,0.25399191,0.66985003]) < 0.00001)
controller.applicationDidFinishLaunching(Notification(name: NSApplication.didFinishLaunchingNotification))
precondition(controller.angleDebugger.contentView.window === controller.diagnosticWindow,
             "The scene and camera previews must share the diagnostics window")
controller.showDiagnostics()
controller.diagnosticWindow.contentView!.layoutSubtreeIfNeeded()
precondition(controller.versionLabel.stringValue == controller.buildVersion)
precondition(controller.versionMenu.title == "EyeCursor \(controller.buildVersion)")
precondition(controller.statusItem!.menu!.items.contains(controller.versionMenu))
precondition(controller.headPracticeMenu.title == "Calibrate head movement")
let longMenuStatus = String(repeating: "Eye camera is temporarily unavailable. ", count: 5)
controller.localError = longMenuStatus
controller.updateMenu()
let menuFont = controller.statusItem!.menu!.font ?? NSFont.menuFont(ofSize: 0)
let menuTextWidth = { (title: String) in
    (title as NSString).size(withAttributes: [.font: menuFont]).width
}
precondition(menuTextWidth(controller.statusMenu.title) <= menuTextWidth(controller.headPracticeMenu.title),
             "Transient tracker messages must not widen the menu beyond its action labels")
precondition(controller.statusMenu.toolTip == longMenuStatus,
             "The complete tracker message must remain available on hover")
controller.localError = nil
controller.updateMenu()
precondition(controller.versionLabel.superview === controller.diagnosticWindow.contentView,
             "The version must stay outside both scrolling panels")
precondition(abs(controller.versionLabel.alignmentRect(forFrame: controller.versionLabel.frame).maxX - (controller.diagnosticWindow.contentView!.bounds.maxX - 12)) < 1)
precondition(abs(controller.versionLabel.frame.minY - 6) < 1,
             "The build version must remain pinned to the bottom-right")
precondition(controller.preview.window === controller.angleDebugger.contentView.window)
precondition(controller.preview.bounds.width <= 240 && controller.preview.bounds.width > 200,
             "IR preview must stay compact")
precondition(controller.angleDebugger.sceneView.bounds.width > 400,
             "The embedded scene must retain usable space")
let stepsFrame = controller.calibrationSteps.convert(controller.calibrationSteps.bounds,
                                                     to: controller.diagnosticWindow.contentView)
let sceneFrame = controller.angleDebugger.sceneView.convert(controller.angleDebugger.sceneView.bounds,
                                                           to: controller.diagnosticWindow.contentView)
precondition(stepsFrame.minX >= sceneFrame.maxX,
             "Calibration steps must stay inside the right sidebar")
precondition((controller.angleDebugger.sidebar.arrangedSubviews.first as? NSButton)?.title == "Reset laboratory",
             "Reset laboratory must be the first control in the right sidebar")
let longCameraName = String(repeating: "Very long USB camera name ", count: 12)
let rigFixture = EyeCamerasState(active_eye: "left", eyes: [
    "left": EyeCameraSlot(device_id: "left-usb", rotation: 180, connected: true, fps: 30, status: "Connected", error: nil),
    "right": EyeCameraSlot(device_id: "right-usb", rotation: 0, connected: false, fps: 0, status: "Disconnected", error: longCameraName)
], devices: [EyeCameraDevice(id: "left-usb", name: longCameraName)], error: nil)
controller.renderEyeSetup(rigFixture)
precondition(controller.leftRotation.state == .on && controller.rightRotation.state == .off)
precondition(controller.leftCameraChoice.selectedItem?.representedObject as? String == "left-usb")
precondition(controller.rightCameraChoice.selectedItem?.representedObject as? String == "right-usb",
             "Remember an unplugged eye without silently selecting the other device")
precondition(controller.leftCameraChoice.title.count < 40)
precondition(controller.leftCameraChoice.selectedItem!.toolTip!.contains(longCameraName))
precondition(controller.secondaryEyeStatus.stringValue == "Disconnected")
precondition(controller.trackingEyeTitle.stringValue.contains("180°"))
controller.diagnosticWindow.contentView!.layoutSubtreeIfNeeded()
precondition(!controller.eyeSetupStack.isHidden && controller.eyeSetupStack.superview != nil)
precondition(controller.preview.bounds.width <= 240, "Long device names must not stretch the sidebar")
controller.toggleEyeSetup()
controller.diagnosticWindow.contentView!.layoutSubtreeIfNeeded()
precondition(controller.eyeSetupStack.isHidden)
precondition(controller.secondaryEyePreview.bounds.width == controller.preview.bounds.width)
precondition(abs(controller.secondaryEyePreview.bounds.height - controller.secondaryEyePreview.bounds.width * 0.75) <= 0.5, "Eye preview bounds: \(controller.secondaryEyePreview.bounds), active: \(controller.preview.bounds)")
if let path = ProcessInfo.processInfo.environment["EYECURSOR_EYES_SNAPSHOT"] {
    let view = controller.diagnosticWindow.contentView!
    controller.diagnosticWindow.display()
    CATransaction.flush()
    let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds)!
    view.effectiveAppearance.performAsCurrentDrawingAppearance { view.cacheDisplay(in: view.bounds, to: bitmap) }
    try! bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
}
let arrangedCameras = controller.cameraStack!.arrangedSubviews
let firstVideo = arrangedCameras.firstIndex(of: controller.preview)!
let secondVideo = arrangedCameras.firstIndex(of: controller.secondaryEyePreview)!
precondition(firstVideo < secondVideo)
precondition(!arrangedCameras[(firstVideo+1)..<secondVideo].contains { $0 is NSButton || $0 is NSSlider || $0 is NSStackView },
             "Eye previews must be adjacent apart from their headings and status readouts")
precondition(arrangedCameras.firstIndex(of: controller.previewAlignButton)! > secondVideo)
precondition(arrangedCameras.firstIndex(of: controller.thresholdLabel)! > secondVideo)
precondition(!arrangedCameras.contains { $0 is NSSegmentedControl }, "Both eyes track without tabs")
precondition(arrangedCameras.firstIndex(of: controller.eyeSetupToggle)! > arrangedCameras.firstIndex(of: controller.facePreview)!,
             "All camera controls must follow all video feeds")
let firstFrame = controller.preview.convert(controller.preview.bounds, to: controller.cameraStack)
let secondFrame = controller.secondaryEyePreview.convert(controller.secondaryEyePreview.bounds, to: controller.cameraStack)
precondition(abs(firstFrame.midY - secondFrame.midY) - firstFrame.height < 60,
             "Keep the eye feeds close together")
// Real identical-model cameras differ by USB location, not their shared suffix.
let twinDevices = [EyeCameraDevice(id: "0x1100000c456366", name: "USB Camera"),
                   EyeCameraDevice(id: "0x1200000c456366", name: "USB Camera")]
let twins = EyeCamerasState(active_eye: "right", eyes: [
    "left": EyeCameraSlot(device_id: twinDevices[0].id, rotation: 180, connected: true, fps: 30, status: "Connected", error: nil),
    "right": EyeCameraSlot(device_id: twinDevices[1].id, rotation: 0, connected: true, fps: 30, status: "Connected", error: nil)
], devices: twinDevices, error: nil)
controller.renderEyeSetup(twins)
precondition(controller.leftCameraChoice.numberOfItems == 3 && controller.rightCameraChoice.numberOfItems == 3,
             "Identical cameras must remain separately selectable")
precondition(Set(controller.leftCameraChoice.itemTitles).count == 3)
precondition(controller.leftCameraChoice.selectedItem?.representedObject as? String == twinDevices[0].id)
precondition(controller.rightCameraChoice.selectedItem?.representedObject as? String == twinDevices[1].id)
precondition(controller.preview.selection == nil && controller.secondaryEyePreview.selection != nil,
             "Eye-area selection must follow the calibrated camera in the fixed left/right layout")
let openMenu = controller.leftCameraChoice.menu!
let itemsBefore = openMenu.items
controller.menuWillOpen(openMenu)
controller.renderEyeSetup(rigFixture)
precondition(openMenu.items == itemsBefore, "Polling must not rebuild an open camera menu")
precondition(controller.eyeCameraMenuOpen)
controller.menuDidClose(openMenu)
precondition(!controller.eyeCameraMenuOpen)
controller.deferredEyeSetup = nil
controller.renderEyeSetup(rigFixture)
let initialIR = controller.preview.convert(controller.preview.bounds, to: controller.diagnosticWindow.contentView)
let initialWebcam = controller.facePreview.convert(controller.facePreview.bounds, to: controller.diagnosticWindow.contentView)
controller.resizeCameraSidebar(to: 400)
precondition(controller.preview.bounds.width > initialIR.width + 100)
precondition(controller.facePreview.bounds.width > initialWebcam.width + 100)
precondition(abs(controller.preview.bounds.height / controller.preview.bounds.width - 0.75) < 0.001,
             "Dragging the camera divider must scale both videos with their aspect ratio")
controller.resizeCameraSidebar(to: 264)
let expandedSceneWidth = controller.angleDebugger.sceneView.bounds.width
controller.angleDebugger.toggleSidebar()
precondition(controller.angleDebugger.sidebarScroll.isHidden, "The controls must be hidden")
precondition(controller.angleDebugger.sidebarToggle.image != nil, "The expand icon must be present")
precondition(controller.angleDebugger.sidebarToggle.title.isEmpty, "The icon button must have no title")
precondition(controller.angleDebugger.sidebarToggle.bounds.width <= 36,
             "The icon button must stay compact (width: \(controller.angleDebugger.sidebarToggle.bounds.width))")
precondition(controller.angleDebugger.sidebarToggle.accessibilityLabel() == "Expand controls",
             "The expand action must have an accessible label")
precondition(controller.angleDebugger.sceneView.bounds.width > expandedSceneWidth + 300)
controller.angleDebugger.toggleSidebar()
precondition(!controller.angleDebugger.sidebarScroll.isHidden &&
             controller.angleDebugger.sidebarToggle.image != nil &&
             controller.angleDebugger.sidebarToggle.accessibilityLabel() == "Collapse controls")
precondition(abs(controller.angleDebugger.sceneView.bounds.width - expandedSceneWidth) < 1)
for message in ["Ready", String(repeating: "Waiting for synchronized eye and head samples. ", count: 12), ""] {
    controller.diagnosticText.stringValue = message
    controller.faceText.stringValue = message
    controller.clearEyeRegion.isHidden.toggle()
    controller.diagnosticWindow.contentView!.layoutSubtreeIfNeeded()
    precondition(controller.preview.convert(controller.preview.bounds, to: controller.diagnosticWindow.contentView) == initialIR)
    precondition(controller.facePreview.convert(controller.facePreview.bounds, to: controller.diagnosticWindow.contentView) == initialWebcam,
                 "Changing status text or eye-region controls must never move the videos")
}
precondition(controller.angleDebugger.sceneView.isPlaying && controller.surface.monochrome)
_ = controller.windowShouldClose(controller.diagnosticWindow)
precondition(!controller.angleDebugger.sceneView.isPlaying && !controller.surface.monochrome,
             "Closing diagnostics must stop rendering and restore the target style")
controller.showAngleDebugger()
precondition(controller.diagnosticWindow.isVisible && controller.angleDebugger.sceneView.isPlaying,
             "The angle shortcut must reopen the same combined window")
let screen = NSScreen.screens.first!
let laptopScreen = NSScreen.screens.first { candidate in
    guard let number = candidate.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else { return false }
    return CGDisplayIsBuiltin(number.uint32Value) != 0
} ?? screen
let id = (screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as! NSNumber).stringValue
func state(_ phase: String, valid: Bool = true, headPitch: Double = 0, cursor: Bool = false, tracked: Bool = true, irEye: Bool = false, circleStart: Double? = nil, fixedTarget: [Double]? = nil, savedTarget: [Double]? = nil, rawGaze: [Double]? = nil, references: Bool = false, webcamRays: [[Double]] = [[0,0,-1],[0,0,-1]], referenceCount: Int = 1, referenceSession: String = "test", referenceShift: Double = 0, geometric: Bool = false, accuracy: [String:Any]? = nil, eyeSide: String? = nil, calibrationProgress: Double = 0.9, accepted: Bool = true, targetIndex: Int = 2, calibrationTarget: [Double]? = nil, cursorProgress: Double = 0.4) -> TrackerState {
    let complete = phase == "complete"
    let captured: [[String:Any]] = references ? (0..<referenceCount).map { i in
        var head = neutralHead; head[3] += referenceShift + Double(i)*0.0001
        return ["id":i+1,"eye":[0.5,0.4],"head":head,"target":[0.8,0.2],"source":"cursor","predicted_before":[0.6,0.4]]
    } : []
    let payload: [String: Any] = [
        "eye_cameras": eyeSide != nil ? ["active_eye":eyeSide!,"eyes":[:],"devices":[]] as Any : NSNull(),
        "source": "test", "camera_connected": true, "valid": valid, "display_valid": valid && complete,
        "calibrated": complete, "desktop_cursor": complete,
        "desktop_gaze": complete && valid ? [laptopScreen.frame.midX, screen.frame.maxY - laptopScreen.frame.midY] as Any : NSNull(),
        "gaze": complete && valid ? [0.5,0.5] as Any : NSNull(),
        "unclamped_gaze":valid ? rawGaze as Any? ?? NSNull() : NSNull(),
        "head_camera": ["name":"Test webcam", "connected":true,"face_visible":tracked,"fps":30.0,
                        "features":[0.0,headPitch,0.0,0.5,0.4,log(0.3)],"eye_rays":webcamRays],
        "eye_direction": irEye && tracked ? ["vector":[0.1,0.2,0.97],"center":[320.0,240.0],"pupil":[325.0,245.0],
                                               "head_features":[0.0,headPitch,0.0,0.5,0.4,log(0.3)],"model_ready":true] as Any : NSNull(),
        "blink_click_enabled": false,
        "eye_model": ["phase": "collecting", "can_freeze": false, "message": "Test"],
        "onboarding": ["accuracy_check":accuracy as Any? ?? NSNull(),"phase": phase, "display_id": id, "display_index": 1, "display_count": 1,
                       "target": complete ? NSNull() as Any : (calibrationTarget ?? [0.08,0.92]), "progress": complete ? 1.0 : calibrationProgress,
                       "message": "Test", "elapsed": 10.0, "fast_path": false, "sample_accepted": accepted,
                       "stopped_stage": "head",
                       "screen_path": circleStart == nil ? NSNull() as Any : "quick",
                       "screen_path_started_at": circleStart as Any? ?? NSNull(), "screen_target_index":targetIndex,
                       "screen_fit_status": "Eye and target positions disagree; refining fit",
                       "calibration_rays":captured,"calibration_session_id":referenceSession,
                       "geometry_calibration":geometric ? ["phase":"validate","message":"Checking fresh measurements","remaining_seconds":4.0,"applied":false] as Any : NSNull(),
                       "geometry_model":geometric ? ["depth_screen_widths":1.4,"reference_log_face_width":log(0.3),"camera_aspect":16.0/9.0,"eye_separation_screen_widths":6.4/30.2] as Any : NSNull(),
                       "cursor_calibration": ["active":cursor,"positions":1,"ready":true,"message":"Live alignment",
                                              "stage":geometric ? "geometry" : "positions","remaining_seconds":4.0,"head_cue":NSNull(),"progress":cursorProgress,"live_preview":true,
                                              "fixed_target":fixedTarget as Any? ?? NSNull(),
                                              "sample_accepted":valid && accepted,"target_complete":savedTarget != nil,
                                              "target_position":savedTarget as Any? ?? NSNull()]]
    ]
    return try! JSONDecoder().decode(TrackerState.self, from: JSONSerialization.data(withJSONObject: payload))
}
func deliver(_ state: TrackerState) {
    controller.lastReply = Date(); controller.lastState = state; controller.render(state)
}
let eyeOriginScene = AngleDebugger()
eyeOriginScene.update(state("complete", eyeSide: "left"), at: 10)
let leftOrigin = eyeOriginScene.referenceEyeOrigin(neutralHead)
eyeOriginScene.update(state("complete", eyeSide: "right"), at: 11)
let rightOrigin = eyeOriginScene.referenceEyeOrigin(neutralHead)
precondition(abs(rightOrigin.x - leftOrigin.x - eyeOriginScene.eyeSeparation()) < 0.0001,
             "The selected tracking eye must also select the anatomical origin in the scene")
// Webcam predictions must depend on each iris, never the selected target.
let webcamPreview = AngleDebugger()
webcamPreview.update(state("complete", webcamRays: []), at: 10)
webcamPreview.rebuild(at: 10)
precondition(webcamPreview.geometry.childNode(withName: "webcam-eye-0", recursively: true) == nil,
             "No webcam eye measurement must not create a target-directed guide")
let independentRays: [[Double]] = [[0.9,0.1,-1],[-0.2,-0.1,-1]]
webcamPreview.update(state("complete", webcamRays: independentRays), at: 11)
webcamPreview.rebuild(at: 11)
let initialWebcamHits = (0..<2).map { webcamPreview.geometry.childNode(withName: "webcam-screen-hit-\($0)", recursively: true)!.simdPosition }
for i in 0..<2 {
    let beam = webcamPreview.geometry.childNode(withName: "webcam-eye-\(i)", recursively: true)!
    let actual = beam.simdOrientation.act(SIMD3<Float>(0,1,0))
    precondition(simd_distance(actual, AngleGeometry.unit(SIMD3<Float>(independentRays[i].map(Float.init)))) < 0.00001)
    precondition(abs(initialWebcamHits[i].z) < 0.0001)
}
precondition(abs(initialWebcamHits[0].x) > webcamPreview.value("width")/2,
             "Off-screen webcam predictions must not be clamped to the screen")
webcamPreview.sliders["tx"]!.doubleValue = 90
webcamPreview.sliders["ty"]!.doubleValue = 10
webcamPreview.rebuild(at: 11.1)
for i in 0..<2 {
    precondition(webcamPreview.geometry.childNode(withName: "webcam-screen-hit-\(i)", recursively: true)!.simdPosition == initialWebcamHits[i],
                 "Moving the target must not move webcam predictions")
}
webcamPreview.update(state("complete", webcamRays: [[-0.5,0.2,-1],independentRays[1]]), at: 12)
webcamPreview.rebuild(at: 12)
precondition(webcamPreview.geometry.childNode(withName: "webcam-screen-hit-0", recursively: true)!.simdPosition != initialWebcamHits[0])
precondition(webcamPreview.geometry.childNode(withName: "webcam-screen-hit-1", recursively: true)!.simdPosition == initialWebcamHits[1],
             "Changing one iris must leave the other eye prediction unchanged")
// Hold the rendered pose, including a partially smoothed movement, through
// lost detections, expired measurements, and a failed tracker poll.
let heldPreview = AngleDebugger()
precondition(heldPreview.geometry.childNode(withName: "tracked-head", recursively: true) == nil,
             "Before the first detection there must be no simulated head")
heldPreview.update(state("complete", headPitch: 0.4, irEye: true), at: 100)
heldPreview.rebuild(at: 100)
heldPreview.update(state("complete", headPitch: -0.4, irEye: true), at: 100.1)
heldPreview.rebuild(at: 100.15)
let heldEye = heldPreview.lastEye
let heldMetrics = heldPreview.metrics.stringValue
let angularValueStart = (heldMetrics as NSString).range(of: ": ").upperBound
precondition(heldPreview.metrics.attributedStringValue.attribute(.foregroundColor, at: angularValueStart, effectiveRange: nil) as? NSColor == .white)
let heldNodes = ["tracked-head", "webcam-eye-0", "webcam-eye-1", "ir-direction"]
let heldTransforms = heldNodes.map { heldPreview.geometry.childNode(withName: $0, recursively: true)!.simdTransform }
func assertHeldPose() {
    precondition(heldPreview.lastEye == heldEye, "Tracking loss must hold the last rendered eye position")
    for (index, name) in heldNodes.enumerated() {
        precondition(heldPreview.geometry.childNode(withName: name, recursively: true)!.simdTransform == heldTransforms[index],
                     "Tracking loss must preserve head orientation and eye directions")
    }
}
heldPreview.update(state("complete", valid: false, tracked: false), at: 100.16)
heldPreview.rebuild(at: 100.16)
assertHeldPose()
precondition(heldPreview.metrics.stringValue == heldMetrics, "Missing measurements must retain the last displayed values")
var metricOffset = 0
for row in heldMetrics.components(separatedBy: "\n") {
    let colon = (row as NSString).range(of: ":")
    for position in metricOffset...(metricOffset + colon.location) {
        precondition(heldPreview.metrics.attributedStringValue.attribute(.foregroundColor, at: position, effectiveRange: nil) as? NSColor == .white,
                     "Labels and colons must remain white during tracking loss")
    }
    precondition(heldPreview.metrics.attributedStringValue.attribute(.foregroundColor, at: metricOffset + colon.upperBound + 1, effectiveRange: nil) as? NSColor == .gray,
                 "Only held measurement values must turn gray")
    metricOffset += (row as NSString).length + 1
}
heldPreview.rebuild(at: 102)
assertHeldPose()
precondition(heldPreview.geometry.childNode(withName: "calibrated-screen-gaze", recursively: true) == nil)
heldPreview.invalidate()
heldPreview.rebuild(at: 103)
assertHeldPose()
precondition(heldPreview.metrics.stringValue == heldMetrics)
precondition(heldPreview.alignmentOffset == nil, "Held observations must not be reported as live alignment")
heldPreview.update(state("complete", headPitch: 0.7, irEye: true), at: 104)
heldPreview.rebuild(at: 104)
precondition(heldPreview.geometry.childNode(withName: "tracked-head", recursively: true)!.simdTransform != heldTransforms[0],
             "Fresh tracking must resume head rotation around the observed eye midpoint")
precondition(heldPreview.metrics.attributedStringValue.attribute(.foregroundColor, at: angularValueStart, effectiveRange: nil) as? NSColor == .white,
             "Recovered measurements must regain their normal color")
let recoveredMetrics = heldPreview.metrics.stringValue
heldPreview.update(state("complete", headPitch: 0.7), at: 104.1)
heldPreview.rebuild(at: 104.1)
precondition(heldPreview.metrics.stringValue == recoveredMetrics)
let rightEyeRange = (recoveredMetrics as NSString).range(of: "Right eye: ")
precondition(heldPreview.metrics.attributedStringValue.attribute(.foregroundColor, at: rightEyeRange.upperBound, effectiveRange: nil) as? NSColor == .white,
             "Head measurements remain live during an IR-only dropout")
precondition(heldPreview.metrics.attributedStringValue.attribute(.foregroundColor, at: angularValueStart, effectiveRange: nil) as? NSColor == .gray)
// Expiry without an explicit missing-detection packet must also hold geometry.
let recoveredEye = heldPreview.lastEye
heldPreview.rebuild(at: 105)
precondition(heldPreview.lastEye == recoveredEye)
for pitch in [-Double.pi/6, Double.pi/6] {
    controller.angleDebugger.invalidate()
    deliver(state("screen", headPitch: pitch))
    for eye in 0..<2 {
        let beam = controller.angleDebugger.geometry.childNode(withName: "webcam-eye-\(eye)", recursively: true)!
        let direction = beam.simdOrientation.act(SIMD3<Float>(0,1,0))
        precondition(abs(direction.y + Float(sin(pitch))) < 0.00001,
                     "Webcam eye directions must rotate with the measured head pitch")
    }
    var pose = neutralHead; pose[1] = pitch
    precondition(simd_length(AngleGeometry.headRotation(pose,relativeTo: pose).act(headForward)-headForward) < 0.00001,
                 "Neutral capture must also cancel pitch")
}
deliver(state("screen"))
precondition(controller.calibrationSteps.actionButton.title == "Stop calibration")
precondition(!controller.calibrationSteps.manualButton.isHidden && controller.calibrationSteps.manualButton.isEnabled)
precondition(controller.cursorAlignMenu.isEnabled,
             "Manual calibration must be available even while guided calibration is running")
precondition(controller.calibrationSteps.manualButton.action == #selector(CalibrationApp.alignWithCursor))
controller.calibrationSteps.layoutSubtreeIfNeeded()
precondition(controller.calibrationSteps.manualButton.frame.maxY <= controller.calibrationSteps.actionButton.frame.minY)
if let path = ProcessInfo.processInfo.environment["EYECURSOR_MANUAL_SNAPSHOT"] {
    let view=controller.calibrationSteps
    view.scrollToVisible(view.bounds)
    controller.diagnosticWindow.display()
    CATransaction.flush()
    RunLoop.current.run(until:Date(timeIntervalSinceNow:0.15))
    let bitmap=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
    view.effectiveAppearance.performAsCurrentDrawingAppearance { view.cacheDisplay(in:view.bounds,to:bitmap) }
    try! bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:path))
}

precondition(controller.calibrationSteps.rows.filter { !$0.isHidden }.count == 3)
precondition(controller.calibrationSteps.rows[0].stringValue.hasPrefix("1. Look at center"))
precondition(controller.calibrationSteps.actionButton.isEnabled)
let pathStart = ProcessInfo.processInfo.systemUptime - 0.15
let circleState = state("screen", circleStart: pathStart)
deliver(circleState)
precondition(controller.window.isVisible && controller.active)
precondition(controller.calibrationSteps.rows[1].stringValue.contains("four dots"))
precondition(controller.calibrationSteps.countdown.stringValue.contains("available"))
precondition(controller.calibrationSteps.countdown.stringValue.contains("samples"))
let circleOrigin = controller.window.frame.origin
RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.04))
controller.animateCalibration()
precondition(controller.window.frame.origin != circleOrigin, "Circle must animate between tracker replies")
precondition(controller.surface.progress == 0.9, "Moving target must retain collected progress")
deliver(state("screen", circleStart:pathStart, calibrationProgress:0.1, accepted:false))
precondition(controller.surface.progress == 0.9 && !controller.surface.accepted,
             "A rejected quick-calibration fixation must pause rather than rewind the ring")
deliver(state("screen", circleStart:pathStart, calibrationProgress:0.98, accepted:false))
precondition(controller.surface.progress == 0.9, "Rejected samples cannot grow the ring")
deliver(state("screen", circleStart:pathStart, calibrationProgress:0.95))
precondition(controller.surface.progress == 0.95)
deliver(state("screen", circleStart:pathStart, calibrationProgress:0.1, targetIndex:3))
precondition(controller.surface.progress == 0.1, "A genuinely new dot starts its own progress")
deliver(state("screen", circleStart:pathStart, referenceSession:"new-run", calibrationProgress:0.05, targetIndex:3))
precondition(controller.surface.progress == 0.05, "An explicit new calibration session starts fresh")
deliver(state("verify", calibrationProgress:0.7))
deliver(state("verify", calibrationProgress:0.0, accepted:false))
precondition(controller.surface.progress == 0.7 && !controller.surface.accepted)
precondition(controller.statusMenu.toolTip?.contains("70%") == true || controller.statusMenu.title.contains("70%"),
             "The menu percentage must agree with the paused visual progress")
deliver(state("verify", calibrationProgress:0.2, calibrationTarget:[0.75,0.25]))
precondition(controller.surface.progress == 0.2)

deliver(state("paused"))
precondition(controller.calibrationSteps.actionButton.title == "Retry step 1")
precondition(!controller.calibrationSteps.rows[0].stringValue.contains("✓"))
precondition(!controller.calibrationSteps.rows[1].stringValue.contains("✓"))
precondition(!controller.calibrationSteps.rows[2].stringValue.contains("✓"))
deliver(state("screen"))
controller.angleDebugger.invalidate()
controller.angleDebugger.rebuild()
precondition(controller.angleDebugger.alignmentOffset == nil, "Missing live data cannot display fabricated alignment")
precondition(controller.active)
controller.lastReply = Date(timeIntervalSinceNow: -1)
controller.refresh()
precondition(!controller.calibrationSteps.actionButton.isEnabled, "Stale state must not allow retry")
precondition(!controller.changing, "A delayed poll must not POST cancellation")
precondition(controller.active, "A delayed poll must not discard calibration UI state")
deliver(state("complete"))
precondition(controller.diagnosticText.stringValue == "Calibration complete",
             "Completed IR status must not include changing gaze or pupil details")
precondition(controller.calibrationSteps.actionButton.title == "Align with system cursor")
precondition(controller.angleDebugger.geometry.childNode(withName: "calibrated-screen-gaze", recursively: true) != nil)
precondition(controller.angleDebugger.geometry.childNode(withName: "webcam-eye-0", recursively: true) != nil)
precondition(controller.angleDebugger.geometry.childNode(withName: "webcam-eye-1", recursively: true) != nil)
precondition(!controller.active && controller.dot.isVisible, "Completed calibration must show the desktop cursor")
controller.lastReply = Date(timeIntervalSinceNow: -1)
controller.refresh()
precondition(controller.dot.isVisible && !controller.changing, "Stale cursor starts fading without changing the fit")
deliver(state("complete"))
precondition(controller.dot.isVisible, "Fresh gaze must restore the circle after a poll gap")
deliver(state("complete",valid:false))
precondition(controller.angleDebugger.geometry.childNode(withName: "calibrated-screen-gaze", recursively: true) == nil)
precondition(controller.dot.isVisible, "Missing gaze must start fading the presentation")
let lossTime = ProcessInfo.processInfo.systemUptime
controller.animateCursor(at: lossTime + 0.75)
precondition(controller.dot.isVisible && controller.dot.alphaValue > 0 && controller.dot.alphaValue < 0.51)
controller.animateCursor(at: lossTime + 1.51)
precondition(!controller.dot.isVisible, "The panel must hide after its fade completes")
controller.hideCursor() // Restore the real clock after the deterministic future ticks.
deliver(state("complete", cursor:true))
precondition(controller.calibrationSteps.manualButton.isHidden)
precondition(controller.calibrationSteps.rows.filter { !$0.isHidden }.count == 4,
             "Cursor alignment must retain its own four instructions")
let mouseTarget = NSPoint(x: screen.frame.minX + screen.frame.width * 0.2,
                          y: screen.frame.minY + screen.frame.height * 0.2)
controller.animateCursorReference(mouse:mouseTarget)
precondition(controller.cursorReference.isVisible && controller.cursorReference.ignoresMouseEvents)
precondition(controller.cursorReference.frame.midX == mouseTarget.x && controller.cursorReference.frame.midY == mouseTarget.y,
             "Alignment reference must sit exactly on the system cursor")
precondition(controller.cursorReferenceSurface.headCue == nil)
precondition(controller.cursorReferenceSurface.progress == 0.4)
deliver(state("complete", cursor:true, accepted:false, cursorProgress:0.1))
controller.animateCursorReference(mouse:mouseTarget)
precondition(controller.cursorReferenceSurface.progress == 0.4 && !controller.cursorReferenceSurface.accepted,
             "Manual alignment must pause on a rejected sample too")
deliver(state("complete", cursor:true, cursorProgress:0.6))
controller.animateCursorReference(mouse:mouseTarget)
precondition(controller.cursorReferenceSurface.progress == 0.6)

precondition(controller.dot.frame.midX != mouseTarget.x, "Measured gaze must not be replaced with the mouse target")
controller.lastReply = Date(timeIntervalSinceNow:-1)
controller.animateCursorReference(mouse:mouseTarget)
precondition(!controller.cursorReference.isVisible, "Stale alignment must hide its reference ring")
deliver(state("complete", cursor:true, fixedTarget:[0.2,0.3]))
precondition(controller.calibrationSteps.heading.stringValue == "IR preview alignment")
precondition(controller.previewAlignButton.title == "Finish preview alignment" && controller.previewAlignButton.isEnabled)
controller.animateCursorReference(mouse:mouseTarget)
let previewTarget = NSPoint(x: screen.frame.minX + screen.frame.width * 0.2,
                            y: screen.frame.maxY - screen.frame.height * 0.3)
precondition(abs(controller.cursorReference.frame.midX-previewTarget.x) < 1 && abs(controller.cursorReference.frame.midY-previewTarget.y) < 1)
controller.animateCursorReference(mouse:NSPoint(x:0,y:0))
precondition(abs(controller.cursorReference.frame.midY-previewTarget.y) < 1,
             "Preview marker must stay fixed when the mouse or pupil moves")
precondition(controller.cursorReferenceSurface.hollow, "Keep the pupil visible inside the preview marker")
deliver(state("complete"))
controller.animateCursorReference()
precondition(!controller.cursorReference.isVisible, "Finishing preview alignment must hide its reference")
deliver(state("complete", valid:false, cursor:true, savedTarget:[0.2,0.8]))
precondition(controller.previewAlignButton.isEnabled,
             "A temporary invalid eye sample must not disable preview alignment")
controller.alignWithPreview()
precondition(controller.pendingPreviewAlignment == .start &&
             controller.previewAlignButton.title.contains("queued"),
             "A click during a tracking gap must wait for the next usable sample")
controller.processPendingPreviewAlignment()
precondition(controller.pendingPreviewAlignment == .start,
             "An invalid sample must not consume the queued click")
controller.alignWithPreview()
precondition(controller.pendingPreviewAlignment == nil,
             "A second click must cancel the queued action")
controller.animateCursorReference(mouse:mouseTarget)
precondition(controller.cursorReferenceSurface.completed,
             "Saved alignment must keep its checkmark through tracking loss")
precondition(!controller.cursorReferenceSurface.accepted,
             "Saved status must not invent a fresh accepted eye sample")
controller.animateCursorReference(mouse:NSPoint(x:mouseTarget.x+4,y:mouseTarget.y))
precondition(controller.cursorReferenceSurface.completed)
controller.animateCursorReference(mouse:NSPoint(x:mouseTarget.x+6,y:mouseTarget.y))
precondition(!controller.cursorReferenceSurface.completed && controller.cursorReferenceSurface.progress == 0,
             "Leaving the 10 px diameter must immediately reset the marker before the next server reply")
deliver(state("complete",cursor:true,fixedTarget:[0.5,0.5],geometric:true))
controller.animateCursorReference(mouse:NSPoint(x:0,y:0))
precondition(controller.calibrationSteps.heading.stringValue == "Fixed-target head calibration")
precondition(controller.calibrationSteps.actionButton.title == "Stop head calibration")
precondition(controller.headPracticeMenu.title == "Stop head calibration")
precondition(controller.previewAlignButton.isEnabled,
             "Other calibration modes must not make the preview button flicker")
precondition(controller.calibrationSteps.countdown.stringValue.contains("Checking"))
precondition(abs(controller.cursorReference.frame.midX-screen.frame.midX)<1 && abs(controller.cursorReference.frame.midY-screen.frame.midY)<1,
             "The known target must remain at screen center independently of mouse movement")
precondition(!controller.cursorReferenceSurface.hollow)
let physicalOrigin = controller.angleDebugger.referenceEyeOrigin(neutralHead)
precondition(abs(physicalOrigin.z-controller.angleDebugger.value("width")*1.4)<0.001,
             "The scene must use the same calibrated depth as the geometric cursor map")
controller.timer?.invalidate(); controller.animationTimer?.invalidate(); controller.diagnosticTimer?.invalidate()
let evidence = AngleDebugger()
evidence.update(state("complete", irEye:true, rawGaze:[1.4,-0.2], references:true),at:200)
evidence.rebuild(at:200)
evidence.update(state("complete", irEye:true, rawGaze:[1.4,-0.2], references:true),at:200.4)
evidence.rebuild(at:200.4)
let savedBatch = evidence.geometry.childNode(withName:"saved-reference-rays",recursively:true)!
precondition(savedBatch.geometry!.elements[0].primitiveCount == 1)
precondition(savedBatch.geometry!.materials.allSatisfy {
    $0.transparency == 0.25 && ($0.diffuse.contents as? NSColor) == .white && !$0.readsFromDepthBuffer && !$0.writesToDepthBuffer
}, "Previous measurements and their endpoints must be white at 25 percent opacity")
let currentReference = AngleDebugger()
currentReference.update(state("screen", irEye:false, references:true),at:200)
currentReference.rebuild(at:200)
precondition(currentReference.referenceGeometry.childNode(withName:"saved-reference-rays",recursively:true) != nil,
             "Accepted observations must be visible before screen calibration completes or a 3D eye model is ready")
precondition(abs(ScreenCalibrationPath.target(elapsed:6,corner:0).x - 0.08) < 0.00001)
precondition(abs(ScreenCalibrationPath.target(elapsed:6,corner:3).y - 0.92) < 0.00001)
if let path = ProcessInfo.processInfo.environment["EYECURSOR_CALIBRATION_SNAPSHOT"] {
    currentReference.sceneView.frame = NSRect(x:0,y:0,width:900,height:650)
    currentReference.sceneView.isPlaying = false
    let picture = currentReference.sceneView.snapshot()
    let bitmap = NSBitmapImageRep(data:picture.tiffRepresentation!)!
    try! bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:path))
}
let currentLine = currentReference.geometry.childNode(withName:"current-target-reference",recursively:true)!
precondition(abs(currentLine.geometry!.firstMaterial!.transparency - 0.9) < 0.0001)
let currentHalfLength = Float((currentLine.geometry as! SCNCylinder).height)/2
precondition(simd_distance(currentLine.simdConvertPosition([0,currentHalfLength,0],to:currentReference.geometry),currentReference.lastTarget) < 0.0001,
             "Only the current reference must connect the current eye to the active target")
currentReference.update(state("complete", irEye:true, references:true),at:201)
currentReference.rebuild(at:201)
precondition(currentReference.geometry.childNode(withName:"current-target-reference",recursively:true) == nil,
             "A completed calibration must not leave an active target reference")
let savedOrigin = evidence.referenceOrigins[1]!
let (_,absoluteTurn) = evidence.headGeometry(combinedPose)
precondition(simd_length(absoluteTurn.act(headForward)-headForward) > 0.0001,
             "The diagnostic scene must retain an actually rotated head")
let ray = evidence.geometry.childNode(withName:"live-gaze-ray",recursively:true)!
let rayHalfLength = Float((ray.geometry as! SCNCylinder).height)/2
let rayEnd = ray.simdConvertPosition([0,rayHalfLength,0],to:evidence.geometry)
precondition(rayEnd.x > evidence.value("width")/2 && abs(rayEnd.z) < 0.01,
             "Live raw ray must reach its off-screen plane estimate, not the fenced desktop dot")
let greenQuality = evidence.rayQuality
evidence.update(state("complete",valid:false,tracked:false,references:true),at:200.5)
evidence.rebuild(at:200.5)
precondition(evidence.rayQuality < greenQuality && evidence.rayQuality > 0)
evidence.rebuild(at:202)
precondition(evidence.rayQuality < 0.05 && evidence.geometry.childNode(withName:"live-gaze-ray",recursively:true) != nil,
             "Lost tracking must leave a red last-known ray visible")
precondition(evidence.referenceOrigins[1]! == savedOrigin)
evidence.update(state("complete",references:true,referenceCount:160),at:203)
evidence.rebuild(at:203)
precondition(evidence.referenceOrigins.count == 160)
let allSaved = evidence.referenceGeometry.childNode(withName:"saved-reference-rays",recursively:true)!.geometry!
precondition(allSaved.elements[0].primitiveCount == 160 && allSaved.elements[1].primitiveCount == 320,
             "Every accepted measurement needs a white segment and both endpoints")
evidence.update(state("complete",references:true,referenceCount:160,referenceSession:"next",referenceShift:0.1),at:204)
evidence.rebuild(at:204)
precondition(simd_distance(evidence.referenceOrigins[1]!,savedOrigin)>1,
             "A new session with reused IDs and the same count cannot reuse old geometry")
precondition(!evidence.sceneView.cameraControlConfiguration.allowsTranslation)
for _ in 0..<100 { evidence.sceneView.zoom(by:100) }
precondition(simd_distance(evidence.camera.simdPosition,evidence.sceneView.orbitCenter) <= 240.01)
for _ in 0..<100 { evidence.sceneView.zoom(by:-100) }
precondition(simd_distance(evidence.camera.simdPosition,evidence.sceneView.orbitCenter) >= 34.99)
let desktopFrames = [CGRect(x:0,y:0,width:1000,height:800),CGRect(x:1000,y:300,width:1200,height:900)]
precondition(desktopFence(CGPoint(x:999,y:500),frames:desktopFrames) == CGPoint(x:999,y:500))
precondition(desktopFence(CGPoint(x:1001,y:100),frames:desktopFrames) == CGPoint(x:992,y:100))
precondition(desktopFence(CGPoint(x:1600,y:100),frames:desktopFrames) == CGPoint(x:1600,y:308))
let lab = controller.angleDebugger
lab.state = nil
lab.connectedDisplays = [
    LaboratoryDisplay(id:"laptop",key:"test-laptop",name:"Laptop",frame:CGRect(x:0,y:0,width:1440,height:900),builtin:true),
    LaboratoryDisplay(id:"external",key:"test-external",name:"External monitor",frame:CGRect(x:1440,y:100,width:1920,height:1080),builtin:false),
    LaboratoryDisplay(id:"portrait",key:"test-portrait",name:"Portrait monitor",frame:CGRect(x:-1080,y:0,width:1080,height:1920),builtin:false)
]
lab.displayPoses = ["test-external":[-25,8,3],"test-portrait":[20,0,0]]
lab.aspect = 1.6
lab.refreshDisplayControls()
lab.rebuild()
precondition(lab.geometry.childNode(withName:"laptop-keyboard-reference",recursively:true) != nil)
precondition(lab.geometry.childNode(withName:"display-external",recursively:true) != nil)
precondition(lab.geometry.childNode(withName:"display-portrait",recursively:true) != nil)
precondition(lab.displayChoice.numberOfItems == 3 && lab.displaySliders.count == 5)
precondition(lab.displaySliders[0].doubleValue == -25 && lab.displaySliders[1].doubleValue == 8,
             "Restored controls must show the saved external monitor placement")
for display in lab.connectedDisplays {
    let (center, rotation, width, height) = lab.displayTransform(display)
    let mapped = lab.sceneDesktopPoint([display.frame.midX + display.frame.width/4,
                                       screen.frame.maxY - display.frame.midY - display.frame.height/4])!
    precondition(simd_distance(mapped, center+rotation.act([width/4,height/4,0.08])) < 0.001,
                 "Gaze points must map to each monitor, including negative coordinates and portrait displays")
}
precondition(lab.sceneDesktopPoint([100000,100000]) == nil)
precondition(!lab.sidebar.arrangedSubviews.contains { ($0 as? NSButton)?.title.contains("neutral") == true })
let externalTransform = lab.displayTransform(lab.connectedDisplays[1])
precondition(externalTransform.0.x > 0 && externalTransform.0.z == 3)
precondition(externalTransform.1.act([0,0,1]).x < 0)
precondition(AngleDebugger.migrateDisplayPoses(["external":[-25,8,3]])["external"]! == [-25,0,3],
             "Saved tilt must be removed while preserving yaw and depth")
for offset in [-12.0, 12.0] {
    lab.displayPoses["test-external"] = [-25,offset,3]
    let moved = lab.displayTransform(lab.connectedDisplays[1])
    precondition(abs(moved.0.x - externalTransform.0.x - Float(offset - 8)) < 0.0001)
    precondition(moved.0.y == externalTransform.0.y && moved.0.z == 3,
                 "Side-to-side movement must leave monitor height and depth unchanged")
    precondition(simd_distance(moved.1.act([0,0,1]),externalTransform.1.act([0,0,1])) < 0.0001,
                 "Side-to-side movement must not tilt the monitor")
}
lab.displayPoses["test-external"] = [-25,8,3]
let portraitTransform = lab.displayTransform(lab.connectedDisplays[2])
precondition(portraitTransform.0.x < 0 && portraitTransform.3 > portraitTransform.2)
let settingsSuite = "local.eyecursor.lifecycle.\(UUID().uuidString)"
let settings = UserDefaults(suiteName: settingsSuite)!
settings.set(["retained-external":[-25.0,8.0,3.0]],forKey:"laboratoryDisplayPlacement")
let firstLab = AngleDebugger(preferences:settings)
firstLab.sliders["width"]!.doubleValue = 48
firstLab.sliders["yaw"]!.doubleValue = -14
firstLab.targetMode.state = .off
firstLab.changed()
let restoredLab = AngleDebugger(preferences:settings)
precondition(restoredLab.value("width") == 48 && restoredLab.value("yaw") == -14)
precondition(restoredLab.targetMode.state == .off)
precondition(restoredLab.displayPoses["retained-external"]! == [-25,8,3],
             "Disconnected monitor positions must survive laboratory settings changes")
restoredLab.connectedDisplays = lab.connectedDisplays
restoredLab.refreshDisplayControls()
for (index, angle) in [(0, -30.0), (3, 15.0), (4, 10.0)] {
    restoredLab.displaySliders[index].doubleValue = angle
    restoredLab.displayChanged(restoredLab.displaySliders[index])
}
let editedPose = restoredLab.displayPoses["test-external"]!
precondition(editedPose == [-30,0,0,15,10])
let changedTransform = restoredLab.displayTransform(restoredLab.connectedDisplays[1])
let expectedRotation = AngleGeometry.rotation(yaw: -.pi/6, pitch: .pi/12, roll: .pi/18)
precondition(simd_distance(changedTransform.1.act([0,1,0]), expectedRotation.act([0,1,0])) < 0.001)
restoredLab.rebuild()
let editedSurface = restoredLab.geometry.childNode(withName:"display-external", recursively:true)!
precondition(simd_distance(editedSurface.simdOrientation.act([0,1,0]), expectedRotation.act([0,1,0])) < 0.001)
let editedDisplay = restoredLab.connectedDisplays[1]
let editedHit = restoredLab.sceneDesktopPoint([editedDisplay.frame.midX, screen.frame.maxY-editedDisplay.frame.midY])!
precondition(simd_distance(editedHit, changedTransform.0+expectedRotation.act([0,0,0.08])) < 0.001)
restoredLab.displayChoice.selectItem(at: 2); restoredLab.selectDisplay()
precondition(restoredLab.displaySliders.allSatisfy { $0.doubleValue == 0 })
restoredLab.displayChoice.selectItem(at: 0); restoredLab.selectDisplay()
precondition(restoredLab.displaySliders.allSatisfy { !$0.isEnabled }, "The calibration reference stays fixed")
restoredLab.displaySliders[0].doubleValue = 45
restoredLab.displayChanged(restoredLab.displaySliders[0])
precondition(restoredLab.displayPoses["test-laptop"] == nil)
let reloadedDisplays = AngleDebugger(preferences:settings)
precondition(reloadedDisplays.displayPoses["test-external"] == editedPose,
             "Monitor angles must survive relaunch and disconnected displays")
restoredLab.connectedDisplays.remove(at: 1); restoredLab.refreshDisplayControls()
precondition(restoredLab.displayChoice.numberOfItems == 2)
restoredLab.connectedDisplays = lab.connectedDisplays; restoredLab.refreshDisplayControls()
restoredLab.displayChoice.selectItem(at: 1); restoredLab.selectDisplay()
precondition(restoredLab.displaySliders[3].doubleValue == 15)
precondition(restoredLab.value("width") == 48 && restoredLab.value("yaw") == -14,
             "Monitor adjustments must not change eye or reference geometry")
let longDisplayName = String(repeating: "External monitor with a very long device name ", count: 10)
restoredLab.connectedDisplays.append(LaboratoryDisplay(id:"long", key:"long", name:longDisplayName,
    frame:CGRect(x:3360,y:0,width:1920,height:1080), builtin:false))
restoredLab.refreshDisplayControls()
precondition(restoredLab.displayChoice.itemArray.allSatisfy { $0.title.count <= 32 },
             "Device names must not widen the monitor selector")
precondition(restoredLab.displayChoice.lastItem?.toolTip == longDisplayName,
             "Truncated device names must remain available in a tooltip")
restoredLab.connectedDisplays = []; restoredLab.refreshDisplayControls()
precondition(!restoredLab.displayChoice.isEnabled && restoredLab.displaySliders.allSatisfy { !$0.isEnabled })
restoredLab.resetAll()
precondition(restoredLab.displaySliders.allSatisfy { $0.doubleValue == 0 })
let resetLab = AngleDebugger(preferences:settings)
precondition(abs(resetLab.value("width") - 30.2) < 0.001 && resetLab.targetMode.state == .on)
precondition(resetLab.displayPoses.isEmpty)
settings.removePersistentDomain(forName:settingsSuite)
if let path = ProcessInfo.processInfo.environment["EYECURSOR_MONITOR_CONTROLS_SNAPSHOT"] {
    let view = controller.diagnosticWindow.contentView!
    view.layoutSubtreeIfNeeded()
    lab.sidebar.scrollToVisible(lab.displayControls.frame.insetBy(dx:0,dy:-80))
    controller.diagnosticWindow.display(); CATransaction.flush()
    precondition(lab.displayChoice.alignmentRect(forFrame:lab.displayChoice.frame).width <= 294.5,
                 "Monitor selector must fit the existing sidebar padding")
    let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds)!
    view.effectiveAppearance.performAsCurrentDrawingAppearance { view.cacheDisplay(in:view.bounds,to:bitmap) }
    try! bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:path))
}
if let path = ProcessInfo.processInfo.environment["EYECURSOR_SCENE_SNAPSHOT"] {
    lab.camera.simdPosition = [65,48,115]; lab.camera.look(at:SCNVector3(6,6,12))
    lab.sceneView.isPlaying = false
    let picture = lab.sceneView.snapshot()
    let bitmap = NSBitmapImageRep(data:picture.tiffRepresentation!)!
    try! bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:path))
}
let accuracyFixture: [String:Any] = [
    "status":"complete", "target_index":5, "target_count":5,
    "targets":[[0.25,0.25],[0.75,0.25],[0.75,0.75],[0.25,0.75],[0.5,0.32]],
    "mean_error_points":42.0, "worst_error_points":70.0,
    "viewport_size":[1440.0,900.0], "remaining_seconds":0.0,
    "rows":[
        ["target":[0.25,0.25],"measured":[0.28,0.27],"error_points":47.0,"precision_points":3.0,"samples":12],
        ["target":[0.75,0.25],"measured":[0.79,0.28],"error_points":64.0,"precision_points":4.0,"samples":12],
        ["target":[0.75,0.75],"measured":[0.76,0.76],"error_points":17.0,"precision_points":2.0,"samples":12],
        ["target":[0.25,0.75],"measured":[0.29,0.79],"error_points":68.0,"precision_points":3.0,"samples":12],
        ["target":[0.5,0.32],"measured":[0.51,0.32],"error_points":14.0,"precision_points":2.0,"samples":12]]]
deliver(state("verify", accuracy:accuracyFixture))
precondition(controller.active && controller.window.isVisible)
precondition(controller.accuracyButton.title == "Stop accuracy check")
precondition(controller.calibrationSteps.countdown.stringValue.contains("Accuracy check"))
precondition(controller.calibrationSteps.rows[2].stringValue.contains("Active"))
deliver(state("complete", accuracy:accuracyFixture))
precondition(controller.accuracyButton.isEnabled)
precondition(controller.accuracySummary.stringValue.contains("Mean 42 pt"))
precondition(controller.accuracyButton.superview === controller.calibrationSteps,
             "Accuracy checking belongs to the right-side calibration controls")
controller.calibrationSteps.layoutSubtreeIfNeeded()
precondition(controller.accuracyButton.frame.maxY <= controller.calibrationSteps.actionButton.frame.minY)
precondition(controller.accuracySummary.frame.maxY <= controller.accuracyButton.frame.minY)
let cameraStack = controller.preview.superview as! NSStackView
precondition(cameraStack.arrangedSubviews.first === controller.trackingEyeTitle,
             "The left eye feed must remain the first camera section")
let scene = controller.angleDebugger
scene.rebuild()
var markers = scene.geometry.childNode(withName:"accuracy-check-markers",recursively:false)!
precondition(markers.childNodes.filter { $0.name?.hasPrefix("accuracy-measured-") == true }.count == 5)
let topLeft = markers.childNode(withName:"accuracy-measured-0",recursively:false)!
precondition(abs(topLeft.simdPosition.x + scene.value("width")*0.25) < 0.001)
precondition(abs(topLeft.simdPosition.y - scene.value("width")/scene.aspect*0.25) < 0.001)
precondition(abs(topLeft.simdPosition.z-0.12) < 0.001, "Check markers must lie on the laptop screen")
func accuracySnapshot(_ suffix: String) {
    guard let path = ProcessInfo.processInfo.environment["EYECURSOR_ACCURACY_SNAPSHOT"] else { return }
    scene.sceneView.frame = NSRect(x:0,y:0,width:900,height:650)
    scene.camera.simdPosition = [24,18,44]; scene.camera.look(at:SCNVector3(0,-2,4))
    scene.sceneView.isPlaying = false
    let picture = scene.sceneView.snapshot()
    let bitmap = NSBitmapImageRep(data:picture.tiffRepresentation!)!
    try! bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:path+suffix+".png"))
}
accuracySnapshot("-complete")
var partialAccuracy = accuracyFixture
partialAccuracy["status"] = "checking"; partialAccuracy["target_index"] = 3
let fixtureRows = accuracyFixture["rows"] as! [[String:Any]]
partialAccuracy["rows"] = [fixtureRows[0], ["target":[0.75,0.25],"samples":0]]
deliver(state("verify",accuracy:partialAccuracy)); scene.rebuild()
markers = scene.geometry.childNode(withName:"accuracy-check-markers",recursively:false)!
precondition(markers.childNodes.filter { $0.name?.hasPrefix("accuracy-measured-") == true }.count == 1)
precondition(markers.childNodes.filter { $0.name?.hasPrefix("accuracy-pending-") == true }.count == 3)
precondition(markers.childNode(withName:"accuracy-missing-1",recursively:false) != nil)
accuracySnapshot("-partial")
partialAccuracy["status"] = "incomplete"
deliver(state("complete",accuracy:partialAccuracy)); scene.rebuild()
markers = scene.geometry.childNode(withName:"accuracy-check-markers",recursively:false)!
precondition(markers.childNodes.filter { $0.name?.hasPrefix("accuracy-pending-") == true }.isEmpty,
             "Stopped checks must mark the unmeasured targets missing")
deliver(state("complete")); scene.rebuild()
precondition(scene.geometry.childNode(withName:"accuracy-check-markers",recursively:false) == nil,
             "An unchecked mapping must not retain old check markers")
controller.window.orderOut(nil);controller.dot.orderOut(nil)
print("Native lifecycle passed: no timeout cancellation, completion shows cursor, stale fading and recovery, missing gaze opacity and expiry.")
