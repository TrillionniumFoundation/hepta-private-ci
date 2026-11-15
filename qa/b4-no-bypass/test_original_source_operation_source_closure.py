"""Guard one borrowed Source operation across each actual original native lane.

The native mechanisms are separately authored and must be executed on the
fixed source. This static suite is not ordinary task or adoption acceptance.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_source_operation_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
SOURCE = AGENT + "cell_q24_training_source.rs"
OWNER = AGENT + "cell_q24_training_source_owner.rs"
NATIVE = AGENT + "cell_composed_q24_training_owner.rs"
OPERATION = AGENT + "cell_q24_training_source_operation.rs"
LANE = AGENT + "cell_q24_training_source_lane.rs"
STAGE = AGENT + "cell_q24_training_stage.rs"
MODEL = AGENT + "cell_q24_training_model_lane.rs"
BOUND = AGENT + "cell_q24_source_bound_stage.rs"
DATASET = AGENT + "cell_q24_dataset_remote.rs"
EXPECTED = {
    "learning_original_source_operation_handle": ("codex-rs/hepta-agentd/src/cell_q24_training_stage.rs", "codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs"),
    "learning_original_source_operation_begin": ("codex-rs/hepta-agentd/src/cell_q24_training_stage.rs", "codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs"),
    "learning_original_source_operation_owner_proof": ("codex-rs/hepta-agentd/src/cell_q24_training_source_lane.rs",),
    "learning_original_source_operation_same": ("codex-rs/hepta-agentd/src/cell_q24_training_source_owner.rs",),
    "learning_original_source_operation_after": ("codex-rs/hepta-agentd/src/cell_q24_training_stage.rs", "codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs"),
    "learning_original_source_operation_finish": ("codex-rs/hepta-agentd/src/cell_q24_training_stage.rs", "codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs"),
    "learning_original_source_operation_fenced": ("codex-rs/hepta-agentd/src/cell_q24_training_source.rs", "codex-rs/hepta-agentd/src/cell_q24_training_source_owner.rs", "codex-rs/hepta-agentd/src/cell_composed_q24_training_owner.rs"),
    "learning_original_source_operation_freeze": ("codex-rs/hepta-agentd/src/cell_q24_training_source_operation.rs",),
    "learning_original_source_operation_lane_proof": ("codex-rs/hepta-agentd/src/cell_q24_training_stage.rs", "codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs"),
    "learning_original_source_operation_lane_admission": ("codex-rs/hepta-agentd/src/cell_q24_source_bound_stage.rs", "codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs"),
    "learning_original_source_operation_cancel_create": ("codex-rs/hepta-agentd/src/cell_q24_training_stage.rs",),
    "learning_original_source_operation_cancel_worker": ("codex-rs/hepta-agentd/src/cell_q24_training_stage.rs",),
    "learning_original_source_operation_cancel_joined": ("codex-rs/hepta-agentd/src/cell_q24_training_stage.rs",),
    "learning_original_source_operation_cancel_bind": ("codex-rs/hepta-agentd/src/cell_q24_training_stage.rs",),
    "learning_original_source_operation_cancel_live": ("codex-rs/hepta-agentd/src/cell_q24_training_stage.rs",),
    "learning_original_source_operation_cancel_fenced": ("codex-rs/hepta-agentd/src/cell_q24_training_stage.rs",),
}
# The existing verifier reserves function_order for non-generic functions.
# These three generic functions retain explicit function-local checks here;
# their global marker records do not substitute for this scoped verification.
SCOPED_GENERIC = {
    "codex-rs/hepta-agentd/src/cell_q24_training_source_lane.rs": [
        {
            "function": "fn require_original<",
            "sequence": [
                "let operation = self.operation.ok_or(CellQ24TrainingOwnerErrorV1::Binding(",
                "CellQ24TrainingOwnerV1::require_original_source_operation(training, operation)?",
                "Ok(())"
            ]
        }
    ],
    "codex-rs/hepta-agentd/src/cell_q24_training_stage.rs": [
        {
            "function": "fn in_lane<",
            "sequence": [
                "&SourceLaneProof<'_>",
                ".try_acquire_owned()",
                "SourceLaneCancellation::new(Arc::clone(&self.source_abandoned))",
                "SourceLaneCancellation::worker(&cancellation)",
                "tokio::task::spawn_blocking(move ||",
                "let _permit = permit",
                "owners.try_lock()",
                "owners.source_fenced",
                "SourceLaneCancellationState::stage_is_fenced(&worker_cancellation)",
                "training",
                ".require_original_dataset_scope(",
                "training.original_source_for_operation()?",
                "if source.is_some()",
                "SourceLaneCancellationState::bind_source(&worker_cancellation)?",
                "OriginalCellQ24TrainingSourceV1::begin_source_operation(source)",
                "SourceLaneProof::from_operation(operation.as_ref())",
                "work(&mut owners, &proof)",
                "OriginalCellQ24TrainingSourceOperationV1::read_after_native(",
                "owners.require_captured_tail_current().is_err()",
                "SourceLaneCancellationState::require_live(&worker_cancellation)",
                "OriginalCellQ24TrainingSourceOperationV1::finish(operation, source)",
                "result",
                "})",
                ".await",
                ".map_err(|_| Error::CommitUncertain)",
                "SourceLaneCancellation::joined(&mut cancellation)",
                "completed?"
            ]
        }
    ],
    "codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs": [
        {
            "function": "fn in_model_lane<",
            "sequence": [
                "&SourceLaneProof<'_>",
                ".try_acquire_owned()",
                "self.owners.try_lock()",
                "if owners.source_fenced",
                "source_abandoned",
                ".load(std::sync::atomic::Ordering::Acquire)",
                "require_original_dataset_scope(",
                "training.original_source_for_operation()?",
                "OriginalCellQ24TrainingSourceV1::begin_source_operation(source)",
                "let original = owners.read_original_completion()?",
                "SourceLaneProof::from_operation(operation.as_ref())",
                "work(&mut owners.training, &original, &proof)",
                "OriginalCellQ24TrainingSourceOperationV1::read_after_native(",
                "let current = owners",
                "read_original_completion()",
                "require_retained_attestation_current(&current)",
                "current.receipt != original.receipt || current.attestation != original.attestation",
                "source_abandoned",
                ".load(std::sync::atomic::Ordering::Acquire)",
                "OriginalCellQ24TrainingSourceOperationV1::finish(operation, source)",
                "result"
            ]
        }
    ]
}


class OriginalSourceOperationClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def body(self, source, function):
        code = self.code(source)
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        return code[start:end + 1]

    def require_scoped(self, path, source):
        for row in SCOPED_GENERIC.get(path, ()):
            body = self.body(source, row["function"])
            PROOF._verify_required_order(
                {"required_order": [row["sequence"]]}, body, path + ":" + row["function"]
            )

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
        self.require_scoped(path, source)

    def rejects(self, path, function, marker, replacement=""):
        source = (ROOT / path).read_text()
        code = self.code(source)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        self.verifies(path, source)
        changed = source[:offset] + replacement + source[offset + len(marker):]
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_exact_original_callers_and_private_operations_remain_closed(self):
        paths = {
            path for identifier in EXPECTED for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        sources = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                extra = dict(sources)
                extra[AGENT + "unregistered_source_operation.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertEqual(self.boundaries["learning_source_bound_training_admission"].product_callers, ())
        self.assertEqual(
            self.boundaries["learning_source_bound_training_live_check"].product_callers,
            (NATIVE, STAGE),
        )
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_actual_before_after_full_material_and_same_custody_are_required(self):
        for path, function, marker in (
            (OPERATION, "fn begin_source_operation(", ".compare_exchange(IDLE, ACTIVE, Ordering::AcqRel, Ordering::Acquire)"),
            (OPERATION, "fn begin_source_operation(", "source.live.material_once_for_operation(&operation.config)"),
            (OPERATION, "fn begin_source_operation(", "require_same_material(&source.material, &before)?"),
            (OPERATION, "fn require_same_identity(", "!Arc::ptr_eq(self.source, source)"),
            (OPERATION, "fn require_same_identity(", "!Arc::ptr_eq(&self.config, &source.config)"),
            (OPERATION, "fn require_same_identity(", "!Arc::ptr_eq(&self.baseline, &source.live.baseline)"),
            (OPERATION, "fn require_same_identity(", "source.operation_state.load(Ordering::Acquire) != ACTIVE"),
            (OPERATION, "fn read_after_native(", "self.phase = Phase::ReadingAfter"),
            (OPERATION, "fn read_after_native(", "source.live.material_once_for_operation(&self.config)"),
            (OPERATION, "fn read_after_native(", "require_same_material(before, &after)?"),
            (OPERATION, "fn read_after_native(", "capture_binding(&self.config, &after) != source.binding"),
            (OPERATION, "fn material_once_for_operation(", "self.read_original_evidence(config).await?"),
            (OPERATION, "fn material_once_for_operation(", ".read_current_material(config, &self.baseline)"),
            (OPERATION, "fn material_once_for_operation(", "require_observations(config, &material)?"),
            (SOURCE, "fn require_same_material(", "before.receipt() != after.receipt()"),
            (SOURCE, "fn require_same_material(", "before.batch().encoded() != after.batch().encoded()"),
            (SOURCE, "fn require_same_material(", "before.batch().digest() != after.batch().digest()"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker)

    def test_native_tail_and_fresh_original_windows_precede_once_only_finish(self):
        for path, function, marker in (
            (OPERATION, "fn finish(", "mut self"),
            (OPERATION, "fn finish(", "!matches!(self.phase, Phase::AfterRead)"),
            (OPERATION, "fn finish(", "self.require_fresh()?"),
            (OPERATION, "fn finish(", "source.operation_state.store(IDLE, Ordering::Release)"),
            (OPERATION, "fn require_fresh(", "let fresh_now = now()?"),
            (SOURCE, "fn now(", "SystemTime::now()"),
            (OPERATION, "fn require_fresh(", "verify_original_evidence(&self.config, fresh_now)?"),
            (OPERATION, "fn require_fresh(", "OriginalCellQ24DatasetV1::require_original_freeze_current("),
            (DATASET, "fn require_original_freeze_current(", "let payload = freeze_payload("),
            (DATASET, "fn require_original_freeze_current(", "LearningEvidenceRoleV1::Evaluator"),
            (DATASET, "fn require_original_freeze_current(", "verified.principal() != &receipt.producer"),
            (DATASET, "fn require_original_freeze_current(", "verify_dataset_snapshot_receipt_v3(receipt, at)?"),
            (STAGE, "fn in_lane<", "owners.require_captured_tail_current().is_err()"),
            (MODEL, "fn in_model_lane<", "require_retained_attestation_current(&current)"),
            (MODEL, "fn in_model_lane<", "current.receipt != original.receipt || current.attestation != original.attestation"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker)
        for path, function in ((STAGE, "fn in_lane<"), (MODEL, "fn in_model_lane<")):
            for marker in (
                "OriginalCellQ24TrainingSourceV1::begin_source_operation(source)",
                "OriginalCellQ24TrainingSourceOperationV1::read_after_native(",
                "OriginalCellQ24TrainingSourceOperationV1::finish(operation, source)",
            ):
                with self.subTest(path=path, marker=marker):
                    self.rejects(path, function, marker)

    def test_cancellation_drop_and_failed_proof_fence_original_custody(self):
        for path, function, marker in (
            (OPERATION, "fn drop(", ".store(FENCED, Ordering::Release)"),
            (NATIVE, "fn require_current(", "OriginalCellQ24TrainingSourceV1::source_operation_fenced(source)"),
            (NATIVE, "fn require_current(", "self.fenced = true"),
            (OWNER, "fn require_original_source_operation(", "self.fenced = true"),
            (LANE, "fn drop(", "self.state.fetch_or(CANCELLED, Ordering::AcqRel)"),
            (LANE, "fn drop(", "self.stage_fenced.store(true, Ordering::Release)"),
            (LANE, "fn bind_source(", "self.state.fetch_or(SOURCE_BOUND, Ordering::AcqRel)"),
            (LANE, "fn bind_source(", "if before & CANCELLED != 0"),
            (LANE, "fn require_live(", "self.stage_fenced.load(Ordering::Acquire)"),
            (STAGE, "fn in_lane<", "let _permit = permit"),
            (STAGE, "fn in_lane<", "SourceLaneCancellationState::bind_source(&worker_cancellation)?"),
            (STAGE, "fn in_lane<", "SourceLaneCancellationState::require_live(&worker_cancellation)"),
            (STAGE, "fn in_lane<", "SourceLaneCancellation::joined(&mut cancellation)"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker)

    def test_candidate_and_admission_use_this_borrowed_operation_proof(self):
        for path, function, marker in (
            (BOUND, "fn from_original_stage(", "SourceLaneProof::require_original(source, &mut owners.training)?"),
            (MODEL, "fn read_candidate_material(", "SourceLaneProof::require_original(source, training)?"),
            (LANE, "fn require_original<", "self.operation.ok_or("),
            (LANE, "fn require_original<", "CellQ24TrainingOwnerV1::require_original_source_operation(training, operation)?"),
            (OWNER, "fn require_original_source_operation(", "OriginalCellQ24TrainingSourceOperationV1::require_original_source(operation, source)"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker)

    def test_independent_capture_and_native_precommit_withdrawal_checks_remain(self):
        source = (ROOT / SOURCE).read_text()
        full = self.body(source, "fn current_material(")
        self.assertEqual(full.count("self.read_original_evidence(config).await?"), 2)
        self.assertEqual(full.count(".read_current_material(config, &self.baseline)"), 2)
        single = self.body((ROOT / OPERATION).read_text(), "fn material_once_for_operation(")
        self.assertEqual(single.count("self.read_original_evidence(config).await?"), 1)
        self.assertEqual(single.count(".read_current_material(config, &self.baseline)"), 1)
        native = self.body((ROOT / NATIVE).read_text(), "fn fit_or_readback(")
        self.assertEqual(native.count("self.require_live_source_if_captured()?"), 2)
        after_fit = native.index("self.plan.fit(")
        source_after = native.index("self.require_live_source_if_captured()?", after_fit)
        self.assertLess(source_after, native.index("self.journal.complete("))
        self.rejects(NATIVE, "fn fit_or_readback(", "self.require_live_source_if_captured()?")
        self.rejects(STAGE, "fn execute_training(", "training.require_live_source_if_captured()?")
        self.rejects(SOURCE, "fn current_material(", "self.read_original_evidence(config).await?")

    def test_operation_cannot_gain_clone_deserialization_effects_or_reset(self):
        for path, mutation in (
            (OPERATION, "impl Clone for OriginalCellQ24TrainingSourceOperationV1<'_> {}"),
            (OPERATION, "use serde::Deserialize;"),
            (OPERATION, "fn bypass() { owner.fit_or_readback(); }"),
            (OPERATION, "fn bypass() { key.sign(); }"),
            (LANE, "impl Clone for SourceLaneProof<'_> {}"),
            (LANE, "fn bypass() { state.store(false); }"),
            (STAGE, "fn bypass() { state.store(false); }"),
            (MODEL, "fn bypass() { state.store(false); }"),
        ):
            with self.subTest(path=path, mutation=mutation):
                source = (ROOT / path).read_text()
                self.verifies(path, source)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, source + "\n" + mutation + "\n")

    def test_generic_lane_markers_cannot_be_transplanted_outside_function(self):
        for path, rows in SCOPED_GENERIC.items():
            for row in rows:
                source = (ROOT / path).read_text()
                function = row["function"]
                marker = row["sequence"][-2]
                code = self.code(source)
                start = code.index(function)
                end = PROOF._rust_item_end(code, start)
                self.assertIsNotNone(end)
                offset = source.index(marker, start, end + 1)
                moved = (
                    source[:offset] + source[offset + len(marker):]
                    + "\nfn outside_original_lane() { " + marker + "; }\n"
                )
                with self.subTest(path=path, marker=marker):
                    self.require_scoped(path, source)
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.require_scoped(path, moved)


if __name__ == "__main__":
    unittest.main()
