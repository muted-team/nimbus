import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.check_package import check


class PackageLayoutTests(unittest.TestCase):
    def package(self, folder, missing=None, pointer='runtime-v1.2.3'):
        files = {'Nimbus v1.2.3/Nimbus': b'executable',
                 'Nimbus v1.2.3/.nimbus-current': pointer.encode(),
                 'Nimbus v1.2.3/.nimbus-bootstrap.json': b'{"format":1}',
                 'Nimbus v1.2.3/runtimes/runtime-v1.2.3/.nimbus-runtime.json': json.dumps({'format': 1, 'version': '1.2.3'}).encode(),
                 'Nimbus v1.2.3/runtimes/runtime-v1.2.3/Nimbus-runtime': b'runtime',
                 'Nimbus v1.2.3/runtimes/runtime-v1.2.3/ui/index.html': b'ui'}
        path = Path(folder) / 'release.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, value in files.items():
                if missing is None or not name.endswith(missing):
                    archive.writestr(name, value)
        return path

    def test_complete_and_broken_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(check(self.package(folder)), [])
            self.assertTrue(check(self.package(folder, missing='Nimbus-runtime')))
            self.assertTrue(check(self.package(folder, missing='.nimbus-runtime.json')))
            self.assertTrue(check(self.package(folder, pointer='../elsewhere')))
            self.assertTrue(check(self.package(folder, pointer='runtime-v9.9.9')))

    def test_macos_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'mac.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('Nimbus.app/Contents/MacOS/Nimbus', b'executable')
                archive.writestr('Nimbus.app/Contents/MacOS/ui/index.html', b'ui')
            self.assertEqual(check(path), [])
