"""A borrowed original-owner result removes recursion, never current I/O.

These mutations guard the concrete same-continuation route. They do not prove
native execution, the cumulative frame budget, deployment or ordinary A/B/C.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

from rust_source_marker_support import source_marker_span

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_candidate_operation_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OP = AGENT + "cell_q24_candidate_stage_operation.rs"
READBACK = AGENT + "cell_q24_candidate_stage_readback.rs"
EVALUATION = AGENT + "cell_q24_candidate_stage_evaluation.rs"
MODEL = AGENT + "cell_q24_candidate_stage_model.rs"
OWNERS = AGENT + "cell_q24_candidate_stage_owners.rs"
STAGES = AGENT + "authority_host_learning_resident_stages.rs"
AUTH = AGENT + "authority_host_learning_resident_auth.rs"
GATE = AGENT + "authority_host_learning_resident_gate.rs"
RUNTIME = AGENT + "authority_host_learning_resident_runtime.rs"
HOST = AGENT + "cell_q24_model_command_host.rs"
EFFECT = AGENT + "cell_q24_model_command_effect.rs"
EXPECTED = {
    "learning_original_candidate_operation_begin": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_adoption.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_evaluation.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_next_use.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_readback.rs",),
    "learning_original_candidate_operation_close": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_adoption.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_evaluation.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_next_use.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_readback.rs",),
    "learning_original_candidate_operation_current_material": (EVALUATION,),
    "learning_original_candidate_operation_current_evaluation": (MODEL,),
    "learning_original_candidate_operation_evidence_read": (STAGES,),
    "learning_original_candidate_operation_evidence_execute": (STAGES,),
    "learning_original_candidate_operation_evidence_consume": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs",),
    "root_resident_concrete_stages_execute": (RUNTIME,),
    "root_resident_concrete_stages_evidence_consume": (AUTH,),
}


class OriginalCandidateOperationClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows, path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement="", occurrence=0):
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        cursor = start
        for _ in range(occurrence + 1):
            first, cursor = source_marker_span(source, marker, cursor, end + 1)
        self.verifies(path, source)
        changed = source[:first] + replacement + source[cursor:]
        self.assertNotEqual(changed, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_only_concrete_same_operation_callers_can_borrow_or_consume(self):
        paths = {path for identifier in EXPECTED for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                extra = dict(sources)
                extra[AGENT + "unregistered_operation.rs"] = (
                    f"fn bypass(owner: &mut {row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_full_original_prefix_brackets_work_and_failure_keeps_the_lane_fenced(self):
        for marker in (
            "owners.require_live_deadline()?", "owners.training_prefix(supplied)?",
            "owners.operation.try_lock()", "if lane.failed", "lane.failed = true",
            "common.read_prefix(&owners.common, &training_cut).await?",
            "common.original_dataset.as_ref().ok_or(Error::CommitUncertain)?.clone()",
            "common.original_training.as_ref().ok_or(Error::CommitUncertain)?.clone()",
            "common.records[..3].to_vec()",
            "auth::verify_prefix(&owners.common.material, &training_cut, &common, fresh)?",
        ):
            self.rejects(OP, "fn begin(", marker)
        self.rejects(OP, "fn begin(", "lane.failed = true", "lane.failed = false")
        for marker in (
            "common.read_prefix(&self.owners.common, &self.training_cut).await?",
            "common.original_dataset.as_ref() != Some(&self.dataset)",
            "common.original_training.as_ref() != Some(&self.training)",
            "common.records.get(..3) != Some(self.records.as_slice())",
            "auth::require_clock(self.started, fresh)?",
            "auth::verify_prefix(&self.owners.common.material, &self.training_cut, &common, fresh)?",
        ):
            self.rejects(OP, "fn close(", marker)

    def test_private_proof_cannot_be_cloned_forged_deserialized_or_rearmed_on_drop(self):
        self.rejects(OP, "fn require_owner(", "!std::ptr::eq(self.owners, owners)")
        self.rejects(OP, "fn into_original_parts(", "self.operation.0.require_owner(owners)?")
        self.rejects(OP, "fn into_original_parts(", "self.authenticate_result(snapshot, observed)?")
        source = (ROOT / OP).read_text()
        self.verifies(OP, source)
        for addition in (
            "impl Clone for OriginalCandidateOperationEvidence<'_> {}",
            "impl Drop for CandidateOriginalOperation<'_> {}",
            "#[derive(Deserialize)] struct CallerProof {}",
            "struct CallerProof { pub(crate) operation: ClosedCandidateOriginalOperation<'static> }",
            "struct CallerProof { pub(super) snapshot: LearningIterationSnapshotV1 }",
            "fn cached() { read_cached(); }",
            "fn reconnect() { UnixStream::connect(); }",
        ):
            with self.subTest(addition=addition):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(OP, source + "\n" + addition + "\n")

    def test_complete_role_signatures_and_model_record_are_reauthenticated_at_consumption(self):
        for marker in (
            "auth::require_clock(self.started, observed)?", "auth::require_clock(observed, fresh)?",
            "self.owners.require_live_deadline()?", "for (receipt, signature) in &self.records",
            "auth::verify_receipt(&self.owners.common.material, receipt, signature, fresh)?",
        ):
            self.rejects(OP, "fn authenticate_prefix(", marker)
        for marker in (
            "snapshot != &self.snapshot", "operation.authenticate_prefix(observed)?",
            "operation.owners.verify_original_evaluation(",
            "&operation.supplied, &operation.training_cut, &operation.training, &self.evaluation, fresh",
            "signatures.push(self.evaluation.attestation().clone())",
            "self.model_completion.as_ref().ok_or(Error::CommitUncertain)?",
            "completed.model() != model",
            "completed.material().original_evaluation() != &self.evaluation",
            "completed.material().authenticate_current(fresh)",
            "completed.material().require_original_model_input(",
            "input.material_digest() != model.material_digest()",
            "self.model_completion.is_some() || self.evaluation.snapshot() != snapshot",
            "model.snapshot() != snapshot", "model.snapshot().receipts.len() != 5",
            "!model.snapshot().receipts.starts_with(&self.evaluation.snapshot().receipts)",
            "operation.supplied.receipts.get(4).is_some_and(|expected| expected != model.receipt())",
            "OriginalCellQ24ModelCommandReceiptV1::original_record_for_root(model, &signatures)",
        ):
            self.rejects(OP, "fn authenticate_result(", marker)

        for marker in (
            "completed.model().clone()",
            "completed.material().original_evaluation().clone()",
            "model: Some(model), model_completion: Some(completed)",
        ):
            self.rejects(OP, "fn model(", marker)

    def test_root_consumes_only_after_actual_root_io_and_independent_reads_start_again(self):
        for marker in (
            "ResidentOriginalStageOwnersV3::execute_original_stage(",
            "match completed.candidate",
            "Some(original) => authentication::candidate_continuation_attestations(",
            "authentication::original_attestations(",
        ):
            self.rejects(RUNTIME, "fn continue_original(", marker)
        for marker in (
            "let (_, fresh) = owner.read(cancellation).await?",
            "ResidentOriginalStageOwnersV3::require_initial(",
            "ResidentOriginalStageOwnersV3::consume_original_candidate_evidence(",
            "stages, original, snapshot, fresh / 1_000",
            "ResidentOriginalModelProofV3::from_original_readback(",
            "verify_original_evidence(", "model.as_ref(), fresh / 1_000",
        ):
            self.rejects(AUTH, "fn candidate_continuation_attestations(", marker)
        self.rejects(AUTH, "fn original_attestations(",
                     "ResidentOriginalStageOwnersV3::read_original_candidate_evidence(")
        self.rejects(STAGES, "fn read_original_candidate_evidence(",
                     "OriginalCellQ24CandidateStageOwnersV1::read_original_evidence(stages, snapshot).await")
        for function in ("fn read_original_evidence(", "fn execute_original_evidence("):
            self.rejects(OWNERS, function, "tokio::time::timeout_at(self.end.into()")
            self.rejects(OWNERS, function, "self.require_live_deadline()?")

    def test_model_finish_precedes_last_actual_model_current_and_fresh_authentication(self):
        for marker in (
            "OriginalCellQ24DatasetCommandReadbackV1::readback(",
            "OriginalCellQ24TrainingCommandOwnerV1::read_original_model_training(",
            "state.material_connection.take().ok_or(Error::Unavailable)?",
            "connection.bind_original_training(dataset.snapshot().clone(), &training)?",
        ):
            self.rejects(HOST, "fn original_inputs(", marker)
        for path, function in ((HOST, "fn recover_deployment("), (EFFECT, "fn original_response(")):
            self.rejects(path, function, "self.original_inputs(&mut state)?")
            self.rejects(path, function,
                         "OriginalCellEvaluationModelMaterialClientV1::begin_model_read(inputs.material.as_ref())")
        for marker in (
            "OriginalCellEvaluationModelReadV1::finish(operation)",
            "after.binding() != expected_material",
            "after.original_evaluation() != &context.evaluation",
            "OriginalCellQ24TrainingCommandOwnerV1::read_original_model(",
            "context.authenticate(started)?", "require_clock(started, fresh)?",
            "after.authenticate_current(fresh)?", "after.require_original_model_input(",
        ):
            self.rejects(EFFECT, "fn current_after(", marker)
        self.rejects(EFFECT, "fn original_response(", "observed != after")
        self.rejects(EFFECT, "fn original_response(", "state.retained.as_ref().is_some_and(|old| old != &current)")

    def test_actual_checkpoint_clock_revalidates_all_evidence_before_any_next_stage(self):
        self.rejects(GATE, "fn checkpoint(", ") -> Result<u64, Error>")
        self.rejects(
            GATE, "fn checkpoint(",
            "self.local(GateActionV3::Checkpoint(next), predecessor).await",
            "self.local(GateActionV3::Checkpoint(next), predecessor).await.map(|_| 0)",
        )
        for marker in (
            "let committed_at = gate.checkpoint(&predecessor, coordinator.snapshot().clone()).await?",
            "authentication::verify_checkpoint_evidence(",
            "&evidence.signatures, evidence.model.as_ref(), fresh, committed_at",
        ):
            self.rejects(RUNTIME, "fn continue_original(", marker)
        self.rejects(RUNTIME, "fn continue_original(", "fresh, committed_at", "fresh, fresh")
        for marker in (
            "committed_at_ms < before_ms", "return Err(Error::CommitUncertain)",
            "verify_original_evidence(",
            "profile, verifier, snapshot, signatures, model, committed_at_ms / 1_000",
            ".map_err(|_| Error::CommitUncertain)",
        ):
            self.rejects(AUTH, "fn verify_checkpoint_evidence(", marker)
        self.rejects(AUTH, "fn verify_checkpoint_evidence(",
                     "committed_at_ms / 1_000", "before_ms / 1_000")

    def test_ineligible_and_uncertain_effects_cannot_become_model_success(self):
        for marker in (
            "matches!(context.require_qualified(), Err(Error::Ineligible))",
            "OriginalCellEvaluationModelReadV1::finish(operation)",
            "completed.binding() != expected_material",
            "completed.original_evaluation() != &context.evaluation",
            "completed.authenticate_current(fresh)?", "return Ok(wire::Outcome::Ineligible)",
            "state.execution_requested = true", "self.bootstrap.cancellation.load(Ordering::Acquire)",
            "if result.is_err() && state.execution_requested", "state.fenced = true",
        ):
            self.rejects(EFFECT, "fn original_response(", marker)
        source = (ROOT / EFFECT).read_text()
        self.verifies(EFFECT, source)
        for addition in (
            "fn resume(state: &mut State) { state.execution_requested = false; }",
            "fn resume(state: &mut State) { state.fenced = false; }",
            "fn recover() { recover_original_model(); }",
        ):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(EFFECT, source + "\n" + addition + "\n")


if __name__ == "__main__":
    unittest.main()
