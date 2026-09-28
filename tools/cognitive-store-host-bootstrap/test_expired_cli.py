#!/usr/bin/env python3
"""Exercise the actual bootstrap CLI, not a hand-spliced transition fixture."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_bootstrap import bootstrap, anchor, authority, OWNER, HEX_B, HEX_C, HEX_D


class ExpiredCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = b"independent-host-test-key" * 3
        self.key_file = self.root / "key"
        self.key_file.write_bytes(self.key)
        os.chmod(self.key_file, 0o600)
        self.input = self.root / "input.json"
        self.output = self.root / "output.json"
        self.details = self.root / "details.json"
        self.payload = bootstrap.prepare(
            owner=OWNER, anchor=anchor(), authority=authority(expiry=500),
            lease_id="lease-1", generation=1, pointer_digest=HEX_C,
            database_digest=HEX_D, predecessor=None, now=100,
        )
        self.install(self.payload)

    def install(self, payload, key=None):
        bootstrap.atomic_write(self.input, bootstrap.envelope(payload, key or self.key))

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(Path(bootstrap.__file__)),
             "--key-file", str(self.key_file), *args],
            text=True, capture_output=True, check=False, timeout=10,
        )

    def transition(self, target, details):
        self.details.write_text(json.dumps(details), encoding="utf-8")
        return self.cli("transition", "--input", str(self.input), "--target", target,
                        "--details", str(self.details), "--output", str(self.output))

    def assert_success(self, result, target):
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(self.output.read_text())
        self.assertEqual(document["payload"]["state"], target)
        self.assertEqual(document["payload"]["authority"], self.payload["authority"])
        self.assertEqual(document["payload"]["writer_generation"], 1)
        self.assertEqual(document["payload"]["recovery_anchor"], self.payload["recovery_anchor"])
        expected = bootstrap.sign(document["payload"], self.key)
        self.assertEqual(document["signature"], expected)

    def test_expired_cli_can_record_revocation(self):
        self.assert_success(self.transition("revoked", {"reason": "expired shutdown"}), "revoked")

    def test_expired_cli_can_record_indeterminate(self):
        self.assert_success(self.transition("indeterminate", {"reason": "unknown pointer"}), "indeterminate")

    def test_expired_cli_can_prepare_governed_rollback_evidence(self):
        current = bootstrap.transition(self.payload, "active", details={"canary": {
            "status": "committed", "before_state_digest": HEX_B, "after_state_digest": HEX_C,
        }}, now=101)
        self.install(current)
        self.assert_success(self.transition("rollback_prepared", {"compatibility_digest": HEX_D}), "rollback_prepared")

    def test_expired_cli_can_record_rollback_terminal(self):
        current = bootstrap.transition(self.payload, "indeterminate", details={"reason": "unknown"}, now=101)
        current = bootstrap.transition(current, "rollback_prepared", details={"compatibility_digest": HEX_D}, now=102)
        self.install(current)
        self.assert_success(self.transition("rolled_back", {"reason": "external reconciliation"}), "rolled_back")

    def test_expired_cli_cannot_activate(self):
        result = self.transition("active", {"canary": {
            "status": "committed", "before_state_digest": HEX_B, "after_state_digest": HEX_C,
        }})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_expired_cli_verify_still_rejects_admission(self):
        result = self.cli("verify", "--input", str(self.input))
        self.assertNotEqual(result.returncode, 0)

    def test_expired_cli_inspect_is_explicitly_non_authorizing(self):
        result = self.cli("inspect", "--input", str(self.input))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIs(json.loads(result.stdout)["admission_authority"], False)

    def test_tampered_expired_bundle_cannot_record_terminal(self):
        document = json.loads(self.input.read_text())
        document["payload"]["database_sha256"] = "f" * 64
        self.input.write_text(json.dumps(document))
        self.assertNotEqual(self.transition("revoked", {"reason": "tamper"}).returncode, 0)
        self.assertFalse(self.output.exists())

    def test_wrong_host_key_cannot_record_terminal(self):
        self.install(self.payload, b"another-host-key" * 4)
        self.assertNotEqual(self.transition("revoked", {"reason": "wrong key"}).returncode, 0)
        self.assertFalse(self.output.exists())

    def test_terminal_bundle_cannot_reactivate(self):
        current = bootstrap.transition(self.payload, "revoked", details={"reason": "revoke"}, now=101)
        self.install(current)
        self.assertNotEqual(self.transition("active", {}).returncode, 0)
        self.assertFalse(self.output.exists())

    def test_terminal_still_requires_reason(self):
        self.assertNotEqual(self.transition("indeterminate", {}).returncode, 0)
        self.assertFalse(self.output.exists())

    def test_historical_authentication_rejects_invalid_expiry_shape(self):
        payload = copy.deepcopy(self.payload)
        payload["authority"]["lease_expires_at_unix_seconds"] = True
        self.install(payload)
        self.assertNotEqual(self.transition("revoked", {"reason": "invalid"}).returncode, 0)
        self.assertFalse(self.output.exists())

    def test_details_cannot_forge_observation_time(self):
        self.assertNotEqual(self.transition("revoked", {
            "reason": "time drift", "observed_at_unix_seconds": 1,
        }).returncode, 0)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
