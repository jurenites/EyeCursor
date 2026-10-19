"""Native app owns one tracker process; terminal launch keeps its existing flow."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import monitor_demo


class NativeAppLaunchTests(unittest.TestCase):
    def test_native_lock_rejects_duplicate_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.venv').mkdir()
            source = root / '3DTracker' / 'monitor_demo.py'
            with patch.object(monitor_demo, '__file__', str(source)):
                first = monitor_demo.claim_native_instance(8765)
                try:
                    with self.assertRaisesRegex(SystemExit, 'already running'):
                        monitor_demo.claim_native_instance(8765)
                finally:
                    first.close()
                second = monitor_demo.claim_native_instance(8765)
                second.close()

    def test_app_host_uses_native_mode_without_spawning_another_ui(self):
        capture = MagicMock()
        capture.isOpened.return_value = True
        with patch.object(monitor_demo.sys, 'argv', ['monitor_demo.py', '--native-host-pid', '100']), \
             patch.object(monitor_demo.sys, 'platform', 'darwin'), \
             patch.object(monitor_demo, 'claim_native_instance'), \
             patch.object(monitor_demo, 'MODEL_PATH') as model, \
             patch.object(monitor_demo, 'USBCameraSource'), \
             patch.object(monitor_demo, 'EyeCameraRig', return_value=capture), \
             patch.object(monitor_demo, 'ReconnectingCapture', return_value=capture), \
             patch.object(monitor_demo, 'HeadCamera') as head, \
             patch.object(monitor_demo, 'HybridOnboarding'), \
             patch.object(monitor_demo, 'ThreadingHTTPServer') as server, \
             patch.object(monitor_demo.threading, 'Thread'), \
             patch.object(monitor_demo.signal, 'signal'), \
             patch.object(monitor_demo.os, 'getppid', return_value=1), \
             patch.object(monitor_demo, 'build_native_helper') as build, \
             patch.object(monitor_demo.subprocess, 'Popen') as spawn:
            model.is_file.return_value = True
            monitor_demo.main()
            build.assert_not_called()
            spawn.assert_not_called()
            head.return_value.start.assert_called_once()
            head.return_value.close.assert_called_once()
            capture.read.assert_not_called()  # Host exited before the first frame.
            capture.release.assert_called_once()
            server.return_value.server_close.assert_called_once()

    def test_host_option_rejects_browser_mode(self):
        with patch.object(monitor_demo.sys, 'argv', ['monitor_demo.py', '--native-host-pid', str(os.getpid()), '--web-calibration']), \
             patch.object(monitor_demo.sys, 'platform', 'darwin'):
            with self.assertRaises(SystemExit) as result:
                monitor_demo.main()
            self.assertEqual(result.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
