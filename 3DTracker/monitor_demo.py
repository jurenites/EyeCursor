"""Local single-eye monitor calibration using the original 3DTracker output."""

import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
import plistlib
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
import webbrowser

import cv2
import numpy as np

import Orlosky3DEyeTracker as tracker
from eye_gestures import FixationDoubleBlink
from gaze_mapping import desktop_fence
from live_capture import ReconnectingCapture
from eye_cameras import EyeCameraRig
from binocular_tracking import CompanionEyeTracker
from eye_model import EyeModelCalibration
from eye_geometry import DetectionLatch
from screen_gaze import ScreenGazeMotion
from onboarding import Onboarding
from head_camera import HeadCamera, MODEL_PATH
from hybrid_onboarding import HybridOnboarding
from app_version import versioned_build


TARGETS = {
    "top_left": (0.08, 0.08),
    "top_right": (0.92, 0.08),
    "bottom_right": (0.92, 0.92),
    "bottom_left": (0.08, 0.92),
}
MIN_CONFIDENCE = 0.50
AUTO_TARGETS = ["center", *TARGETS]
HOLD_SECONDS = 1.0
HOLD_WINDOW_SECONDS = 1.5
DETECTION_GRACE_SECONDS = 0.15
MIN_HOLD_COVERAGE = 0.8
MIN_TARGET_MOVEMENT = 0.025
MAX_FEATURE_SPREAD = 0.012
MAX_CENTER_ERROR_PERCENT = 10
TARGET_TRAVEL_SECONDS = 0.55
DISPLAY_GRACE_SECONDS = 0.25


def validate_viewport(viewport):
    if (not isinstance(viewport, list) or len(viewport) != 4
            or not all(type(value) in (int, float) and math.isfinite(value) for value in viewport)
            or not all(0 < value <= 20000 for value in viewport[2:])):
        raise ValueError("A valid display area is required for calibration")


