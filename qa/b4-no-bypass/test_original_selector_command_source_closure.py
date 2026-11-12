"""Close original Selector command admission to its original owner.

These source gates protect custody and dispatch boundaries. Native behavior
cases separately exercise real Published/Selector reads, once admission and ACKs.
They do not certify an installed external-UID ordinary stage dispatcher.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_selector_command_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
MAIN = AGENT + "circuit_selection_command.rs"
WIRE = AGENT + "circuit_selection_command_wire.rs"
SERVICE = AGENT + "circuit_selection_command_service.rs"
EVIDENCE = AGENT + "circuit_selection_command_evidence.rs"
OWNER = AGENT + "circuit_selection_receipt_owner.rs"
EXPECTED = {
    "learning_original_selector_command_context": ("codex-rs/hepta-agentd/src/circuit_selection_command_stage_binding.rs",),
    "learning_original_selector_command_owner_consume": (),
    "learning_original_selector_command_owner_profile": ("codex-rs/hepta-agentd/src/circuit_selection_command_service.rs",),
    "learning_original_selector_command_owner_factory": ("codex-rs/hepta-agentd/src/circuit_selection_receipt_owner.rs",),
    "learning_original_selector_command_client_create": (),
    "learning_original_selector_command_client_recover": (),
    "learning_original_selector_command_client_execute": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs",),
    "learning_original_selector_command_client_readback": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs",),
    "learning_original_selector_command_client_attestation": (),
    "learning_original_selector_command_owner_serve": (),
    "learning_original_selector_command_owner_evidence": (),
    "learning_original_owner_command_channel": ('codex-rs/hepta-agentd/src/cell_q24_training_command.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_material_command.rs', 'codex-rs/hepta-agentd/src/cell_q24_material_command_service.rs', 'codex-rs/hepta-agentd/src/circuit_learning_read_capability.rs', 'codex-rs/hepta-agentd/src/circuit_learning_read_service.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs', 'codex-rs/hepta-agentd/src/circuit_next_use_command.rs', 'codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_candidate_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_candidate.rs', 'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs', 'codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs', 'codex-rs/hepta-agentd/src/authority_host_learning_resident_transport.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_command.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_service.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs', 'codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_service.rs', 'codex-rs/hepta-agentd/src/artifact_original_head_client.rs', 'codex-rs/hepta-agentd/src/artifact_original_head_service.rs', 'codex-rs/hepta-agentd/src/artifact_original_registry_source.rs'),
    "learning_original_owner_snapshot_encode": ("codex-rs/hepta-agentd/src/cell_q24_training_command_wire.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_wire.rs", "codex-rs/hepta-agentd/src/circuit_selection_command.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_wire.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_profile.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_store.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_wire.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_contract.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_wire.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_context.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_model.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_export.rs",),
    "learning_original_owner_snapshot_decode": ("codex-rs/hepta-agentd/src/cell_q24_training_command_wire.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_wire.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_store.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_wire.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_wire.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_verify.rs",),
    "learning_original_published_read_client_context": ("codex-rs/hepta-agentd/src/circuit_selection_receipt_owner.rs", "codex-rs/hepta-agentd/src/circuit_next_use_receipt_owner.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_service.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs",),
    "learning_original_circuit_selection_remote_attest": ("codex-rs/hepta-agentd/src/circuit_selection_command_service.rs",),
    "learning_original_circuit_selection_remote_readback": ("codex-rs/hepta-agentd/src/circuit_selection_command_service.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_evidence.rs"),
}


class OriginalSelectorCommandClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def rejects(self, path, function, marker, replacement=""):
        source = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(source)
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + replacement + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_only_concrete_original_owner_edges_open_and_factories_stay_closed(self):
        paths = {path for identifier in EXPECTED for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                call = f"owner.{method}()" if row.receiver_type else f"{method}()"
                receiver = f"owner: &{row.receiver_type}" if row.receiver_type else ""
                extra = dict(sources)
                extra[AGENT + "unregistered_selector_command.rs"] = f"fn bypass({receiver}) {{ {call}; }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertEqual(self.boundaries["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_fresh_context_uses_opaque_actual_training_and_full_original_binding(self):
        for function, marker in (
            ("fn from_original_training(", "original: &OriginalCellQ24TrainingCommandReceiptV1"),
            ("fn from_original_training(", "original.receipt().clone()"),
            ("fn from_original_training(", "original.attestation().clone()"),
            ("fn authenticate(", "LearningIterationObservationV1::TrainingNoUpdateV2(_)"),
            ("fn authenticate(", "receipt.observed_unix_seconds != self.training_evidence.issued_at"),
            ("fn binding(", "&encode_original_owner_snapshot_v1(&self.training)?"),
            ("fn binding(", "self.scope.binding().as_array()"),
            ("fn binding(", "&self.training_evidence.signing_bytes()"),
            ("fn binding(", "&self.training_evidence.signature"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(MAIN, function, marker)

    def test_owner_origin_cannot_be_promoted_by_connection_or_caller_flag(self):
        self.rejects(OWNER, "fn create(", "command_origin: CommandOrigin::FreshCreate")
        self.rejects(OWNER, "fn recover(", "command_origin: CommandOrigin::Recovered")
        self.rejects(OWNER, "fn original_command_profile(",
                     "matches!(self.command_origin, CommandOrigin::Recovered)", "false")
        self.rejects(SERVICE, "fn from_original_receipt_owner(",
                     "OriginalCircuitSelectionReceiptOwnerV1::original_command_profile(&owner)")
        self.rejects(SERVICE, "fn from_original_receipt_owner(",
                     "AtomicBool::new(readback_only)", "AtomicBool::new(false)")
        self.rejects(SERVICE, "fn command_response(",
                     "request.require_context(&self.context, self.binding, request_id)?")
        self.rejects(SERVICE, "fn command_response(",
                     "self.execution_requested.swap(true, Ordering::AcqRel)")

    def test_client_consumes_unknown_exchange_and_checks_time_after_last_peer_io(self):
        for marker in (
            "slot.take().ok_or(Error::Unavailable)?", "channel.execution_requested = true",
            ".request(&encoded)", "response.require_request(&request)?",
            "channel.peer.check_peer_lifetime()?", "require_clock(started_at, current)?",
            "self.context.authenticate(current)?", "previous != &original",
            "wire::CommandResult::Uncertain => return Err(Error::CommitUncertain)",
        ):
            with self.subTest(marker=marker):
                self.rejects(MAIN, "fn exchange(", marker)
        # The async future owns this private Drop fence through the blocking
        # await; a queued task must inspect the same flag before sending Execute.
        for marker in (
            "let queued_execute_fence = QueuedExecuteFence {",
            "abandoned: Arc::clone(&abandoned)",
            "if action == wire::Action::Execute && abandoned.load(Ordering::Acquire)",
            "drop(queued_execute_fence)",
        ):
            with self.subTest(queued_cancel=marker):
                self.rejects(MAIN, "fn exchange(", marker)
        self.rejects(MAIN, "fn drop(", "self.abandoned.store(")
        self.rejects(MAIN, "fn drop(", "true, Ordering::Release",
                     "false, Ordering::Release")
        self.rejects(MAIN, "fn receipt_attestation(",
                     "OriginalCircuitSelectionCommandClientV1::readback(self).await?")

    def test_command_and_readback_keep_actual_owner_and_original_transport_bounds(self):
        self.rejects(SERVICE, "fn original_response(",
                     "OriginalCircuitSelectionReceiptOwnerV1::attest_original_remote_selection(")
        self.rejects(SERVICE, "fn original_response(",
                     "OriginalCircuitSelectionReceiptOwnerV1::readback_remote(")
        self.rejects(SERVICE, "fn serve_commands(", "tokio::task::spawn_blocking(")
        self.rejects(SERVICE, "fn serve_evidence_readback(",
                     "timeout > Duration::from_millis(500)")
        self.rejects(EVIDENCE, "fn evidence_response(",
                     "OriginalCircuitSelectionReceiptOwnerV1::readback_remote(")
        self.rejects(EVIDENCE, "fn evidence_response(",
                     "wire::authenticate_receipt(&self.context, receipt, signed, now()?)?")
        self.rejects(EVIDENCE, "fn evidence_response(",
                     "request.receipt_digest != original.attestation.payload_digest.to_string()")

    def test_response_verifies_exact_extension_baseline_and_independent_original_roles(self):
        for function, marker in (
            ("fn require_request(", "self.action != request.action"),
            ("fn decode_completed(", "snapshot.len() > 10_924"),
            ("fn decode_completed(", "STANDARD_NO_PAD.encode(&bytes) != snapshot"),
            ("fn authenticate_completed(", "snapshot.receipts[..context.training.receipts.len()] != context.training.receipts"),
            ("fn authenticate_receipt(", "*candidate_bundle == baseline"),
            ("fn authenticate_receipt(", "receipt.predecessor != context.training.head_digest"),
            ("fn authenticate_receipt(", "LearningEvidenceRoleV1::Selector"),
            ("fn authenticate_receipt(", "verify_signed_actor_separation(&training, &selector, current)?"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(WIRE, function, marker)

    def test_no_key_writer_callback_or_readback_effect_factory_can_be_added(self):
        for path in (MAIN, WIRE, SERVICE, EVIDENCE):
            source = (ROOT / path).read_text()
            rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
            forbidden = ("SigningKey", ".sign(", "File::open", "UnixStream::connect",
                         ".commit_once(", ".publish(", "with_root_learning_stage_owners(")
            if path == EVIDENCE:
                forbidden += ("attest_original_remote_selection", "Action::Execute")
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / path
                target.parent.mkdir(parents=True)
                for marker in forbidden:
                    with self.subTest(path=path, marker=marker):
                        target.write_text(source + "\n" + marker + "\n")
                        with self.assertRaises(PROOF.VerificationFailure):
                            PROOF._verify_protected_files(root, {"protected_file": rows})


if __name__ == "__main__":
    unittest.main()
