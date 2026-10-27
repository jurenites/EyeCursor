"""Deterministic multi-view alignment, low-rate fusion and device safety checks."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

import numpy as np
from dual_head_camera import DualHeadCamera, ViewAlignment, SCALE
from head_camera import HeadCamera
from monitor_demo import Calibration

BASE = np.array([0., 0., 0., .5, .4, -1.2])


def packet(features, stamp, epoch=1):
    return {'features': np.asarray(features).tolist(), 'time': stamp, 'epoch': epoch}


def trained(noisy=False):
    rng = np.random.default_rng(412)
    model = ViewAlignment()
    model.begin()
    # Six independent small head motions; oblique camera with coupled axes.
    matrix = np.eye(6)
    matrix[0, 1] = .25
    matrix[3, 5] = -.18
    for i in range(240):
        s = rng.uniform(-.8, .8, 6)
        p = s @ matrix + [.2, -.3, .1, .5, -.4, .3]
        if noisy:
            p += rng.normal(0, .07, 6)
        model.add(packet(BASE+p*SCALE, i*.15), packet(BASE+s*SCALE, i*.15))
    model.finish()
    return model


class AlignmentTests(unittest.TestCase):
    def test_maps_held_out_oblique_view_to_primary_frame(self):
        model = trained()
        predicted = model.predict(BASE)
        np.testing.assert_allclose(predicted, BASE+np.array([.2,-.3,.1,.5,-.4,.3])*SCALE, atol=.0002)
        self.assertLess(model.validation_error, .01)
        self.assertIsNone(model.predict(BASE+10*SCALE))

    def test_static_and_unrelated_views_cannot_enable_assistance(self):
        for random_primary in (False, True):
            model = ViewAlignment(); model.begin()
            rng = np.random.default_rng(1)
            for i in range(120):
                p = BASE+rng.normal(0, 1, 6)*SCALE if random_primary else BASE
                s = BASE+rng.normal(0, 1, 6)*SCALE if random_primary else BASE
                model.add(packet(p, i*.3), packet(s, i*.3))
            with self.assertRaises(ValueError): model.finish()
            self.assertIsNone(model.model)

    def test_duplicate_frames_and_wide_skew_do_not_inflate_training(self):
        model = ViewAlignment(); model.begin()
        for i in range(100):
            model.add(packet(BASE, 1), packet(BASE, 1))
        self.assertEqual(len(model.rows), 1)
        model.add(packet(BASE, 2.1), packet(BASE, 2))
        self.assertEqual(len(model.rows), 1)
        with self.assertRaises(ValueError): model.finish()

    def test_low_fps_transfers_correction_without_replaying_old_pose(self):
        model = trained()
        predicted = model.predict(BASE)
        old = predicted + .2*SCALE
        current = old + .5*SCALE
        result, weight, reason = model.assist(packet(current, 10.06), packet(old, 10), packet(BASE, 10))
        self.assertAlmostEqual(weight, .125)
        np.testing.assert_allclose(result['features'], current-.125*.2*SCALE)
        self.assertEqual(reason, 'assisting')
        result, weight, _ = model.assist(packet(current, 10.2), packet(old, 10), packet(BASE, 10))
        self.assertEqual(weight, 0)
        np.testing.assert_allclose(result['features'], current)

    def test_noisy_primary_benefits_on_unseen_samples(self):
        model = trained(noisy=True)
        truth = BASE+np.array([.2,-.3,.1,.5,-.4,.3])*SCALE
        rng = np.random.default_rng(65)
        errors, combined = [], []
        for i in range(150):
            noisy = truth+rng.normal(0, .07, 6)*SCALE
            result, weight, _ = model.assist(packet(noisy, i), packet(noisy, i), packet(BASE, i))
            self.assertGreater(weight, 0)
            errors.append(np.mean(((noisy-truth)/SCALE)**2))
            combined.append(np.mean(((np.array(result['features'])-truth)/SCALE)**2))
        self.assertLess(np.mean(combined), np.mean(errors)*.7)

    def test_moved_camera_rejected_immediately_and_repeated_disagreement_invalidates(self):
        model = trained()
        for i in range(4):
            result, weight, reason = model.assist(packet(BASE+3*SCALE, i),
                                                 packet(BASE+3*SCALE, i), packet(BASE, i))
            self.assertEqual(weight, 0)
            self.assertEqual(reason, 'views_disagree')
        self.assertIsNone(model.model)


class RigTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'head.json'
        self.primary = HeadCamera(lambda: [], 'laptop')
        self.secondary = HeadCamera(lambda: [], 'table')
        self.primary.epoch = self.secondary.epoch = 1
        self.rig = DualHeadCamera(self.primary, lambda: [], self.path, lambda: {'left', 'right'},
                                 factory=lambda *a, **kw: self.secondary, clock=lambda: 10.06)
        self.secondary.start = MagicMock()
        self.secondary.close = MagicMock()
        self.rig.devices = [{'id': 'table', 'name': 'Table webcam'}]

    def publish(self, camera, features, stamp):
        camera.history.append({'pose': {'features': np.asarray(features).tolist()}, 'time': stamp, 'epoch': camera.epoch})

    def test_assignment_rejects_both_ir_devices_and_primary_then_persists_exact_id(self):
        for device in ('left', 'right', 'laptop', 'missing'):
            with self.assertRaises(ValueError): self.rig.configure(device)
        self.rig.configure('table')
        self.assertEqual(json.loads(self.path.read_text())['secondary_camera_id'], 'table')
        self.secondary.start.assert_called_once()
        self.rig.configure(None)
        self.secondary.close.assert_called_once()
        self.assertIsNone(self.rig.secondary)

    def test_builtin_cannot_be_secondary_before_default_primary_resolves(self):
        self.path.write_text(json.dumps({'secondary_camera_id': 'laptop'}))
        primary = HeadCamera(lambda: [])
        rig = DualHeadCamera(primary, lambda: [{'id':'laptop', 'type':'AVCaptureDeviceTypeBuiltInWideAngleCamera'}], self.path)
        self.assertIsNone(rig.selected_id)
        self.assertIsNotNone(rig.error)

    def test_disabled_path_and_stale_secondary_keep_primary_features_and_timestamp(self):
        self.publish(self.primary, BASE, 10.04)
        output = self.rig.sample_at(10.06)
        self.assertEqual(output['features'], BASE.tolist())
        self.rig.configure('table'); self.rig.alignment = trained()
        self.publish(self.secondary, BASE, 9.8)
        output = self.rig.sample_at(10.06)
        self.assertEqual(output['time'], 10.04)
        self.assertEqual(output['features'], BASE.tolist())
        self.assertEqual(output['secondary_view']['weight'], 0)
        self.primary.history.clear()
        self.assertIsNone(self.rig.sample_at(10.06))

    def test_aligned_features_reach_gaze_input_and_diagnostics(self):
        self.rig.configure('table'); self.rig.alignment = trained()
        truth = self.rig.alignment.predict(BASE)
        self.publish(self.primary, truth+.2*SCALE, 10.04)
        self.publish(self.secondary, BASE, 10.04)
        output = self.rig.sample_at(10.06)
        self.assertGreater(output['secondary_view']['weight'], 0)
        np.testing.assert_allclose(output['features'], truth+.15*SCALE)
        self.assertEqual(self.rig.status(10.06)['features'], output['features'])
        self.assertFalse(self.rig.status(10.06)['second_view']['metric_triangulation'])

    def test_accumulated_skew_is_not_accepted(self):
        self.rig.configure('table'); self.rig.alignment = trained()
        self.publish(self.primary, BASE, 10)
        self.publish(self.secondary, BASE, 9.9)
        output = self.rig.sample_at(10.1)
        self.assertEqual(output['secondary_view']['weight'], 0)

    def test_reconnect_discards_alignment_and_changes_gaze_epoch(self):
        self.rig.configure('table'); self.rig._check_session()
        self.rig.alignment = trained()
        epoch = self.rig.epoch
        self.secondary.epoch += 1
        self.publish(self.primary, BASE, 10.04)
        output = self.rig.sample_at(10.06)
        self.assertGreater(output['epoch'], epoch)
        self.assertIsNone(self.rig.alignment.model)

    def test_api_rejects_changes_during_calibration_and_clears_maps_when_idle(self):
        calibration = Calibration('test')
        calibration.head_camera = self.rig
        flow = MagicMock(); flow.phase = 'screen'; flow.cursor_calibration.active = False
        calibration.onboarding = flow
        with self.assertRaisesRegex(ValueError, 'Finish or stop'):
            calibration.configure_head_camera({'camera_id': 'table'})
        self.assertIsNone(self.rig.selected_id)
        flow.phase = 'complete'
        calibration.configure_head_camera({'camera_id': 'table'})
        flow.arm.assert_called_once_with(start=False)
        calibration.eye_cameras = MagicMock()
        with self.assertRaisesRegex(ValueError, 'face webcam'):
            calibration.configure_eye_cameras({'left': {'device_id': 'table'}})


if __name__ == '__main__':
    unittest.main()
