"""Track the second eye without sharing the legacy detector's mutable globals.

Both eyes produce independent pupil detections and paired head samples.
Screen calibration and fusion live in binocular_calibration; raw camera rays
from different coordinate frames are never averaged.
"""
import importlib.util
from pathlib import Path
import threading

import cv2
from eye_model import EyeModelCalibration


def independent_detector():
    source = Path(__file__).with_name('Orlosky3DEyeTracker.py')
    spec = importlib.util.spec_from_file_location('_companion_eye_detector', source)
    detector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(detector)
    detector.DISPLAY_ENABLED = False
    return detector


class CompanionEyeTracker:
    def __init__(self, calibration, render, detector=None):
        self.calibration = calibration
        self.rig = calibration.eye_cameras
        self.render = render
        self.detector = detector if detector is not None else independent_detector()
        self.context = None
        self.last_serial = None
        self.eye_model = EyeModelCalibration()
        self.stop = threading.Event()
        self.thread = None

    def process_next(self):
        with self.calibration.lock:
            primary = self.rig.context()[0]
            threshold = self.calibration.detection_threshold
            model_generation = id(self.calibration.eye_model)
        eye = 'right' if primary == 'left' else 'left'
        sample = self.rig.snapshot(eye)
        if sample is None or sample['serial'] == self.last_serial:
            return False
        context = (sample['context'], sample['revision'], sample['session'], model_generation)
        if context != self.context:
            self.detector.reset_tracking_state()
            self.eye_model.start()
            self.context = context
        self.last_serial = sample['serial']
        self.detector.pupil_confidence_threshold = threshold
        self.detector.pupil_confidence_threshold_sphere = threshold
        self.eye_model.threshold = threshold
        self.detector.eye_sphere_adjustment_enabled = self.eye_model.phase == 'collecting'
        self.detector.process_frame(sample['frame'], timestamp=sample['time'])
        result = self.detector.get_last_tracking_result()
        self.eye_model.observe(result, sample['time'])
        if self.eye_model.status(sample['time'])['can_freeze']:
            self.eye_model.freeze(sample['time'])
        if result is not None and self.calibration.head_camera is not None:
            result['head_pose'] = self.calibration.head_camera.sample_at(sample['time'])
        image = self.render(sample['frame'], result, threshold=threshold,
                            eye_model_ready=self.eye_model.phase == 'ready')
        ok, jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 78])
        if ok:
            self.rig.publish_tracking(eye, sample, result, jpeg.tobytes(), threshold)
        return True

    def start(self):
        self.thread = threading.Thread(target=self._run, name='second-eye-tracking', daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            try:
                self.process_next()
            except Exception as error:
                # Keep the capture streams and primary calibration alive if a
                # malformed frame fails detection. Surface the error in status.
                with self.rig.lock:
                    eye = 'right' if self.rig.context()[0] == 'left' else 'left'
                    self.rig.tracking_errors[eye] = str(error)
            self.stop.wait(.005)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
