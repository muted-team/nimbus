"""The open checkout must work without any private service package."""

import ast
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules import paths, profiles, uniq


class ClientBoundaryTests(unittest.TestCase):
    def test_private_login_and_signing_packages_are_absent(self):
        for name in (
            "login",
            "signing",
            "signers",
            "device",
            "session_manager",
            "profile_fetch",
            "publish",
        ):
            self.assertFalse((ROOT / "modules" / name).exists())
            self.assertFalse((ROOT / "modules" / (name + ".py")).exists())
        self.assertFalse((ROOT / "server").exists())

    def test_profile_store_and_readback_work_with_synthetic_remote_rows(self):
        with tempfile.TemporaryDirectory() as temporary, paths.use_root(temporary):
            profiles.save_row(
                "synthetic.user",
                {
                    "username": "synthetic.user",
                    "nickname": "Synthetic",
                    "followers": 42,
                    "method": "ssr",
                },
            )
            self.assertEqual(profiles.get("synthetic.user")["followers"], 42)

    def test_unique_preview_preserves_image_and_returns_valid_local_output(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temporary, paths.use_root(temporary):
            source = Path(temporary) / "fixture.png"
            Image.new("RGB", (60, 40), (20, 60, 120)).save(source)
            settings = uniq.normalize(None)
            settings["enabled"] = True
            settings["compress"].update(enabled=True, min=90, max=90)
            with patch.object(uniq, "load", return_value=settings):
                result = uniq.render_file(source)
            with Image.open(io.BytesIO(result)) as image:
                image.load()
                self.assertGreater(image.width, 0)
                self.assertGreater(image.height, 0)
            self.assertTrue(source.exists())

    def test_profile_edit_is_a_thin_service_bridge_without_native_tiktok_code(self):
        self.assertFalse(hasattr(profiles, "profile_edit_update"))
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        handler = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_api_profile_edit"
        )
        dispatched = {
            n.func.attr
            for n in ast.walk(handler)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "profile_edit"
        }
        self.assertEqual(dispatched, {"info", "plan", "update"})
        source = (ROOT / "modules/profile_edit.py").read_text(encoding="utf-8")
        bridge = ast.parse(source)
        calls = {
            n.func.attr
            for n in ast.walk(bridge)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "cloud"
        }
        self.assertEqual(calls, {"profile_info", "profile_plan", "profile_update"})
        self.assertNotIn("curl_cffi", source)
        self.assertNotIn("sign_url", source)
        self.assertNotIn("/passport/", source)
        self.assertNotIn("tiktok.com", source)


if __name__ == "__main__":
    unittest.main()
