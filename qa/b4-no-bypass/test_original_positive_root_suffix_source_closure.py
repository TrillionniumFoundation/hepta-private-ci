"""Pinned gated Root/Candidate suffix closure; no native or ordinary claim.

The fixed Model proof contains five receipts and four original role signatures.
Selection and NextUse extend that proof through distinct original owners.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from protected_record_support import align_protected_record, require_protected_record

from rust_source_marker_support import source_marker_span

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    "qualification/learn-ordinary-ce434/"
    "model-root-closure-repair-441-20261112/route-current-contract.json"
)
SPEC = importlib.util.spec_from_file_location(
    "positive_root_suffix_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


# Explicit ownership migration, separate from the pinned formatter-only map.
# Every other historical authorization, effect-order and visibility guard stays.
_ORIGINAL_STATE_SLOT_MARKERS = {
    "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs": {
        "candidate: Mutex<CandidateLane>":
            "candidate: OriginalStateSlot<CandidateLane>",
        "evaluation: Mutex<EvaluationLane>":
            "evaluation: OriginalStateSlot<EvaluationLane>",
        "operation: Mutex<OperationLane>":
            "operation: OriginalStateSlot<OperationLane>",
    },
    "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_operation.rs": {
        "lane: MutexGuard<'a, OperationLane>":
            "lane: OriginalStateLease<'a, OperationLane>",
        "owners.operation.try_lock()":
            "let mut lane = owners.operation.try_take()?;",
        "if lane.failed":
            "if lane.state()?.failed",
        "lane.failed = true":
            "lane.state_mut()?.failed = true",
        "owners\n            .common\n            .continuation\n            .try_lock()":
            "let mut common_lease = owners.common.continuation.try_take()?;\n        let common = common_lease.state_mut()?;",
        "auth::verify_prefix(&owners.common.material, &training_cut, &common, fresh)?":
            "auth::verify_prefix(&owners.common.material, &training_cut, common, fresh)?",
        "self\n            .owners\n            .common\n            .continuation\n            .try_lock()":
            "let mut common_lease = self.owners.common.continuation.try_take()?;\n        let common = common_lease.state_mut()?;",
        "auth::verify_prefix(\n            &self.owners.common.material,\n            &self.training_cut,\n            &common,\n            fresh,\n        )?":
            "auth::verify_prefix(\n            &self.owners.common.material,\n            &self.training_cut,\n            common,\n            fresh,\n        )?",
        "drop(common)":
            "drop(common_lease)",
        "self.0.lane.failed = false":
            "self.0.lane.state_mut()?.failed = false",
        "self.operation.0.lane.failed = false":
            "self.operation.0.lane.state_mut()?.failed = false",
        "let mut common":
            "let mut common_lease",
        "owners.common.continuation.try_lock()":
            "let mut common_lease = owners.common.continuation.try_take()?;\n        let common = common_lease.state_mut()?;",
        "self.owners.common.continuation.try_lock()":
            "let mut common_lease = self.owners.common.continuation.try_take()?;\n        let common = common_lease.state_mut()?;",
        "auth::verify_prefix(&self.owners.common.material, &self.training_cut, &common, fresh)?":
            "auth::verify_prefix(\n            &self.owners.common.material,\n            &self.training_cut,\n            common,\n            fresh,\n        )?",
    },
    "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_adoption.rs": {
        "let mut common: tokio::sync::MutexGuard<'_, Continuation> = self\n                .common\n                .continuation\n                .try_lock()\n                .map_err(|_| Error::QueueFull)?;":
            "let mut common_lease = self.common.continuation.try_take()?;\n            let common: &mut Continuation = common_lease.state_mut()?;",
        "let mut common = self.common.continuation.try_lock().map_err(|_| Error::QueueFull)?;":
            "let mut common_lease = self.common.continuation.try_take()?;\n            let common: &mut Continuation = common_lease.state_mut()?;",
    },
    "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_next_use.rs": {
        "let mut common: tokio::sync::MutexGuard<'_, Continuation> = self\n                .common\n                .continuation\n                .try_lock()\n                .map_err(|_| Error::QueueFull)?;":
            "let mut common_lease = self.common.continuation.try_take()?;\n            let common: &mut Continuation = common_lease.state_mut()?;",
        "let mut common = self.common.continuation.try_lock().map_err(|_| Error::QueueFull)?;":
            "let mut common_lease = self.common.continuation.try_take()?;\n            let common: &mut Continuation = common_lease.state_mut()?;",
    },
}


def original_state_slot_guards(row):
    replacements = _ORIGINAL_STATE_SLOT_MARKERS.get(row["path"], {})

    def project(value):
        if isinstance(value, str):
            return replacements.get(value, value)
        if isinstance(value, list):
            return [project(item) for item in value]
        if isinstance(value, dict):
            return {key: project(item) for key, item in value.items()}
        return value

    return project(row)


class OriginalPositiveRootSuffixClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        contract_bytes = (ROOT / CONTRACT_PATH).read_bytes()
        if hashlib.sha256(contract_bytes).hexdigest() != (
            "ac2f3d9e8ab1f290fd5894deddbeda977231600ff885cb551a1f7b96764f849e"
        ):
            raise AssertionError("historical positive-root contract changed")
        cls.contract = json.loads(contract_bytes)
        cls.manifest = PROOF._load_manifest(ROOT / "CALLERS.toml")
        def explicit_original_types(value):
            if isinstance(value, str):
                return value.replace(
                    "let closed = CandidateOriginalOperation::close(operation)",
                    "let closed: ClosedCandidateOriginalOperation<'_> = CandidateOriginalOperation::close(operation)",
                )
            if isinstance(value, list):
                return [explicit_original_types(item) for item in value]
            if isinstance(value, dict):
                return {key: explicit_original_types(item) for key, item in value.items()}
            return value
        for collection in ("rows", "mutations"):
            for index, row in enumerate(cls.contract[collection]):
                if row["path"].endswith(("cell_q24_candidate_stage_adoption.rs", "cell_q24_candidate_stage_next_use.rs")):
                    row = explicit_original_types(row)
                cls.contract[collection][index] = original_state_slot_guards(row)
        cls.contract["rows"] = [align_protected_record(row, cls.manifest["protected_file"])
                                for row in cls.contract["rows"]]


    def verifies(self, path, source):
        rows = [row for row in self.contract["rows"] if row["path"] == path]
        self.assertEqual(len(rows), 1, path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, case):
        path, function = case["path"], case["function"]
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        first, after = source_marker_span(source, case["marker"], start, end + 1)
        self.verifies(path, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, source[:first] + source[after:])

    def test_complete_guard_records_and_exact_caller_delta_are_installed(self):
        for row in self.contract["rows"]:
            with self.subTest(path=row["path"]):
                require_protected_record(row, self.manifest["protected_file"])
                self.verifies(row["path"], (ROOT / row["path"]).read_text())
        actual = {row["id"]: row for row in self.manifest["boundary"]}
        expected = [
            *[change["after"] for change in self.contract["boundary"]["changes"]],
            *self.contract["boundary"]["additions"],
        ]
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for row in expected:
            with self.subTest(boundary=row["id"]):
                self.assertEqual(actual[row["id"]], row)
                self.assertEqual(inventory.count(row["id"]), 1)

    def test_fixed_model_prefix_cannot_absorb_unsigned_suffix_or_another_model(self):
        for case in self.contract["mutations"]:
            if "authority_host_learning_resident_" in case["path"]:
                with self.subTest(case=case):
                    self.rejects(case)

    def test_original_channels_model_finish_and_owner_effects_remain_real(self):
        for case in self.contract["mutations"]:
            if any(name in case["path"] for name in (
                "cell_q24_no_update_stage_state.rs",
                "cell_q24_candidate_stage_model.rs",
                "cell_q24_candidate_stage_adoption.rs",
            )):
                with self.subTest(case=case):
                    self.rejects(case)

    def test_readiness_and_full_original_s_c_evidence_remain_separate(self):
        for case in self.contract["mutations"]:
            if any(name in case["path"] for name in (
                "cell_q24_candidate_stage_next_use.rs",
                "cell_q24_candidate_stage_suffix.rs",
                "cell_q24_candidate_stage_operation.rs",
            )):
                with self.subTest(case=case):
                    self.rejects(case)

    def test_verifier_uses_original_evidence_scope_and_all_three_context_pins(self):
        for case in self.contract["mutations"]:
            if case["path"].endswith("circuit_learning_model_context.rs"):
                with self.subTest(case=case):
                    self.rejects(case)

    def test_private_adoption_data_cannot_create_signers_or_reconnect(self):
        for row in self.contract["additions"]:
            source = (ROOT / row["path"]).read_text()
            self.verifies(row["path"], source)
            for injection in (
                "\nfn bypass() { UnixStream::connect(); }\n",
                "\nfn bypass() { SigningKey::generate(); }\n",
                "\nfn bypass() { channel.next = 1; }\n",
                "\nfn bypass() { execution_requested = false; }\n",
            ):
                with self.subTest(path=row["path"], injection=injection):
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verifies(row["path"], source + injection)


if __name__ == "__main__":
    unittest.main()
