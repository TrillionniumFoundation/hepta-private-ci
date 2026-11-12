"""Keep actual historical execution and checkpoint inside one source borrow."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "historical_q24_stage_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CONTEXT = AGENT + "learning_iteration_historical_context.rs"
RUNTIME = AGENT + "learning_iteration_historical_runtime.rs"
LANE = AGENT + "cell_q24_learning_historical_stage.rs"
OPERATION = AGENT + "cell_q24_learning_historical_operation.rs"
RECEIPTS = AGENT + "cell_q24_learning_historical_receipts.rs"


class HistoricalQ24StageSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {r.identifier: r for r in PROOF._boundary_rows(cls.manifest)}

    def rejects(self, path, function, marker, occurrence=0):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        assert end is not None
        body = source[start : end + 1]
        self.assertGreater(body.count(marker), occurrence)
        offset = -len(marker)
        for _ in range(occurrence + 1):
            offset = body.index(marker, offset + len(marker))
        offset += start
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker) :])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_real_context_lane_and_runtime_have_closed_callers(self):
        expected = {
            "historical_stage_original_context": (RUNTIME,),
            "historical_stage_original_borrow": (LANE,),
            "historical_stage_actual_operation": (LANE,),
            "historical_stage_original_lane": (RUNTIME,),
            "historical_stage_runtime": (AGENT + "learning_iteration.rs",),
        }
        paths = {CONTEXT, RUNTIME, LANE, OPERATION, RECEIPTS}
        for identifier, callers in expected.items():
            row = self.boundaries[identifier]
            self.assertEqual(row.product_callers, callers)
            paths.add(row.definition_path)
            paths.update(callers)
        index = {
            p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text()))
            for p in paths
        }
        for identifier in expected:
            row = self.boundaries[identifier]
            with self.subTest(boundary=identifier):
                PROOF._verify_boundary(ROOT, row, index, ())
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=()), index, ())

    def test_actual_root_aggregate_trust_and_identity_cannot_be_replaced(self):
        for function, marker in (
            ("fn from_original_bootstrap(", "bootstrap.retained_source.is_some()"),
            ("fn from_original_bootstrap(", "bootstrap.scope.as_ref() != Some(prepared.scope())"),
            ("fn from_original_bootstrap(", "bootstrap.verifier.trust_digest() != prepared.initial().owners.evidence_trust_digest"),
            ("fn from_original_bootstrap(", "OriginalRootQ24CheckpointV1::require_original_owners(checkpoint, original)?"),
            ("fn require_original_aggregate(", "!std::ptr::eq(self.original.as_ref(), original)"),
        ):
            with self.subTest(marker=marker):
                self.rejects(CONTEXT, function, marker)

    def test_one_bounded_lane_holds_borrow_and_cancellation_through_postchecks(self):
        for marker in (
            "context.require_original_aggregate(self)?",
            ".try_acquire_owned()",
            "let _permit = permit;",
            "CellQ24PreparedLearningV1::with_original_prepared_operation(&inner.prepared",
            "OriginalCellQ24TrainingStageV1::with_original_training_operation(",
            "OriginalQ24StageOperationV1::run(&mut operation, work)",
            "if result.is_ok()",
        ):
            with self.subTest(marker=marker):
                self.rejects(LANE, "fn run_original_historical_stage(", marker)
        for occurrence in (0, 1):
            self.rejects(LANE, "fn run_original_historical_stage(",
                         "context.require_in_operation(read, OriginalHistoricalStageAdmissionV1::ReadOnly)?", occurrence)

    def test_signature_and_checkpoint_cannot_escape_stage_postchecks(self):
        for marker in (
            "self.authenticate_receipt(coordinator.snapshot(), decision)?",
            "self.authenticate_receipt(coordinator.snapshot(), &receipt)?",
            ".validate_observation(&receipt.observation)?",
            ".commit_checkpoint(previous, coordinator.snapshot())",
            "committed != coordinator.snapshot().head_digest",
            ".map_err(|_| Error::CommitUncertain)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(OPERATION, "fn execute(", marker)

    def test_root_b_execution_borrows_the_actual_mutable_trainer(self):
        for marker in (
            "OriginalQ24TrainingOperationV1::read_original_training_evidence(self.training)?",
            "original.snapshot() != snapshot",
            ".execute_original_root_evaluation(\n                    self.training,\n                    &original,",
        ):
            with self.subTest(marker=marker):
                self.rejects(OPERATION, "fn execute_stage(", marker)

    def test_cold_recovery_waits_only_after_authenticated_checkpoint_prefix(self):
        for path, function, marker in (
            (OPERATION, "fn restore(", "OriginalHistoricalRestoreModeV1::Readback"),
            (OPERATION, "fn restore(", "self.owners.generation.is_none() && generation_receipt(receipt)"),
            (OPERATION, "fn restore(", "self.authenticate_receipt(&snapshot, receipt)?"),
            (OPERATION, "fn run_stage(", "actual.as_ref() != Some(&expected)"),
            (OPERATION, "fn run_stage(", "self.authenticate_receipt(&expected, receipt)?"),
            (RUNTIME, "fn process_original_historical(", "self.wait_original_successor_stage(&state, &prefix, next)"),
            (RUNTIME, "fn process_original_historical(", "OriginalHistoricalWorkV1::ConfirmRecovery(current.snapshot)"),
        ):
            with self.subTest(marker=marker):
                self.rejects(path, function, marker)

    def test_original_receipts_and_independent_current_roles_are_mandatory(self):
        for function, marker in (
            ("fn read_receipt(", "&receipt != expected"),
            ("fn verify_receipt(", "OriginalReceiptVerificationV1::verify(&verification, &signed, self.current_time()?)"),
            ("fn authenticate_receipt(", "self.verify_receipt(snapshot, decision)?"),
            ("fn authenticate_receipt(", "independent_receipt_stages(snapshot, receipt)"),
            ("fn authenticate_receipt(", "verify_signed_actor_separation(&prior, &current, self.current_time()?)"),
        ):
            with self.subTest(marker=marker):
                self.rejects(RECEIPTS, function, marker)


if __name__ == "__main__":
    unittest.main()
