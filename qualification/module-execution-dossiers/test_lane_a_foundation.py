"""Closed-world tests for Lane A current implementation truth."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify_lane_a_foundation.py"
SPEC = importlib.util.spec_from_file_location("verify_lane_a_foundation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


class LaneAFoundationTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = verify.read_json(verify.MATRIX_PATH)
        cls.capability_map = verify.read_json(verify.CAPABILITY_MAP_PATH)

    def test_exact_repository_truth_is_valid(self) -> None:
        verify.validate_matrix(self.matrix)

    def test_closed_world_module_set(self) -> None:
        self.assertEqual(
            [row["module"] for row in self.matrix["modules"]],
            verify.EXPECTED_MODULES,
        )
        self.assertEqual(self.matrix["moduleCoverage"], 7)

    def test_every_current_capability_has_one_evidence_mapping(self) -> None:
        verify.validate_capability_map(self.matrix, self.capability_map)
        declared = [
            (row["module"], capability)
            for row in self.matrix["modules"]
            for capability in row["currentCapabilities"]
        ]
        mapped = [
            (entry["module"], entry["summary"])
            for entry in self.capability_map["entries"]
        ]
        self.assertEqual(len(declared), len(set(declared)))
        self.assertEqual(len(mapped), len(set(mapped)))
        self.assertCountEqual(mapped, declared)
        self.assertEqual(self.capability_map["entryCount"], len(mapped))

    def test_operations_cannot_claim_unimplemented_durability(self) -> None:
        value = deepcopy(self.matrix)
        value["modules"][3]["states"]["durability"] = "durable"
        with self.assertRaises(verify.VerificationError):
            verify.validate_matrix(value)

    def test_authbus_cannot_claim_policy_quota_or_key_hosting(self) -> None:
        for capability in (
            "authorization policy evaluation",
            "quota reservation and settlement",
            "host trust provisioning and key lifecycle management",
        ):
            with self.subTest(capability=capability):
                value = deepcopy(self.matrix)
                value["modules"][5]["currentCapabilities"].append(capability)
                with self.assertRaises(verify.VerificationError):
                    verify.validate_matrix(value)

    def test_authbus_cannot_claim_all_replay_paths_are_durable(self) -> None:
        value = deepcopy(self.matrix)
        value["modules"][5]["states"]["durability"] = "durable"
        with self.assertRaises(verify.VerificationError):
            verify.validate_matrix(value)

    def test_repository_cannot_self_grant_acceptance(self) -> None:
        value = deepcopy(self.matrix)
        value["closure"]["externalAcceptance"] = "closed"
        with self.assertRaises(verify.VerificationError):
            verify.validate_matrix(value)

    def test_current_and_target_capabilities_are_disjoint(self) -> None:
        for row in self.matrix["modules"]:
            self.assertFalse(
                set(row["currentCapabilities"]) & set(row["targetOnlyCapabilities"])
            )

    def test_missing_extra_or_duplicate_capability_mapping_is_rejected(self) -> None:
        entries = self.capability_map["entries"]
        extra = {
            **entries[0],
            "capabilityId": "test.undeclared.v1",
            "summary": "undeclared capability",
        }
        duplicate_mapping = {**entries[0], "capabilityId": "test.duplicate.v1"}
        for case, invalid_entries in (
            ("missing", entries[:-1]),
            ("extra", [*entries, extra]),
            ("duplicate_id", [*entries, entries[0]]),
            ("duplicate_mapping", [*entries, duplicate_mapping]),
        ):
            with self.subTest(case=case):
                value = deepcopy(self.capability_map)
                value["entries"] = invalid_entries
                value["entryCount"] = len(invalid_entries)
                with self.assertRaises(verify.VerificationError):
                    verify.validate_capability_map(self.matrix, value)

    def test_unproven_production_caller_is_rejected(self) -> None:
        value = deepcopy(self.capability_map)
        value["entries"][0]["productionCaller"] = "unproven-product"
        with self.assertRaises(verify.VerificationError):
            verify.validate_capability_map(self.matrix, value)

    def test_frozen_wire_vector_is_self_consistent(self) -> None:
        verify.validate_wire_vector()

    def test_source_receipt_preserves_scope_and_nonclaims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            verify.write_source_receipt(output, verify.git_value("rev-parse", "HEAD"))
            receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(receipt["moduleCoverage"], 7)
        declared = {
            (row["module"], capability)
            for row in self.matrix["modules"]
            for capability in row["currentCapabilities"]
        }
        self.assertEqual(receipt["capabilityCoverage"], len(declared))
        self.assertEqual(
            receipt["currentImplementationTruth"], "source_and_test_anchored"
        )
        self.assertEqual(receipt["targetArchitectureImplementation"], "partial")
        self.assertEqual(receipt["externalAcceptance"], "not_claimed")
        current = verify.validate_native_bindings()["currentSourceBinding"]
        self.assertEqual(receipt["nativeSourceObservations"], current["observations"])
        self.assertEqual(receipt["sourceSha"], current["sourceSha"])
        self.assertEqual(receipt["sourceTree"], current["sourceTree"])

    def test_operations_semantic_replay_guards_are_source_pinned(self) -> None:
        model = (ROOT / "codex-rs/hepta-operations/src/model.rs").read_text(
            encoding="utf-8"
        )
        ledger = (ROOT / "codex-rs/hepta-operations/src/ledger.rs").read_text(
            encoding="utf-8"
        )
        outbox = (ROOT / "codex-rs/hepta-operations/src/outbox.rs").read_text(
            encoding="utf-8"
        )
        tests = (ROOT / "codex-rs/hepta-operations/src/ledger_tests.rs").read_text(
            encoding="utf-8"
        )
        outbox_tests = (
            ROOT / "codex-rs/hepta-operations/src/outbox_tests.rs"
        ).read_text(encoding="utf-8")
        self.assertIn("ReferenceAuthorityWitness::expected_digest", tests)
        self.assertIn("reference_witness_digest_binds_every_semantic_field", tests)
        self.assertIn(
            "authorized_replay_revalidates_payload_operation_and_expiry", tests
        )
        self.assertIn("pub fn expected_digest", model)
        self.assertIn("AuthorityWitnessDigestMismatch", model)
        self.assertIn("if !witness.validates(&record.key, now_unix_ms)", ledger)
        self.assertIn("owner_generation: Generation", outbox)
        self.assertIn("acknowledged_replay_retains_generation_fence", outbox_tests)

    def test_evidence_migration_contract_is_fail_closed(self) -> None:
        store = (ROOT / "docs/lane-a-foundation/kernel.evidence/STORE_V1.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("fail closed", store)
        self.assertNotIn("fail open", store.lower())

    def test_current_protocol_registry_is_closed_world_and_non_authorizing(
        self,
    ) -> None:
        registry = json.loads(
            (ROOT / "docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(registry["schemaVersion"], 1)
        self.assertEqual(registry["lane"], "LANE-A-FOUNDATION")
        self.assertEqual(registry["authority"], "none")
        self.assertEqual(
            [row["module"] for row in registry["protocols"]],
            verify.EXPECTED_MODULES,
        )
        self.assertEqual(len(registry["protocols"]), 7)
        for row in registry["protocols"]:
            self.assertTrue(row["protocolId"].startswith("hepta."))
            self.assertTrue(row["source"])
            self.assertTrue(row["invariants"])

    def test_native_observation_manifest_binds_current_candidate_blobs(self) -> None:
        bindings = json.loads(
            (
                ROOT
                / "qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            bindings["sourceCodeCommitRole"], "provenance_only_non_authoritative"
        )
        self.assertEqual(
            bindings["candidateBinding"],
            "runtime_head_tree_and_source_blob_receipt",
        )
        observed_digest = verify.hashlib.sha256(
            verify.json.dumps(
                bindings["observations"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        self.assertEqual(bindings["sourceObservationDigest"], observed_digest)
        current = verify.validate_native_bindings()["currentSourceBinding"]
        self.assertEqual(current["sourceSha"], verify.git_value("rev-parse", "HEAD"))
        self.assertEqual(
            current["sourceTree"], verify.git_value("rev-parse", "HEAD^{tree}")
        )
        for observed, historical in zip(
            current["observations"], bindings["observations"], strict=True
        ):
            data = (ROOT / observed["path"]).read_bytes()
            self.assertEqual(observed["blobSha"], verify.git_blob_sha(data))
            self.assertEqual(observed["historicalBlobSha"], historical["blobSha"])


if __name__ == "__main__":
    unittest.main()
