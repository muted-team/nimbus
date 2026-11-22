import contextlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import config, paths
with patch.object(config, "get", side_effect=lambda name, default=None: default):
    from modules import client_device, client_session
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


class HttpProfileLifecycleTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(paths.use_root(self.root))
        stack.enter_context(patch.object(config, "get", side_effect=lambda name, default=None: default))
        stack.enter_context(patch.object(client_session, "_state_generations", {}))
        stack.enter_context(client_device.use_browser_profile("chrome152"))

    def seed(self, username="synthetic.user"):
        originals = {}
        for profile in client_device.BROWSER_PROFILES:
            with client_device.use_browser_profile(profile):
                folder = client_session.session_directory()
                folder.mkdir(parents=True, exist_ok=True)
                for suffix in (".json", ".jar", ".state", ".browser.state", ".device.json", ".device.state"):
                    path = folder / (username + suffix)
                    value = f"synthetic-{profile}-{suffix}".encode()
                    path.write_bytes(value)
                    originals[path] = value
        return originals

    def test_forget_clears_all_http_profiles_but_preserves_each_device(self):
        originals = self.seed()
        other = self.seed("synthetic.other")
        self.assertEqual(client_session.clear_session("synthetic.user"), 1)
        for path, value in originals.items():
            if path.name.endswith((".device.json", ".device.state")):
                self.assertEqual(path.read_bytes(), value)
            else:
                self.assertFalse(path.exists(), path)
            self.assertFalse(client_session.write_state_if_current(path, "stale-response", 0))
        self.assertEqual(client_session.clear_session("synthetic.user"), 0)
        self.assertEqual(client_session.clear_session("synthetic.user", new_device=True), 0)
        self.assertTrue(all(not path.exists() for path in originals))
        self.assertEqual({path: path.read_bytes() for path in other}, other)
        self.assertEqual(client_device.browser_profile(), "chrome152")

    def test_account_rename_moves_all_profile_bytes_and_invalidates_old_replies(self):
        originals = self.seed()
        self.assertTrue(client_session.rename_jar("synthetic.user", "synthetic.new"))
        for path, value in originals.items():
            target = path.with_name(path.name.replace("synthetic.user", "synthetic.new", 1))
            self.assertFalse(path.exists(), path)
            self.assertEqual(target.read_bytes(), value)
            self.assertFalse(client_session.write_state_if_current(path, "stale-response", 0))
            self.assertFalse(client_session.write_state_if_current(target, "stale-response", 0))
        self.assertEqual(client_device.browser_profile(), "chrome152")

    def test_late_profile_rename_failure_rolls_back_all_prior_moves(self):
        originals = self.seed()
        replace = Path.replace

        def fail_camoufox(path, target):
            if path.parent.name == "camoufox158" and path.name.endswith(".state"):
                raise OSError("synthetic late namespace failure")
            return replace(path, target)

        with patch.object(Path, "replace", autospec=True, side_effect=fail_camoufox):
            with self.assertRaises(OSError):
                client_session.rename_jar("synthetic.user", "synthetic.new")
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        self.assertEqual(list(self.root.rglob("synthetic.new.*")), [])

    def test_rename_collision_keeps_all_old_and_new_profile_state_bytes(self):
        originals = self.seed()
        target = self.root / "sessions/camoufox158/synthetic.new.device.state"
        target.write_bytes(b"synthetic-previous-camoufox-device")
        originals[target] = target.read_bytes()
        with self.assertRaises(OSError):
            client_session.rename_jar("synthetic.user", "synthetic.new")
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        self.assertEqual(list(self.root.rglob("synthetic.new.*")), [target])

    def test_repeating_an_already_completed_rename_is_a_noop(self):
        originals = self.seed()
        self.assertTrue(client_session.rename_jar("synthetic.user", "synthetic.new"))
        targets = {path.with_name(path.name.replace("synthetic.user", "synthetic.new", 1)): value
                   for path, value in originals.items()}
        self.assertFalse(client_session.rename_jar("synthetic.user", "synthetic.new"))
        self.assertEqual({path: path.read_bytes() for path in targets}, targets)

    def test_fileless_rename_transfers_quarantine_without_claiming_files_moved(self):
        from modules import profiles
        profiles.mark_identity_conflict("synthetic.user")
        marker = profiles.identity_conflict_marker("synthetic.user")
        self.assertFalse(client_session.rename_jar("synthetic.user", "synthetic.new"))
        self.assertIs(profiles.identity_conflict_marker("synthetic.new"), marker)
        self.assertIsNone(profiles.identity_conflict_marker("synthetic.user"))

    def test_fileless_rename_preserves_orphan_state_and_newer_target_quarantine(self):
        from modules import profiles
        targets = self.seed("synthetic.new")
        profiles.mark_identity_conflict("synthetic.user")
        profiles.mark_identity_conflict("synthetic.new")
        newer = profiles.identity_conflict_marker("synthetic.new")
        self.assertFalse(client_session.rename_jar("synthetic.user", "synthetic.new"))
        self.assertEqual({path: path.read_bytes() for path in targets}, targets)
        self.assertIs(profiles.identity_conflict_marker("synthetic.new"), newer)
        self.assertIsNone(profiles.identity_conflict_marker("synthetic.user"))

    def test_account_rename_collision_restores_the_shared_registry(self):
        from modules import accounts
        originals = self.seed()
        registry = paths.here(accounts.ACCOUNTS_FILE)
        registry.write_text(json.dumps({"accounts": [{"username": "synthetic.user",
                                                      "password": "synthetic-password"}]}))
        before = registry.read_bytes()
        target = self.root / "sessions/camoufox158/synthetic.new.device.state"
        target.write_bytes(b"synthetic-previous-camoufox-device")
        originals[target] = target.read_bytes()
        with self.assertRaises(OSError):
            accounts.update_account("synthetic.user", {"username": "synthetic.new"})
        self.assertEqual(registry.read_bytes(), before)
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    def test_remove_account_removes_authentication_from_all_three_namespaces(self):
        from modules import accounts, avatars, eventlog
        originals = self.seed()
        registry = paths.here(accounts.ACCOUNTS_FILE)
        registry.write_text(json.dumps({"accounts": [{"username": "synthetic.user",
                                                      "password": "synthetic-password"}]}))
        with patch.object(avatars, "remove"), patch.object(eventlog, "say"):
            self.assertTrue(accounts.remove_account("synthetic.user", new_device=True))
        self.assertEqual(json.loads(registry.read_text())["accounts"], [])
        self.assertTrue(all(not path.exists() for path in originals))

    def test_remove_account_keeps_distinct_devices_via_profile_bound_resets(self):
        from modules import accounts, avatars, cloud, eventlog
        originals = self.seed()
        registry = paths.here(accounts.ACCOUNTS_FILE)
        registry.write_text(json.dumps({"accounts": [{"username": "synthetic.user",
                                                      "password": "synthetic-password"}]}))
        seen = []

        def keep(username):
            seen.append(client_device.browser_profile())
            return True

        with patch.object(cloud, "keep_device", side_effect=keep), patch.object(
                avatars, "remove"), patch.object(eventlog, "say"):
            self.assertTrue(accounts.remove_account("synthetic.user"))
        self.assertEqual(seen, ["chrome152", "firefox155", "camoufox158"])
        for path, value in originals.items():
            if path.name.endswith((".device.json", ".device.state")):
                self.assertEqual(path.read_bytes(), value)
            else:
                self.assertFalse(path.exists())
