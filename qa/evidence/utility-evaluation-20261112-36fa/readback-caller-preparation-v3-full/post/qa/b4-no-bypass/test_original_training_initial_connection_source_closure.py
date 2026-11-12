"""Keep the initial Trainer descriptor and actual Material origin inseparable.

Mutation gates protect the production handoff. Native cases separately use
actual Material and Trainer owners; same-UID fixtures do not deploy role hosts.
"""

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_training_connection_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CONNECTION = AGENT + "cell_q24_training_command_connection.rs"
MATERIAL = AGENT + "cell_q24_material_command.rs"
HELPER = AGENT + "cell_q24_material_dataset_readback.rs"
WIRE = AGENT + "cell_q24_material_command_wire.rs"
SERVICE = AGENT + "cell_q24_material_command_service.rs"
EXPECTED = {
    "learning_original_training_initial_connection_create": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_training_initial_connection_recover": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_training_initial_connection_dataset": ('codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_state.rs'),
    "learning_original_material_initial_context_check": ("codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_auth.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_context.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_host.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_service.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_host.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", 'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs',),
    "learning_original_material_dataset_context_check": ("codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_training_candidate_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_stage_binding.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_stage_binding.rs", "codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_context.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", 'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs',),
    "learning_original_owner_command_channel": ("codex-rs/hepta-agentd/src/cell_q24_training_command.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command_service.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_capability.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_selection_command.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_candidate_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_candidate.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_transport.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_command.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_service.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_service.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_readback.rs", 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_readback_owner.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs', 'codex-rs/hepta-agentd/src/artifact_original_head_client.rs', 'codex-rs/hepta-agentd/src/artifact_original_head_service.rs', 'codex-rs/hepta-agentd/src/artifact_original_registry_source.rs',),
}


class OriginalTrainingConnectionClosureTests(unittest.TestCase):
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

    def test_only_concrete_initial_handoff_checks_open(self):
        paths = {path for identifier in EXPECTED for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                receiver = f"owner: &{row.receiver_type}" if row.receiver_type else ""
                call = f"owner.{method}()" if row.receiver_type else f"{method}()"
                extra = dict(sources)
                extra[AGENT + "unregistered_initial_trainer.rs"] = f"fn extra({receiver}) {{ {call}; }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_initial_handoff_binds_original_actor_peer_full_context_and_clock(self):
        for marker in (
            "peer.actor_id != material.initial.owners.trainer",
            "original_owner_command_channel_v1(",
            "original_owner_pidfd,",
            ".check_peer_lifetime()",
            "current_binding != initial_binding || fresh_now < started_at",
        ):
            with self.subTest(marker=marker):
                self.rejects(CONNECTION, "fn bind_original_stream(", marker)
        self.rejects(HELPER, "fn require_original_command_initial(", "wire::context_binding(self, at)?")
        self.rejects(CONNECTION, "fn from_original_stream(", "Origin::Fresh")
        self.rejects(CONNECTION, "fn recover_from_original_stream(", "Origin::Recovered(expected)", "Origin::Fresh")

    def require_one_initial_transport(self, source):
        code = self.code(source)
        if len(re.findall(r"\boriginal_owner_command_channel_v1\s*\(", code)) != 1:
            raise PROOF.VerificationFailure("one original initial transport only")
        start = code.index("fn bind_original_dataset(")
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        if re.search(r"\b(?:original_owner_command_channel_v1|timeout|lifetime)\b", code[start:end + 1]):
            raise PROOF.VerificationFailure("actual Dataset cannot start another transport or deadline")

    def test_actual_dataset_moves_the_same_transport_after_final_peer_io_and_authentication(self):
        source = (ROOT / CONNECTION).read_text()
        self.verifies(CONNECTION, source)
        self.require_one_initial_transport(source)
        for marker in (
            "context.validate()? != self.material.initial",
            ".check_peer_lifetime()",
            "OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(",
            "original_binding != self.initial_binding",
            "fresh_now < started_at",
            "verified_at < fresh_now",
            "peer: self.peer",
        ):
            self.rejects(CONNECTION, "fn bind_original_dataset(", marker)
        for call in ("original_owner_command_channel_v1();", "original_owner_command_channel_v1 /* extra */ ();"):
            changed = source.replace("let binding = context.binding()?;", call + "\n        let binding = context.binding()?;", 1)
            with self.assertRaises(PROOF.VerificationFailure):
                self.require_one_initial_transport(changed)

    def test_opaque_material_keeps_original_freeze_binding_and_full_signatures(self):
        self.rejects(HELPER, "fn require_original_dataset_context(", "self.original_context != binding")
        self.rejects(HELPER, "fn require_original_dataset_context(", "wire::authenticate_cut(expected, Role::Dataset, self.clone(), at)?")
        self.rejects(WIRE, "fn authenticate_cut(", "completed.original_context != expected_context")
        for marker in (
            "receipt.observed_unix_seconds != signed.issued_at",
            "signed.expires_at != expires_at",
            "LearningEvidenceRoleV1::Observer",
            "verified.principal() != &signer.principal",
        ):
            self.rejects(WIRE, "fn authenticate_cut(", marker)
        self.rejects(WIRE, "fn decode_completed(", "original_context: context_binding(config, at)?")
        self.rejects(SERVICE, "fn original_cut(", "original_context: self.binding")
        for function in ("fn recover_original_experience_stream(", "fn recover_original_dataset_stream("):
            self.rejects(MATERIAL, function, "original_context,")
        source = (ROOT / MATERIAL).read_text()
        for replacement in ("pub original_context: Digest32", "original_context: Digest32"):
            changed = source.replace("original_context: Digest32", replacement, 1)
            if replacement.startswith("pub"):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(MATERIAL, changed)
            else:
                changed = changed.replace("#[derive(Clone, Debug, Eq, PartialEq)]", "#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize)]", 1)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(MATERIAL, changed)

    def test_recovered_connection_cannot_rearm_or_renew_retained_training_evidence(self):
        for marker in (
            "Origin::Fresh => (false, None)",
            "Origin::Recovered(expected) => (",
            "wire::authenticate_receipt(",
            ".map(|(receipt, attestation)|",
            "receipt,",
            "attestation,",
            "verified_at)",
            ".transpose()?",
            "retained: Mutex::new(retained)",
        ):
            with self.subTest(marker=marker):
                self.rejects(CONNECTION, "fn bind_original_dataset(", marker)
        self.rejects(CONNECTION, "fn recover_from_original_stream(", "expected: Option<(LearningIterationReceiptV1, SignedLearningEvidenceV1)>", "expected: Option<OriginalCellQ24TrainingCommandReceiptV1>")
        source = (ROOT / CONNECTION).read_text()
        changed = source.replace("origin: Origin,", "pub origin: Origin,", 1)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(CONNECTION, changed)

    def test_late_binding_accepts_only_the_sealed_original_material_cut(self):
        self.rejects(CONNECTION, "fn bind_original_dataset(", "completed: OriginalCellQ24MaterialCommandReceiptV1", "completed: LearningIterationSnapshotV1")
        source = (ROOT / CONNECTION).read_text()
        for declaration in (
            "impl Clone for OriginalCellQ24TrainingCommandConnectionV1 {}",
            "fn bypass() { HostAuthorityPeerChannel::from_stream(); }",
            "fn bypass() { UnixStream::connect(); }",
            "fn bypass() { serde_json::from_slice(); }",
        ):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(CONNECTION, source + "\n" + declaration)


if __name__ == "__main__":
    unittest.main()