def list_mac_cameras():
    """List devices in the same uniqueID order as OpenCV's AVFoundation backend."""
    cache = Path(__file__).resolve().parents[1] / ".venv" / "swift-cache"
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CLANG_MODULE_CACHE_PATH"] = str(cache)
    env["SWIFT_MODULE_CACHE_PATH"] = str(cache)
    command = ["/usr/bin/swift", "-suppress-warnings", "-module-cache-path", str(cache),
               str(Path(__file__).with_name("list_cameras.swift"))]
    try:
        completed = subprocess.run(command, env=env, capture_output=True, text=True,
                                   check=True, timeout=30)
        return json.loads(completed.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise SystemExit(f"Could not enumerate macOS cameras: {error}") from error


def choose_usb_camera(cameras, requested_index=None, requested_id=None):
    """Never fall back to an iPhone or built-in camera."""
    matches = [camera for camera in cameras
               if "usb" in camera["name"].lower() and "camera" in camera["name"].lower()]
    if requested_id:
        matches = [camera for camera in matches if camera["id"] == requested_id]
    if requested_index is not None:
        matches = [camera for camera in matches if camera["index"] == requested_index]
    if len(matches) != 1:
        found = ", ".join(f'{camera["index"]}: {camera["name"]}' for camera in cameras) or "none"
        raise ValueError(f"Expected exactly one USB eye camera, found {len(matches)}. Visible cameras: {found}. "
                         "Reconnect the USB camera or use --list-cameras and --camera-id to identify it.")
    return matches[0]


class USBCameraSource:
    """Resolve indices anew, but bind retries to the first selected device ID."""
    def __init__(self, requested_index=None, requested_id=None):
        self.requested_index = requested_index
        self.device_id = requested_id
        self.name = "USB eye camera"

    def open(self):
        try:
            cameras = list_mac_cameras()
        except SystemExit as error:
            raise RuntimeError(str(error)) from error
        selected = choose_usb_camera(cameras,
                                     None if self.device_id else self.requested_index,
                                     self.device_id)
        self.device_id = selected["id"]
        self.name = selected["name"]
        print(f'Opening {self.name} [{self.device_id}] at index {selected["index"]}', flush=True)
        return cv2.VideoCapture(selected["index"], cv2.CAP_AVFOUNDATION)


def usable(result, threshold=MIN_CONFIDENCE):
    return bool(result and result.get("pupil_ellipse") and result.get("gaze_direction")
                and result.get("confidence", 0) >= threshold)


def render_diagnostic_frame(frame, result, eye_region=None, threshold=MIN_CONFIDENCE, display_result=None, display_accepted=None, hybrid=False, eye_model_ready=False):
    """Show the detector's candidate and model direction on the raw eye image."""
    # Text and confidence are presented by the UI outside this image.
    result = display_result or result
    image = tracker.crop_to_aspect_ratio(frame).copy()
    height, width = image.shape[:2]
    accepted = usable(result, threshold) if display_accepted is None else display_accepted
    if eye_region:
        x0, y0, x1, y1 = eye_region
        cv2.rectangle(image, (round(x0 * width), round(y0 * height)),
                      (round(x1 * width), round(y1 * height)), (255, 210, 0), 2)
    if result:
        iris = result.get("iris_ellipse")
        if iris and iris.get("center") and iris.get("axes"):
            cv2.ellipse(image, (tuple(iris["center"]), tuple(iris["axes"]), iris["angle_degrees"]),
                        (200, 175, 80), 1)
        ellipse = result.get("pupil_ellipse")
        if ellipse and ellipse.get("center") and ellipse.get("axes"):
            center = tuple(round(value) for value in ellipse["center"])
            fitted = (tuple(ellipse["center"]), tuple(ellipse["axes"]), ellipse["angle_degrees"])
            cv2.ellipse(image, fitted, (40, 220, 40) if accepted else (40, 70, 255), 2)
            cv2.circle(image, center, 4, (40, 220, 40) if accepted else (40, 70, 255), -1)
            if eye_model_ready and accepted and result.get("eye_center") and result.get("eye_model_estimated", False):
                eye_center = tuple(result["eye_center"])
                cv2.circle(image, eye_center, 5, (255, 230, 60), -1)
                radius = round(result.get("sphere_radius", 0))
                if 0 < radius < max(width, height) * 2:
                    cv2.circle(image, eye_center, radius, (255, 230, 60), 1)
                dx, dy = center[0] - eye_center[0], center[1] - eye_center[1]
                length = math.hypot(dx, dy)
                if length > 2:
                    # A near-axial view must have a short projected arrow. The
                    # old fixed 90 px extension exaggerated even tiny offsets.
                    scale = min(2.0, 140.0 / length)
                    tip = (round(eye_center[0] + dx * scale),
                           round(eye_center[1] + dy * scale))
                    cv2.arrowedLine(image, eye_center, tip, (0, 255, 0), 3, tipLength=0.17)
        seed = result.get("seed_point")
        if seed:
            cv2.drawMarker(image, tuple(seed), (255, 0, 255), cv2.MARKER_CROSS, 12, 1)
    return image


class Calibration:
    def __init__(self, source, desktop_cursor=False, require_eye_model=False):
        self.detection_threshold = MIN_CONFIDENCE
        self.last_accepted = None
        self.last_display = None
        self.detection_latch = DetectionLatch()
        self.screen_motion = ScreenGazeMotion()
        self.source = source
        self.lock = threading.RLock()
        self.samples = deque(maxlen=120)
        self.hold_frames = deque(maxlen=240)
        self.latest = None
        self.corners = {}
        self.matrix = None
        self.center_error = None
        self.desktop_cursor = desktop_cursor
        self.viewport = None
        self.native = None
        self.target_since = 0
        self.center_sample = None
        self.previous_fixation = None
        self.awaiting_movement = False
        self.blink_click_enabled = False
        self.gesture = FixationDoubleBlink()
        self.click_event = None
        self.click_serial = 0
        self.diagnostic_jpeg = None
        self.diagnostic_raw_frame = None
        self.diagnostic_lock = threading.Lock()
        self.frame_times = deque(maxlen=90)
        self.preview_times = deque(maxlen=90)
        self.eye_region = None
        self.eye_model = EyeModelCalibration(self.detection_threshold)
        self.require_eye_model = require_eye_model
        self.onboarding = None
        self.head_camera = None
        self.eye_camera_id = None
        self.eye_cameras = None
        self.last_reported_phase = None

    def configure_eye_cameras(self, settings):
        if self.eye_cameras is None:
            raise ValueError("Two-eye setup is available in native USB camera mode")
        with self.lock:
            before = self.eye_cameras.context()
            self.eye_cameras.configure(settings)
            if before != self.eye_cameras.context():
                self.source = self.eye_cameras.name
                self.eye_camera_id = self.eye_cameras.device_id
                if self.onboarding:
                    self.onboarding.source_key = self.eye_camera_id
                    rotation = self.eye_cameras.context()[2] == 180
                    self.onboarding.orientation = (rotation, rotation)
                self.set_eye_region(None)
                with self.diagnostic_lock:
                    self.diagnostic_raw_frame = None
                    self.diagnostic_jpeg = None

    def usable(self, result):
        if self.onboarding and getattr(self.onboarding, 'hybrid', False):
            return bool(result and result.get('confidence', 0) >= self.detection_threshold
                        and self.onboarding.observation(result) is not None)
        return usable(result, self.detection_threshold)

    def feature(self, result):
        if self.onboarding and getattr(self.onboarding, 'hybrid', False):
            return self.onboarding.feature(result)
        return result['gaze_direction'][:2] if result and result.get('gaze_direction') else None

    def update_screen_motion(self):
        """Consume each measured display sample once, independently of HTTP polling."""
        calibrated = ((self.onboarding.has_screen_mapping if getattr(self.onboarding, 'hybrid', False)
                       else self.onboarding.phase == 'complete') if self.onboarding else
                      self.matrix is not None and (not self.native or self.native['phase'] == 'complete'))
        if not calibrated or not self.latest:
            self.screen_motion.reset()
            return
        result = self.latest['result']
        if not self.usable(result) and self.last_display is not self.latest:
            self.screen_motion.interrupt_confirmation()
            return
        feature = self.feature(result)
        desktop = (self.onboarding.desktop_point(feature) if self.onboarding else
                   self.desktop_point(self.map_gaze(feature)))
        if desktop is None:
            self.screen_motion.reset()
            return
        displays = ([d['viewport'] for d in self.onboarding.displays] if self.onboarding else [self.viewport])
        viewport = next((v for v in displays if v and v[0] <= desktop[0] <= v[0]+v[2]
                         and v[1] <= desktop[1] <= v[1]+v[3]), None)
        if viewport is None:
            self.screen_motion.reset()
            return
        alignment = getattr(self.onboarding, 'cursor_calibration', None)
        mapping = (alignment.candidate if alignment and alignment.active and alignment.candidate is not None
                   else getattr(self.onboarding, 'mapping', None))
        context = (self.source, self.eye_camera_id, id(self.onboarding),
                   id(mapping) if self.onboarding else id(self.matrix),
                   tuple(tuple(v) for v in displays))
        self.screen_motion.update(desktop, viewport, self.latest['time'], context)

    def set_detection_threshold(self, value):
        if type(value) not in (int, float) or not math.isfinite(value) or not .2 <= value <= .95:
            raise ValueError("Detection threshold must be between 0.20 and 0.95")
        with self.lock:
            self.detection_threshold = float(value)
            self.eye_model.threshold = float(value)
            self.samples.clear()
            self.hold_frames.clear()
            self.last_accepted = None
            self.last_display = None
            self.detection_latch.reset()
            self.screen_motion.reset()
            self.gesture.reset()
            self.click_event = None

    def start_eye_model(self):
        if self.source == "video demo":
            raise ValueError("Use the live eye camera for eye calibration")
        with self.lock:
            self.reset()
            tracker.reset_tracking_state()
            self.latest = None
            self.diagnostic_jpeg = None
            self.eye_model.start()

    def freeze_eye_model(self):
        with self.lock:
            if not self.latest or time.monotonic() - self.latest["time"] >= .5:
                raise ValueError("Wait for a fresh eye camera frame before fixing the eye model")
            self.eye_model.freeze(time.monotonic())
            tracker.eye_sphere_adjustment_enabled = False
            self.samples.clear()
            self.hold_frames.clear()

    def reset_eye_model(self):
        with self.lock:
            self.reset()
            tracker.reset_tracking_state()
            self.eye_model = EyeModelCalibration(self.detection_threshold)
            self.latest = None
            self.diagnostic_jpeg = None

    def set_eye_region(self, region):
        if region is not None:
            if (not isinstance(region, list) or len(region) != 4
                    or not all(type(value) in (int, float) and math.isfinite(value)
                               and 0 <= value <= 1 for value in region)
                    or region[2] - region[0] < 0.125 or region[3] - region[1] < 0.125):
                raise ValueError("Select an eye area at least 1/8 of the image width and height")
        with self.lock:
            self.eye_region = tuple(region) if region is not None else None
            tracker.eye_region = self.eye_region
            self.reset_eye_model()
            if self.onboarding:
                self.onboarding.arm()

    def set_diagnostic_frame(self, frame, result, camera_context=None, camera_sample=None):
        # Keep an unannotated frame for inspecting reflection/edge failures.
        # Encoding is on demand, so ordinary previews pay only for this copy.
        raw = tracker.crop_to_aspect_ratio(frame).copy()
        previous = self.last_display
        held = (previous["result"] if previous
                and time.monotonic() - previous["time"] <= DISPLAY_GRACE_SECONDS else None)
        image = render_diagnostic_frame(frame, result, self.eye_region, self.detection_threshold,
                                        held, True if held else None, hybrid=self.head_camera is not None,
                                        eye_model_ready=self.eye_model.phase == "ready")
        ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 78])
        if ok:
            with self.diagnostic_lock:
                if camera_context is not None and self.eye_cameras.context() != camera_context:
                    return
                self.diagnostic_jpeg = jpeg.tobytes()
                self.diagnostic_raw_frame = raw
                self.preview_times.append(time.monotonic())
            if camera_sample is not None:
                self.eye_cameras.publish_tracking(camera_context[0], camera_sample, result,
                                                   jpeg.tobytes(), self.detection_threshold)

    @staticmethod
    def frame_rate(stamps, now):
        if len(stamps) < 2 or now - stamps[-1] > .5 or stamps[-1] <= stamps[0]:
            return 0.0
        return round((len(stamps) - 1) / (stamps[-1] - stamps[0]), 1)

    def add_frame(self, result):
        now = time.monotonic()
        with self.lock:
            self.frame_times.append(now)
            self.latest = {"time": now, "result": result}
            candidate = bool(result and result.get("pupil_ellipse") and result.get("gaze_direction"))
            if self.detection_latch.update(result.get("confidence", 0) if result else 0,
                                           candidate, self.detection_threshold, now):
                self.last_display = self.latest
            if self.usable(result):
                self.last_accepted = self.latest
            self.eye_model.observe(result, now)
            if self.usable(result):
                self.samples.append((now, self.feature(result)))
            if self.native and self.native["phase"] == "collecting":
                feature = self.feature(result) if self.usable(result) else None
                self.hold_frames.append((now, feature))
            self.advance_native(now)
            if self.onboarding:
                self.onboarding.update(result, now)
            self.update_screen_motion()
            if (self.blink_click_enabled and self.desktop_cursor and self.source != "video demo"
                    and ((self.onboarding and self.onboarding.phase == "complete")
                         or (not self.onboarding and self.native and self.native["phase"] == "complete"))):
                if self.onboarding:
                    point = self.onboarding.desktop_point(self.feature(result)) if self.usable(result) else None
                else:
                    point = self.desktop_point(self.map_gaze(result["gaze_direction"][:2])) if self.usable(result) else None
                if not self.screen_motion.accepted:
                    point = None
                destination = self.gesture.update(now, point, not result or not result.get("pupil_ellipse"))
                if destination is not None:
                    self.click_serial += 1
                    self.click_event = {"id": self.click_serial, "point": destination, "time": now}
            else:
                self.gesture.reset()
                self.click_event = None

    def interrupt_stream(self):
        with self.lock:
            self.screen_motion.reset()
            self.latest = None
            self.last_accepted = None
            self.last_display = None
            self.detection_latch.reset()
            self.samples.clear()
            self.hold_frames.clear()
            self.gesture.reset()
            self.click_event = None
            self.eye_model.last_good = None
            self.eye_model.estimates.clear()
            if self.native and self.native["phase"] == "collecting":
                self.native["progress"] = 0

    def start_native(self, viewport):
        validate_viewport(viewport)
        if self.source == "video demo":
            raise ValueError("Connect the live eye camera to calibrate. Sample video is for tracking checks only.")
        with self.lock:
            if self.eye_model.phase != "ready":
                raise ValueError("Complete step 1 in Eye camera diagnostics and choose Use eye model first")
            self.reset()
            self.viewport = viewport
            self.native = {"phase": "collecting", "step": 0, "target": [0.5, 0.5],
                           "progress": 0, "message": "Look at the white dot"}
            self.target_since = time.monotonic() + TARGET_TRAVEL_SECONDS

    def advance_native(self, now):
        """Collect only steady, recent gaze after time to find each new target."""
        if not self.native or self.native["phase"] != "collecting":
            return
        self.native["progress"] = 0
        if now < self.target_since:
            self.samples.clear()
            self.hold_frames.clear()
            return
        if self.awaiting_movement:
            feature = self.hold_frames[-1][1] if self.hold_frames else None
            self.samples.clear()
            self.hold_frames.clear()
            if feature is not None and np.linalg.norm(np.array(feature) - self.previous_fixation) >= MIN_TARGET_MOVEMENT:
                self.awaiting_movement = False
                self.target_since = now
            self.native["message"] = "Move your gaze to the dot, then hold it still"
            return
        frames = [(stamp, feature) for stamp, feature in self.hold_frames
                  if now - stamp < HOLD_WINDOW_SECONDS and stamp >= self.target_since]
        recent = [(stamp, feature) for stamp, feature in frames if feature is not None]
        if not recent or now - recent[-1][0] > DETECTION_GRACE_SECONDS:
            self.samples.clear()
            self.hold_frames.clear()
            self.native["message"] = "Pupil not detected clearly. Adjust the eye camera and look at the dot."
            return
        if len(recent) < 2:
            self.native["message"] = "Hold your gaze on the dot"
            return
        if (any(right[0] - left[0] > 0.2 for left, right in zip(frames, frames[1:]))
                or any(right[0] - left[0] > DETECTION_GRACE_SECONDS
                       for left, right in zip(recent, recent[1:]))):
            self.samples.clear()
            self.hold_frames.clear()
            return
        if np.max(np.std([feature for _, feature in recent], axis=0)) > MAX_FEATURE_SPREAD:
            self.samples.clear()
            self.hold_frames.clear()
            self.native["message"] = "Hold your gaze on the dot"
            return
        # Only intervals with confident detections at both ends contribute.
        # Brief misses pause the ring; neither missing nor low-confidence frames
        # contribute time or gaze coordinates to the fit.
        duration = sum(right[0] - left[0] for left, right in zip(frames, frames[1:])
                       if left[1] is not None and right[1] is not None)
        self.native["progress"] = min(1, duration / HOLD_SECONDS)
        self.native["message"] = "Hold your gaze on the dot"
        coverage = duration / (now - recent[0][0])
        if (duration < HOLD_SECONDS or len(recent) < 8 or coverage < MIN_HOLD_COVERAGE
                or frames[-1][1] is None):
            return
        name = AUTO_TARGETS[self.native["step"]]
        feature = [statistics.median(values) for values in zip(*(item[1] for item in recent))]
        try:
            if name == "center":
                self.center_sample = feature
                self.samples.clear()
                self.hold_frames.clear()
            else:
                self.capture(name, self.viewport, automatic=True)
            if self.native["step"] == len(AUTO_TARGETS) - 1:
                prediction = self.map_gaze(self.center_sample)
                if prediction is None:
                    raise ValueError("Could not validate the center. Please try again.")
                self.center_error = [round(abs(value - 0.5) * 100, 1) for value in prediction]
                if max(self.center_error) > MAX_CENTER_ERROR_PERCENT:
                    raise ValueError("The center check was too far off. Adjust the camera and try again.")
                self.desktop_cursor = True
                self.native.update(phase="complete", target=None, progress=1,
                                   message="Eye-cursor is ready. Use its menu-bar circle to recalibrate or quit.")
            else:
                self.previous_fixation = np.array(feature)
                self.awaiting_movement = True
                self.native["step"] += 1
                next_name = AUTO_TARGETS[self.native["step"]]
                self.native.update(target=list(TARGETS[next_name]), progress=0,
                                   message="Move your gaze to the dot")
                self.target_since = now + TARGET_TRAVEL_SECONDS
        except ValueError as error:
            self.matrix = None
            self.native.update(phase="retry", target=None, progress=0, message=str(error))

    def map_gaze(self, feature):
        if self.matrix is None:
            return None
        point = np.array([[[feature[0], feature[1]]]], dtype=np.float32)
        mapped = cv2.perspectiveTransform(point, self.matrix)[0, 0]
        if not np.isfinite(mapped).all():
            return None
        return [float(mapped[0]), float(mapped[1])]

    def state(self):
        with self.lock:
            if self.onboarding:
                self.onboarding.tick()
            latest = self.latest
            result = latest["result"] if latest else None
            fresh = bool(latest and time.monotonic() - latest["time"] < 0.5)
            valid = bool(fresh and self.usable(result))
            calibrated = self.matrix is not None and (not self.native or self.native["phase"] == "complete")
            mapped = self.map_gaze(result["gaze_direction"][:2]) if valid and calibrated else None
            desktop = self.desktop_point(mapped)
            if self.onboarding:
                calibrated = (self.onboarding.has_screen_mapping if getattr(self.onboarding,"hybrid",False)
                              else self.onboarding.phase == "complete")
                desktop = self.onboarding.desktop_point(self.feature(result)) if valid and calibrated else None
                mapped = None
                if desktop:
                    for display in self.onboarding.displays:
                        x, y, width, height = display["viewport"]
                        if x <= desktop[0] <= x + width and y <= desktop[1] <= y + height:
                            mapped = [(desktop[0] - x) / width, (desktop[1] - y) / height]
                            break
            # Only the display bridges a short rejected interval. Samples and clicks
            # continue to require a real accepted frame.
            bridged = False
            previous = self.last_display
            if (not valid and fresh and calibrated and previous
                    and time.monotonic() - previous["time"] <= DISPLAY_GRACE_SECONDS):
                feature = self.feature(previous["result"])
                desktop = (self.onboarding.desktop_point(feature) if self.onboarding
                           else self.desktop_point(self.map_gaze(feature)))
                bridged = desktop is not None
            # Share the same bridged screen position with the 3D scene and overlay.
            if self.onboarding and desktop:
                for display in self.onboarding.displays:
                    x,y,width,height=display['viewport']
                    if x<=desktop[0]<=x+width and y<=desktop[1]<=y+height:
                        mapped=[(desktop[0]-x)/width,(desktop[1]-y)/height]
                        break
            click = None
            raw_mapped, raw_desktop = mapped, desktop
            self.update_screen_motion()
            if desktop is not None:
                desktop = self.screen_motion.sample(time.monotonic())
                if self.onboarding and desktop is not None:
                    desktop = desktop_fence(desktop, [d['viewport'] for d in self.onboarding.displays])
                if desktop is not None:
                    x, y, width, height = next((d['viewport'] for d in self.onboarding.displays
                        if d['viewport'][0] <= desktop[0] <= d['viewport'][0]+d['viewport'][2]
                        and d['viewport'][1] <= desktop[1] <= d['viewport'][1]+d['viewport'][3]),
                        self.screen_motion.viewport) if self.onboarding else self.screen_motion.viewport
                    mapped = [(desktop[0]-x)/width, (desktop[1]-y)/height]
                else:
                    mapped = None
            eye_direction = None
            unclamped_gaze = (self.onboarding.estimate_uv(self.feature(result))
                              if valid and getattr(self.onboarding,'hybrid',False) else None)
            if (fresh and result and result.get("eye_model_estimated")
                    and result.get("confidence", 0) >= self.detection_threshold):
                direction = result.get("gaze_direction")
                if direction and len(direction) == 3 and np.isfinite(direction).all():
                    eye_direction = {"vector": direction, "center": result.get("eye_center"),
                                     "pupil": (result.get("pupil_ellipse") or {}).get("center"),
                                     "radius_px": result.get("sphere_radius"),
                                     "head_features": (result.get("head_pose") or {}).get("features"),
                                     "yaw_degrees": math.degrees(math.atan2(direction[0], direction[2])),
                                     "pitch_degrees": math.degrees(math.atan2(direction[1], math.hypot(direction[0], direction[2]))),
                                     "model_ready": self.eye_model.phase == "ready"}
            with self.diagnostic_lock:
                preview_fps = self.frame_rate(self.preview_times, time.monotonic())
            if self.click_event and self.blink_click_enabled and self.desktop_cursor and valid and calibrated:
                age = time.monotonic() - self.click_event["time"]
                if (age < 0.35 and desktop is not None and self.screen_motion.accepted
                        and np.linalg.norm(np.array(self.click_event['point']) - desktop) <= 24):
                    click = {"id": self.click_event["id"], "point": self.click_event["point"], "age_ms": age * 1000}
            head_state = self.head_camera.status() if self.head_camera else None
            phase = self.onboarding.phase if self.onboarding else None
            if phase != self.last_reported_phase:
                print(f"Calibration phase: {phase} · {self.onboarding.message if self.onboarding else ''}", flush=True)
                self.last_reported_phase = phase
            if self.onboarding and getattr(getattr(self.onboarding,'cursor_calibration',None),'active',False):
                cursor_message='Cursor alignment · '+self.onboarding.cursor_calibration.message
            elif not calibrated:
                if phase == 'cancelled':
                    cursor_message = 'Calibration cancelled · No screen map. Choose Restart calibration.'
                elif phase == 'paused':
                    reason = self.onboarding.message
                    action = 'Continue the step in diagnostics.' if getattr(self.onboarding, 'hybrid', False) else 'Choose Restart calibration.'
                    cursor_message = ('Calibration incomplete · ' + reason + '. ' + action)
                else:
                    cursor_message = 'Calibration in progress' if phase in ('fitting','head','screen','verify') else 'Waiting for calibration'
            elif not fresh:
                cursor_message = 'Calibration complete · Waiting for the eye camera'
            elif head_state and not head_state['face_visible']:
                cursor_message = 'Calibration complete · Face the laptop webcam'
            elif not valid and not bridged:
                cursor_message = 'Calibration complete · Waiting for a reliable eye sample'
            elif raw_desktop is not None and self.screen_motion.pending:
                cursor_message = ('Waiting for a stable gaze estimate' if desktop is None else
                                  'Holding gaze while a sudden jump is checked')
            elif desktop is None:
                cursor_message = 'Calibration complete · Gaze outside the calibrated range. Return your head toward its calibration position.'
            else:
                cursor_message = 'Eye cursor active' if self.desktop_cursor else 'Calibration complete · Desktop cursor disabled'
            return {
                "source": self.source,
                "eye_camera_id": self.eye_camera_id,
                "eye_cameras": self.eye_cameras.status() if self.eye_cameras else None,
                "mode": "hybrid" if self.head_camera else "ir",
                "head_camera": head_state,
                "camera_connected": fresh,
                "valid": valid,
                "display_valid": bool(desktop is not None and (valid or bridged)),
                "display_bridged": bridged,
                "detection_threshold": self.detection_threshold,
                "confidence": round(result.get("confidence", 0), 3) if fresh and result else 0,
                "pupil_center": ((result.get("pupil_ellipse") or {}).get("center")
                                 if fresh and result and isinstance(result.get("pupil_ellipse"), dict) else None),
                "detection_evidence": ({"raw_pupil": result.get("raw_pupil_confidence", result.get("confidence", 0)),
                                        "iris_pupil": result.get("iris_pupil_confidence", 0),
                                        "shape_source": result.get("pupil_shape_source", "pupil"),
                                        "temporal_tracking": result.get("temporal_tracking")}
                                       if fresh and result else None),
                "gaze": mapped,
                "unclamped_gaze": unclamped_gaze,
                "raw_gaze": raw_mapped,
                "raw_desktop_gaze": raw_desktop,
                "gaze_smoothing": {"holding_jump": bool(desktop is not None and self.screen_motion.pending)},
                "captured": list(self.corners),
                "calibrated": calibrated,
                "center_error": self.center_error,
                "desktop_cursor": self.desktop_cursor,
                "cursor_message": cursor_message,
                "desktop_gaze": desktop,
                "calibration": dict(self.native) if self.native else None,
                "blink_click_enabled": self.blink_click_enabled,
                "click_event": click,
                "eye_region": list(self.eye_region) if self.eye_region else None,
                "eye_model": self.eye_model.status(time.monotonic()),
                "eye_direction": eye_direction,
                "onboarding": self.onboarding.state() if self.onboarding else None,
                "performance": {"tracking_fps": self.frame_rate(self.frame_times, time.monotonic()),
                                "preview_fps": preview_fps},
            }

    def desktop_point(self, mapped):
        if mapped is None or self.viewport is None:
            return None
        # Do not pin an off-screen estimate to an edge and imply a valid fixation.
        if not all(0 <= value <= 1 for value in mapped):
            return None
        left, top, width, height = self.viewport
        return [left + mapped[0] * width, top + mapped[1] * height]

    def capture(self, name, viewport=None, automatic=False):
        if name not in TARGETS and name != "center":
            raise ValueError("Unknown target")
        if self.source == "video demo":
            raise ValueError("Use the live eye camera for screen calibration")
        if self.desktop_cursor or viewport is not None:
            validate_viewport(viewport)
        with self.lock:
            if self.require_eye_model and self.eye_model.phase != "ready":
                raise ValueError("Calibrate and fix the eye model before calibrating the monitor")
            if self.native and not automatic:
                raise ValueError("Calibration is controlled by the desktop application")
            if self.viewport is not None and viewport != self.viewport:
                raise ValueError("The calibration area changed. Start over on the monitor you want to track")
            now = time.monotonic()
            recent = [feature for timestamp, feature in self.samples if now - timestamp < HOLD_WINDOW_SECONDS]
            latest_result = self.latest["result"] if self.latest else None
            if (len(recent) < 8 or not self.latest or now - self.latest["time"] > 0.4
                    or not self.usable(latest_result)):
                raise ValueError("Hold the camera still and keep the pupil visible for a moment, then retry")
            feature = [statistics.median(values) for values in zip(*recent)]
            if name == "center":
                if self.matrix is None:
                    raise ValueError("Capture the four corners first")
                prediction = self.map_gaze(feature)
                self.center_error = [round(abs(prediction[0] - 0.5) * 100, 1), round(abs(prediction[1] - 0.5) * 100, 1)]
                self.samples.clear()
                return {"center_error": self.center_error}

            proposed = dict(self.corners)
            proposed[name] = feature
            if len(proposed) == 4:
                source = np.array([proposed[key] for key in TARGETS], dtype=np.float32)
                target = np.array(list(TARGETS.values()), dtype=np.float32)
                distances = [np.linalg.norm(source[i] - source[j]) for i in range(4) for j in range(i + 1, 4)]
                if min(distances) < 0.015 or not cv2.isContourConvex(source.reshape(-1, 1, 2)) or cv2.contourArea(source) < 0.0005:
                    raise ValueError("Corner measurements overlap or cross. Keep the camera fixed and recapture the corners")
                matrix = cv2.getPerspectiveTransform(source, target)
                if not np.isfinite(matrix).all():
                    raise ValueError("Calibration could not be calculated. Please recapture the corners")
                self.matrix = matrix
            self.corners = proposed
            self.viewport = viewport
            self.center_error = None
            self.samples.clear()
            self.hold_frames.clear()
            return {"captured": list(self.corners), "calibrated": self.matrix is not None}

    def reset(self):
        with self.lock:
            self.screen_motion.reset()
            self.last_accepted = None
            self.last_display = None
            self.detection_latch.reset()
            self.corners = {}
            self.matrix = None
            self.center_error = None
            self.viewport = None
            self.samples.clear()
            self.hold_frames.clear()
            self.native = None
            self.center_sample = None
            self.previous_fixation = None
            self.awaiting_movement = False
            self.gesture.reset()
            self.click_event = None


