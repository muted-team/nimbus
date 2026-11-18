"""Userdata stays outside immutable runtimes, including worker threads."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DataRootTests(unittest.TestCase):
    def test_launcher_environment_and_thread_default(self):
        with tempfile.TemporaryDirectory() as folder:
            code = '''
import json, threading
from modules import paths, photo_source, config, accounts, db, eventlog, campaign, signin
result = {}
def collect():
    result.update(root=str(paths.here(paths.ROOT / 'config.json')),
                  media=str(photo_source.library_root()),
                  config=str(config.path('photos_dir')),
                  accounts=str(paths.here(accounts.ACCOUNTS_FILE)),
                  db=str(paths.here(db.DB_FILE)),
                  events=str(eventlog._events_log_path()),
                  report=str(campaign._report_path()),
                  login=str(paths.here(signin.LOG_FILE)))
thread = threading.Thread(target=collect); thread.start(); thread.join()
print(json.dumps(result))
'''
            run = subprocess.run([sys.executable, '-c', code], env={**os.environ, 'NIMBUS_DATA_ROOT': folder},
                                 capture_output=True, text=True, check=True)
            values = json.loads(run.stdout)
            for name, value in values.items():
                self.assertTrue(Path(value).is_relative_to(Path(folder).resolve()), (name, value))

    def test_context_override_preserves_external_paths(self):
        from modules import paths
        with tempfile.TemporaryDirectory() as folder:
            external = Path(folder).parent / 'external-user-file'
            with paths.use_root(folder):
                self.assertEqual(paths.here(paths.ROOT / 'sessions'), Path(folder) / 'sessions')
                self.assertEqual(paths.here(external), external)


if __name__ == '__main__':
    unittest.main()
