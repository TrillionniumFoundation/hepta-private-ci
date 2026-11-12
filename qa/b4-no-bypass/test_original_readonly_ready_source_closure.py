"""Protect original Ready-only T/S reads and their consumed host capabilities.

These are source/mutation gates. Native deep-owner cases and deployed ordinary
tasks remain distinct evidence, including their real process/UID custody.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_readonly_ready_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
TRAINING = AGENT + "cell_q24_training_command_readback.rs"
SELECTION = AGENT + "circuit_selection_command_readback.rs"
BOOTSTRAP = AGENT + "cell_q24_training_bootstrap_readback.rs"
DISPATCH = AGENT + "learning_iteration_command_evidence.rs"
EXPECTED = {
    'learning_source_bound_training_stage_readback': ('codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_model_command_lane.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs'),
    'learning_original_owner_command_channel': ("codex-rs/hepta-agentd/src/cell_q24_training_command.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command_service.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_capability.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_selection_command.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_candidate_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_candidate.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_transport.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_command.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_service.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_service.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_service.rs", "codex-rs/hepta-agentd/src/artifact_original_head_client.rs", "codex-rs/hepta-agentd/src/artifact_original_head_service.rs", "codex-rs/hepta-agentd/src/artifact_original_registry_source.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_capability.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_completion_readiness_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_service.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_command.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_command_service.rs", "codex-rs/hepta-agentd/src/circuit_model_version_service.rs",),
    'learning_original_circuit_selection_remote_readback': ('codex-rs/hepta-agentd/src/circuit_selection_command_service.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_evidence.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs'),
    'learning_original_selector_command_context': ('codex-rs/hepta-agentd/src/circuit_selection_command_stage_binding.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs'),
    'learning_original_selector_command_owner_factory': ('codex-rs/hepta-agentd/src/circuit_selection_receipt_owner.rs', 'codex-rs/hepta-agentd/src/circuit_selection_readback_host.rs'),
    'learning_original_material_initial_context_check': ("codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_auth.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_context.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_host.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_service.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_host.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_context.rs", "codex-rs/hepta-agentd/src/circuit_model_version_host.rs",),
    'learning_original_material_dataset_context_check': ("codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/cell_q24_training_candidate_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_stage_binding.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_stage_binding.rs", "codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_context.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_completion_readiness.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_stage_binding.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material.rs",),
    'learning_original_next_use_command_owner_factory': ('codex-rs/hepta-agentd/src/circuit_next_use_receipt_owner.rs', 'codex-rs/hepta-agentd/src/circuit_next_use_readback_host.rs'),
    'learning_original_training_readonly_initial': (),
    'learning_original_training_readonly_bind': ('codex-rs/hepta-agentd/src/circuit_selection_readback_host.rs', 'codex-rs/hepta-agentd/src/circuit_next_use_readback_host.rs'),
    'learning_original_training_readonly_first_ready': (),
    'learning_original_training_readonly_backend': ('codex-rs/hepta-agentd/src/learning_iteration_command_evidence.rs',),
    'learning_original_selection_readonly_initial': (),
    'learning_original_selection_readonly_bind': ('codex-rs/hepta-agentd/src/circuit_next_use_readback_host.rs',),
    'learning_original_selection_readonly_first_ready': (),
    'learning_original_selection_readonly_backend': ('codex-rs/hepta-agentd/src/learning_iteration_command_evidence.rs',),
    'learning_original_training_readonly_serve': (),
    'learning_original_training_readonly_response': ('codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_readback.rs',),
    'learning_original_training_bootstrap_readonly_serve': (),
    'learning_original_selection_readonly_serve': (),
    'learning_original_selector_readonly_host': (),
    'learning_original_observer_readonly_host': (),
}
FUNCTIONS = {
    TRAINING: {
        "from_original_stream", "bind_original_training", "read_original_training",
        "bind_completed", "readback", "binding", "request", "require_request",
    },
    SELECTION: {
        "from_original_stream", "bind_original_selection", "read_original_selection",
        "bind_completed", "readback", "context_binding", "request", "require_request",
    },
    AGENT + "cell_q24_training_command_readback_service.rs": {
        "serve_original_training_readback", "serve_original_training_readback_channel",
        "original_training_readback_response",
    },
    BOOTSTRAP: {
        "serve_original_training_readback", "serve_original_training_readback_channel",
        "original_training_readback_response",
    },
    AGENT + "circuit_selection_command_readback_service.rs": {
        "serve_original_selection_readback", "serve_original_selection_readback_channel",
        "original_selection_readback_response",
    },
    AGENT + "circuit_selection_readback_host.rs": {"into_command_owner_from_original_readbacks"},
    AGENT + "circuit_next_use_readback_host.rs": {"into_command_owner_from_original_readbacks"},
    DISPATCH: {"read_original_command"},
}


class OriginalReadonlyReadySourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def rows(self, path):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        # One path can carry independent complete records; verify every one.
        self.assertTrue(rows, path)
        return rows

    def verifies(self, path, source):
        if path in (TRAINING, SELECTION):
            # Locate the real constant in masked Rust. A string or comment
            # containing a preferred operation cannot substitute for its value.
            code = self.code(source)
            matches = list(re.finditer(r"\bconst OPERATION\s*:", code))
            self.assertEqual(len(matches), 1)
            actual = re.match(
                r'const OPERATION\s*:\s*&str\s*=\s*"([^"\\]*)"\s*;',
                source[matches[0].start():],
            )
            self.assertIsNotNone(actual)
            operation = ("runtime.learning.original-q24-training.readback.v1"
                         if path == TRAINING else
                         "runtime.learning.original-circuit-selection.readback.v1")
            self.assertEqual(actual.group(1), operation)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": self.rows(path)})

    def rejects(self, path, function, marker, replacement="", *, at=None):
        source = (ROOT / path).read_text()
        code = self.code(source)
        start = code.index("fn " + function + "(")
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1) if at is None else at
        self.assertEqual(source[offset:offset + len(marker)], marker)
        self.verifies(path, source)
        with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
            self.verifies(path, source[:offset] + replacement + source[offset + len(marker):])

    def test_only_actual_readonly_backends_and_consuming_hosts_are_registered(self):
        paths = set(FUNCTIONS)
        paths.update(path for identifier in EXPECTED for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        ))
        sources = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, callers in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                receiver = f"owner: &{row.receiver_type}" if row.receiver_type else ""
                method = row.symbol.rsplit("::", 1)[-1]
                call = f"owner.{method}()" if row.receiver_type else f"{method}()"
                extra = dict(sources)
                extra[AGENT + "unexpected_readonly_authority.rs"] = f"fn bypass({receiver}) {{ {call}; }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), sources, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_every_initial_peer_actual_read_and_final_signature_guard_remains_in_order(self):
        for path, expected in FUNCTIONS.items():
            rows = self.rows(path)[0]["required_function_order"]
            self.assertEqual({row["function"][3:-1] for row in rows}, expected)
            code = self.code((ROOT / path).read_text())
            for row in rows:
                cursor = code.index(row["function"]) + len(row["function"])
                for marker in row["sequence"]:
                    offset = code.index(marker, cursor)
                    cursor = offset + len(marker)
                    with self.subTest(path=path, function=row["function"], marker=marker):
                        self.rejects(path, row["function"][3:-1], marker, at=offset)

    def test_first_actual_response_cannot_restart_sequence_or_initial_deadline(self):
        for path in (TRAINING, SELECTION):
            self.rejects(path, "bind_completed", "ReadbackOrigin::ReadFromOriginal => 2",
                         "ReadbackOrigin::ReadFromOriginal => 1")
            self.rejects(path, "from_original_stream", "channel.check_peer_lifetime()?",
                         "if false { channel.check_peer_lifetime()?; }")
            self.rejects(path, "read_original_training" if path == TRAINING else "read_original_selection",
                         "original.peer.check_peer_lifetime()?",
                         "if false { original.peer.check_peer_lifetime()?; }")
            source = (ROOT / path).read_text()
            operation = ("runtime.learning.original-q24-training.readback.v1"
                         if path == TRAINING else
                         "runtime.learning.original-circuit-selection.readback.v1")
            changed = source.replace(operation, operation.replace("readback", "command"), 1)
            changed += "\n// " + operation + "\n"
            with self.assertRaises(AssertionError):
                self.verifies(path, changed)

    def test_unknown_read_and_changed_complete_signature_permanently_consume_channel(self):
        for path, receipt in ((TRAINING, "training"), (SELECTION, "selection")):
            self.rejects(path, "readback", "self.peer.take().ok_or(Error::Unavailable)?")
            self.rejects(path, "readback", f"if completed != self.{receipt}",
                         f"if completed == self.{receipt}")
            self.rejects(path, "readback", "wire::CommandResult::Missing | wire::CommandResult::Pending")
        self.rejects(DISPATCH, "read_original_command", ".take()")
        self.rejects(DISPATCH, "read_original_command", ".verify(role, &signature, payload, current)")
        self.rejects(DISPATCH, "read_original_command",
                     "*slot.try_lock().map_err(|_| unavailable())? = Some(original);")

    def test_readonly_paths_cannot_acquire_writer_key_bootstrap_or_command_purpose(self):
        for path in FUNCTIONS:
            source = (ROOT / path).read_text()
            for forbidden in self.rows(path)[0]["forbidden"]:
                with self.subTest(path=path, forbidden=forbidden):
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verifies(path, source + "\n" + forbidden + "\n")
        for marker in ("let result = match self.ready()?", "None => wire::CommandResult::ReadbackRequired"):
            self.rejects(BOOTSTRAP, "original_training_readback_response", marker)

    def test_evidence_dispatch_checks_original_scope_and_receipt_before_command_backend(self):
        path = AGENT + "learning_iteration_evidence_client.rs"
        for marker in (
            "snapshot.request != self.initial.request", "receipt.actor_id != self.actor_id",
            "LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?",
            "learning_iteration_receipt_signing_bytes_v1(receipt)?",
            "if let Some(command) = &self.command",
            ".read_original_command(command, receipt, &payload, role)",
        ):
            with self.subTest(marker=marker):
                self.rejects(path, "readback", marker)


if __name__ == "__main__":
    unittest.main()
