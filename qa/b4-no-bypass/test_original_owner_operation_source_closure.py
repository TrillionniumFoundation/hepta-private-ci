"""Original Prepared/Trainer/B operations keep custody through their postchecks.

These source-closure mutations qualify guard coverage, not native execution or
the ordinary whole-chain read budgets.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_owner_operation_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
EXPECTED = {
    "q24_original_prepared_owner_lane": (
        "cell_q24_learning_stage_owners.rs", "cell_q24_learning_successor.rs",
        "cell_q24_learning_evaluation_root.rs", "cell_q24_publication_material.rs",
        "cell_q24_learning_generation_operation.rs", "cell_q24_training_material.rs",
    ),
    "q24_original_receipt_read_frame": (
        "cell_q24_publication_material.rs", "cell_q24_learning_generation_operation.rs",
        "cell_q24_training_material.rs",
    ),
    "q24_original_b_frame_before": ("cell_q24_learning_historical_receipts.rs",),
    "q24_original_b_frame_after": (
        "cell_q24_learning_historical_operation.rs", "cell_q24_publication_material.rs",
        "cell_q24_learning_generation_operation.rs", "cell_q24_training_material.rs",
    ),
    "q24_original_b_frame_model": (
        "cell_q24_learning_historical_operation.rs", "cell_q24_learning_historical_receipts.rs",
    ),
    "q24_original_b_frame_material": ("cell_q24_publication_material.rs",),
    "q24_original_b_borrowed_model": ("cell_q24_learning_b_operation.rs",),
    "q24_original_publication_material_read": (
        "cell_q24_publication_driver.rs", "cell_q24_publication_root_stage.rs",
    ),
    "q24_original_publication_material_current": ("cell_q24_publication_driver.rs",),
    "q24_original_successor_source_read": ("learning_iteration_successor.rs",),
    "q24_original_successor_operation_binding": ("cell_q24_learning_successor.rs",),
    "q24_original_successor_operation": ("cell_q24_publication_successor.rs",),
    "q24_original_generation_source_install": ("cell_q24_learning_stage_owners.rs",),
    "q24_original_training_completion_read": ("cell_q24_training_material.rs",),
}


class OriginalOwnerOperationClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {r.identifier: r for r in PROOF._boundary_rows(cls.manifest)}
        paths = {
            AGENT + "cell_q24_learning_stage_owners.rs",
            AGENT + "cell_q24_training_stage.rs",
            AGENT + "cell_q24_learning_historical_stage.rs",
        }
        for identifier, callers in EXPECTED.items():
            paths.add(cls.boundaries[identifier].definition_path)
            paths.update(AGENT + p for p in callers)
        cls.index = {
            p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text()))
            for p in paths
        }

    def rejects(self, filename, function, marker, occurrence=0):
        path = AGENT + filename
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        assert end is not None
        body = source[start:end + 1]
        self.assertGreater(body.count(marker), occurrence, marker)
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
            for replacement in ("", "/* removed original check */"):
                target.write_text(source[:offset] + replacement + source[offset + len(marker):])
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_original_operations_have_exact_typed_product_callers(self):
        for identifier, callers in EXPECTED.items():
            row = self.boundaries[identifier]
            with self.subTest(boundary=identifier):
                self.assertEqual(row.product_callers, tuple(AGENT + p for p in callers))
                PROOF._verify_boundary(ROOT, row, self.index, ())
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.index, ())
                extra = dict(self.index)
                extra[AGENT + "unregistered_owner_operation.rs"] = (
                    f"fn bypass() {{ {row.symbol}(); }}"
                )
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_original_prepared_lane_keeps_lock_cancel_and_err_postchecks(self):
        filename = "cell_q24_learning_operation_lane.rs"
        function = "fn in_original_prepared_lane<T>("
        for marker in (
            ".try_acquire_owned()", "FenceAggregateOnDrop {", "armed: true",
            "let _permit = permit", "inner\n                .owners\n                .try_lock()",
            "CellQ24PreparedLearningV1::with_original_prepared_operation(&inner.prepared, |read| {",
            "let result = work(owners, &runtime, read)", "if result.is_ok()", "fence.armed = false",
        ):
            with self.subTest(marker=marker):
                self.rejects(filename, function, marker)
        for marker in (
            "OriginalPreparedReadV1::require_prepared(read, &inner.prepared)",
            "crate::AgentdRootQ24ModelFactoryV1::require_current(",
        ):
            for occurrence in (0, 1):
                self.rejects(filename, function, marker, occurrence)
        for occurrence in (0, 1, 2):
            self.rejects(filename, function, "inner.cancelled.load(Ordering::Acquire)", occurrence)

    def test_read_frame_cannot_become_an_actor_or_replace_original_trust(self):
        filename = "cell_q24_learning_historical_operation.rs"
        for marker in (
            "OriginalPreparedReadV1::require_prepared(read, &inner.prepared)",
            "owners.root_evaluation.is_none()", "owners.evaluation.is_some()",
            "inner.verifier.trust_digest()", "inner.prepared.initial().owners.evidence_trust_digest",
            "inner.verifier.objective_digest()", "inner.prepared.initial().request.envelope.objective_digest",
            "context: None", "original_b: None",
        ):
            self.rejects(filename, "fn from_original_receipt_read(", marker)
        self.rejects(filename, "fn original_stage_context(", "self.context.ok_or(Error::WrongScope)")
        for marker in ("self.original_stage_context()?", "let result = self.run_stage(work)",
                       "self.finish_original_b_read()?"):
            self.rejects(filename, "fn run(", marker)

    def test_b_frame_uses_actual_readbacks_and_preserves_original_model_scope(self):
        filename = "cell_q24_learning_b_operation.rs"
        for function in ("fn require_original_b_read(", "fn finish_original_b_read("):
            for marker in (
                "OriginalQ24TrainingOperationV1::read_original_training_evidence(self.training)?",
                "self.owners.complete_original_root_evaluation(",
                "OriginalRootBEvaluationActionV1::Readback",
            ):
                self.rejects(filename, function, marker)
        for marker in ("self.original_b.take()", "!before.same_original_observation(&after)",
                       "return Err(Error::CommitUncertain)"):
            self.rejects(filename, "fn finish_original_b_read(", marker)
        self.rejects(filename, "fn model_root_action(", "self.require_original_b_read()?")
        for marker in (
            "!snapshot.receipts.starts_with(&evidence.snapshot().receipts)",
            "snapshot.receipts.get(evidence.snapshot().receipts.len()) != Some(observed.receipt())",
            "factory.commit_from_original_b(evidence, observed)",
            "factory.read_from_original_b(evidence, observed)",
            "local.attest_original_root_decision(", "local.read_original_root_decision(",
        ):
            self.rejects("cell_q24_learning_model_root.rs", "fn model_root_action_from_original_b(", marker)
        for occurrence in (0, 1):
            self.rejects("cell_q24_learning_model_root.rs", "fn model_root_action_from_original_b(",
                         "evidence.require_current_training_source()?", occurrence)

    def test_publication_effect_has_original_manifest_checks_on_both_sides(self):
        filename = "cell_q24_publication_material.rs"
        function = "fn with_original_root_publication<T>("
        for marker in (
            ".in_original_prepared_lane(", ".with_original_training_operation(",
            "OriginalQ24StageOperationV1::from_original_receipt_read(",
            "effect_started.store(true, Ordering::Release)", "let value = work()",
            "operation.finish_original_b_read()?", "started.load(Ordering::Acquire)",
        ):
            self.rejects(filename, function, marker)
        for occurrence in (0, 1):
            self.rejects(filename, function,
                         "operation.read_publication_material(&snapshot)? != manifest", occurrence)

    def test_successor_session_and_historical_source_surround_actual_read(self):
        filename = "cell_q24_learning_successor.rs"
        function = "fn with_original_successor_read<T>("
        self.rejects(filename, function, "!std::ptr::eq(self, context.owners().as_ref())")
        for occurrence in (0, 1):
            self.rejects(filename, function, ".require_original_successor_operation(read)", occurrence)
        filename = "learning_iteration_successor.rs"
        function = "fn require_original_successor_operation("
        self.rejects(filename, function, "RegisteredHistoricalLearningSourceV1::require_original_stage_operation(")
        for occurrence in (0, 1):
            self.rejects(filename, function, "self.session.require_current_successor_session()", occurrence)

    def test_generation_and_material_read_use_existing_completion_only(self):
        filename = "cell_q24_learning_generation_operation.rs"
        function = "fn install_original_generation_in_operation("
        for marker in (
            "owners.generation.is_some()", "OriginalGenerationLearningRoleV1::Selection",
            "OriginalGenerationLearningRoleV1::NextUse",
            ".block_on(selection.observe_original_selection(&snapshot))",
            "operation.authenticate_receipt(&snapshot, receipt)?", "operation.finish_original_b_read()?",
        ):
            self.rejects(filename, function, marker)
        filename = "cell_q24_training_material.rs"
        function = "fn read_original_material_in_operation("
        for marker in (
            "OriginalQ24TrainingOperationV1::read_original_completion_in_operation(",
            "operation.authenticate_receipt(&expected, receipt)?", "operation.finish_original_b_read()?",
        ):
            for occurrence in (0, 1):
                self.rejects(filename, function, marker, occurrence)


if __name__ == "__main__":
    unittest.main()
