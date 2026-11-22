"""Release assembly keeps the native launcher separate from runtime code."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build


class BuildLayoutTests(unittest.TestCase):
    def test_linux_keeps_system_gi_namespaces_dynamic_with_bundled_overrides(self):
        options = {
            '--nofollow-import-to=gi.repository.*',
            '--include-package=gi.overrides',
            '--no-deployment-flag=gi-runtime-namespaces',
            '--no-deployment-flag=excluded-module-usage',
        }
        self.assertTrue(options <= set(build.nuitka_command('linux', Path('fixture-output'))))
        for target in ('win32', 'darwin'):
            with self.subTest(target=target):
                self.assertFalse(options & set(build.nuitka_command(target, Path('fixture-output'))))

    def test_every_runtime_explicitly_bundles_the_public_tls_trust_store(self):
        for target in ("linux", "win32", "darwin"):
            with self.subTest(target=target):
                self.assertIn("--include-package-data=certifi", build.nuitka_command(target, Path("fixture-output")))

    def test_runtime_name_and_launcher_metadata(self):
        for target, binary in [('linux', 'Nimbus-runtime'), ('win32', 'Nimbus-runtime.exe')]:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                built, destination = root / 'app.dist', root / 'Nimbus v1.2.3'
                built.mkdir()
                (built / binary).write_bytes(b'synthetic runtime')
                write_text = Path.write_text

                def windows_write_text(path, data, **options):
                    return write_text(path, data, **{"newline": "\r\n", **options})

                with (patch('build.subprocess.run') as compiler,
                      patch.object(Path, "write_text", windows_write_text)):
                    build.assemble_installation(built, destination, target, '1.2.3')
                self.assertEqual((destination / '.nimbus-current').read_bytes(), b'runtime-v1.2.3\n')
                self.assertEqual((destination / '.nimbus-bootstrap.json').read_text(), '{"format": 1}\n')
                self.assertEqual((destination / 'runtimes/runtime-v1.2.3' / binary).read_bytes(), b'synthetic runtime')
                self.assertEqual((destination / "runtimes/runtime-v1.2.3/.nimbus-runtime.json").read_text(), '{"format": 1, "version": "1.2.3"}\n')
                compiler.assert_called_once()
                self.assertIn('--output-filename=' + binary, build.nuitka_command(target, root))

    def test_macos_retains_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            built = root / 'app.app'
            built.mkdir()
            with patch('build.subprocess.run') as compiler:
                build.assemble_installation(built, root / 'Nimbus.app', 'darwin', '1.2.3')
            compiler.assert_not_called()
            self.assertTrue((root / 'Nimbus.app').is_dir())


if __name__ == '__main__':
    unittest.main()
