#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name("bootstrap.py")
spec = importlib.util.spec_from_file_location("cognitive_store_bootstrap", MODULE)
bootstrap = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(bootstrap)

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
OWNER = "00000000-0000-4000-8000-000000000058"


def anchor(state=HEX_B):
    return {
        "profile": "hepta:cognitive:exact-current-cut:v1",
        "owner_agent_id": OWNER,
        "schema_digest": HEX_A,
        "state_digest": state,
    }


def authority(epoch=1, owner_epoch=1, expiry=500):
    return {
        "agent_id": OWNER,
        "grant_digest": HEX_A,
        "authority_epoch": epoch,
        "owner_epoch": owner_epoch,
        "lease_expires_at_unix_seconds": expiry,
        "fencing_token_digest": HEX_C,
        "issuer_receipt_digest": HEX_D,
    }


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.key = b"k" * 64
        self.payload = bootstrap.prepare(
            owner=OWNER,
            anchor=anchor(),
            authority=authority(),
            lease_id="lease-1",
            generation=1,
            pointer_digest=HEX_C,
            database_digest=HEX_D,
            predecessor=None,
            now=100,
        )

    def test_signed_prepare_round_trip_and_atomic_permissions(self):
        value = bootstrap.envelope(self.payload, self.key)
        self.assertEqual(bootstrap.verify(value, self.key, now=100), self.payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            bootstrap.atomic_write(path, value)
            self.assertEqual(bootstrap.load_json(path), value)
            self.assertTrue(stat.S_ISREG(path.stat().st_mode))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_atomic_write_replaces_existing_bundle_without_temp_leak(self):
        first = bootstrap.envelope(self.payload, self.key)
        second_payload = bootstrap.transition(
            self.payload,
            "revoked",
            details={"reason": "replace atomically"},
            now=102,
        )
        second = bootstrap.envelope(second_payload, self.key)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "bundle.json"
            bootstrap.atomic_write(path, first)
            bootstrap.atomic_write(path, second)
            self.assertEqual(bootstrap.load_json(path), second)
            self.assertEqual([entry.name for entry in root.iterdir()], ["bundle.json"])

    def test_activation_requires_committed_cut_advancing_canary(self):
        with self.assertRaises(ValueError):
            bootstrap.transition(self.payload, "active", details={"canary": {"status": "failed"}}, now=101)
        active = bootstrap.transition(
            self.payload,
            "active",
            details={
                "canary": {
                    "status": "committed",
                    "before_state_digest": HEX_B,
                    "after_state_digest": HEX_C,
                    "operation_digest": HEX_D,
                }
            },
            now=101,
        )
        self.assertEqual(active["state"], "active")
        self.assertEqual(active["canary"]["after_state_digest"], HEX_C)

    def test_revocation_is_terminal(self):
        revoked = bootstrap.transition(self.payload, "revoked", details={"reason": "operator revoke"}, now=102)
        with self.assertRaises(ValueError):
            bootstrap.transition(revoked, "active", details={}, now=103)

    def test_pointer_publication_ambiguity_is_explicit(self):
        value = bootstrap.transition(self.payload, "indeterminate", details={"reason": "pointer rename fsync unknown"}, now=104)
        self.assertEqual(value["state"], "indeterminate")

    def test_rollback_requires_compatibility_digest(self):
        active = bootstrap.transition(
            self.payload,
            "active",
            details={"canary": {"status": "committed", "before_state_digest": HEX_B, "after_state_digest": HEX_C}},
            now=101,
        )
        with self.assertRaises(ValueError):
            bootstrap.transition(active, "rollback_prepared", details={}, now=105)
        rollback = bootstrap.transition(active, "rollback_prepared", details={"compatibility_digest": HEX_D}, now=105)
        self.assertEqual(rollback["state"], "rollback_prepared")

    def test_stale_or_expired_authority_rejects(self):
        with self.assertRaises(ValueError):
            bootstrap.prepare(
                owner=OWNER,
                anchor=anchor(),
                authority=authority(expiry=99),
                lease_id="lease-expired",
                generation=2,
                pointer_digest=HEX_C,
                database_digest=HEX_D,
                predecessor=HEX_A,
                now=100,
            )


if __name__ == "__main__":
    unittest.main()
