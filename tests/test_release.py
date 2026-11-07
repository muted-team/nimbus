"""Release numbering and migration from the previous private client."""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules import changelog

class ReleaseTests(unittest.TestCase):
    def test_patch_version_increments_only_when_requested(self):
        self.assertEqual(changelog.bump('1.0.9'), '1.0.10')

    def test_legacy_client_data_is_imported_despite_lower_release_number(self):
        spec = importlib.util.spec_from_file_location('release_app', ROOT / 'app.py')
        app = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'webview': types.ModuleType('webview')}):
            spec.loader.exec_module(app)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            old = base / 'TikTok Web API v1.1.3'
            old.mkdir()
            (old / 'accounts.json').write_text('{"accounts":[{"username":"synthetic"}]}')
            (old / 'media').mkdir()
            (old / 'media' / 'synthetic.txt').write_text('test')
            new = base / 'Nimbus v1.0.0'
            new.mkdir()
            with patch.object(app, '_log'):
                app._carry_over(new)
            self.assertEqual((new / 'accounts.json').read_bytes(), (old / 'accounts.json').read_bytes())
            self.assertTrue((new / 'media' / 'synthetic.txt').exists())
            self.assertTrue((old / 'media' / 'synthetic.txt').exists())

    def test_linux_builder_keeps_gtk_and_windows_builder_keeps_webview2(self):
        import build
        linux = build.nuitka_command('linux', Path('/tmp/fixture-output'))
        windows = build.nuitka_command('win32', Path('/tmp/fixture-output'))
        self.assertFalse(any('nofollow-import-to=webview.platforms.gtk' in a for a in linux))
        self.assertIn('--windows-console-mode=disable', windows)
        self.assertFalse(any(a.startswith('--windows-') for a in linux))

if __name__ == '__main__':
    unittest.main()
