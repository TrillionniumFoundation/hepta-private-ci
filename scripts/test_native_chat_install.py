"""Real FD inputs and closed plans; never calls Root services or keyring."""

import copy
import json
import os
import sys
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import native_chat_install_io as io
import native_chat_install_plan as plan
from native_chat_install_test_support import fixture


@unittest.skipUnless(sys.platform == "linux", "closed Linux systemd installer")
class PlanTests(unittest.TestCase):
    def test_original_dispatch_and_restore_preserve_each_purpose(self):
        request, policy, unit, desktop = fixture()
        checked = plan.checked(request, policy, unit, desktop)
        chat = plan.gateway_args(checked, "fresh-chat")
        baseline = plan.gateway_args(checked)
        self.assertEqual(
            baseline, [request["gateway"]["path"], *checked["original_args"][2:]]
        )
        self.assertNotIn("--serve-ui", chat)
        self.assertEqual(chat[: len(baseline)], baseline)
        self.assertEqual(
            chat[len(baseline) :],
            [
                "--chat-socket",
                plan.SOCKET,
                "--chat-owner-uid",
                "0",
                "--chat-auth-keyring-account",
                "fresh-chat",
                "--chat-capability-file",
                str(plan.CAPABILITY),
            ],
        )
        changed = json.loads(checked["target_policy"])
        original = json.loads(policy)
        original["controller_principal"]["gateway_executable"] = request["gateway"][
            "path"
        ]
        self.assertEqual(changed, original)
        self.assertEqual(json.loads(desktop), checked["desktop"])

    def test_stale_originals_and_other_principals_cannot_be_installed(self):
        request, policy, unit, desktop = fixture()
        for modified in (policy + b" ",):
            with self.assertRaises(ValueError):
                plan.checked(request, modified, unit, desktop)
        altered = json.loads(policy)
        for mutation in (
            lambda p: p.update(workload_uid=1000),
            lambda p: p["controller_principal"].update(desktop_uid=986),
            lambda p: p.update(agent_workload_uids={}),
        ):
            candidate = copy.deepcopy(altered)
            mutation(candidate)
            raw = io.encode(candidate)
            fixed = {**request, "original_policy_sha256": io.digest(raw)}
            with self.assertRaises(ValueError):
                plan.checked(fixed, raw, unit, desktop)

    def test_old_helper_and_duplicate_or_unknown_configuration_are_rejected(self):
        request, policy, unit, desktop = fixture()
        old = copy.deepcopy(request)
        old["credential_helper"]["sha256"] = "b" * 64
        with self.assertRaises(ValueError):
            plan.checked(old, policy, unit, desktop)
        for field in ("chat_keyring_account", "unsupported_flag"):
            raw = io.encode({**json.loads(desktop), field: "already-configured"})
            changed = copy.deepcopy(request)
            changed["desktop_config"]["sha256"] = io.digest(raw)
            with self.assertRaises(ValueError):
                plan.checked(changed, policy, unit, raw)
        bad = io.encode({**json.loads(desktop), "state_dir": None})
        malformed = copy.deepcopy(request)
        malformed["desktop_config"]["sha256"] = io.digest(bad)
        with self.assertRaises(ValueError):
            plan.checked(malformed, policy, unit, bad)
        with self.assertRaises(ValueError):
            json.loads('{"schema":1,"schema":2}', object_pairs_hook=io.unique_object)


@unittest.skipUnless(sys.platform == "linux", "Linux non-following FD checks")
class PhysicalInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".hepta-install-test-", dir=Path.home()
        )
        self.root = Path(self.temporary.name)
        self.uid = os.getuid()

    def tearDown(self):
        self.temporary.cleanup()

    def test_real_fd_detects_mutation_replacement_links_and_fifo_without_blocking(self):
        path = self.root / "public.json"
        path.write_bytes(b"first")
        path.chmod(0o600)
        self.assertEqual(io.read_public(path, owner=self.uid), b"first")
        with self.assertRaises(ValueError):
            with io.regular_file(path, self.uid):
                path.write_bytes(b"other")
        with self.assertRaises(ValueError):
            with io.regular_file(path, self.uid):
                path.unlink()
                path.write_bytes(b"other")
        alias = self.root / "alias"
        alias.symlink_to(path)
        with self.assertRaises(OSError):
            io.read_public(alias, owner=self.uid)
        os.link(path, self.root / "hardlink")
        with self.assertRaises(ValueError):
            io.read_public(path, owner=self.uid)
        fifo = self.root / "fifo"
        os.mkfifo(fifo, 0o600)
        started = time.monotonic()
        with self.assertRaises(ValueError):
            io.read_public(fifo, owner=self.uid)
        self.assertLess(time.monotonic() - started, 1)

    def test_bounded_bundle_fixture_and_changed_resource(self):
        entries = []
        for name in ("hepta-robrix", "resources/icon.svg", "licenses/font.txt"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.parent.chmod(0o700)
            target.write_bytes(name.encode())
            target.chmod(0o600)
            entries.append(
                {"path": name, "sha256": io.digest(name.encode()), "size": len(name)}
            )
        manifest = self.root / "bundle-manifest.json"
        raw = io.encode(
            {
                "schema": "hepta.native.renderer-bundle.v1",
                "makepad_revision": "original",
                "files": entries,
                "installs_services": False,
            }
        )
        manifest.write_bytes(raw)
        manifest.chmod(0o600)
        request = {
            "renderer_manifest": {"path": str(manifest), "sha256": io.digest(raw)},
            "renderer": {"path": str(self.root / "hepta-robrix")},
        }
        # Only the test caller's UID changes: all real FD/namespace checks run.
        regular = io.regular_file
        with patch.object(
            io,
            "regular_file",
            side_effect=lambda path, owner=0: regular(path, self.uid),
        ):
            self.assertEqual(io.renderer_bundle(request), 3)
            (self.root / "resources/icon.svg").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                io.renderer_bundle(request)


if __name__ == "__main__":
    unittest.main()
