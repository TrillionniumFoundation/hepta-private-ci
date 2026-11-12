"""Keep ordinary NoUpdate dispatch on the same original owners and Root future.

The resident companion supplies the only fresh-CAS gate. This source suite
must be qualified with that companion; six native mechanism cases separately
use actual Material/Published owners without manufacturing a resident grant.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_no_update_stage_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CORE = AGENT + "cell_q24_no_update_stage_owners.rs"
INPUTS = AGENT + "cell_q24_no_update_stage_inputs.rs"
STATE = AGENT + "cell_q24_no_update_stage_state.rs"
AUTH = AGENT + "cell_q24_no_update_stage_auth.rs"
EXECUTE = AGENT + "cell_q24_no_update_stage_execute.rs"
SELECTOR = AGENT + "circuit_selection_command_stage_binding.rs"
NEXT_USE = AGENT + "circuit_next_use_command_stage_binding.rs"
READINESS = AGENT + "circuit_learning_completion_readiness.rs"
READINESS_OWNER = AGENT + "circuit_learning_completion_readiness_service.rs"
EXPECTED = {
    "learning_original_owner_command_channel": ("codex-rs/hepta-agentd/src/cell_q24_training_command.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command_service.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_capability.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_selection_command.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_candidate_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_candidate.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_transport.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_command.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_service.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_service.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_service.rs", "codex-rs/hepta-agentd/src/artifact_original_head_client.rs", "codex-rs/hepta-agentd/src/artifact_original_head_service.rs", "codex-rs/hepta-agentd/src/artifact_original_registry_source.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_capability.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_completion_readiness_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_service.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_command.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_command_service.rs", "codex-rs/hepta-agentd/src/circuit_model_version_service.rs",),
    "circuit_feature_original_selection_observation": ("codex-rs/hepta-agentd/src/circuit_selection_receipt_owner.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_sources.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_c_task.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_completion_readiness_service.rs", "codex-rs/hepta-agentd/src/circuit_model_version_task.rs",),
    "learning_original_material_command_client_from_original_experience_stream": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs",),
    "learning_original_material_command_client_from_original_dataset_stream": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs",),
    "learning_original_material_command_client_recover_original_experience_stream": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs",),
    "learning_original_material_command_client_recover_original_dataset_stream": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs",),
    "learning_original_material_command_client_execute": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs",),
    "learning_original_material_command_client_readback": ("codex-rs/hepta-agentd/src/cell_q24_material_dataset_readback.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs",),
    "learning_original_training_initial_connection_create": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_training_initial_connection_recover": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_training_initial_connection_dataset": ('codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_state.rs'),
    "learning_original_training_command_client_execute": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs",),
    "learning_original_training_command_client_readback": ('codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs', 'codex-rs/hepta-agentd/src/circuit_learning_retained_context.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_state.rs'),
    "learning_original_selector_command_context": ('codex-rs/hepta-agentd/src/circuit_selection_command_stage_binding.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs'),
    "learning_original_selector_command_client_execute": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs",),
    "learning_original_selector_command_client_readback": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs",),
    "learning_original_next_use_command_context": ("codex-rs/hepta-agentd/src/circuit_next_use_command_stage_binding.rs",),
    "learning_original_next_use_command_client_attest": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs",),
    "learning_original_next_use_command_client_readback": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs",),
    "learning_original_material_initial_context_check": ("codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_auth.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_context.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_host.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_service.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_host.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_context.rs", "codex-rs/hepta-agentd/src/circuit_model_version_host.rs",),
    "learning_original_material_dataset_context_check": ("codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_training_candidate_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_stage_binding.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_stage_binding.rs", "codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_context.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_completion_readiness.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_stage_binding.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material.rs",),
    "learning_original_no_update_stage_create": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_no_update_stage_recover": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_no_update_stage_initial": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs",),
    "learning_original_no_update_stage_resident_gate": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs",),
    "learning_original_no_update_stage_execute": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_owners.rs",),
    "learning_original_selector_stage_binding": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs",),
    "learning_original_next_use_stage_binding": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs",),
    "learning_original_c_readiness_binding": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs",),
    "learning_original_c_readiness_current": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs",),
    "learning_original_c_readiness_serve": (),
}


class OriginalNoUpdateStageClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

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

    def test_only_concrete_original_edges_and_resident_installation_are_registered(self):
        paths = {
            path for identifier in EXPECTED
            for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        sources = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                receiver = f"owner: &{row.receiver_type}" if row.receiver_type else ""
                call = f"owner.{method}()" if row.receiver_type else f"{method}()"
                extra = dict(sources)
                extra[AGENT + "unregistered_ordinary_stage.rs"] = f"fn extra({receiver}) {{ {call}; }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_initial_fixed_context_and_original_deadlines_precede_all_late_binding(self):
        for marker in (
            "OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)",
            "material.initial.owners.owner(stage)",
            "require_timing(input.timeout, input.lifetime, Duration::from_secs(30))?",
            "require_timing(\n        streams.version.timeout,\n        streams.version.lifetime,\n        Duration::from_secs(30),\n    )?",
            "Duration::from_millis(500)",
            "let admitted_at = Instant::now()",
            "let end = admitted_at.checked_add(lifetime)",
            "completion\n        .check_peer_lifetime()",
            "auth::require_clock(started_at, fresh)?",
            "if Instant::now() >= end",
            "root: None",
        ):
            self.rejects(INPUTS, "fn bind(", marker)
        self.rejects(INPUTS, "fn require_timing(", "lifetime > Duration::from_secs(300)")
        for marker in (
            "initial != &self.material.initial",
            "scope != &self.material.scope",
            "verifier.trust_digest() != self.material.verifier.trust_digest()",
            "verifier.scope_digest() != self.material.verifier.scope_digest()",
            "verifier.objective_digest() != self.material.verifier.objective_digest()",
            "auth::require_material(&self.material, self.initial_binding)?",
        ):
            self.rejects(CORE, "fn require_initial(", marker)

    def test_resident_gate_and_same_cancellation_remain_at_actual_effect_edges(self):
        self.rejects(CORE, "fn install_fresh_resident_gate(", "self.origin != Origin::Fresh || self.root.is_some()")
        for marker in (
            "self.origin != Origin::Fresh",
            "self\n            .root\n            .as_ref()\n            .ok_or(",
            "let before_readback =",
            "before_readback?",
            "let before_dispatch =",
            "before_dispatch?",
            "let after_dispatch =",
            "if after_dispatch.is_err()",
            "self.await_completed_c(snapshot, &mut state).await?",
            "RootResidentLearningEffectGateV3::training_cancellation(gate)",
            "OriginalCellQ24TrainingCommandClientV1::execute_training(trainer, dispatch)",
            "ready.as_ref() != Some(&value.receipt().observation)",
        ):
            self.rejects(EXECUTE, "fn execute_original_stage(", marker)
        for marker in (
            "for _ in 0..128",
            "RootResidentLearningEffectGateV3::require_current(",
            "OriginalCircuitCompletionReadinessClientV1::read_current(readiness)",
            "state.read_prefix(self, snapshot).await?",
            "tokio::time::sleep(Duration::from_secs(2)).await",
        ):
            self.rejects(EXECUTE, "fn await_completed_c(", marker)
        for addition in (
            "impl Clone for OriginalCellQ24NoUpdateStageOwnersV1 {}",
            "pub fn install_fresh_resident_gate() {}",
            "fn unbound() { with_root_learning_stage_owners(); }",
        ):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(CORE, (ROOT / CORE).read_text() + "\n" + addition)

    def test_recovery_and_attestation_use_real_owner_reads_and_final_clock(self):
        self.rejects(CORE, "fn recover_original_streams(", "Origin::Recovered", "Origin::Fresh")
        for function, read in (
            ("fn validate_recovery<'a>", "state.read_prefix(self, snapshot).await?"),
            ("fn receipt_attestation<'a>", "state.read_attestation(self, snapshot, receipt).await?"),
        ):
            for marker in (
                "tokio::time::timeout_at(self.end.into()",
                "let started_at = auth::now()?",
                read,
                "auth::require_material(&self.material, self.initial_binding)?",
                "auth::require_clock(started_at, fresh)?",
            ):
                self.rejects(CORE, function, marker)
        for marker in (
            "if snapshot.receipts.is_empty()",
            "OriginalCellQ24MaterialCommandClientV1::readback(&self.experience)",
            "return Err(Error::CommitUncertain)",
            "if &actual != expected",
        ):
            self.rejects(STATE, "fn read_prefix(", marker)
        self.rejects(STATE, "fn read_attestation(", "self.read_stage(owners, receipt.observation.stage()).await?")

    def test_late_binding_consumes_same_transport_and_authenticates_opaque_predecessors(self):
        for path in (SELECTOR, NEXT_USE, READINESS):
            for marker in (
                "peer.check_peer_lifetime()?",
                "OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(",
                "dataset, material",
            ):
                self.rejects(path, "fn bind_original_stage_channel(", marker)
            for addition in (
                "fn reopen() { original_owner_command_channel_v1(); }",
                "fn reopen() { HostAuthorityPeerChannel::from_stream(); }",
                "fn reopen() { UnixStream::connect(); }",
                "fn renew() { Instant::now(); }",
            ):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, (ROOT / path).read_text() + "\n" + addition)
        for path in (SELECTOR, NEXT_USE):
            self.rejects(path, "fn bind_original_stage_channel(", "Origin::Recovered => true", "Origin::Recovered => false")
        for function, marker in (
            ("fn ensure_trainer(", "self.trainer_initial.take()"),
            ("fn ensure_selector(", "self.selector_initial.take()"),
            ("fn ensure_next_use(", "self.next_use_initial.take()"),
            ("fn ensure_readiness(", "self\n                .readiness_initial\n                .take()"),
        ):
            self.rejects(STATE, function, marker)

    def test_readiness_only_original_unresolved_publication_remains_pending(self):
        for marker in (
            "self.require_task_input_current()?",
            "PublishedCircuitCellOwnerV1::read_learning_selection(",
            "CircuitTaskSourceReadbackV1::read_run_publication(",
            "Err(CircuitTaskErrorV1::ReconciliationRequired)",
            "PublishedCircuitCellOwnerV1::snapshot(",
            "Err(error) => return Err(Error::Source(error))",
            "self.read_original()?",
            "current.source_publication != Some(before.publication_digest())",
        ):
            self.rejects(READINESS_OWNER, "fn read_original_readiness(", marker)
        self.rejects(READINESS_OWNER, "fn serve_readiness_channel(", "for request_id in 1..=128")
        self.rejects(READINESS_OWNER, "fn readiness_response(", "bytes.is_empty() || bytes.len() > 16_384")
        self.rejects(READINESS, "fn bind_original_stage_channel(", "original::context_binding(&context, started_at)?")

    def test_readiness_consumes_unknown_transport_and_never_regresses_completed_identity(self):
        for marker in (
            ".take()\n            .ok_or(Error::Unavailable)?",
            "!(1..=128).contains(&channel.next_request_id)",
            "channel.peer.request(&bytes)?",
            "response\n            .request\n            .require_context(",
            "channel.peer.check_peer_lifetime()?",
            "let fresh = now()?",
            "fresh < started_at || original::context_binding(&self.context, fresh)? != self.binding",
            "retained\n                .as_ref()\n                .is_some_and(|prior| current.as_ref() != Some(prior))",
            "*retained = Some(ready.clone())",
        ):
            self.rejects(READINESS, "fn read_current(", marker)
        self.rejects(READINESS, "fn require_context(", "self.purpose != PURPOSE")
        for marker in (
            "request.require_context(&self.context, self.binding, request_id)?",
            "self.read_original_readiness()?",
            "fresh < started_at || wire::context_binding(&self.context, fresh)? != self.binding",
        ):
            self.rejects(READINESS_OWNER, "fn readiness_response(", marker)

    def test_candidate_is_preserved_and_no_model_authority_or_signature_renewal_is_added(self):
        self.rejects(CORE, "fn prepare_proposal<'a>", "Err(Error::OwnerUnavailable(")
        self.rejects(STATE, "fn record_training(", "self.pin(owners, original.receipt(), original.attestation())?")
        for function, marker in (
            ("fn record_selection(", "original.snapshot().training_no_update_v2().is_none()"),
            ("fn record_selection(", "original.training_attestation() != training.attestation()"),
            ("fn record_next_use(", "original.selection_attestation() != selection.attestation()"),
            ("fn pin(", "prior != &(receipt.clone(), signature.clone())"),
        ):
            self.rejects(STATE, function, marker)
        for marker in (
            "receipt.observed_unix_seconds != signature.issued_at",
            "material\n        .verifier\n        .verify(",
            "learning_iteration_receipt_signing_bytes_v1(receipt)?",
        ):
            self.rejects(AUTH, "fn verify_receipt(", marker)
        for marker in (
            "verify_signed_actor_separation(&verified[2], &verified[3], at)",
            "verify_signed_actor_separation(&verified[2], &verified[4], at)",
            "verify_signed_actor_separation(&verified[3], &verified[4], at)",
        ):
            self.rejects(AUTH, "fn verify_prefix(", marker)


if __name__ == "__main__":
    unittest.main()