def make_handler(calibration):
    page = Path(__file__).with_name("monitor_demo.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif self.path == "/state":
                self.respond(200, calibration.state())
            elif self.path in ("/diagnostics/left.jpg", "/diagnostics/right.jpg"):
                eye = self.path.rsplit("/", 1)[1].split(".")[0]
                jpeg = calibration.eye_cameras.jpeg(eye) if calibration.eye_cameras else None
                if jpeg is None:
                    self.respond(503, {"error": f"Waiting for the {eye} eye camera"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(jpeg)
            elif self.path == "/diagnostics/head.jpg":
                jpeg = calibration.head_camera.jpeg() if calibration.head_camera else None
                if jpeg is None:
                    self.respond(503, {"error": "Waiting for the laptop webcam"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(jpeg)
            elif self.path == "/diagnostics/raw.png":
                with calibration.diagnostic_lock:
                    raw = calibration.diagnostic_raw_frame
                if raw is None or not calibration.state()["camera_connected"]:
                    self.respond(503, {"error": "Waiting for a fresh eye camera frame"})
                    return
                ok, png = cv2.imencode(".png", raw)
                if not ok:
                    self.respond(503, {"error": "Could not encode eye camera frame"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(png.tobytes())
            elif self.path == "/diagnostics/frame.jpg":
                with calibration.diagnostic_lock:
                    jpeg = calibration.diagnostic_jpeg
                if jpeg is None:
                    self.respond(503, {"error": "Waiting for an eye camera frame"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(jpeg)
            else:
                self.respond(404, {"error": "Not found"})

        def do_POST(self):
            if self.path not in ("/capture", "/reset", "/calibration/start", "/blink-click", "/eye-region", "/eye-cameras",
                                 "/eye-model/start", "/eye-model/freeze", "/onboarding/displays",
                                 "/onboarding/start", "/onboarding/retry", "/onboarding/stop", "/onboarding/cancel", "/detection-threshold",
                                 "/onboarding/cursor-start", "/onboarding/cursor-sample", "/onboarding/cursor-finish", "/onboarding/head-refine", "/onboarding/preview-start", "/onboarding/accuracy-start"):
                self.respond(404, {"error": "Not found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > 1024:
                    raise ValueError("Request too large")
                body = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("Expected a JSON object")
                if self.path.startswith("/onboarding/"):
                    with calibration.lock:
                        if not calibration.onboarding:
                            raise ValueError("Automatic onboarding is available in native live-camera mode")
                        if self.path == "/onboarding/displays":
                            calibration.onboarding.configure(body.get("displays"))
                        elif self.path == "/onboarding/start":
                            calibration.onboarding.arm()
                        elif self.path == "/onboarding/stop":
                            if getattr(calibration.onboarding, 'hybrid', False):
                                calibration.onboarding.stop_step()
                            else:calibration.onboarding.cancel()
                        elif self.path == "/onboarding/retry":
                            if not getattr(calibration.onboarding, 'hybrid', False):
                                raise ValueError('Step retry is available for IR + webcam calibration')
                            calibration.onboarding.retry_step()
                        elif self.path == '/onboarding/preview-start':
                            if not getattr(calibration.onboarding,'hybrid',False):
                                raise ValueError('Preview alignment requires IR + webcam tracking')
                            calibration.onboarding.start_preview_alignment(body.get('target'))
                        elif self.path == '/onboarding/accuracy-start':
                            if not getattr(calibration.onboarding,'hybrid',False):
                                raise ValueError('Accuracy checking requires IR + webcam tracking')
                            calibration.onboarding.start_accuracy_check()
                        elif self.path == '/onboarding/head-refine':
                            if not getattr(calibration.onboarding,'hybrid',False):
                                raise ValueError('Head practice requires IR + webcam tracking')
                            calibration.onboarding.start_head_refinement()
                        elif self.path.startswith('/onboarding/cursor-'):
                            if not getattr(calibration.onboarding,'hybrid',False):
                                raise ValueError('Cursor alignment requires IR + webcam tracking')
                            if self.path.endswith('start'):calibration.onboarding.start_cursor_calibration()
                            elif self.path.endswith('finish'):calibration.onboarding.finish_cursor_calibration()
                            else:calibration.onboarding.cursor_sample(body.get('target'))
                        else:
                            calibration.onboarding.cancel()
                        result = calibration.state()
                elif calibration.onboarding and self.path in ("/eye-model/start", "/eye-model/freeze", "/calibration/start", "/capture"):
                    raise ValueError("Eye and monitor calibration now advance automatically. Use Restart calibration to begin again.")
                elif self.path == "/eye-cameras":
                    calibration.configure_eye_cameras(body)
                    result = calibration.state()
                elif self.path == "/eye-model/start":
                    calibration.start_eye_model()
                    result = calibration.state()
                elif self.path == "/eye-model/freeze":
                    calibration.freeze_eye_model()
                    result = calibration.state()
                elif self.path == "/detection-threshold":
                    calibration.set_detection_threshold(body.get("threshold"))
                    result = calibration.state()
                elif self.path == "/eye-region":
                    calibration.set_eye_region(body.get("region"))
                    result = calibration.state()
                elif self.path == "/blink-click":
                    if type(body.get("enabled")) is not bool:
                        raise ValueError("Expected enabled to be true or false")
                    with calibration.lock:
                        calibration.blink_click_enabled = body["enabled"]
                        calibration.gesture.reset()
                        calibration.click_event = None
                    result = calibration.state()
                elif self.path == "/calibration/start":
                    calibration.start_native(body.get("viewport"))
                    result = calibration.state()
                elif self.path == "/reset":
                    with calibration.lock:
                        if calibration.onboarding:
                            calibration.onboarding.cancel()
                        else:
                            calibration.reset()
                    result = {"captured": [], "calibrated": False}
                else:
                    result = calibration.capture(body.get("target"), body.get("viewport"))
                self.respond(200, result)
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.respond(400, {"error": str(error)})

        def log_message(self, format, *args):
            pass

    return Handler


def build_native_helper(name):
    if name == "native_calibration":
        with versioned_build(Path(__file__).resolve().parents[1]) as version:
            return _build_native_helper(name, version)
    return _build_native_helper(name)


def _build_native_helper(name, version=None):
    source = Path(__file__).with_name(name + ".swift")
    motion_source = Path(__file__).with_name("gaze_motion.swift")
    dependencies = [motion_source]
    if name == "native_calibration":
        dependencies.append(source.with_name("angle_debugger.swift"))
    cache = Path(__file__).resolve().parents[1] / ".venv" / "swift-cache"
    cache.mkdir(parents=True, exist_ok=True)
    binary = cache.parent / name.replace("_", "-")
    if name == "native_calibration":
        contents = cache.parent / "EyeCursor.app" / "Contents"
        binary = contents / "MacOS" / "EyeCursor"
        binary.parent.mkdir(parents=True, exist_ok=True)
        resources = contents / "Resources"
        resources.mkdir(parents=True, exist_ok=True)
        icon = source.parent.parent / "assets" / "app-icon" / "EyeCursor.icns"
        shutil.copy2(icon, resources / icon.name)
        menu_icon = icon.with_name("eye-cursor-menubar.svg")
        shutil.copy2(menu_icon, resources / "EyeCursorMenuBar.svg")
        # Keep the bundle identifier stable across the product rename.
        (contents / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": "EyeCursor", "CFBundleIdentifier": "local.eyetracker.calibration",
            "CFBundleName": "EyeCursor", "CFBundleDisplayName": "EyeCursor",
            "CFBundlePackageType": "APPL",
            "CFBundleIconFile": "EyeCursor.icns",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version.split('.')[1],
            "EyeCursorProjectRoot": str(source.resolve().parent.parent),
            "NSCameraUsageDescription": "EyeCursor uses your eye camera and laptop webcam to calibrate and control the cursor with your gaze.",
            "NSHighResolutionCapable": True,
        }))
    if not binary.exists() or binary.stat().st_mtime < max(p.stat().st_mtime for p in [source, *dependencies]):
        print(f"Building {name.replace('_', ' ')}...", flush=True)
        entry = cache / name / "main.swift"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_bytes(source.read_bytes())
        subprocess.run(["/usr/bin/swiftc", "-module-cache-path", str(cache),
                        *map(str, dependencies), str(entry), "-o", str(binary)], check=True)
    return binary


def claim_native_instance(port):
    """Prevent Finder and terminal launches from opening the cameras twice."""
    import fcntl
    lock_path = Path(__file__).resolve().parents[1] / ".venv" / f"eyecursor-{port}.lock"
    lock = lock_path.open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise SystemExit("EyeCursor is already running. Use its menu-bar icon, or quit it before starting again.")
    return lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--camera", type=int, help="Use this index only if it identifies a USB camera")
    source.add_argument("--camera-id", help="Exact macOS camera unique ID from --list-cameras")
    source.add_argument("--video", type=Path, help="Video for pipeline testing; it cannot calibrate a live user")
    source.add_argument("--stream-url", help="Live HTTP MJPEG or RTSP eye-camera stream")
    hybrid_mode = parser.add_mutually_exclusive_group()
    hybrid_mode.add_argument("--hybrid", dest="hybrid", action="store_true", default=None,
                             help="IR pupil plus built-in webcam head compensation (native default)")
    hybrid_mode.add_argument("--ir-only", dest="hybrid", action="store_false", help="Use the previous IR-only calibration")
    parser.add_argument("--head-camera-id", help="Exact head-camera ID, built-in or external; never auto-substituted")
    parser.add_argument("--list-cameras", action="store_true", help="Show macOS cameras and exit")
    parser.add_argument("--flip-horizontal", action="store_true")
    parser.add_argument("--flip-vertical", action="store_true")
    parser.add_argument("--no-display", action="store_true", help="Skip OpenCV preview window")
    parser.add_argument("--no-calibration-ui", "--no-browser", dest="no_calibration_ui", action="store_true",
                        help="Run tracking/API only, without opening the calibration interface")
    parser.add_argument("--web-calibration", action="store_true", help="Use the legacy browser calibration instead of the native macOS app")
    parser.add_argument("--debug-cursor", action="store_true",
                        help="Show a 16-point translucent gaze cursor across macOS apps after calibration")
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after N frames for diagnostics")
    parser.add_argument("--loop-video", action="store_true", help="Repeat a sample video while inspecting the calibration interface")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--native-host-pid", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.list_cameras:
        if sys.platform != "darwin":
            raise SystemExit("--list-cameras currently supports macOS only")
        for camera in list_mac_cameras():
            print(f'{camera["index"]}: {camera["name"]} [{camera["id"]}]')
        return

    native_ui = (sys.platform == "darwin" and not args.web_calibration
                 and not args.no_calibration_ui and not args.max_frames)
    if args.native_host_pid is not None and (not native_ui or args.native_host_pid <= 1):
        parser.error("--native-host-pid requires native macOS mode and a valid parent PID")
    # Keep this handle alive until main returns, releasing the lock on any exit.
    instance_lock = claim_native_instance(args.port) if native_ui else None
    hybrid = native_ui and not args.video and args.hybrid is not False
    if args.hybrid and not hybrid:
        parser.error("--hybrid requires native macOS live-camera mode")
    if hybrid and not MODEL_PATH.is_file():
        raise SystemExit("Run .venv/bin/python 3DTracker/setup_hybrid.py before starting hybrid mode")
    if native_ui and not args.video and not args.stream_url and args.camera is None and args.camera_id is None and (args.flip_horizontal or args.flip_vertical):
        parser.error("Use per-eye rotation in Diagnostics, or select an explicit --camera-id for legacy flips")
    if args.debug_cursor and (sys.platform != "darwin" or args.max_frames):
        parser.error("--debug-cursor requires macOS and a running calibration server")
    ui_binary = build_native_helper("native_calibration") if native_ui and not args.native_host_pid else None
    cursor_binary = build_native_helper("gaze_cursor") if args.debug_cursor and not native_ui else None
    # Native calibration owns the visible UI; the OpenCV window is a legacy diagnostic.
    show_preview = not args.no_display and not native_ui
    tracker.DISPLAY_ENABLED = show_preview
    tracker.reset_tracking_state()
    usb_source = None
    eye_rig = None
    if args.video:
        capture = cv2.VideoCapture(str(args.video))
        source_name = "video demo"
    elif args.stream_url:
        if not args.stream_url.startswith(("http://", "https://", "rtsp://")):
            raise SystemExit("--stream-url must start with http://, https://, or rtsp://")
        capture = ReconnectingCapture(lambda: cv2.VideoCapture(args.stream_url))
        source_name = "wireless eye camera"
    else:
        if sys.platform == "darwin":
            if native_ui and args.camera is None and args.camera_id is None:
                eye_rig = EyeCameraRig(list_mac_cameras,
                    Path(__file__).resolve().parents[1] / ".venv/eye-cameras.json",
                    excluded_id=args.head_camera_id)
                eye_rig.start()
                usb_source = eye_rig
                capture = eye_rig
            else:
                usb_source = USBCameraSource(args.camera, args.camera_id)
                capture = ReconnectingCapture(usb_source.open)
            source_name = usb_source.name
        else:
            if args.camera_id:
                raise SystemExit("--camera-id currently supports macOS only")
            capture = ReconnectingCapture(lambda: cv2.VideoCapture(
                args.camera if args.camera is not None else 0, cv2.CAP_ANY))
            source_name = f"camera {args.camera or 0}"
    if not capture.isOpened():
        if not native_ui or args.video:
            raise SystemExit(f"Could not open {source_name}. Check its connection and source settings, then retry.")
        print(f"Waiting for {source_name}. EyeCursor remains available in the menu bar.", flush=True)

    calibration = Calibration(source_name, desktop_cursor=args.debug_cursor, require_eye_model=native_ui)
    calibration.eye_cameras = eye_rig
    if hybrid:
        if args.head_camera_id and usb_source is not None and args.head_camera_id == usb_source.device_id:
            raise SystemExit('The head webcam and IR eye camera must be different devices')
        calibration.head_camera = HeadCamera(list_mac_cameras, args.head_camera_id)
        calibration.head_camera.start()
        calibration.onboarding = HybridOnboarding(calibration, calibration.head_camera,
            diagnostic_path=Path(__file__).resolve().parents[1] / ".venv/head-calibration-debug.json")
    elif native_ui and not args.video:
        source_key = args.stream_url or (usb_source.device_id if sys.platform == "darwin" else str(args.camera or 0))
        calibration.onboarding = Onboarding(calibration,
            Path(__file__).resolve().parents[1] / ".venv" / "calibration-profile.json",
            source_key, (args.flip_horizontal, args.flip_vertical))
    cursor_process = None
    ui_process = None
    companion = CompanionEyeTracker(calibration, render_diagnostic_frame) if eye_rig else None
    server = None
    if not args.max_frames:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(calibration))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Monitor calibration: {url}", flush=True)
        if not args.no_calibration_ui and not native_ui:
            webbrowser.open(url)
    print("Choose Quit in the EyeCursor menu-bar menu or press Ctrl+C to quit." if native_ui else
          "Press Q in the tracker preview to quit; F freezes the estimated eye sphere.", flush=True)
    count = 0
    valid = 0
    stream_interrupted = False
    if args.native_host_pid:
        def stop_from_app(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop_from_app)
    try:
        if companion:
            companion.start()
        if ui_binary:
            ui_process = subprocess.Popen([str(ui_binary), str(args.port)] + (["--hybrid"] if hybrid else []))
        if cursor_binary:
            cursor_process = subprocess.Popen([str(cursor_binary), str(args.port)])
        while True:
            if args.native_host_pid and os.getppid() != args.native_host_pid:
                break
            if ui_process and ui_process.poll() is not None:
                break
            if calibration.onboarding:
                with calibration.lock:
                    calibration.onboarding.tick()
                    if not args.stream_url and sys.platform == "darwin":
                        calibration.onboarding.source_key = usb_source.device_id
                        calibration.eye_camera_id = usb_source.device_id
                        if eye_rig:
                            rotated = eye_rig.context()[2] == 180
                            calibration.onboarding.orientation = (rotated, rotated)
            ok, frame = capture.read()
            captured_at = eye_rig.frame_time if eye_rig and ok else time.monotonic()
            if not ok:
                if eye_rig and eye_rig.active_fresh():
                    time.sleep(.005)
                    continue
                if args.video and args.loop_video:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    tracker.reset_tracking_state()
                    continue
                if args.video or args.max_frames:
                    break
                if not stream_interrupted:
                    print("Eye stream interrupted; waiting for the same live source to reconnect.", flush=True)
                    calibration.interrupt_stream()
                    stream_interrupted = True
                time.sleep(0.05)
                continue
            if not args.video and capture.recovered:
                with calibration.lock:
                    if calibration.onboarding:
                        calibration.onboarding.arm()
                    else:
                        calibration.reset_eye_model()
                print("Eye stream restored with a new capture session. Recalibrate before recording.", flush=True)
            elif stream_interrupted:
                print("Eye stream resumed.", flush=True)
            stream_interrupted = False
            if args.flip_horizontal and args.flip_vertical:
                frame = cv2.flip(frame, -1)
            elif args.flip_horizontal:
                frame = cv2.flip(frame, 1)
            elif args.flip_vertical:
                frame = cv2.flip(frame, 0)
            with calibration.lock:
                if eye_rig and eye_rig.frame_context != eye_rig.context():
                    continue  # Settings changed while this frame was being read.
                if native_ui:
                    tracker.pupil_confidence_threshold = calibration.detection_threshold
                    tracker.pupil_confidence_threshold_sphere = calibration.detection_threshold
                    tracker.eye_sphere_adjustment_enabled = calibration.eye_model.phase == "collecting"
                tracker.process_frame(frame, timestamp=(tracker.video_frame_timestamp(capture)
                                                       if args.video else captured_at))
                result = tracker.get_last_tracking_result()
                if result is not None and hybrid:
                    result['capture_time'] = captured_at
                    result['head_pose'] = calibration.head_camera.sample_at(captured_at)
                calibration.add_frame(result)
            # Publish every processed frame. Encoding and preview reads must not
            # wait behind the state/calibration lock or skip two of three images.
            if server:
                calibration.set_diagnostic_frame(frame, result, eye_rig.frame_context if eye_rig else None,
                                                 eye_rig.frame_sample if eye_rig else None)
            count += 1
            if usable(result):
                valid += 1
            if args.max_frames and count >= args.max_frames:
                break
            if show_preview:
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key in (ord("f"), ord("F")):
                    tracker.toggle_eye_sphere_adjustment()
            if args.video and not args.max_frames:
                time.sleep(1 / (capture.get(cv2.CAP_PROP_FPS) or 30))
    except KeyboardInterrupt:
        pass
    finally:
        for process in (cursor_process, ui_process):
            if not process or process.poll() is not None:
                continue
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if companion:
            companion.close()
        capture.release()
        if calibration.head_camera:
            calibration.head_camera.close()
        if server:
            server.shutdown()
            server.server_close()
        if show_preview:
            cv2.destroyAllWindows()
    print(f"Processed {count} frames; {valid} passed the pupil confidence threshold.")


if __name__ == "__main__":
    main()
