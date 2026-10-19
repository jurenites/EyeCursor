"""Round-trip checks for the compact gaze/cursor timeline."""

from datetime import datetime, timezone
import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from session_recorder import compact_tracking, expand_tracking, SessionManager


class CompactTimelineTest(unittest.TestCase):
    def test_recorder_keeps_raw_gaze_separate_from_smoothed_feedback(self):
        class OneSample:
            stopped = False
            def is_set(self): return self.stopped
            def wait(self, seconds): self.stopped = True
        for state, expected in (({'valid': True, 'gaze': [.5, .5], 'raw_gaze': [.8, .2]}, [.8, .2]),
                                ({'valid': True, 'gaze': [.4, .6]}, [.4, .6]),
                                ({'valid': False, 'gaze': [.5, .5], 'raw_gaze': [.8, .2]}, [None, None])):
            with tempfile.TemporaryDirectory() as folder, patch('session_recorder.read_state', return_value=state):
                SessionManager._sample_gaze(None, {'folder': Path(folder), 'stop': OneSample(), 'epoch_ns': 0})
                sample = json.loads((Path(folder) / 'gaze.jsonl').read_text())
                self.assertEqual([sample['x'], sample['y']], expected)

    def test_utc_anchor_every_24_samples_and_replay_alignment(self):
        epoch = int(datetime(2026, 10, 5, 10, tzinfo=timezone.utc).timestamp() * 1e9)
        manifest = {"started_at_unix_ns": epoch, "screen_frames": 50}
        gaze = [{"t_ms": i * 1000 / 24, "unix_ns": epoch + round(i * 1e9 / 24),
                 "valid": i != 25, "x": .4, "y": .6} for i in range(50)]
        frames = [{"t_ms": i * 1000 / 24, "cursor_on_display": True,
                   "cursor_nx": .5, "cursor_ny": .3} for i in range(50)]
        compact = compact_tracking(manifest, gaze, frames)
        self.assertEqual([len(group["gaze_xy"]) for group in compact["groups"]], [24, 24, 2])
        self.assertEqual([group["video_ms"] for group in compact["groups"]], [0.0, 1000.0, 2000.0])
        self.assertEqual([group["utc"] for group in compact["groups"]], [
            "2026-10-05T10:00:00.000Z", "2026-10-05T10:00:01.000Z",
            "2026-10-05T10:00:02.000Z"])
        decoded = expand_tracking(compact, manifest)
        self.assertEqual(len(decoded["gaze"]), 50)
        self.assertFalse(decoded["gaze"][25]["valid"])
        self.assertAlmostEqual(decoded["gaze"][49]["t_ms"], 49 * 1000 / 24, places=2)
        self.assertEqual(decoded["frames"][49]["cursor_nx"], .5)


if __name__ == "__main__":
    unittest.main()
