import json
from pathlib import Path
import tempfile
import unittest

from app_version import versioned_build


class AppVersionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / '3DTracker').mkdir()
        self.source = self.root / '3DTracker' / 'main.swift'
        self.source.write_text('initial source')

    def build(self):
        with versioned_build(self.root) as version:
            return version

    def test_initial_and_unchanged_build(self):
        self.assertEqual(self.build(), '0.1')
        self.assertEqual(self.build(), '0.1')

    def test_changed_builds_increase_without_decimal_rollover(self):
        for minor in range(1, 12):
            self.source.write_text(f'source {minor}')
            self.assertEqual(self.build(), f'0.{minor}')

    def test_failed_build_does_not_publish_version(self):
        self.build()
        self.source.write_text('changed')
        with self.assertRaises(RuntimeError):
            with versioned_build(self.root) as version:
                self.assertEqual(version, '0.2')
                raise RuntimeError('compiler failed')
        self.assertEqual(json.loads((self.root / 'version.json').read_text())['version'], '0.1')
        self.assertEqual(self.build(), '0.2')

    def test_concurrent_source_edit_requires_rebuild(self):
        with self.assertRaisesRegex(RuntimeError, 'changed during the build'):
            with versioned_build(self.root):
                self.source.write_text('edited during compilation')
        self.assertFalse((self.root / 'version.json').exists())

    def test_instructions_and_backend_changes_are_versioned(self):
        self.build()
        (self.root / 'AGENTS.md').write_text('Shared instructions')
        self.assertEqual(self.build(), '0.2')
        (self.root / '3DTracker' / 'backend.py').write_text('changed backend')
        self.assertEqual(self.build(), '0.3')


if __name__ == '__main__':
    unittest.main()
