// Geometry laboratory. Saved centimetres are display assumptions, never tracker calibration.
import AppKit
import SceneKit
import simd

struct DebugEyeDirection: Decodable {
    let vector: [Double]
    let center: [Double]?
    let pupil: [Double]?
    let radius_px: Double?
    let head_features: [Double]?
    let model_ready: Bool
}

struct CalibrationRay: Decodable {
    let id: Int
    let eye: [Double]
    let head: [Double]
    let target: [Double]
    let source: String
    let predicted_before: [Double]?
    let error_px: Double?
}

struct LaboratoryDisplay {
    let id: String
    let key: String
    let name: String
    let frame: CGRect
    let builtin: Bool

    static func connected() -> [LaboratoryDisplay] {
        NSScreen.screens.compactMap { screen in
            guard let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else { return nil }
            let id = number.uint32Value
            let key: String
            if let uuid = CGDisplayCreateUUIDFromDisplayID(id)?.takeRetainedValue() {
                key = CFUUIDCreateString(nil,uuid) as String
            } else { key = "display-\(id)" }
            return LaboratoryDisplay(id:number.stringValue,key:key,
                name:screen.localizedName,frame:screen.frame,builtin:CGDisplayIsBuiltin(id) != 0)
        }
    }
}

final class BoundedSceneView: SCNView {
    let orbitCenter = SIMD3<Float>(0,0,26)
    func zoom(by delta: Float) {
        guard let camera = pointOfView else { return }
        let offset = camera.simdPosition-orbitCenter
        let distance = simd_length(offset)
        guard distance.isFinite, distance > 0.01 else { return }
        let next = min(240,max(35,distance * exp(min(0.3,max(-0.3,delta*0.008)))))
        camera.simdPosition = orbitCenter + offset/distance*next
    }
    override func scrollWheel(with event: NSEvent) { zoom(by: Float(event.scrollingDeltaY)) }
    override func magnify(with event: NSEvent) { zoom(by: -Float(event.magnification)*40) }
}

enum AngleGeometry {
    // Match compute_gaze_vector's existing 640x480 / 45-degree diagnostic model.
    // Its sphere radius and projection are heuristic, not calibrated camera optics.
    static func cameraRay(pupil: SIMD2<Float>, center: SIMD2<Float>) -> SIMD3<Float> {
        let origin = SIMD3<Float>(0,0,3)
        let far = SIMD3<Float>((2*pupil.x/640-1)*tan(Float.pi/8)*100*4/3,
                               (1-2*pupil.y/480)*tan(Float.pi/8)*100,-97)
        let d = unit(far-origin)
        let sphere = SIMD3<Float>((2*center.x/640-1)*1.5,(1-2*center.y/480)*1.5,0)
        let l = origin-sphere, b = 2*simd_dot(d,l)
        let disc = b*b-4*(simd_dot(l,l)-pow(1/1.05,2))
        let t = disc < 0 ? -simd_dot(d,l) : (-b-sqrt(disc))/2
        return unit(origin+t*d-sphere)
    }
    static func unit(_ a: SIMD3<Float>) -> SIMD3<Float> { a / max(0.00001, simd_length(a)) }
    static func rotation(yaw: Float, pitch: Float, roll: Float) -> simd_quatf {
        simd_quatf(angle: yaw, axis: [0,1,0]) * simd_quatf(angle: pitch, axis: [1,0,0]) * simd_quatf(angle: roll, axis: [0,0,1])
    }
    static func headRotation(_ pose: [Double], relativeTo reference: [Double]) -> simd_quatf {
        // head_camera.py decomposes MediaPipe R = Rz(roll) Ry(yaw) Rx(pitch).
        // Relative rotations are matrix/quaternion products, not Euler subtraction.
        func cameraRotation(_ p: [Double]) -> simd_quatf {
            simd_quatf(angle:Float(p[2]),axis:[0,0,1]) * simd_quatf(angle:Float(p[0]),axis:[0,1,0]) * simd_quatf(angle:Float(p[1]),axis:[1,0,0])
        }
        let cameraToScreen = simd_quatf(angle: .pi,axis: SIMD3<Float>(0,1,0))
        return cameraToScreen * cameraRotation(pose) * cameraRotation(reference).inverse * cameraToScreen.inverse
    }
    static func eyeMidpoint(imageUV: SIMD2<Float>, depth: Float, verticalFOV: Float,
                            imageAspect: Float, cameraOrigin: SIMD3<Float>, cameraPitch: Float) -> SIMD3<Float> {
        // Unmirrored MediaPipe camera: +X image-right, +Y up, viewing along -Z.
        // Screen frame: +X monitor-right, +Y monitor-up, +Z towards the wearer.
        let fy = 0.5/tan(verticalFOV/2), fx = fy/imageAspect
        let cameraPoint = SIMD3<Float>((imageUV.x-0.5)*depth/fx,(0.5-imageUV.y)*depth/fy,-depth)
        let basis = simd_quatf(angle:cameraPitch,axis:SIMD3<Float>(1,0,0)) * simd_quatf(angle:.pi,axis:SIMD3<Float>(0,1,0))
        return cameraOrigin+basis.act(cameraPoint)
    }
    static func hit(_ origin: SIMD3<Float>, _ direction: SIMD3<Float>) -> SIMD3<Float>? {
        guard direction.z < -0.00001 else { return nil }
        let t = -origin.z / direction.z
        return t > 0 ? origin + t * direction : nil
    }
    static func angle(_ a: SIMD3<Float>, _ b: SIMD3<Float>) -> Float {
        acos(min(1, max(-1, simd_dot(unit(a), unit(b))))) * 180 / .pi
    }
    // Looking along the expected beam: zero separation means parallel, including sign.
    static func alignment(_ expected: SIMD3<Float>, _ actual: SIMD3<Float>) -> SIMD2<Float> {
        let forward = unit(expected)
        let right = unit(simd_cross(forward, abs(forward.y) > 0.99 ? SIMD3<Float>(1,0,0) : SIMD3<Float>(0,1,0)))
        let up = simd_cross(right, forward)
        let depth = simd_dot(actual, forward)
        return [atan2(simd_dot(actual, right), depth) * 180 / .pi,
                atan2(simd_dot(actual, up), depth) * 180 / .pi]
    }
}

final class MonochromeCheckbox: NSButton {
    override func draw(_ rect: NSRect) {
        let box = NSRect(x: 1,y: bounds.midY-7,width: 14,height: 14)
        NSColor.white.withAlphaComponent(0.4).setStroke()
        NSBezierPath(roundedRect: box,xRadius: 3,yRadius: 3).stroke()
        if state == .on {
            NSColor.white.setStroke()
            let tick = NSBezierPath(); tick.lineWidth = 1.5
            tick.move(to: NSPoint(x: 4,y: bounds.midY)); tick.line(to: NSPoint(x: 7,y: bounds.midY-3))
            tick.line(to: NSPoint(x: 12,y: bounds.midY+4)); tick.stroke()
        }
        (title as NSString).draw(at: NSPoint(x: 23,y: bounds.midY-8),withAttributes: [
            .font: NSFont.systemFont(ofSize: 13), .foregroundColor: NSColor.white.withAlphaComponent(0.8)])
    }
}

