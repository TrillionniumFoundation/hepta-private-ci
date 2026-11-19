"""Synthetic NEGATIVE protocol tests. These are NOT real deployed Cell evidence."""
from __future__ import annotations

import base64
import copy
import hashlib
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MODULE = Path(__file__).with_name("a0_deployment_evidence.py")
spec = importlib.util.spec_from_file_location("a0_deployment_evidence", MODULE)
assert spec is not None and spec.loader is not None
a0 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a0)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class A0ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "cells").mkdir()
        (self.root / "artifacts").mkdir()
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.key_id = sha(public)
        self.public_key = self.root / "operator.pem"
        self.public_key.write_bytes(self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ))
        self.cell_id = "cell-A"
        self.weights = b"synthetic-weights-NOT-A-PRODUCTION-ARTIFACT"
        self.checkpoint = b"synthetic-journal-NOT-A-PRODUCTION-JOURNAL"
        self.weights_path = "artifacts/weights.bin"
        self.checkpoint_path = "artifacts/journal.bin"
        (self.root / self.weights_path).write_bytes(self.weights)
        (self.root / self.checkpoint_path).write_bytes(self.checkpoint)
        self.manifest = {
            "schema": a0.SCHEMA_MANIFEST,
            "model_digest": sha(b"model"),
            "mechanism": "sparse-v1",
            "generation": 7,
            "weights_sha256": sha(self.weights),
            "weights_bytes": len(self.weights),
            "parameter_count": 10,
        }
        self.manifest_path = "artifacts/manifest.json"
        manifest_bytes = a0.canonical(self.manifest)
        (self.root / self.manifest_path).write_bytes(manifest_bytes)
        self.registry = {
            "schema": a0.SCHEMA_REGISTRY,
            "host_id": "host-1",
            "observed_at_utc": "2026-10-11T01:00:00Z",
            "active_cells": [
                {"cell_id": self.cell_id, "generation": 7, "mechanism": "sparse-v1"}
            ],
        }
        self.cell = {
            "schema": a0.SCHEMA_CELL,
            "host_id": self.registry["host_id"],
            "observed_at_utc": self.registry["observed_at_utc"],
            "cell_id": self.cell_id,
            "generation": 7,
            "mechanism": "sparse-v1",
            "model_digest": sha(b"model"),
            "manifest_path": self.manifest_path,
            "manifest_sha256": sha(manifest_bytes),
            "weights_path": self.weights_path,
            "weights_sha256": sha(self.weights),
            "weights_bytes": len(self.weights),
            "parameter_count": 10,
            "checkpoint_path": self.checkpoint_path,
            "checkpoint_sha256": sha(self.checkpoint),
            "checkpoint_sequence": 2,
            "reopen_checkpoint_digest": sha(b"verified-runtime-reopen"),
            "resource_receipt": {
                "measurement_kind": "target-host-observed",
                "host_profile_digest": sha(b"host"),
                "cpu_micros": 20,
                "peak_rss_bytes": 10_000,
                "p95_micros": 20,
                "p99_micros": 21,
                "sample_count": 100,
                "replay_verified": True,
            },
        }
        self.write_signed()

    def sign(self, payload: dict) -> dict:
        return {
            "payload": payload,
            "signer_key_id": self.key_id,
            "signature_b64": base64.b64encode(self.key.sign(a0.canonical(payload))).decode(),
        }

    def write_signed(self) -> None:
        (self.root / "registry.json").write_bytes(a0.canonical(self.sign(self.registry)))
        (self.root / "cells" / f"{self.cell_id}.json").write_bytes(
            a0.canonical(self.sign(self.cell))
        )

    def check(self) -> dict:
        return a0.evaluate(self.root, self.public_key)

    def test_signed_format_is_accepted_without_promotion_claim(self) -> None:
        result = self.check()
        self.assertEqual(result["cell_count"], 1)
        self.assertEqual(result["status"], "signed-evidence-format-verified")
        self.assertFalse(result["production_qualification"])

    def test_without_real_weight_bytes_blocked(self) -> None:
        (self.root / self.weights_path).unlink()
        with self.assertRaises((a0.EvidenceError, FileNotFoundError)):
            self.check()

    def test_tampered_weight_bytes_blocked(self) -> None:
        (self.root / self.weights_path).write_bytes(self.weights + b"tamper")
        with self.assertRaisesRegex(a0.EvidenceError, "weights: bytes do not match"):
            self.check()

    def test_tampered_signed_cell_blocked(self) -> None:
        evidence_path = self.root / "cells" / f"{self.cell_id}.json"
        envelope = json.loads(evidence_path.read_text())
        envelope["payload"]["parameter_count"] += 1
        evidence_path.write_bytes(a0.canonical(envelope))
        with self.assertRaisesRegex(a0.EvidenceError, "invalid signature"):
            self.check()

    def test_missing_cell_or_extra_cell_blocks_complete_census(self) -> None:
        (self.root / "cells" / f"{self.cell_id}.json").unlink()
        with self.assertRaises((a0.EvidenceError, FileNotFoundError)):
            self.check()
        self.write_signed()
        (self.root / "cells" / "rogue.json").write_text("{}")
        with self.assertRaisesRegex(a0.EvidenceError, "census differ"):
            self.check()

    def test_synthetic_receipt_rejected_even_if_signed(self) -> None:
        self.cell["resource_receipt"]["measurement_kind"] = "synthetic"
        self.write_signed()
        with self.assertRaisesRegex(a0.EvidenceError, "fixtures, projections"):
            self.check()

    def test_signed_cross_generation_drift_blocked(self) -> None:
        self.registry["active_cells"][0]["generation"] += 1
        self.write_signed()
        with self.assertRaisesRegex(a0.EvidenceError, "registry mismatch in generation"):
            self.check()

    def test_missing_replay_attestation_blocked(self) -> None:
        self.cell["resource_receipt"]["replay_verified"] = False
        self.write_signed()
        with self.assertRaisesRegex(a0.EvidenceError, "host replay attestation"):
            self.check()

    def test_traversal_to_external_artifact_blocked(self) -> None:
        self.cell["weights_path"] = "../../secret"
        self.write_signed()
        with self.assertRaises((a0.EvidenceError, FileNotFoundError)):
            self.check()

    def test_duplicate_json_keys_are_rejected_before_signature_use(self) -> None:
        envelope_path = self.root / "registry.json"
        original = envelope_path.read_text()
        self.assertTrue(original.startswith("{"))
        # Even if a parser would accept last-write-wins, no ambiguous
        # signed registry object is accepted into the deployment census.
        envelope_path.write_text(original[:-1] + ',"signer_key_id":"evil"}')
        with self.assertRaisesRegex(a0.EvidenceError, "duplicate JSON key"):
            self.check()

    def test_symlinked_model_artifacts_are_not_accepted(self) -> None:
        link = self.root / "artifacts" / "linked-weights.bin"
        link.symlink_to(self.root / self.weights_path)
        self.cell["weights_path"] = "artifacts/linked-weights.bin"
        self.write_signed()
        with self.assertRaisesRegex(a0.EvidenceError, "symlinks are not evidence"):
            self.check()

    def test_traversal_even_if_remaining_inside_root_is_rejected(self) -> None:
        self.cell["weights_path"] = "cells/../artifacts/weights.bin"
        self.write_signed()
        with self.assertRaisesRegex(a0.EvidenceError, "traversal components rejected"):
            self.check()

    def test_dot_cell_id_rejected_before_resolving_a_path(self) -> None:
        self.registry["active_cells"][0]["cell_id"] = ".."
        self.write_signed()
        with self.assertRaisesRegex(a0.EvidenceError, "invalid Cell identifier"):
            self.check()

    def test_fresh_explicit_host_snapshot_is_accepted_but_not_qualified(self) -> None:
        result = a0.evaluate(
            self.root, self.public_key,
            expected_host_id="host-1", max_age_seconds=300,
            evaluation_asof_utc=datetime(2026, 10, 11, 1, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(result["host_id"], "host-1")
        self.assertFalse(result["production_qualification"])

    def test_stale_or_future_dated_signed_registry_is_rejected(self) -> None:
        with self.assertRaisesRegex(a0.EvidenceError, "stale"):
            a0.evaluate(
                self.root, self.public_key,
                expected_host_id="host-1", max_age_seconds=300,
                evaluation_asof_utc=datetime(2026, 10, 11, 2, 0, tzinfo=timezone.utc),
            )
        with self.assertRaisesRegex(a0.EvidenceError, "future"):
            a0.evaluate(
                self.root, self.public_key,
                expected_host_id="host-1", max_age_seconds=300,
                evaluation_asof_utc=datetime(2026, 10, 11, 0, 50, tzinfo=timezone.utc),
            )

    def test_wrong_expected_host_and_unbounded_age_are_rejected(self) -> None:
        asof = datetime(2026, 10, 11, 1, 2, tzinfo=timezone.utc)
        with self.assertRaisesRegex(a0.EvidenceError, "independently expected host"):
            a0.evaluate(
                self.root, self.public_key,
                expected_host_id="host-rogue", max_age_seconds=300,
                evaluation_asof_utc=asof,
            )
        with self.assertRaisesRegex(a0.EvidenceError, "maximum snapshot age"):
            a0.evaluate(
                self.root, self.public_key,
                expected_host_id="host-1", max_age_seconds=1_000_000,
                evaluation_asof_utc=asof,
            )

    def test_model_manifest_drift_is_detected(self) -> None:
        self.cell["parameter_count"] += 1
        self.write_signed()
        with self.assertRaisesRegex(a0.EvidenceError, "manifest conflicts"):
            self.check()


if __name__ == "__main__":
    unittest.main()
