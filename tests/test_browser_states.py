import os
from pathlib import Path
import tempfile
import unittest

from modules.browser_states import BrowserStates


class BrowserStatesTests(unittest.TestCase):
    def test_browser_logout_preserves_legacy_and_other_modes_and_servers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "sessions" / "fixture.state"
            legacy.parent.mkdir()
            legacy.write_text("synthetic-http-state")
            a = BrowserStates(root / "browser", "server-a/key-a")
            b = BrowserStates(root / "browser", "server-b/key-a")
            a.write("fixture.user", 3, "synthetic-mode3")
            a.write("fixture.user", 4, "synthetic-mode4")
            b.write("fixture.user", 3, "synthetic-server-b")
            self.assertTrue(a.clear_confirmed("fixture.user", 3, {"ok": True, "confirmed": True}))
            self.assertIsNone(a.read("fixture.user", 3))
            self.assertEqual(a.read("fixture.user", 4), "synthetic-mode4")
            self.assertEqual(b.read("fixture.user", 3), "synthetic-server-b")
            self.assertEqual(legacy.read_text(), "synthetic-http-state")

    def test_unknown_logout_and_invalid_state_preserve_existing_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = BrowserStates(temporary, "synthetic-server")
            store.write("fixture.user", 3, "synthetic-state")
            for response in ({"ok": False}, {"ok": True}, {"ok": True, "confirmed": "yes"}):
                self.assertFalse(store.clear_confirmed("fixture.user", 3, response))
            with self.assertRaises(ValueError):
                store.write("fixture.user", 3, "")
            self.assertEqual(store.read("fixture.user", 3), "synthetic-state")
            if os.name != "nt":
                self.assertEqual(store.path("fixture.user", 3).stat().st_mode & 0o777, 0o600)

    def test_names_cannot_escape_state_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = BrowserStates(temporary, "synthetic-server")
            store.write("../../escape", 3, "synthetic")
            self.assertTrue(store.path("../../escape", 3).is_relative_to(temporary))
            with self.assertRaises(ValueError):
                store.read("fixture.user", True)

    def test_stable_owner_namespace_is_never_renamed_or_casefolded(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = BrowserStates(temporary, "synthetic-server")
            store.write("StableOwner", 3, "synthetic-state")
            self.assertIsNone(store.read("stableowner", 3))
            self.assertIsNone(store.read("display.username", 3))
