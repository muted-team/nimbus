import hashlib
import io
import tempfile
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

from modules import client_updates as u


def release(version="1.0.3", data=b"zip"):
    name = f"nimbus-{version}-linux-x86_64.zip"
    return {
        "tag_name": "v" + version,
        "published_at": "2026-11-15T00:00:00Z",
        "assets": [
            {
                "name": name,
                "size": len(data),
                "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "browser_download_url": f"{u.RELEASES}/download/v{version}/{name}",
            }
        ],
    }


class UpdatesTests(unittest.TestCase):
    def test_platform_mapping_never_cross_installs(self):
        self.assertEqual(u.target("Windows", "AMD64"), "win32-AMD64")
        self.assertEqual(u.target("Darwin", "arm64"), "darwin-arm64")
        self.assertEqual(u.target("Linux", "x86_64"), "linux-x86_64")
        self.assertIsNone(u.target("Linux", "aarch64"))
        self.assertIsNone(u.target("Windows", "arm64"))

    def test_only_new_stable_matching_digest_asset(self):
        result = u.select_release(release(), "1.0.2", "linux-x86_64")
        self.assertTrue(result["available"])
        self.assertTrue(result["verified"])
        self.assertFalse(
            u.select_release(release(), "1.0.4", "linux-x86_64")["available"]
        )
        self.assertIsNone(u.select_release(release(), "1.0.2", "win32-AMD64")["asset"])
        payload = release()
        payload["prerelease"] = True
        with self.assertRaises(u.UpdateError):
            u.select_release(payload, "1.0.2", "linux-x86_64")
        payload = release()
        del payload["assets"][0]["digest"]
        self.assertFalse(u.select_release(payload, "1.0.2", "linux-x86_64")["verified"])

    def test_foreign_asset_url_rejected(self):
        payload = release()
        payload["assets"][0]["browser_download_url"] = "https://evil.test/payload"
        with self.assertRaises(u.UpdateError):
            u.select_release(payload, "1.0.2", "linux-x86_64")

    def test_archive_traversal_links_and_windows_paths_rejected(self):
        for name in (
            "Nimbus v1.0.3/../escape",
            "/escape",
            "Nimbus v1.0.3/C:evil",
            "Nimbus v1.0.3/dir\\evil",
            "Nimbus v1.0.3/NUL.txt",
            "Nimbus v1.0.3/Nimbus.",
            "Nimbus v1.0.3/dir /file",
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr(name, b"malicious")
                archive.seek(0)
                with self.assertRaises(u.UpdateError):
                    u.extract_archive(archive, Path(folder), "Nimbus v1.0.3")
                self.assertEqual(list(Path(folder).iterdir()), [])

    def installation(self, folder):
        from modules import bootstrap
        root = Path(folder).resolve() / "install"
        runtime = root / "runtimes" / "runtime-v1.0.2"
        runtime.mkdir(parents=True)
        (root / bootstrap.MARKER).write_text('{"format":1}')
        (root / bootstrap.POINTER).write_bytes(b'runtime-v1.0.2\n')
        (root / bootstrap.launcher_name()).write_bytes(b"launcher")
        (root / bootstrap.launcher_name()).chmod(0o755)
        (runtime / bootstrap.RUNTIME_MARKER).write_text('{"format":1,"version":"1.0.2"}')
        executable = runtime / bootstrap.executable_name()
        executable.write_bytes(b"current executable")
        return root, u.Updater(root, "1.0.2", True, "linux-x86_64", guarded=True, executable=executable)

    def package(self, pointer="runtime-v1.0.3"):
        from modules import bootstrap
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            top = "Nimbus v1.0.3/"
            z.writestr(top + bootstrap.launcher_name(), b"new launcher (never overwrite existing)")
            z.writestr(top + bootstrap.MARKER, '{"format":1}')
            z.writestr(top + bootstrap.POINTER, pointer + "\n")
            runtime = top + "runtimes/runtime-v1.0.3/"
            z.writestr(runtime + bootstrap.RUNTIME_MARKER, '{"format":1,"version":"1.0.3"}')
            z.writestr(runtime + bootstrap.executable_name(), b"new runtime")
            z.writestr(runtime + "ui/index.html", b"ui")
        return archive.getvalue()

    def test_download_verify_guarded_stage_without_publishing_or_data_changes(self):
        from modules import bootstrap
        data = self.package()
        with tempfile.TemporaryDirectory() as folder:
            root, updater = self.installation(folder)
            (root / "config.json").write_text('{"synthetic":true}')
            with (patch.object(u, "fetch_json", return_value=release(data=data)),
                  patch.object(u.urllib.request, "urlopen", return_value=io.BytesIO(data))):
                status = updater.prepare()
                self.assertEqual(status["state"], "ready")
                self.assertTrue(status["can_restart"])
            final = root / "runtimes/runtime-v1.0.3"
            self.assertFalse(final.exists())
            self.assertEqual((root / "config.json").read_text(), '{"synthetic":true}')
            self.assertEqual((root / bootstrap.launcher_name()).read_bytes(), b"launcher")
            self.assertEqual(bootstrap.selected_runtime(root).name, "runtime-v1.0.2")
            arguments = updater.activation_arguments()
            self.assertEqual(arguments, (str(root), str(updater.staged[1]), "1.0.3"))
            self.assertEqual(updater.staged[2], root)
            with patch.object(u, "fetch_json", side_effect=AssertionError("Must retain verified snapshot")):
                self.assertEqual(updater.check()["latest_version"], "1.0.3")
                self.assertEqual(updater.prepare()["state"], "ready")
            (root / bootstrap.POINTER).write_text("../other\n")
            self.assertFalse(updater.status()["can_restart"])
            with self.assertRaises(u.UpdateError):
                updater.activation_arguments()

    @unittest.skipUnless(sys.platform in ('linux', 'win32'), 'Linux or Windows activation lock')
    def test_verified_stage_handoff_waits_for_guard_and_preserves_all_userdata(self):
        from modules import bootstrap
        from modules.update_lock import InstallationLock
        data = self.package()
        with tempfile.TemporaryDirectory() as folder:
            root, updater = self.installation(folder)
            userdata = {"data.db": b"database fixture", "custom-folder/unknown.bin": b"unknown data", "accounts.json": b"accounts"}
            for name, content in userdata.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            with (patch.object(u, "fetch_json", return_value=release(data=data)),
                  patch.object(u.urllib.request, "urlopen", return_value=io.BytesIO(data))):
                updater.prepare()
            guard = InstallationLock(root).acquire()
            process = None
            try:
                script = "import sys; from modules.bootstrap import activate; activate(*sys.argv[1:4],timeout=5,expected_digest=sys.argv[4])"
                process = subprocess.Popen([sys.executable, "-c", script, *updater.activation_arguments(), updater.activation_digest()],
                                           cwd=Path(__file__).resolve().parents[1])
                time.sleep(.2)
                self.assertIsNone(process.poll(), "Helper must wait for runtime ownership to end")
                self.assertEqual(bootstrap.selected_runtime(root).name, "runtime-v1.0.2")
                guard.close()
                self.assertEqual(process.wait(timeout=10), 0)
                self.assertEqual(bootstrap.selected_runtime(root).name, "runtime-v1.0.3")
                self.assertEqual((root / bootstrap.launcher_name()).read_bytes(), b"launcher")
                for name, content in userdata.items():
                    self.assertEqual((root / name).read_bytes(), content)
            finally:
                guard.close()
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def test_tampered_verified_stage_cannot_be_handed_to_helper(self):
        from modules import bootstrap
        data = self.package()
        with tempfile.TemporaryDirectory() as folder:
            _, updater = self.installation(folder)
            with (patch.object(u, "fetch_json", return_value=release(data=data)),
                  patch.object(u.urllib.request, "urlopen", return_value=io.BytesIO(data))):
                updater.prepare()
            expected = bootstrap.inventory_digest(updater.staged[1])
            self.assertEqual(updater.activation_digest(), expected)
            (updater.staged[1] / bootstrap.executable_name()).write_bytes(b"changed")
            self.assertEqual(updater.activation_digest(), expected, "Helper digest must come from the SAVED verified snapshot")
            self.assertNotEqual(bootstrap.inventory_digest(updater.staged[1]), expected)
            with self.assertRaisesRegex(u.UpdateError, "повреждено"):
                updater.activation_arguments()

    def test_legacy_installation_cannot_prepare_even_with_release_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            root, updater = self.installation(folder)
            updater.guarded = False
            with patch.object(u, "fetch_json", return_value=release(data=self.package())):
                self.assertFalse(updater.check()["supported"])
                with self.assertRaises(u.UpdateError):
                    updater.prepare()
            self.assertIsNone(updater.staged)
            self.assertFalse(list(root.glob(".nimbus-update-*")))

    def test_wrong_archive_pointer_fails_closed_without_installing(self):
        data = self.package("../untrusted")
        with tempfile.TemporaryDirectory() as folder:
            root, updater = self.installation(folder)
            with (patch.object(u, "fetch_json", return_value=release(data=data)),
                  patch.object(u.urllib.request, "urlopen", return_value=io.BytesIO(data))):
                with self.assertRaises(u.UpdateError):
                    updater.prepare()
            self.assertIsNone(updater.staged)
            self.assertFalse(list(root.glob(".nimbus-update-*")))
            self.assertEqual((root / ".nimbus-current").read_text(), "runtime-v1.0.2\n")

    def test_archive_symlink_and_user_data_injection_rejected(self):
        for name, mode in (
            ("Nimbus v1.0.3/link", 0o120777),
            ("Nimbus v1.0.3/config.json", 0o100644),
            ("Nimbus v1.0.3/sessions/account.json", 0o100644),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w") as z:
                    info = zipfile.ZipInfo(name)
                    info.external_attr = mode << 16
                    z.writestr(info, b"untrusted")
                archive.seek(0)
                with self.assertRaises(u.UpdateError):
                    u.extract_archive(archive, Path(folder), "Nimbus v1.0.3")
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_corrupt_download_cleans_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root, updater = self.installation(folder)
            with (patch.object(u, "fetch_json", return_value=release(data=b"good")),
                  patch.object(u.urllib.request, "urlopen", return_value=io.BytesIO(b"evil"))):
                with self.assertRaisesRegex(u.UpdateError, "целостности"):
                    updater.prepare()
            self.assertIsNone(updater.staged)
            self.assertFalse(list(root.glob(".nimbus-update-*")))

    def test_tampered_stage_native_restart_keeps_window_open(self):
        import importlib.util
        import types
        from unittest.mock import Mock
        from modules import bootstrap
        data = self.package()
        with tempfile.TemporaryDirectory() as folder:
            root, updater = self.installation(folder)
            with (patch.object(u, "fetch_json", return_value=release(data=data)),
                  patch.object(u.urllib.request, "urlopen", return_value=io.BytesIO(data))):
                updater.prepare()
            (updater.staged[1] / bootstrap.executable_name()).write_bytes(b"tampered")
            spec = importlib.util.spec_from_file_location("nimbus_tampered_restart", Path(__file__).resolve().parents[1] / "app.py")
            app = importlib.util.module_from_spec(spec)
            webview = types.ModuleType("webview")
            window = Mock()
            webview.windows = [window]
            with patch.dict(sys.modules, {"webview": webview}):
                spec.loader.exec_module(app)
            app._BOOTSTRAP_GUARD = object()
            api = app.Api()
            with (patch.object(api, "_client_updater", return_value=updater),
                  patch("subprocess.Popen") as launch,
                  patch("threading.Timer") as close,
                  patch("modules.update_activity.freeze") as freeze):
                result = api.restart_client_update()
            self.assertIn("повреждено", result["error"])
            launch.assert_not_called()
            close.assert_not_called()
            freeze.assert_not_called()
            window.destroy.assert_not_called()
            self.assertEqual(bootstrap.selected_runtime(root).name, "runtime-v1.0.2")

    def test_activation_digest_requires_verified_prepared_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            _, updater = self.installation(folder)
            with self.assertRaises(u.UpdateError):
                updater.activation_digest()

    def test_concurrent_and_source_installs_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            updater = u.Updater(folder, "1.0.2", False, "linux-x86_64")
            updater.lock.acquire()
            with self.assertRaisesRegex(u.UpdateError, "уже"):
                updater.check()
            updater.lock.release()
            with patch.object(u, "fetch_json", return_value=release()):
                self.assertFalse(updater.check()["supported"])
                with self.assertRaises(u.UpdateError):
                    updater.prepare()




class UpdateBridgeTests(unittest.TestCase):
    def test_unexpected_native_errors_do_not_expose_internal_paths(self):
        import importlib.util
        import sys
        import types
        from unittest.mock import Mock

        spec = importlib.util.spec_from_file_location(
            "nimbus_update_bridge", Path(__file__).resolve().parents[1] / "app.py"
        )
        app = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"webview": types.ModuleType("webview")}):
            spec.loader.exec_module(app)
        api = app.Api()
        updater = Mock()
        updater.check.side_effect = OSError("/private/internal/data.db")
        updater.prepare.side_effect = OSError("/private/internal/config.json")
        with patch.object(api, "_client_updater", return_value=updater):
            for result in (api.check_client_update(), api.prepare_client_update()):
                self.assertIn("error", result)
                self.assertNotIn("/private", str(result))

if __name__ == "__main__":
    unittest.main()
