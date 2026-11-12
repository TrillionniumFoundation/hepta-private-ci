"""Guard original evaluator identity, signature persistence and read-only recovery."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("original_learning_owner_proof", ROOT / "scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "neuron_cell_evaluation_owner.rs"
JOURNAL = AGENT + "learning_owner_journal.rs"

class OriginalLearningOwnerClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_original_sealed_request_cannot_be_replaced_by_caller_bytes(self):
        for marker in ("request.key() != &self.execution", "executed.product_plan != self.config.plan", "request.signing_payload()", "self.journal.commit_once(saved_key", "if saved_payload != payload"):
            with self.subTest(marker=marker): self.rejects(OWNER, "fn attest(", marker)

    def test_claim_and_witness_must_precede_signing_and_saved_readback(self):
        for marker in ("self.journal.claim(key)", "return Err(Error::Pending)", "self.anchor_append(before)?", "let bytes = build()?", "self.journal.complete(key, &bytes)", "self.read(key)?", "if saved != bytes"):
            with self.subTest(marker=marker): self.rejects(JOURNAL, "fn commit_once(", marker)

    def test_recovered_evidence_must_match_original_key_actor_and_identity(self):
        for marker in ("self.config.verifier.verify(", "verified.principal() != &self.config.signer.principal", "verified.controller_id() != &self.config.signer.controller_id", "signed.evidence_id != evidence_id(self.saved.binding_digest)?"):
            with self.subTest(marker=marker): self.rejects(OWNER, "fn decode(", marker)

    def test_constructor_checks_registered_signer_without_probe_signature(self):
        for marker in ("key.verifying_key().to_bytes() != config.signer.verifying_key", "product_evaluation_execution_key_v1(", "config.verifier.require_signer_binding("):
            with self.subTest(marker=marker): self.rejects(OWNER, "fn validate_config(", marker)

    def test_registered_controller_revocation_and_role_are_required(self):
        path = "codex-rs/hepta-learning-ledger/src/signed_evidence.rs"
        for marker in ("if enrolled != &canonical", "enrolled.principal.validate(now)?", "enrolled.revoked_at.is_some_and", "enrolled.roles.contains(&expected_role)"):
            with self.subTest(marker=marker): self.rejects(path, "fn require_signer_binding(", marker)

    def test_feature_dispatch_must_receive_original_durable_cell_admission(self):
        path = "codex-rs/hepta-neuron/src/cell_inference.rs"
        for marker in ("owner.admit_inference(admission.clone())?", "control\n        .bind_cell_inference(&admission)", "if dispatch_at_micros >= prepared.input.deadline_micros", "owner.record_host_queue_age("):
            with self.subTest(marker=marker): self.rejects(path, "fn infer_cell_with_clock(", marker)
        for marker in ("pending.semantic_request_digest != digest", "owner.snapshot(&input.scope)? != pending.snapshot", "prepared.model_request != pending.model_request", "CellExecutionError::UnmeasuredQueueCost", "readback\n        .bind_cell_readback(&pending)"):
            with self.subTest(marker=marker): self.rejects(path, "fn recover_cell_inference(", marker)

    def test_native_control_fences_unknown_execution_and_persists_before_return(self):
        path = "codex-rs/hepta-neuron/src/feature_control.rs"
        for marker in ("self.require_request(request)?", "self\n            .owner\n            .generation_has_unresolved()", "self\n            .owner\n            .admit_generation(", "self.owner\n            .dispatch_generation(", "entered < dispatch || entered >= deadline", "completed < entered || observation.status == NeuronFeatureTerminalStatusV1::Indeterminate", "observation.drive_q24.clear()", "self.owner\n            .settle_generation("):
            with self.subTest(marker=marker): self.rejects(path, "fn execute_feature(", marker)

    def test_source_pending_and_readback_cannot_become_new_work(self):
        path = AGENT + "circuit_task_source_journal.rs"
        for marker in ("if bytes != payload", "ProductEvaluationExecutionStateV1::Pending", "mode == CircuitTaskInputModeV1::Prepare", "self.journal.claim(&key)", "self.anchor_append(before)?", "self.require_bytes(stage, run, payload)"):
            with self.subTest(marker=marker): self.rejects(path, "fn retain(", marker)
        path = AGENT + "circuit_task_source.rs"
        for marker in ("owner.require_active(&request.start.run_id)?", "codec::require_request(&retained, request)?", "if !completed.is_empty()", "dispatch.input_digest != request.start.input_digest", "circuit_cell_operation_id_v1(dispatch)?"):
            with self.subTest(marker=marker): self.rejects(path, "fn resolve(", marker)

    def test_observer_views_cannot_gain_original_writer_capabilities(self):
        forbidden = {
            AGENT + "circuit_task_source_readback.rs": ("pub original:", "Deref", "AgentdCircuitTaskInvocationProviderV1 for", "CircuitTaskInputProviderV1 for", ".withdraw(", ".publish_result("),
            AGENT + "circuit_feature_current_owner.rs": ("CellStateOwnerV1 for PublishedCircuitCellOwnerV1", "pub original:", "pub task:", "into_inner"),
            "codex-rs/hepta-neuron/src/cell_journal_readback.rs": ("CellStateOwnerV1 for", "Deref", "into_inner", ".write_all(", ".compare_and_swap(", ".admit_inference("),
        }
        for path, mutations in forbidden.items():
            rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
            source = (ROOT / path).read_text()
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / path
                target.parent.mkdir(parents=True)
                target.write_text(source)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                for marker in mutations:
                    with self.subTest(path=path, marker=marker):
                        target.write_text(source + "\n" + marker + "\n")
                        with self.assertRaises(PROOF.VerificationFailure):
                            PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_published_task_keeps_original_profile_and_distinct_successor(self):
        path = AGENT + "circuit_feature_current.rs"
        for marker in ("original.previous() != &previous.binding", "previous.receipt.checkpoint_after != previous.source.checkpoint_digest()", "old.scope.run_id == source.scope.run_id\n            || old.observation == source.observation"):
            with self.subTest(marker=marker): self.rejects(path, "fn from_update<", marker)
        for marker in ("journal.owner_binding() != Some(target)", "target.task_digest()\n                != circuit_feature_task_digest_v1(", "manifest.profile != crate::CellQ24GenerationWorkerV1::PROFILE", "current.check_current(target)", "original: Mutex::new(Box::new(journal))", "result.require_current()?"):
            with self.subTest(marker=marker): self.rejects(path, "fn from_parts<", marker)

    def test_retirement_and_next_use_recheck_source_and_actual_cell(self):
        path = AGENT + "circuit_feature_current_retirement.rs"
        for marker in ("Arc::ptr_eq(&self.0, &cell.task.0)", "cell.committed(&before)?", "original.require_current()?", "original.drain()?", "original.is_drained()?", "self.require_current()?"):
            with self.subTest(marker=marker): self.rejects(path, "fn drain_completed_task<", marker)
        path = AGENT + "circuit_feature_current_learning.rs"
        for marker in ("coordinator.next_stage() != Some(LearningIterationStageV1::NextUse)", "prefix.head_digest = selection.predecessor", "self.read_learning_selection(&prefix)?", "actual_selection != selection.observation", "source\n            .read_run_publication(", "self.committed(&before)?", "receipt.bundle_digest != candidate_bundle", "self.task.require_current()?"):
            with self.subTest(marker=marker): self.rejects(path, "fn read_learning_next_use_set(", marker)

    def test_historical_read_never_reactivates_or_repairs_previous_owner(self):
        path = AGENT + "circuit_feature_current_recovery.rs"
        for marker in ("binding != self.publication.previous()", "self.successor.check_current(self.publication.target())"):
            with self.subTest(marker=marker): self.rejects(path, "fn check_current(", marker)
        for marker in ("current\n        .check_current(publication.target())", "NeuronGenerationPredecessorCompletionV1::OwnerDrained", "previous.task_digest()\n            != circuit_feature_task_digest_v1(", "CellOwnerJournalReadbackV1::open_guarded(", "reader\n        .pending_inference(", "before.require_decision(&receipt)", "snapshot.revision != 1", "receipt.checkpoint_after != before.checkpoint_digest()", "source\n        .read_run_publication("):
            with self.subTest(marker=marker): self.rejects(path, "fn recover_predecessor<", marker)
        path = "codex-rs/hepta-neuron/src/cell_journal.rs"
        for marker in ("self.mode == OpenMode::ReadOnlyAcknowledged", "head.is_none() || head != expected || offset != bytes.len()", "self.require_current()?"):
            with self.subTest(marker=marker): self.rejects(path, "fn recover(", marker)
        for marker in ("self.mode == OpenMode::ReadOnlyAcknowledged", ".sync_all()", ".compare_and_swap(self.head, next)", "self.require_current()\n            .map_err(|_| CellExecutionError::CommitUncertain)?"):
            with self.subTest(marker=marker): self.rejects(path, "fn persist(", marker)

    def test_ordinary_assembly_uses_original_current_native_worker_and_normal_channel(self):
        path = AGENT + "circuit_q24_task_profile.rs"
        for marker in ("identity.spawn_generation == 0", "published.require_bundle(&profile.bundle)?", "CellQ24FeatureWorkerV1::new(", "DurableCircuitTaskSourceV1::recover(", "published.open_cell(", "published\n        .control(", "cell.writer()", "circuit_task_channel_v1(", "source.readback()"):
            with self.subTest(marker=marker): self.rejects(path, "fn circuit_q24_task_channel_v1<", marker)

    def test_live_original_owner_current_brackets_physical_read_with_witness(self):
        for marker in ("let before = self.witness.current()?", "self.journal.read_current_anchor()?", "let after = self.witness.current()?", "before != Some(current) || after != before", "if result.is_err()", "self.fenced = true"):
            with self.subTest(marker=marker): self.rejects(JOURNAL, "fn require_current(", marker)

    def test_live_execution_current_replays_original_locked_bytes(self):
        path = "codex-rs/hepta-intelligence-eval/src/product_execution_current.rs"
        for marker in ("length > MAX_FILE_BYTES", "length != self.length", ".take(MAX_FILE_BYTES + 1)", ".read_to_end(&mut bytes)", "&bytes[8..40] != self.binding.as_array()", "next_anchor(current, payload)?", "checksum != next.history_digest.as_array()", "replay(&mut records, payload)?", "current != self.anchor || records != self.records", "self.file.seek(SeekFrom::Start(cursor))", "if result.is_err()"):
            with self.subTest(marker=marker): self.rejects(path, "fn read_current_anchor(", marker)

if __name__ == "__main__":
    unittest.main()