final class AngleDebugger: NSObject, SCNSceneRendererDelegate {
    let contentView = NSView()
    let sidebar = NSStackView()
    let sidebarScroll = NSScrollView()
    let sidebarToggle = NSButton(title: "", target: nil, action: nil)
    private var sidebarWidth: NSLayoutConstraint!
    private(set) var sidebarCollapsed = false
    let sceneView = BoundedSceneView()
    let scene = SCNScene()
    let geometry = SCNNode()
    let referenceGeometry = SCNNode()
    private var referenceGeometryKey = ""
    let camera = SCNNode()
    var outlines: [(SCNNode, Float, SCNMaterial)] = []
    let outlineLock = NSLock()
    var alignmentOffset: SIMD2<Float>?
    let metrics = NSTextField(wrappingLabelWithString: "")
    let mappingMetrics = NSTextField(wrappingLabelWithString: "")
    let cameraRayMetrics = NSTextField(wrappingLabelWithString: "")
    private var cameraMeasurements = MeasurementChannels()
    private var cameraContexts: [String: String] = [:]
    var savedReferences: [CalibrationRay] = []
    var referenceOrigins: [Int:SIMD3<Float>] = [:]
    var rayQuality: Float = 0
    private var lastRayTime: Double?
    private let metricLabels = ["Angular difference", "Plane miss", "Tracking eye", "IR center", "Pupil offset"]
    private var lastMetricRows: [String?] = Array(repeating: nil, count: 5)
    let targetMode = MonochromeCheckbox(checkboxWithTitle: "Follow calibration target", target: nil, action: nil)
    private let preferences: UserDefaults
    private static let settingsKey = "laboratoryAngleSettings"
    var sliders: [String: NSSlider] = [:]
    var values: [String: NSTextField] = [:]
    var defaults: [String: Double] = [:]
    var state: TrackerState?
    var measurements = MeasurementChannels()
    // Display-only history. Missing observations must not move the head back to
    // assumed geometry, and must never become calibration or cursor samples.
    private var displayedMeasurements: [String: [Double]] = [:]
    private var measurementContext = ""
    var aspect: Float = 1.6
    var lastEye = SIMD3<Float>(3.2,2,60)
    var lastTarget = SIMD3<Float>(0,0,0)
    var connectedDisplays: [LaboratoryDisplay] = []
    var displayPoses: [String: [Double]] = [:]
    let displayChoice = NSPopUpButton(frame: .zero, pullsDown: false)
    let displayControls = NSStackView()
    var displaySliders: [NSSlider] = []
    private var displayLabels: [NSTextField] = []
    private let displayFields = [("Yaw", "°", -90.0, 90.0), ("Horizontal offset", " cm", -100.0, 100.0),
                                 ("Depth", " cm", -100.0, 100.0), ("Tilt", "°", -90.0, 90.0),
                                 ("Roll", "°", -180.0, 180.0)]
    private var selectedDisplay: LaboratoryDisplay? {
        guard let key = displayChoice.selectedItem?.representedObject as? String else { return nil }
        return connectedDisplays.first { $0.key == key }
    }
    var anchorDisplay: LaboratoryDisplay? {
        connectedDisplays.first { $0.builtin } ?? connectedDisplays.first
    }

