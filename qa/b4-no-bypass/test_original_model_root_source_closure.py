"""Original Model proof closes Proposal without inventing a signature role.

These exact source mutations are caller/order gates. The six actual-owner
mechanisms remain separate UID0 native cases; neither proves deployment or
independent scientific qualification of the fixture Evaluation panel.
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
    "original_model_root_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
MODEL = AGENT + "authority_host_learning_resident_model.rs"
RECOVERY = AGENT + "authority_host_learning_resident_model_recovery.rs"
AUTH = AGENT + "authority_host_learning_resident_auth.rs"
WIRE = AGENT + "authority_host_learning_resident_wire.rs"
LANE = AGENT + "cell_q24_candidate_stage_model.rs"
OPERATION = AGENT + "cell_q24_candidate_stage_operation.rs"
COMMAND = AGENT + "cell_q24_model_command.rs"
COMMAND_WIRE = AGENT + "cell_q24_model_command_wire.rs"
STAGES = AGENT + "authority_host_learning_resident_stages.rs"
INPUTS = AGENT + "cell_q24_candidate_stage_inputs.rs"
EXPECTED = {
    "learning_original_model_command_initial_create": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_model_command_initial_recover": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_model_command_bind": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs",),
    "learning_original_model_command_client_execute": (),
    "learning_original_model_command_client_readback": ("codex-rs/hepta-agentd/src/circuit_learning_model_context.rs",),
    "learning_original_model_root_record": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_model.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_operation.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_wire.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_context.rs",),
    "learning_original_candidate_stage_model_readback": (),
    "root_resident_concrete_stages_model_readback": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_auth.rs",),
    "root_resident_model_proof_original": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_auth.rs",),
    "root_resident_model_proof_decode": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_wire.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_auth.rs",),
    "root_resident_model_proof_authenticate": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_auth.rs",),
    "root_resident_model_readonly_client": (),
    "learning_original_model_command_host_create": (),
    "learning_original_model_command_host_recover": (),
    "learning_original_model_command_host_serve": (),
    "cell_q24_current_model_owner_create": ("codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs",),
    "learning_original_training_stage_current_model_create": ("codex-rs/hepta-agentd/src/cell_q24_source_bound_stage.rs",),
    "learning_source_bound_stage_current_model_create": ("codex-rs/hepta-agentd/src/cell_q24_model_command_lane.rs",),
    "cell_q24_current_model_owner_recover": ("codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs",),
    "learning_original_training_stage_current_model_recover": ("codex-rs/hepta-agentd/src/cell_q24_source_bound_stage.rs",),
    "learning_source_bound_stage_current_model_recover": ("codex-rs/hepta-agentd/src/cell_q24_model_command_lane.rs",),
    "cell_q24_current_model_owner_commit": ("codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs",),
    "learning_original_training_stage_current_model_commit": ("codex-rs/hepta-agentd/src/cell_q24_source_bound_stage.rs",),
    "learning_source_bound_stage_current_model_commit": ("codex-rs/hepta-agentd/src/cell_q24_model_command_lane.rs",),
    "cell_q24_current_model_owner_readback": ("codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs",),
    "learning_original_training_stage_current_model_readback": ("codex-rs/hepta-agentd/src/cell_q24_source_bound_stage.rs",),
    "learning_source_bound_stage_current_model_readback": ("codex-rs/hepta-agentd/src/cell_q24_model_command_lane.rs",),
    "learning_original_training_command_model_training": ("codex-rs/hepta-agentd/src/cell_q24_model_command_host.rs",),
    "learning_original_training_command_model_create": ("codex-rs/hepta-agentd/src/cell_q24_model_command_effect.rs", "codex-rs/hepta-agentd/src/cell_q24_model_read_host_operation.rs",),
    "learning_original_training_command_model_recover": ("codex-rs/hepta-agentd/src/cell_q24_model_command_host.rs",),
    "learning_original_training_command_model_commit": ("codex-rs/hepta-agentd/src/cell_q24_model_command_effect.rs", "codex-rs/hepta-agentd/src/cell_q24_model_read_host_operation.rs",),
    "learning_original_training_command_model_readback": ("codex-rs/hepta-agentd/src/cell_q24_model_command_effect.rs", "codex-rs/hepta-agentd/src/cell_q24_model_read_host_operation.rs",),
    "cell_q24_model_material_digest": ("codex-rs/hepta-agentd/src/cell_q24_model_proposal_admission.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_verify.rs",),
    "root_resident_gate_effect_current": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_adoption.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_evaluation.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_readback.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs",),
    "root_resident_gate_training_cancel": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_adoption.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs",),
    "root_resident_concrete_stages_initial": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_auth.rs",),
    "learning_original_owner_command_channel": ("codex-rs/hepta-agentd/src/cell_q24_training_command.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command_service.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_capability.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_selection_command.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_candidate_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_candidate.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_transport.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_command.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_service.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_service.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_service.rs", "codex-rs/hepta-agentd/src/artifact_original_head_client.rs", "codex-rs/hepta-agentd/src/artifact_original_head_service.rs", "codex-rs/hepta-agentd/src/artifact_original_registry_source.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_capability.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_completion_readiness_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_service.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_command.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_command_service.rs", "codex-rs/hepta-agentd/src/circuit_model_version_service.rs",),
    "learning_original_owner_snapshot_encode": ("codex-rs/hepta-agentd/src/cell_q24_training_command_wire.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_wire.rs", "codex-rs/hepta-agentd/src/circuit_selection_command.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_wire.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_profile.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_store.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_wire.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_contract.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_wire.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_context.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_model.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_export.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_wire.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_context.rs",),
    "learning_original_owner_snapshot_decode": ("codex-rs/hepta-agentd/src/cell_q24_training_command_wire.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_wire.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_store.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_wire.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_wire.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_verify.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_wire.rs",),
    "learning_original_material_initial_context_check": ("codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_auth.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_context.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_host.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_service.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_host.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_context.rs", "codex-rs/hepta-agentd/src/circuit_model_version_host.rs",),
    "learning_original_material_dataset_context_check": ("codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_training_candidate_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_stage_binding.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_stage_binding.rs", "codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_context.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_completion_readiness.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_stage_binding.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material.rs",),
    "cell_q24_original_training_observation": ("codex-rs/hepta-agentd/src/cell_q24_training_receipt_owner.rs", "codex-rs/hepta-agentd/src/cell_q24_model_proposal_admission.rs", "codex-rs/hepta-agentd/src/cell_q24_model_current_admission.rs",),
    "learning_source_bound_training_stage_readback": ('codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_model_command_lane.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs'),
}


class OriginalModelRootClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement="", occurrence=0):
        source = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(source)
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        cursor = start
        for _ in range(occurrence + 1):
            offset, cursor = source_marker_span(source, marker, cursor, end + 1)
        self.verifies(path, source)
        changed = source[:offset] + replacement + source[cursor:]
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_actual_model_edges_are_exact_and_unregistered_owners_stay_closed(self):
        paths = {
            path for identifier in EXPECTED for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
                (ROOT / path).read_text())) for path in paths
        }
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                receiver = f"owner: &mut {row.receiver_type}" if row.receiver_type else ""
                call = f"owner.{method}()" if row.receiver_type else f"{method}()"
                extra = dict(sources)
                extra[AGENT + "unregistered_original_model.rs"] = f"fn bypass({receiver}) {{ {call}; }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_root_projection_requires_the_original_complete_model_and_full_context(self):
        for function, markers in (
            ("fn from_original_readback(", (
                "let prefix = fixed_model_prefix(profile, snapshot, signatures)?",
                "let predecessors = &signatures[..4]",
                "original.snapshot() != &prefix || original.authority() != AuthorityPosture::DENY_ALL",
                "OriginalCellQ24ModelCommandReceiptV1::original_record_for_root(original, predecessors)",
                "require_record(profile, &prefix, record, now)?",
                "binding(profile, verifier, &prefix, predecessors, context, record)?",
            )),
            ("fn fixed_model_prefix(", (
                "profile.scope.validate_snapshot(snapshot)?",
                "snapshot.request != profile.initial.request",
                "snapshot.owners != profile.initial.owners",
                "!(5..=7).contains(&snapshot.receipts.len())",
                "signatures.len() + 1 != snapshot.receipts.len()",
                "snapshot.training_no_update_v2().is_some()",
                "complete.candidate().is_none()",
                ".all(|(receipt, stage)| receipt.observation.stage() == stage)",
                "for receipt in &snapshot.receipts[..5]",
                "prefix.record(receipt.clone(), receipt.observed_unix_seconds)?",
                "profile.scope.validate_snapshot(prefix.snapshot())?",
                "prefix.snapshot().receipts.len() != 5",
                "prefix.next_stage() != Some(Stage::Selection)",
                "prefix.candidate() != complete.candidate()",
            )),
            ("fn require_record(", (
                "profile.scope.validate_snapshot(snapshot)?",
                "snapshot.request != profile.initial.request",
                "snapshot.owners != profile.initial.owners",
                "snapshot.receipts.len() != stages.len()",
                "snapshot.training_no_update_v2().is_some()",
                "complete.next_stage() != Some(Stage::Selection)",
                '&record[..8] != b"HQ24PROP"',
                "prefix.record(receipt.clone(), receipt.observed_unix_seconds)?",
                "record[8..40] != *prefix.snapshot().head_digest.as_array()",
                "at < snapshot.receipts[3].observed_unix_seconds",
                "at >= snapshot.request.envelope.expiry_unix_seconds",
                "receipt.actor_id != snapshot.owners.proposal",
                "receipt.evidence_digest != composition",
                "disposition: LearningProposalDispositionV1::UpdateCandidates",
            )),
            ("fn binding(", (
                "profile.binding,", "profile.scope.binding(),",
                "verifier.trust_digest(),", "verifier.scope_digest(),",
                "verifier.objective_digest(),", "context,",
                "encode_original_owner_snapshot_v1(snapshot)",
                "bytes.extend_from_slice(record)", "let original = signed.signing_bytes()",
                "bytes.extend_from_slice(&original)", "bytes.extend_from_slice(&signed.signature)",
            )),
        ):
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    self.rejects(MODEL, function, marker)
        self.rejects(COMMAND, "fn original_record_for_root(",
                     "predecessors != self.predecessors.as_slice()")

    def test_every_non_model_receipt_keeps_one_original_role_signature(self):
        for marker in (
            "proposal_count > 1", "!(5..=7).contains(&snapshot.receipts.len())",
            "snapshot.receipts[4].observation.stage() != LearningIterationStageV1::Proposal",
            "signatures.len() + proposal_count != snapshot.receipts.len()",
            "signatures.len() > 6", "proposal_count == 0 && signatures.len() > 5", ".zip(signatures)",
            "LearningIterationStageV1::Training => LearningEvidenceRoleV1::Generator",
            "LearningEvidenceRoleV1::Evaluator",
            "evidence.principal().principal_id != receipt.actor_id",
            "&receipt.actor_id != snapshot.owners.owner(stage)",
            "evidence.trust_digest() != snapshot.owners.evidence_trust_digest",
            "evidence.objective_digest() != snapshot.request.envelope.objective_digest",
            "verify_signed_actor_separation(&previous.1, current, now)",
        ):
            with self.subTest(marker=marker):
                self.rejects(AUTH, "fn verify_non_model_attestations(", marker)
        for marker in (
            "verify_non_model_attestations(profile, verifier, snapshot, signatures, now)?",
            "(false, None) => Ok(())",
            "(true, Some(model)) => model.require_original(profile, verifier, snapshot, signatures, now)",
            "(false, Some(_)) | (true, None) => Err(Error::WrongScope)",
        ):
            self.rejects(AUTH, "fn verify_original_evidence(", marker)
        self.rejects(AUTH, "fn verify_attestations(",
                     "verify_original_evidence(profile, verifier, snapshot, signatures, None, now)")

    def test_dispatch_rereads_dte_then_original_model_and_preserves_unknown(self):
        for marker in (
            "self.common.origin != Origin::Fresh || snapshot.receipts.len() != 4",
            "Action::Execute",
        ):
            self.rejects(LANE, "fn execute_original_model(", marker)
        for marker in (
            "evaluation_cut.next_stage() != Some(Stage::Proposal)",
            "disposition: LearningEvaluationDispositionV1::Qualified",
            "evaluation_cut.snapshot() != snapshot", "if lane.failed", "lane.failed = true",
            "lane.initial.take().ok_or(Error::CommitUncertain)?",
            "OriginalCellQ24ModelCommandConnectionV1::bind_original_evaluation(",
            "OriginalCellQ24ModelCommandClientV1::begin_original_model_commit(",
            "RootResidentLearningEffectGateV3::training_cancellation(gate)",
            "CandidateOriginalOperation::begin(self, snapshot).await?",
            "before.snapshot() != evaluation_cut.snapshot()",
            "before.training_attestation() != operation.training.attestation()",
            "if &before != after", "current != &actual",
            "CandidateOriginalOperation::close(operation)",
            "original.material().original_evaluation() != &before",
            "let actual = original.model().clone()",
            "original.finish().await.map_err(|_| Error::CommitUncertain)?",
            "current.authority() != AuthorityPosture::DENY_ALL",
            "current.snapshot().receipts.len() != 5",
            "lane.retained = Some(current.clone())", "lane.failed = false",
            "closed.model(completed)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(LANE, "fn original_model(", marker)
        self.rejects(LANE, "fn original_model(",
                     "OriginalCellQ24CandidateStageOwnersV1::read_evaluation_in_operation(")
        self.rejects(LANE, "fn original_model(",
                     "OriginalCellQ24ModelCommandClientV1::begin_original_model_read(")
        for occurrence in (0, 1):
            self.rejects(LANE, "fn original_model(",
                         "RootResidentLearningEffectGateV3::require_current(",
                         occurrence=occurrence)
        self.rejects(LANE, "fn original_model(", "lane.failed = true", "lane.failed = false")
        for marker in (
            "common.original_dataset.as_ref() != Some(&self.dataset)",
            "common.original_training.as_ref() != Some(&self.training)",
            "common.records.get(..3) != Some(self.records.as_slice())",
            "auth::require_clock(self.started, fresh)?",
            "auth::verify_prefix(&self.owners.common.material, &self.training_cut, &common, fresh)?",
        ):
            self.rejects(OPERATION, "fn close(", marker)
        self.rejects(OPERATION, "fn authenticate_result(",
                     "operation.owners.verify_original_evaluation(")

    def test_initial_model_stream_and_final_root_io_cannot_be_replaced_by_future_dtos(self):
        for marker in (
            "model.peer.actor_id != material.initial.owners.proposal",
            "OriginalCellQ24ModelCommandConnectionV1::from_original_stream(",
            "OriginalCellQ24ModelCommandConnectionV1::recover_from_original_stream(",
            "let end = end.min(evaluator_end).min(model_end)", "ModelLane::new(model)",
        ):
            self.rejects(INPUTS, "fn bind(", marker)
        for marker in (
            "receipt.observation.stage() != LearningIterationStageV1::Proposal",
            "ResidentOriginalStageOwnersV3::read_original_candidate_evidence(",
            "candidate_continuation_attestations(",
        ):
            self.rejects(AUTH, "fn original_attestations(", marker)
        for marker in (
            "let (_, fresh) = owner.read(cancellation).await?",
            "ResidentOriginalStageOwnersV3::require_initial(",
            "ResidentOriginalStageOwnersV3::consume_original_candidate_evidence(",
            "ResidentOriginalModelProofV3::from_original_readback(",
            "verify_original_evidence(",
        ):
            self.rejects(AUTH, "fn candidate_continuation_attestations(", marker)
        for marker in (
            "Stage::Evaluation | Stage::Proposal => match self",
            "if matches!(self, Self::Candidate(_))",
            "snapshot.training_no_update_v2().is_none()",
        ):
            self.rejects(STAGES, "fn require_stage(", marker)

    def test_cold_model_pin_is_readonly_and_wire_none_preserves_prior_shape(self):
        for marker in (
            "ClientOriginV3::Readback(authorization)", "model: Some(model)",
        ):
            self.rejects(RECOVERY, "fn recover_original_model_root_stream(", marker)
        for function, marker in (
            ("fn decode_current(", "encoded.len() != 203"),
            ("fn decode_current(", "ResidentOriginalModelProofV3::decode_root_reply("),
            ("fn decode_current(", "snapshot.as_ref().ok_or(Error::WrongScope)?"),
            ("fn decode_current(", "None if !attestations.is_empty() || dispatch_pending || model.is_some()"),
            ("fn require_original_prefix(", "!current.attestations.starts_with(&previous.attestations)"),
            ("fn require_original_prefix(", "previous.model.as_ref().is_some_and(|saved|"),
            ("fn require_original_prefix(", ".is_none_or(|model| model.encode() != *saved)"),
        ):
            self.rejects(WIRE, function, marker)
        source = (ROOT / WIRE).read_text()
        self.verifies(WIRE, source)
        marker = '#[serde(default, skip_serializing_if = "Option::is_none")]'
        self.assertEqual(source.count(marker), 1)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(WIRE, source.replace(marker, "", 1))
        for path, addition in (
            (MODEL, "fn forged() { SigningKey::generate(); }"),
            (MODEL, "pub struct ResidentOriginalModelProofV3 {}"),
            (RECOVERY, "fn fresh() { ClientOriginV3::Fresh; }"),
            (COMMAND, "struct CallerRecord { pub record: [u8; 80] }"),
            (COMMAND_WIRE, "struct CallerPayload { pub batch: Vec<u8> }"),
            (LANE, "fn retry() { RootResidentLearningEffectGateV3::new(); }"),
        ):
            with self.subTest(path=path, addition=addition):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, (ROOT / path).read_text() + "\n" + addition + "\n")

    def test_model_record_codec_reconstructs_only_original_proposal(self):
        for function, markers in (
            ("fn require_initial(", (
                "self.schema != 1", "self.purpose != PURPOSE", "self.nonce != nonce",
                "self.operation_id != material.initial.request.operation_id.as_str()",
                "self.actor_id != material.initial.owners.proposal.as_str()",
                "self.scope != material.scope.binding().to_string()",
            )),
            ("fn decode_completed(", (
                "let fresh = context.authenticate(current)?", "context.require_qualified()?",
                "record.len() != 107", "bytes.len() != 80",
                "STANDARD_NO_PAD.encode(&bytes) != record",
                "record_bytes(context, material, at)? != bytes || at > fresh",
                "coordinator.record(receipt, at)?", "coordinator.snapshot().receipts.len() != 5",
                "context.dataset.attestations()[0].clone()", "context.dataset.attestations()[1].clone()",
                "context.training.attestation().clone()", "context.evaluation.attestation().clone()",
            )),
        ):
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    self.rejects(COMMAND_WIRE, function, marker)


if __name__ == "__main__":
    unittest.main()
