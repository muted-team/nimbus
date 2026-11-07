"""Native acceptance uses the actual webview DOM rather than HTTP alone."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class NativeUiCheckTests(unittest.TestCase):
    def test_check_records_rendered_routes_and_closes_exact_window(self):
        spec = importlib.util.spec_from_file_location('check_app', ROOT / 'app.py')
        app = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'webview': types.ModuleType('webview')}):
            spec.loader.exec_module(app)
        window = Mock()
        window.events.loaded.wait.return_value = True
        window.evaluate_js.side_effect = lambda source: {'heading': 'Fixture', 'ready': True, 'overflow': False, 'errors': []} if 'querySelector' in source else True
        with tempfile.TemporaryDirectory() as temporary, patch.object(app.time, 'sleep'):
            report = Path(temporary) / 'check.json'
            app._check_ui(window, report)
            result = json.loads(report.read_text(encoding='utf-8'))
            self.assertTrue(result['ok'])
            self.assertEqual(len(result['routes']), 7)
        window.destroy.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