    init(preferences: UserDefaults = .standard) {
        self.preferences = preferences
        super.init()
        let root = contentView
        sceneView.scene = scene
        sceneView.delegate = self
        sceneView.backgroundColor = NSColor(white: 0.025,alpha: 1)
        sceneView.antialiasingMode = .multisampling4X
        sceneView.allowsCameraControl = true
        sceneView.cameraControlConfiguration.allowsTranslation = false
        sceneView.defaultCameraController.interactionMode = .orbitTurntable
        sceneView.defaultCameraController.inertiaEnabled = false
        sceneView.defaultCameraController.minimumVerticalAngle = -35
        sceneView.defaultCameraController.maximumVerticalAngle = 70
        sceneView.preferredFramesPerSecond = 60
        scene.rootNode.addChildNode(geometry)
        geometry.addChildNode(referenceGeometry)
        camera.camera = SCNCamera(); camera.camera?.zNear = 0.1; camera.camera?.zFar = 1000
        scene.rootNode.addChildNode(camera); sceneView.pointOfView = camera
        sceneView.translatesAutoresizingMaskIntoConstraints = false; root.addSubview(sceneView)
        let scroll = sidebarScroll; scroll.hasVerticalScroller = true
        scroll.translatesAutoresizingMaskIntoConstraints = false; root.addSubview(scroll)
        let stack = sidebar; stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 12
        stack.edgeInsets = NSEdgeInsets(top: 20,left: 18,bottom: 20,right: 18)
        scroll.documentView = stack; stack.translatesAutoresizingMaskIntoConstraints = false
        sidebarWidth = scroll.widthAnchor.constraint(equalToConstant: 330)
        NSLayoutConstraint.activate([
            sceneView.leadingAnchor.constraint(equalTo: root.leadingAnchor), sceneView.topAnchor.constraint(equalTo: root.topAnchor),
            sceneView.bottomAnchor.constraint(equalTo: root.bottomAnchor), sceneView.trailingAnchor.constraint(equalTo: scroll.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: root.trailingAnchor), scroll.topAnchor.constraint(equalTo: root.topAnchor),
            scroll.bottomAnchor.constraint(equalTo: root.bottomAnchor), sidebarWidth,
            sceneView.widthAnchor.constraint(greaterThanOrEqualToConstant: 320),
            stack.leadingAnchor.constraint(equalTo: scroll.contentView.leadingAnchor), stack.widthAnchor.constraint(equalToConstant: 330),
            stack.topAnchor.constraint(equalTo: scroll.contentView.topAnchor)
        ])
        sidebarToggle.bezelStyle = .regularSquare
        sidebarToggle.imagePosition = .imageOnly
        sidebarToggle.imageScaling = .scaleProportionallyDown
        sidebarToggle.target = self; sidebarToggle.action = #selector(toggleSidebar)
        sidebarToggle.translatesAutoresizingMaskIntoConstraints = false; root.addSubview(sidebarToggle)
        NSLayoutConstraint.activate([
            sidebarToggle.topAnchor.constraint(equalTo: sceneView.topAnchor, constant: 10),
            sidebarToggle.trailingAnchor.constraint(equalTo: sceneView.trailingAnchor, constant: -12),
            sidebarToggle.widthAnchor.constraint(equalToConstant: 28),
            sidebarToggle.heightAnchor.constraint(equalToConstant: 28)
        ])
        updateSidebarToggle()
        func add(_ view: NSView) { stack.addArrangedSubview(view); view.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -36).isActive = true }
        func caption(_ text: String, bold: Bool = false) {
            let label = NSTextField(wrappingLabelWithString: text); label.font = .systemFont(ofSize: bold ? 17 : 11,weight: bold ? .semibold : .regular)
            label.textColor = bold ? .white : .secondaryLabelColor; add(label)
        }
        let reset = NSButton(title: "Reset laboratory",target: self,action: #selector(resetAll)); add(reset)
        caption("Angle laboratory", bold: true)
        caption("Drag to orbit, scroll to zoom. The scene shows your connected monitors. The calibration dot stays above this window.")
        metrics.font = .monospacedDigitSystemFont(ofSize: 11,weight: .regular); add(metrics)
        cameraRayMetrics.font = .monospacedDigitSystemFont(ofSize: 11,weight: .regular)
        add(cameraRayMetrics)
        cameraRayMetrics.heightAnchor.constraint(equalToConstant: 74).isActive = true
        mappingMetrics.font = .monospacedDigitSystemFont(ofSize: 11,weight: .regular)
        mappingMetrics.textColor = .secondaryLabelColor; add(mappingMetrics)
        mappingMetrics.heightAnchor.constraint(equalToConstant: 42).isActive = true
        // Live samples may disappear between frames. Keep the controls below
        // these labels stationary regardless of text wrapping or availability.
        metrics.heightAnchor.constraint(equalToConstant: 90).isActive = true
        targetMode.state = .on; targetMode.target = self; targetMode.action = #selector(changed); add(targetMode)
        func control(_ key: String, _ title: String, _ value: Double, _ lo: Double, _ hi: Double) {
            let label = NSTextField(labelWithString: ""); label.font = .monospacedDigitSystemFont(ofSize: 11,weight: .regular)
            label.identifier = NSUserInterfaceItemIdentifier(title); values[key] = label; add(label)
            let slider = NSSlider(value: value,minValue: lo,maxValue: hi,target: self,action: #selector(changed))
            slider.trackFillColor = .white
            slider.identifier = NSUserInterfaceItemIdentifier(key); sliders[key] = slider; defaults[key] = value; add(slider)
        }
        control("tx", "Manual target X (%)",50,0,100); control("ty", "Manual target Y (%)",50,0,100)
        caption("ASSUMED GEOMETRY · centimetres",bold: false)
        control("width", "Screen width",30.2,20,80)
        caption("CONNECTED DISPLAYS")
        displayChoice.target = self; displayChoice.action = #selector(selectDisplay)
        displayChoice.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        add(displayChoice)
        caption("The laptop stays fixed as the reference. Select another monitor to set its angles and position. These settings affect the scene only.")
        displayControls.orientation = .vertical; displayControls.alignment = .leading; displayControls.spacing = 8
        add(displayControls)
        for (index, field) in displayFields.enumerated() {
            let label = NSTextField(labelWithString: "")
            label.font = .monospacedDigitSystemFont(ofSize: 11, weight: .regular)
            displayLabels.append(label); displayControls.addArrangedSubview(label)
            let slider = NSSlider(value: 0, minValue: field.2, maxValue: field.3,
                                  target: self, action: #selector(displayChanged(_:)))
            slider.tag = index; slider.trackFillColor = .white
            slider.setAccessibilityLabel(field.0)
            displaySliders.append(slider); displayControls.addArrangedSubview(slider)
            label.widthAnchor.constraint(equalTo: displayControls.widthAnchor).isActive = true
            slider.widthAnchor.constraint(equalTo: displayControls.widthAnchor).isActive = true
        }
        control("distance", "Head distance",30,25,110)
        control("hx", "Head horizontal",0,-25,25); control("hy", "Head vertical",0,-25,25)
        control("ipd", "Eye separation",6.4,4,8)
        control("webcam", "Webcam above screen edge",0.7,0,6)
        control("camera_fov", "Webcam vertical FOV (assumed)",45,20,100)
        control("camera_pitch", "Webcam mount pitch to screen",0,-25,25)
        caption("RIGHT EYE · local center offset (cm)")
        control("cx", "Center X",0,-3,3); control("cy", "Center Y",0,-3,3); control("cz", "Center Z",0,-3,3)
        caption("IR FITTED CENTER · pixel offsets\nReprojects the pupil using the tracker's existing heuristic sphere model. Live input only.")
        control("px", "Fitted center X (px)",0,-80,80); control("py", "Fitted center Y (px)",0,-80,80)
        caption("IR MOUNT / ANGLE OFFSETS · degrees")
        control("yaw", "Yaw",0,-90,90); control("pitch", "Pitch",0,-90,90); control("roll", "Roll",0,-180,180)
        caption("Magenta = left IR camera. Orange = right IR camera. Small matching dots mark their estimated screen-plane intersections; X/Y are percentages from the laptop screen’s top-left, including off-screen values. These are independent, approximate directions, not two cursor targets. Missing measurements hide only that camera’s ray. Green = the existing single EyeCursor estimate. Red = its last direction while tracking is unavailable. Blue = webcam iris estimates. Bright white = current eye-to-target reference; faint white = previous accepted measurements.\n\nHead depth, eye centers and camera mounting are approximate. Calibration learns the screen map; it does not measure anatomical eye centers. Controls affect this view only.")
        restoreSettings(); refreshDisplays(); updateLabels(); rebuild(); setView()
    }
    func installCalibrationSteps(_ view: NSView) {
        view.translatesAutoresizingMaskIntoConstraints = false
        sidebar.insertArrangedSubview(view, at: 1)
        NSLayoutConstraint.activate([
            view.widthAnchor.constraint(equalTo: sidebar.widthAnchor, constant: -36)
        ])
    }

    @objc func toggleSidebar() {
        sidebarCollapsed.toggle()
        sidebarWidth.constant = sidebarCollapsed ? 0 : 330
        sidebarScroll.isHidden = sidebarCollapsed
        updateSidebarToggle()
        contentView.window?.contentView?.layoutSubtreeIfNeeded()
    }

    private func updateSidebarToggle() {
        let action = sidebarCollapsed ? "Expand controls" : "Collapse controls"
        let symbol = sidebarCollapsed ? "chevron.left" : "chevron.right"
        sidebarToggle.image = NSImage(systemSymbolName: symbol, accessibilityDescription: action)
        sidebarToggle.toolTip = action
        sidebarToggle.setAccessibilityLabel(action)
    }

    func activate(on screen: NSScreen?) {
        if let screen = screen {
            aspect = Float(screen.frame.width / screen.frame.height)
        }
        sceneView.isPlaying = true
        refreshDisplays()
        rebuild()
    }

    func refreshDisplays() {
        connectedDisplays = LaboratoryDisplay.connected()
        if let saved = preferences.dictionary(forKey:"laboratoryDisplayPlacement") as? [String:[Double]] {
            displayPoses = saved
        } else {
            displayPoses = Self.migrateDisplayPoses(preferences.dictionary(forKey:"laboratoryDisplayPoses") as? [String:[Double]] ?? [:])
        }
        if let anchor = anchorDisplay { aspect = Float(anchor.frame.width/anchor.frame.height) }
        refreshDisplayControls()
        rebuild()
    }

    func restoreSettings() {
        guard let saved = preferences.dictionary(forKey:Self.settingsKey) else { return }
        for (key,slider) in sliders {
            guard let number = saved[key] as? NSNumber, number.doubleValue.isFinite else { continue }
            slider.doubleValue = min(slider.maxValue,max(slider.minValue,number.doubleValue))
        }
        if let follow = saved["followTarget"] as? NSNumber {
            targetMode.state = follow.boolValue ? .on : .off
        }
    }

    func saveSettings() {
        var saved = sliders.mapValues { $0.doubleValue }
        saved["followTarget"] = targetMode.state == .on ? 1 : 0
        preferences.set(saved,forKey:Self.settingsKey)
    }

    static func migrateDisplayPoses(_ old: [String:[Double]]) -> [String:[Double]] {
        // Old values were yaw, tilt, depth. Keep yaw/depth, without interpreting
        // the removed tilt angle as a sideways distance.
        old.mapValues { pose in
            pose.count == 3 && pose.allSatisfy({ $0.isFinite }) ? [pose[0],0,pose[2]] : [0,0,0]
        }
    }

    // Placement keeps the original yaw/horizontal/depth slots; new angles append
    // to them so previously saved monitor positions retain their meaning.
    static func normalizedDisplayPose(_ pose: [Double]?) -> [Double] {
        guard let pose = pose, [3, 5].contains(pose.count), pose.allSatisfy({ $0.isFinite }) else {
            return [0,0,0,0,0]
        }
        return pose.count == 3 ? pose + [0,0] : pose
    }

    func refreshDisplayControls() {
        let previousKey = displayChoice.selectedItem?.representedObject as? String
        displayChoice.removeAllItems()
        for display in connectedDisplays {
            let name = display.name + (display.id == anchorDisplay?.id ? " (reference)" : "")
            let title = name.count > 32 ? String(name.prefix(31)) + "…" : name
            let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            item.representedObject = display.key; item.toolTip = name
            displayChoice.menu?.addItem(item)
        }
        let index = connectedDisplays.firstIndex { $0.key == previousKey }
            ?? connectedDisplays.firstIndex { $0.id != anchorDisplay?.id } ?? 0
        if !connectedDisplays.isEmpty { displayChoice.selectItem(at: index) }
        displayChoice.isEnabled = !connectedDisplays.isEmpty
        selectDisplay()
    }

    @objc func selectDisplay() {
        let display = selectedDisplay
        let editable = display != nil && display?.id != anchorDisplay?.id
        let pose = Self.normalizedDisplayPose(editable ? displayPoses[display!.key] : nil)
        displayChoice.toolTip = displayChoice.selectedItem?.toolTip
        for (index, slider) in displaySliders.enumerated() {
            slider.isEnabled = editable; slider.doubleValue = pose[index]
            let field = displayFields[index]
            displayLabels[index].stringValue = String(format: "%@: %.1f%@", field.0, pose[index], field.1)
        }
    }

    @objc func displayChanged(_ slider: NSSlider) {
        guard let display = selectedDisplay, display.id != anchorDisplay?.id,
              displaySliders.indices.contains(slider.tag) else { return }
        var pose = Self.normalizedDisplayPose(displayPoses[display.key])
        pose[slider.tag] = slider.doubleValue
        displayPoses[display.key] = pose
        preferences.set(displayPoses, forKey: "laboratoryDisplayPlacement")
        selectDisplay(); rebuild()
    }

    func displayTransform(_ display: LaboratoryDisplay) -> (SIMD3<Float>, simd_quatf, Float, Float) {
        guard let anchor = anchorDisplay else { return ([0,0,0],simd_quatf(angle:0,axis:[0,1,0]),value("width"),value("width")/aspect) }
        let scale = value("width")/Float(anchor.frame.width)
        let pose = display.id == anchor.id ? [0,0,0] : (displayPoses[display.key] ?? [0,0,0])
        let p = Self.normalizedDisplayPose(pose)
        let center = SIMD3<Float>(Float(display.frame.midX-anchor.frame.midX)*scale+Float(p[1]),
                                  Float(display.frame.midY-anchor.frame.midY)*scale,Float(p[2]))
        return (center,AngleGeometry.rotation(yaw:Float(p[0]) * .pi/180,pitch:Float(p[3]) * .pi/180,roll:Float(p[4]) * .pi/180),
                Float(display.frame.width)*scale,Float(display.frame.height)*scale)
    }

    func sceneDesktopPoint(_ point: [Double]) -> SIMD3<Float>? {
        guard point.count == 2, point.allSatisfy({ $0.isFinite }), let primary = NSScreen.screens.first else { return nil }
        let desktop = CGPoint(x:point[0],y:primary.frame.maxY-point[1])
        guard let display = connectedDisplays.first(where: { $0.frame.contains(desktop) }) else { return nil }
        let (center,rotation,w,h) = displayTransform(display)
        return center + rotation.act([Float((desktop.x-display.frame.midX)/display.frame.width)*w,
                                       Float((desktop.y-display.frame.midY)/display.frame.height)*h,0.08])
    }
    func update(_ state: TrackerState, at time: Double = ProcessInfo.processInfo.systemUptime) {
        let context = "\(state.eye_camera_id ?? state.source):\(state.eye_cameras?.active_eye ?? "right"):\(state.eye_cameras?.eyes[state.eye_cameras?.active_eye ?? "right"]?.rotation ?? 0):\(state.head_camera?.name ?? ""):\(state.onboarding?.display_id ?? ""):\(state.calibrated)"
        if context != measurementContext { measurements.reset(); measurementContext = context }
        self.state = state
        if let references = state.onboarding?.calibration_rays { savedReferences = references }
        let headStatus: String
        switch state.onboarding?.head_correction_status {
        case "geometric":
            if let checked = state.onboarding?.geometry_model?.checked_motion {
                headStatus = checked["rotation"] == true && checked["translation"] == true ? "Head: turns + shifts checked" :
                    checked["rotation"] == true ? "Head: turns checked; shifts pending" :
                    checked["translation"] == true ? "Head: shifts checked; turns pending" : "Head: motion partly checked"
            } else { headStatus = "Head: geometric model active" }
        case "inconsistent": headStatus = "Head model: inconsistent fit; local only"
        case "insufficient_repeats": headStatus = "Head model: repeat a target at new poses"
        case "insufficient_motion": headStatus = "Head model: no clear movement measured"
        case "no_cursor_anchors": headStatus = "Head model: use cursor alignment to learn"
        default: headStatus = "Learned head directions: \(state.onboarding?.head_correction_rank ?? 0)"
        }
        mappingMetrics.stringValue = "Accepted samples: \(savedReferences.count)\n\(headStatus)"
        if let error = savedReferences.last?.error_px, error.isFinite {
            mappingMetrics.stringValue += String(format:"\nBefore last anchor: %.0f px miss",error)
        }
        let eye = state.eye_direction
        let paired = validMeasurement(eye?.head_features, count: 6)
        let cameraHead = ["left", "right"].compactMap { side -> [Double]? in
            guard state.eye_cameras?.eyes[side]?.connected == true else { return nil }
            return validMeasurement(state.eye_cameras?.eyes[side]?.scene_direction?.head_features, count: 6)
        }.first
        let head = paired ?? (state.head_camera?.face_visible == true ? validMeasurement(state.head_camera?.features, count: 6) : nil) ?? cameraHead
        measurements.update("head", head, at: time)
        measurements.update("eye", paired != nil ? validMeasurement(eye?.vector, count: 3) : nil, at: time)
        measurements.update("center", paired != nil ? validMeasurement(eye?.center, count: 2) : nil, at: time)
        measurements.update("pupil", paired != nil ? validMeasurement(eye?.pupil, count: 2) : nil, at: time)
        let validGaze = state.gaze.map { $0.count == 2 && $0.allSatisfy({ $0.isFinite && (0...1).contains($0) }) } == true
        measurements.update("gaze", state.calibrated && (state.display_valid ?? state.valid) && validGaze ? state.gaze : nil, at: time)
        let raw = validMeasurement(state.unclamped_gaze ?? state.gaze, count: 2)
        measurements.update("rawGaze", state.valid && state.calibrated ? raw : nil, at: time)
        for i in 0..<2 {
            let rays = state.head_camera?.eye_rays
            measurements.update("ray\(i)", head != nil && state.head_camera?.face_visible == true && rays?.count == 2 ? validMeasurement(rays?[i], count: 3) : nil, at: time)
        }
        for side in ["left", "right"] {
            let slot = state.eye_cameras?.eyes[side]
            let context = "\(slot?.device_id ?? ""):\(slot?.rotation ?? 0):\(slot?.tracking_epoch ?? "")"
            if cameraContexts[side] != context {
                cameraMeasurements.update(side, nil, at: time)
                cameraContexts[side] = context
            }
            if slot?.connected == true,
               let vector = validMeasurement(slot?.scene_direction?.vector, count: 3),
               simd_length(SIMD3<Float>(vector.map(Float.init))) > 0.001,
               let pose = validMeasurement(slot?.scene_direction?.head_features, count: 6) {
                cameraMeasurements.update(side, vector + pose, at: time)
            } else { cameraMeasurements.update(side, nil, at: time) }
        }
        animate(at: time)
    }
    func animate(at time: Double = ProcessInfo.processInfo.systemUptime) {
        if contentView.window?.isVisible == true { rebuild(at: time) }
    }
    func invalidate() {
        state = nil
        measurements.reset()
        cameraMeasurements.reset()
        if contentView.window?.isVisible == true { rebuild() }
    }
    private func validMeasurement(_ values: [Double]?, count: Int) -> [Double]? {
        guard let values = values, values.count == count, values.allSatisfy({ $0.isFinite }) else { return nil }
        return values
    }
    private func displayedSample(_ key: String, at time: Double) -> [Double]? {
        if let sample = measurements.sample(key, at: time) { displayedMeasurements[key] = sample }
        return displayedMeasurements[key]
    }
    private func updateMetrics(_ freshRows: [String?]) {
        let text = NSMutableAttributedString(string: "")
        for i in metricLabels.indices {
            if let fresh = freshRows[i] { lastMetricRows[i] = fresh }
            let row = lastMetricRows[i] ?? "\(metricLabels[i]): –"
            let line = NSMutableAttributedString(string: (i == 0 ? "" : "\n") + row, attributes: [
                .font: metrics.font!, .foregroundColor: NSColor.white
            ])
            if freshRows[i] == nil {
                let valueStart = (line.string as NSString).range(of: ":").upperBound
                line.addAttribute(.foregroundColor, value: NSColor.gray,
                                  range: NSRange(location: valueStart, length: line.length - valueStart))
            }
            text.append(line)
        }
        metrics.attributedStringValue = text
    }
    func value(_ key: String) -> Float { Float(sliders[key]!.doubleValue) }
    func updateLabels() {
        for (key,label) in values { label.stringValue = String(format: "%@: %.1f",label.identifier!.rawValue, value(key)) }
        let fitted = state?.onboarding?.geometry_model
        sliders["distance"]?.isEnabled = fitted == nil
        sliders["ipd"]?.isEnabled = fitted == nil
        if let fitted = fitted {
            values["distance"]?.stringValue = String(format:"Fitted reference distance: %.1f cm",Float(fitted.depth_screen_widths)*value("width"))
            values["ipd"]?.stringValue = String(format:"Model eye separation: %.1f cm",eyeSeparation())
        }
        sliders["tx"]?.isEnabled = targetMode.state != .on || calibrationTarget() == nil
        sliders["ty"]?.isEnabled = sliders["tx"]?.isEnabled ?? true
    }
    @objc func changed() {
        saveSettings()
        updateLabels(); rebuild()
    }
    @objc func resetAll() {
        for (key,v) in defaults { sliders[key]?.doubleValue = v }
        targetMode.state = .on
        displayPoses.removeAll(); preferences.removeObject(forKey:Self.settingsKey)
        preferences.removeObject(forKey:"laboratoryDisplayPlacement")
        preferences.removeObject(forKey:"laboratoryDisplayPoses")
        selectDisplay(); updateLabels(); rebuild(); setView()
    }
    func calibrationTarget() -> [Double]? {
        if let cursor = state?.onboarding?.cursor_calibration, cursor.active {
            return cursor.fixed_target ?? cursor.target_position
        }
        return state?.onboarding?.target ?? state?.calibration?.target
    }
    var trackingEyeSide: String { state?.eye_cameras?.active_eye ?? "right" }
    var trackingEyeSign: Float { trackingEyeSide == "left" ? -1 : 1 }
    func eyeSeparation() -> Float {
        state?.onboarding?.geometry_model.map { Float($0.eye_separation_screen_widths)*value("width") } ?? value("ipd")
    }
    func headGeometry(_ features: [Double]) -> (SIMD3<Float>, simd_quatf) {
        let calibrated = state?.onboarding?.geometry_model
        let referenceWidth = calibrated?.reference_log_face_width ?? log(0.3)
        let distance = calibrated.map { Float($0.depth_screen_widths)*value("width") } ?? value("distance")
        let depth = distance * Float(exp(max(-0.7,min(0.7,referenceWidth-features[5]))))
        let mount = simd_quatf(angle:value("camera_pitch") * .pi/180,axis:SIMD3<Float>(1,0,0))
        // A captured reference must not straighten a physically turned head.
        let rotation = mount * AngleGeometry.headRotation(features,relativeTo: [0,0,0,0,0,0])
        let midpoint = AngleGeometry.eyeMidpoint(imageUV:[Float(features[3]),Float(features[4])],depth:depth,
            verticalFOV:value("camera_fov") * .pi/180,imageAspect:Float(calibrated?.camera_aspect ?? state?.head_camera?.image_aspect ?? 16.0/9.0),
            cameraOrigin:[value("hx"),value("width")/aspect/2+value("webcam")+value("hy"),0],
            cameraPitch:value("camera_pitch") * .pi/180)
        // The observed landmarks are the eye midpoint, not the skull center.
        let head = midpoint-rotation.act([0,2,-5.8])
        return (head,rotation)
    }
    func referenceEyeOrigin(_ features: [Double]) -> SIMD3<Float> {
        let (head,rotation) = headGeometry(features)
        return head+rotation.act([trackingEyeSign*eyeSeparation()/2+value("cx"),2+value("cy"),-5.8+value("cz")])
    }

    func drawCameraDirections(at time: Double, width: Float, height: Float) {
        let text = NSMutableAttributedString(string: "IR screen plane · estimated X/Y\n", attributes: [
            .font: cameraRayMetrics.font!, .foregroundColor: NSColor.secondaryLabelColor
        ])
        let mount = AngleGeometry.rotation(yaw:value("yaw") * .pi/180,
                                           pitch:value("pitch") * .pi/180,roll:value("roll") * .pi/180)
        for (side, color) in [("left", NSColor.magenta), ("right", NSColor.systemOrange)] {
            var row = "\(side.capitalized) IR: unavailable"
            if let observation = cameraMeasurements.sample(side, at: time) {
                let local = AngleGeometry.unit(SIMD3<Float>(observation.prefix(3).map(Float.init)))
                let (head, rotation) = headGeometry(Array(observation.suffix(6)))
                let sign: Float = side == "left" ? -1 : 1
                let offset: SIMD3<Float> = side == trackingEyeSide ? [value("cx"),value("cy"),value("cz")] : .zero
                let origin = head + rotation.act(SIMD3<Float>(sign*eyeSeparation()/2,2,-5.8) + offset)
                let direction = AngleGeometry.unit(rotation.act(mount.act([-local.x,local.y,-local.z])))
                let hit = AngleGeometry.hit(origin, direction)
                let distance = hit.map { simd_distance(origin,$0) } ?? 80
                line(origin,origin+direction*min(200,distance),alpha:0.9,radius:0.045,
                     color:color,name:"ir-camera-ray-\(side)")
                let start = ball(origin,0.20); start.name = "ir-camera-origin-\(side)"
                start.geometry?.firstMaterial?.diffuse.contents = color
                if let hit = hit {
                    let x = (hit.x/width+0.5)*100, y = (0.5-hit.y/height)*100
                    let outside = x < 0 || x > 100 || y < 0 || y > 100
                    row = String(format:"\(side.capitalized) IR: %.1f%%, %.1f%%%@",x,y,outside ? " · outside" : "")
                    if distance <= 200 {
                        let marker = ball(hit,0.18); marker.name = "ir-camera-hit-\(side)"
                        marker.geometry?.firstMaterial?.diffuse.contents = color
                    }
                } else { row = "\(side.capitalized) IR: no plane intersection" }
            }
            text.append(NSAttributedString(string:row + (side == "left" ? "\n" : ""), attributes:[
                .font:cameraRayMetrics.font!, .foregroundColor:color
            ]))
        }
        cameraRayMetrics.attributedStringValue = text
    }
    func setView() {
        sceneView.pointOfView = camera
        camera.camera?.usesOrthographicProjection = false
        camera.simdPosition = [54,34,84]; camera.look(at: SCNVector3(0,0,26))
        sceneView.defaultCameraController.target = SCNVector3(0,0,26)
        updateOutlines(camera)
    }
    func material(_ opacity: CGFloat, wire: Bool = false) -> SCNMaterial {
        let m = SCNMaterial(); m.diffuse.contents = NSColor.white; m.lightingModel = .constant
        m.transparency = opacity; m.isDoubleSided = true; m.writesToDepthBuffer = opacity > 0.8
        return m
    }
    @discardableResult func node(_ shape: SCNGeometry, _ position: SIMD3<Float>, alpha: CGFloat = 0.6, wire: Bool = false) -> SCNNode {
        shape.materials = [material(alpha,wire: wire)]
        let n = SCNNode(geometry: shape); n.simdPosition = position; geometry.addChildNode(n); return n
    }
    func ball(_ p: SIMD3<Float>, _ r: CGFloat, alpha: CGFloat = 0.8, wire: Bool = false) -> SCNNode {
        if wire {
            let n = SCNNode(); n.simdPosition = p; geometry.addChildNode(n)
            outlineLock.lock(); outlines.append((n,Float(r),material(min(0.8,alpha*4)))); outlineLock.unlock()
            return n
        }
        let sphere = SCNSphere(radius: r); sphere.segmentCount = 24
        return node(sphere,p,alpha: alpha)
    }
    func renderer(_ renderer: SCNSceneRenderer, willRenderScene scene: SCNScene, atTime time: TimeInterval) {
        if let viewpoint = renderer.pointOfView { updateOutlines(viewpoint) }
    }
    func updateOutlines(_ viewpoint: SCNNode) {
        outlineLock.lock(); let current = outlines; outlineLock.unlock()
        for (n,r,m) in current {
            let inverse = simd_inverse(n.simdWorldTransform)
            let world = viewpoint.presentation.simdWorldTransform
            let orthographic = viewpoint.camera?.usesOrthographicProjection == true
            let localCamera: simd_float4x4 = simd_mul(inverse, world)
            let sample = orthographic ? SIMD4<Float>(0,0,1,0) : SIMD4<Float>(0,0,0,1)
            let c4: SIMD4<Float> = simd_mul(localCamera, sample)
            let c = SIMD3<Float>(c4.x,c4.y,c4.z)
            let d = simd_length(c)
            guard d > (orthographic ? 0.0001 : r) else { n.geometry = nil; continue }
            let normal = c/d
            let u = AngleGeometry.unit(simd_cross(normal,abs(normal.y)>0.95 ? SIMD3<Float>(1,0,0) : SIMD3<Float>(0,1,0)))
            let v = simd_cross(normal,u)
            let center = orthographic ? SIMD3<Float>(repeating: 0) : c*(r*r/(d*d))
            let radius = orthographic ? r : r*sqrt(1-r*r/(d*d))
            let vertices = (0..<96).map { index -> SCNVector3 in
                let angle = Float(index)*2*Float.pi/96
                return SCNVector3(center+radius*(cos(angle)*u+sin(angle)*v))
            }
            let indices = (0..<96).flatMap { [UInt32($0),UInt32(($0+1)%96)] }
            let contour = SCNGeometry(sources: [SCNGeometrySource(vertices: vertices)],
                                      elements: [SCNGeometryElement(indices: indices,primitiveType: .line)])
            contour.materials = [m]; n.geometry = contour
        }
    }
    @discardableResult func line(_ a: SIMD3<Float>, _ b: SIMD3<Float>, alpha: CGFloat = 0.8, radius: CGFloat = 0.055, color: NSColor = .white, name: String? = nil) -> SCNNode? {
        let delta = b-a, length = simd_length(delta); guard length > 0.0001 else { return nil }
        let n = node(SCNCylinder(radius: radius,height: CGFloat(length)),(a+b)/2,alpha: alpha)
        n.simdOrientation = simd_quatf(from: SIMD3<Float>(0,1,0),to: delta/length)
        n.name = name; n.geometry?.firstMaterial?.diffuse.contents = color
        return n
    }
    func drawAccuracyTargets(width w: Float, height h: Float) {
        guard let report = state?.onboarding?.accuracy_check else { return }
        let group = SCNNode(); group.name = "accuracy-check-markers"; geometry.addChildNode(group)
        let targets = report.targets ?? report.rows.map { $0.target }
        func position(_ uv: [Double]) -> SIMD3<Float> {
            [(Float(min(1,max(0,uv[0])))-0.5)*w,(0.5-Float(min(1,max(0,uv[1]))))*h,0.12]
        }
        func add(_ shape: SCNGeometry, _ point: SIMD3<Float>, _ color: NSColor, _ alpha: CGFloat = 1) -> SCNNode {
            let surface = material(alpha); surface.diffuse.contents = color
            shape.materials = [surface]
            let item = SCNNode(geometry: shape); item.simdPosition = point; group.addChildNode(item)
            return item
        }
        for (index, uv) in targets.enumerated() {
            guard uv.count == 2, uv.allSatisfy({ $0.isFinite }) else { continue }
            let row = report.rows.first { $0.target == uv }
            let measured = row?.measured.flatMap { validMeasurement($0,count:2) }
            let complete = measured != nil && (row?.samples ?? 0) > 0
            let missing = !complete && (row != nil || report.status == "incomplete")
            let active = !complete && !missing && report.status == "checking" && index+1 == report.target_index
            let point = position(uv)
            let radius: CGFloat = active ? 0.36 : 0.27
            if complete {
                let marker = add(SCNCylinder(radius:radius,height:0.035),point,.systemGreen)
                marker.eulerAngles.x = .pi/2; marker.name = "accuracy-measured-\(index)"
            } else if missing {
                for sign in [Float(-1),Float(1)] {
                    if let cross = line(point+[-0.24,sign*0.24,0],point+[0.24,-sign*0.24,0],
                                        radius:0.045,color:.systemRed,name:"accuracy-missing-\(index)") {
                        group.addChildNode(cross)
                    }
                }
            } else {
                let ring = SCNTorus(ringRadius:radius,pipeRadius:0.035)
                let marker = add(ring,point,.white,active ? 1 : 0.45)
                marker.eulerAngles.x = .pi/2; marker.name = "accuracy-pending-\(index)"
            }
            if let estimate = measured, complete {
                let endpoint = position(estimate)+SIMD3<Float>(0,0,0.06)
                if let offset = line(point,endpoint,radius:0.025,color:.systemOrange,name:"accuracy-offset-\(index)") {
                    group.addChildNode(offset)
                }
                let dot = add(SCNCylinder(radius:0.14,height:0.04),endpoint,.systemOrange)
                dot.eulerAngles.x = .pi/2; dot.name = "accuracy-estimate-\(index)"
            }
            let text = SCNText(string:row?.error_points.map { String(format:"%.0f pt",$0) } ?? (missing ? "Missing" : ""),extrusionDepth:0)
            text.font = .systemFont(ofSize:0.65,weight:.medium); text.flatness = 0.1
            let label = add(text,point+[-0.55,0.5,0],.white)
            label.name = "accuracy-label-\(index)"
        }
    }

    func rebuild(at time: Double = ProcessInfo.processInfo.systemUptime) {
        updateLabels()
        outlineLock.lock(); outlines.removeAll(); outlineLock.unlock()
        geometry.childNodes.filter { $0 !== referenceGeometry }.forEach { $0.removeFromParentNode() }
        let w = value("width"), h = w/aspect
        node(SCNPlane(width: CGFloat(w),height: CGFloat(h)),[0,0,0],alpha: 0.07)
        let corners: [SIMD3<Float>] = [[-w/2,-h/2,0],[w/2,-h/2,0],[w/2,h/2,0],[-w/2,h/2,0]]
        for i in 0..<4 { line(corners[i],corners[(i+1)%4],alpha: 0.65) }
        for i in 1..<4 {
            let x = -w/2+w*Float(i)/4, y = -h/2+h*Float(i)/4
            line([x,-h/2,0],[x,h/2,0],alpha: 0.12,radius: 0.025)
            line([-w/2,y,0],[w/2,y,0],alpha: 0.12,radius: 0.025)
        }
        for display in connectedDisplays {
            let (center,rotation,dw,dh) = displayTransform(display)
            if display.id != anchorDisplay?.id {
                let surface = node(SCNPlane(width: CGFloat(dw), height: CGFloat(dh)), center, alpha: 0.07)
                surface.simdOrientation = rotation; surface.name = "display-\(display.id)"
                let corners: [SIMD3<Float>] = [[-dw/2,-dh/2,0],[dw/2,-dh/2,0],[dw/2,dh/2,0],[-dw/2,dh/2,0]]
                for i in 0..<4 {
                    line(center+rotation.act(corners[i]), center+rotation.act(corners[(i+1)%4]), alpha: 0.65)
                }
            }
            let text = SCNText(string:display.name,extrusionDepth:0)
            text.font = .systemFont(ofSize:1.2); text.flatness = 0.3
            let label = node(text,center+rotation.act([-dw/2,dh/2+1,0]),alpha:0.65)
            label.simdOrientation = rotation
        }
        if anchorDisplay?.builtin == true {
            // Passive laptop base; no keys, input handling, or gaze targets.
            let depth = w*0.65
            let base = node(SCNBox(width:CGFloat(w),height:0.35,length:CGFloat(depth),chamferRadius:0.2),
                            [0,-h/2-0.3,depth/2],alpha:0.18)
            base.name = "laptop-keyboard-reference"
            let deck: [SIMD3<Float>] = [[-w/2,-h/2,0],[w/2,-h/2,0],[w/2,-h/2,depth],[-w/2,-h/2,depth]]
            for i in 0..<4 { line(deck[i],deck[(i+1)%4],alpha:0.4) }
            let keys = node(SCNBox(width:CGFloat(w*0.84),height:0.05,length:CGFloat(depth*0.45),chamferRadius:0.3),
                            [0,-h/2,depth*0.35],alpha:0.14)
            keys.name = "keyboard-surface"
            node(SCNBox(width:CGFloat(w*0.32),height:0.05,length:CGFloat(depth*0.24),chamferRadius:0.4),
                 [0,-h/2,depth*0.77],alpha:0.16)
        }
        let webcam = SIMD3<Float>(0,h/2+value("webcam"),0)
        node(SCNBox(width: 2.4,height: 1.2,length: 0.7,chamferRadius: 0.2),webcam,alpha: 0.4)
        let referenceKey = "\(trackingEyeSide)|\(state?.onboarding?.geometry_model?.depth_screen_widths ?? 0):\(state?.onboarding?.geometry_model?.reference_log_face_width ?? 0)|\(state?.onboarding?.calibration_session_id ?? "")|\(savedReferences.count):\(savedReferences.last?.id ?? 0)|\(aspect)|\(state?.head_camera?.image_aspect ?? 16.0/9.0)|\(sliders.keys.sorted().map { value($0) })"
        if referenceKey != referenceGeometryKey {
            referenceGeometryKey = referenceKey
            referenceGeometry.childNodes.forEach { $0.removeFromParentNode() }
            referenceOrigins.removeAll()
            var vertices: [SCNVector3] = []
            for sample in savedReferences where sample.head.count == 6 && sample.target.count == 2 && (sample.head+sample.target).allSatisfy({ $0.isFinite }) {
                let start = referenceEyeOrigin(sample.head)
                let end = SIMD3<Float>((Float(sample.target[0])-0.5)*w,(0.5-Float(sample.target[1]))*h,0)
                referenceOrigins[sample.id] = start
                vertices.append(SCNVector3(start)); vertices.append(SCNVector3(end))
            }
            if !vertices.isEmpty {
                let indices = vertices.indices.map(UInt32.init)
                let lines = SCNGeometryElement(indices:indices,primitiveType:.line)
                let points = SCNGeometryElement(indices:indices,primitiveType:.point)
                points.pointSize = 3; points.minimumPointScreenSpaceRadius = 1; points.maximumPointScreenSpaceRadius = 2
                let all = SCNGeometry(sources:[SCNGeometrySource(vertices:vertices)],elements:[lines,points])
                // Saved evidence stays visible through the translucent scene surfaces.
                all.materials = [material(0.25),material(0.25)]
                all.materials.forEach { $0.readsFromDepthBuffer = false; $0.writesToDepthBuffer = false }
                let batch = SCNNode(geometry:all); batch.name = "saved-reference-rays"; batch.renderingOrder = 20
                referenceGeometry.addChildNode(batch)
            }
        }
        drawAccuracyTargets(width:w,height:h)
        let targetUV = targetMode.state == .on ? calibrationTarget() : nil
        let u = Float(targetUV?.first ?? Double(value("tx")/100)), v = Float(targetUV?.last ?? Double(value("ty")/100))
        let target = SIMD3<Float>((u-0.5)*w,(0.5-v)*h,0); lastTarget = target
        _ = ball(target,0.30)
        drawCameraDirections(at: time, width: w, height: h)
        let liveHead = measurements.sample("head", at: time) != nil
        guard let features = displayedSample("head", at: time) else {
            alignmentOffset = nil
            updateMetrics(Array(repeating: nil, count: 5))
            updateOutlines(sceneView.pointOfView ?? camera)
            return
        }
        let (head,rotation) = headGeometry(features)
        let eyeRadius: CGFloat = 1.2
        let skull = ball(head,1,alpha: 0.12,wire: true); skull.simdScale = [7.7,10,7]; skull.simdOrientation = rotation
        skull.name = "tracked-head"
        let other = head+rotation.act([-trackingEyeSign*eyeSeparation()/2,2,-5.8]); _ = ball(other,eyeRadius,alpha: 0.19,wire: true)
        let nominal = head+rotation.act([trackingEyeSign*eyeSeparation()/2,2,-5.8])
        let eye = nominal+rotation.act([value("cx"),value("cy"),value("cz")]); lastEye = eye
        let expected = AngleGeometry.unit(target-eye)
        _ = ball(nominal,0.13,alpha: 0.35)
        _ = ball(eye,eyeRadius,alpha: 0.19,wire: true)
        _ = ball(eye,0.17)
        let mount = AngleGeometry.rotation(yaw: value("yaw") * .pi/180,pitch: value("pitch") * .pi/180,roll: value("roll") * .pi/180)
        var direction: SIMD3<Float>?
        let liveEye = measurements.sample("eye", at: time) != nil
        if targetUV != nil, liveHead, state?.onboarding?.sample_accepted == true || state?.onboarding?.cursor_calibration?.sample_accepted == true {
            // Highlight only the measurement being made now. Accepted samples
            // remain in the separate, faint history batch.
            line(eye,target,alpha: 0.9,radius: 0.045,name: "current-target-reference")
        }
        let liveCenter = measurements.sample("center", at: time) != nil
        let livePupil = measurements.sample("pupil", at: time) != nil
        let eyeVector = displayedSample("eye", at: time)
        let center = displayedSample("center", at: time)
        let pupilCenter = displayedSample("pupil", at: time)
        if let vector = eyeVector, vector.count == 3,
                  simd_length(SIMD3<Float>(vector.map(Float.init))) > 0.001 {
            var local = AngleGeometry.unit(SIMD3<Float>(vector.map(Float.init)))
            if value("px") != 0 || value("py") != 0,
               let c = center, c.count == 2, let p = pupilCenter, p.count == 2 {
                local = AngleGeometry.cameraRay(pupil: SIMD2<Float>(p.map(Float.init)),
                                                center: SIMD2<Float>(c.map(Float.init))+[value("px"),value("py")])
            }
            // The estimator uses x/right, y/up, z/towards its camera. Rotate 180
            // degrees about Y for an assumed front-facing mount; offsets remain explicit.
            direction = AngleGeometry.unit(rotation.act(mount.act([-local.x,local.y,-local.z])))
        }
        var freshMetrics: [String?] = Array(repeating: nil, count: 5)
        if liveHead { freshMetrics[2] = String(format: "\(trackingEyeSide.capitalized) eye: %.1f, %.1f, %.1f cm",eye.x,eye.y,eye.z) }
        if liveCenter, let c = center {
            freshMetrics[3] = String(format: "IR center: %.1f, %.1f px",c[0],c[1])
            if livePupil, let p = pupilCenter {
                freshMetrics[4] = String(format: "Pupil offset: %+.1f, %+.1f px",p[0]-c[0],p[1]-c[1])
            }
        }
        if let direction = direction {
            let pupil = eye + direction * Float(eyeRadius)
            _ = ball(pupil,0.35); line(eye,pupil,radius: 0.09)
            let hit = AngleGeometry.hit(eye,direction)
            // Raw mounting geometry is not the calibrated screen map. Keep the
            // diagnostic ray short instead of sending an apparent gaze beam off screen.
            line(eye,eye+direction*5,alpha: 0.35, name: "ir-direction")
            alignmentOffset = AngleGeometry.alignment(expected,direction)
            let error = AngleGeometry.angle(expected,direction)
            let miss = hit.map { String(format: "Plane miss: %.1f cm%@",simd_distance($0,target), abs($0.x)>w/2 || abs($0.y)>h/2 ? " (off screen)" : "") } ?? "Plane miss: –"
            if liveHead && liveEye && ((value("px") == 0 && value("py") == 0) || (liveCenter && livePupil)) {
                freshMetrics[0] = String(format: "Angular difference: %.2f°",error)
                freshMetrics[1] = miss
            }
        } else {
            alignmentOffset = nil
        }
        updateMetrics(freshMetrics)
        // Each webcam iris supplies its own approximate direction. The target
        // must never steer these measurements or force binocular convergence.
        let webcamOrigins = trackingEyeSide == "left" ? [other,eye] : [eye,other]
        for (i, origin) in webcamOrigins.enumerated() {
            guard let ray = displayedSample("ray\(i)", at: time),
                  simd_length(SIMD3<Float>(ray.map(Float.init))) > 0.001 else { continue }
            let direction = AngleGeometry.unit(rotation.act(SIMD3<Float>(ray.map(Float.init))))
            let hit = AngleGeometry.hit(origin,direction)
            let distance = hit.map { simd_distance(origin,$0) } ?? 80
            let end = origin+direction*min(200,distance)
            line(origin,end,alpha: 0.55,radius: 0.035,color: .systemCyan,name: "webcam-eye-\(i)")
            if let hit = hit, distance <= 200 {
                let marker = ball(hit,0.18,alpha: 0.8); marker.name = "webcam-screen-hit-\(i)"
                marker.geometry?.firstMaterial?.diffuse.contents = NSColor.systemCyan
            }
        }
        let rawGaze = displayedSample("rawGaze", at: time)
        let freshRay = state?.valid == true && liveHead && (measurements.sample("rawGaze",at: time) != nil || liveEye)
        let dt = max(0,min(1,time-(lastRayTime ?? time))); lastRayTime = time
        rayQuality += (Float(freshRay ? 1 : 0)-rayQuality) * Float(1-exp(-dt/0.25))
        let rayColor = NSColor.systemRed.blended(withFraction: CGFloat(rayQuality), of: .systemGreen) ?? .systemRed
        let rayEnd: SIMD3<Float>
        if let uv = rawGaze {
            if let anchor = anchorDisplay, let primary = NSScreen.screens.first,
               let endpoint = sceneDesktopPoint([Double(anchor.frame.minX)+uv[0]*Double(anchor.frame.width),
                    Double(primary.frame.maxY-anchor.frame.maxY)+uv[1]*Double(anchor.frame.height)]) {
                rayEnd = endpoint
            } else { rayEnd = [(Float(uv[0])-0.5)*w,(0.5-Float(uv[1]))*h,0] }
        } else {
            rayEnd = eye+(direction ?? rotation.act([0,0,-1]))*80
        }
        let rayDelta = rayEnd-eye
        let boundedEnd = eye+AngleGeometry.unit(rayDelta)*min(200,simd_length(rayDelta))
        line(eye,boundedEnd,alpha: 0.9,radius: 0.065,color: rayColor,name: "live-gaze-ray")
        let rayOrigin = ball(eye,0.23,alpha: 1); rayOrigin.name = "live-gaze-origin"
        rayOrigin.geometry?.firstMaterial?.diffuse.contents = rayColor
        if let state = state, state.calibrated, state.display_valid ?? state.valid,
           let point = state.desktop_gaze, let hit = sceneDesktopPoint(point) {
            let marker = ball(hit,0.45,alpha: 1); marker.name = "calibrated-screen-gaze"
            marker.geometry?.firstMaterial?.diffuse.contents = NSColor.systemGreen
            marker.geometry?.firstMaterial?.emission.contents = NSColor.systemGreen
        }
        if !liveHead || (!liveEye && eyeVector != nil) {
            alignmentOffset = nil
        }
        updateOutlines(sceneView.pointOfView ?? camera)
    }
}
