"""Keep purpose-specific Trainer serving on the original captured owner.

Source mutation gates do not prove a deployed role host. Separate native tests
exercise actual Source, Ledger, native/Generator journals and lost replies.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_training_command_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
MAIN = AGENT + "cell_q24_training_command.rs"
SERVICE = AGENT + "cell_q24_training_command_service.rs"
WIRE = AGENT + "cell_q24_training_command_wire.rs"
CHANNEL = AGENT + "learning_owner_command_channel.rs"
BOUND = AGENT + "cell_q24_source_bound_stage.rs"
CODEC = AGENT + "learning_iteration_checkpoint.rs"
EXPECTED = {
    "learning_original_training_command_client_create": (),
    "learning_original_training_command_client_recover": (),
    "learning_original_training_command_client_execute": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs",),
    "learning_original_training_command_client_readback": ('codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs', 'codex-rs/hepta-agentd/src/circuit_learning_retained_context.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_state.rs'),
    "learning_original_training_command_client_attestation": (),
    "learning_original_training_command_owner_create": (AGENT + "cell_q24_training_bootstrap_build.rs",),
    "learning_original_training_command_owner_recover": (AGENT + "cell_q24_training_bootstrap_build.rs",),
    "learning_original_training_command_owner_serve": (),
    "learning_original_training_command_owner_evidence": (AGENT + "cell_q24_training_bootstrap_service.rs",),
    "learning_source_bound_training_command_context": ("codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs",),
    "learning_original_owner_command_channel": ('codex-rs/hepta-agentd/src/cell_q24_training_command.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_material_command.rs', 'codex-rs/hepta-agentd/src/cell_q24_material_command_service.rs', 'codex-rs/hepta-agentd/src/circuit_learning_read_capability.rs', 'codex-rs/hepta-agentd/src/circuit_learning_read_service.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs', 'codex-rs/hepta-agentd/src/circuit_next_use_command.rs', 'codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_candidate_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_candidate.rs', 'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs', 'codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs', 'codex-rs/hepta-agentd/src/authority_host_learning_resident_transport.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_command.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_service.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs', 'codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_service.rs', 'codex-rs/hepta-agentd/src/artifact_original_head_client.rs', 'codex-rs/hepta-agentd/src/artifact_original_head_service.rs', 'codex-rs/hepta-agentd/src/artifact_original_registry_source.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_readback.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs'),
    "learning_original_owner_snapshot_encode": ("codex-rs/hepta-agentd/src/cell_q24_training_command_wire.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_wire.rs", "codex-rs/hepta-agentd/src/circuit_selection_command.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_wire.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_profile.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_store.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_wire.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_contract.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_wire.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_context.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_model.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_export.rs",),
    "learning_original_owner_snapshot_decode": ("codex-rs/hepta-agentd/src/cell_q24_training_command_wire.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_wire.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_wire.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_store.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_wire.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_wire.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_verify.rs",),
}


class OriginalTrainingCommandClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_only_concrete_internal_edges_open_host_factories_stay_closed(self):
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
                extra[AGENT + "unregistered_training_command.rs"] = f"fn unexpected({receiver}) {{ {call}; }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertEqual(self.boundaries["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_external_original_process_and_existing_transport_limits_remain_required(self):
        for marker in ("if same_uid", "peer.pid == std::process::id()", "peer.process_start_ticks == 0",
                       "timeout > Duration::from_secs(30)", "lifetime > Duration::from_secs(300)",
                       "        original_peer_pidfd,", "require_original_process(&peer)?",
                       "channel.check_peer_lifetime()?"):
            with self.subTest(marker=marker):
                self.rejects(CHANNEL, "fn original_owner_command_channel_v1(", marker)
        self.rejects(CHANNEL, "fn bounded_text(", ".take(limit + 1)")
        self.rejects(SERVICE, "fn serve_evidence_readback(", "timeout > Duration::from_millis(500)")

    def test_client_consumes_once_and_pins_complete_original_response(self):
        for marker in ("slot.take().ok_or(Error::Unavailable)?", "channel.execution_requested = true",
                       "request_id.checked_add(1)", "if cancellation",
                       ".is_some_and(|flag| flag.load(Ordering::Acquire))",
                       "return Err(Error::Cancelled)", ".request(&encoded)",
                       "response.require_request(&request)?", "if fresh_now < started_at",
                       "original != &completed", "channel.peer.check_peer_lifetime()?"):
            with self.subTest(marker=marker):
                self.rejects(MAIN, "fn exchange(", marker)
        self.rejects(MAIN, "fn execute_training(", "Some(cancellation)")
        self.rejects(MAIN, "fn receipt_attestation(", "OriginalCellQ24TrainingCommandClientV1::readback(self).await?")

    def test_original_captured_stage_is_required_before_any_command(self):
        self.rejects(SERVICE, "fn bind_original_stage(", "SourceBoundCellQ24TrainingStageV1::require_original_command_context(")
        self.rejects(BOUND, "fn require_original_command_context(", "self.original.require_dataset(dataset)?")
        self.rejects(BOUND, "fn require_original_command_context(", ".in_lane(move |owners|")
        self.rejects(BOUND, "fn require_original_command_context(", "if owners.receipts.config.scope != scope")

    def test_command_calls_actual_execution_and_actual_readback_without_replay(self):
        for marker in ("request.require_context(&self.context, self.binding, next_request_id)?",
                       "self.execution_requested.swap(true, Ordering::AcqRel)",
                       "SourceBoundCellQ24TrainingStageV1::execute_training(",
                       "SourceBoundCellQ24TrainingStageV1::readback("):
            with self.subTest(marker=marker):
                self.rejects(SERVICE, "fn command_response(", marker)
        self.rejects(SERVICE, "fn original_state(", "_ => wire::CommandResult::Uncertain")
        self.rejects(SERVICE, "fn serve_command_channel(", "for count in 0..128_u64")

    def test_recovery_preserves_same_job_and_original_validity_window(self):
        self.rejects(SERVICE, "fn recover_original_stage(", "Admission::ReadbackOnly")
        self.rejects(MAIN, "fn recover_from_original_stream(", "wire::authenticate_receipt(&context, receipt, attestation, now()?)")
        self.rejects(WIRE, "fn authenticate_receipt(", "receipt.observed_unix_seconds != attestation.issued_at")
        self.rejects(WIRE, "fn authenticate_receipt(", "context.verifier.verify(")

    def test_completed_wire_is_bounded_canonical_exact_dataset_extension(self):
        self.rejects(WIRE, "fn decode_completed(", "snapshot.len() > 10_924")
        self.rejects(WIRE, "fn decode_completed(", "STANDARD_NO_PAD.encode(&bytes) != snapshot")
        self.rejects(WIRE, "fn require_exact_extension(", "completed.receipts[..context.dataset.receipts.len()] != context.dataset.receipts")
        self.rejects(CODEC, "fn decode_original_owner_snapshot_v1(", "if codec::encode(&snapshot)? != bytes")
        self.rejects(WIRE, "fn require_request(", "self.request_id != request.request_id")

    def test_existing_evidence_protocol_reads_real_original_stage_each_time(self):
        for marker in ("request.operation != evidence_wire::OPERATION",
                       "request.binding != self.initial_head.to_string()",
                       "request.predecessor != self.context.dataset.head_digest.to_string()",
                       "SourceBoundCellQ24TrainingStageV1::readback(",
                       "wire::authenticate_receipt(",
                       "request.receipt_digest != original.attestation.payload_digest.to_string()",
                       "evidence_wire::Evidence::from_original(&original.attestation)"):
            with self.subTest(marker=marker):
                self.rejects(SERVICE, "fn evidence_response(", marker)

    def test_peer_liveness_io_precedes_final_signature_clock(self):
        source = (ROOT / MAIN).read_text()
        start = source.index("async fn exchange(")
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        body = source[start:end + 1]
        peer = "        channel.peer.check_peer_lifetime()?;\n"
        clock = "        let fresh_now = now()?;\n"
        self.assertEqual(body.count(peer), 1)
        self.assertEqual(body.count(clock), 1)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == MAIN]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / MAIN
            target.parent.mkdir(parents=True)
            target.write_text(source)
            data = {"protected_file": rows}
            PROOF._verify_protected_files(root, data)
            # Keeping both checks but moving pidfd I/O after the clock must fail.
            late = body.replace(peer, "", 1).replace(clock, clock + peer, 1)
            target.write_text(source[:start] + late + source[end + 1:])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, data)


if __name__ == "__main__":
    unittest.main()
