"""Protect the original Trainer's fixed read-only purpose and exact callers.

These source mutations exercise the existing caller verifier. They do not
establish a deployed independent role or successful ordinary learning loop.
Native readback tests separately own the real journals and same-process fixture.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_training_readback_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CLIENT = AGENT + "cell_q24_training_command_readback.rs"
SERVICE = AGENT + "cell_q24_training_command_readback_service.rs"
BOOTSTRAP = AGENT + "cell_q24_training_bootstrap_readback.rs"
EXPECTED = {'learning_source_bound_training_stage_readback': ['codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs',
                                                   'codex-rs/hepta-agentd/src/cell_q24_model_command_lane.rs',
                                                   'codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs'],
 'learning_original_owner_command_channel': ['codex-rs/hepta-agentd/src/cell_q24_training_command.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_material_command.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_material_command_service.rs',
                                             'codex-rs/hepta-agentd/src/circuit_learning_read_capability.rs',
                                             'codex-rs/hepta-agentd/src/circuit_learning_read_service.rs',
                                             'codex-rs/hepta-agentd/src/circuit_selection_command.rs',
                                             'codex-rs/hepta-agentd/src/circuit_selection_command_service.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_service.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs',
                                             'codex-rs/hepta-agentd/src/circuit_next_use_command.rs',
                                             'codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_training_candidate_service.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_candidate.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs',
                                             'codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs',
                                             'codex-rs/hepta-agentd/src/authority_host_learning_resident_transport.rs',
                                             'codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_command.rs',
                                             'codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_service.rs',
                                             'codex-rs/hepta-agentd/src/circuit_retained_version_service.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs',
                                             'codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection.rs',
                                             'codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_service.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs',
                                             'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_readback.rs'],
 'learning_original_material_initial_context_check': ['codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_auth.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_retained_version_context.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_retained_version_host.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_retained_version_service.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_model_command_host.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs'],
 'learning_original_material_dataset_context_check': ['codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_training_candidate_readback.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_selection_command_stage_binding.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_next_use_command_stage_binding.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_retained_version_context.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs']}
ADMITTED = {
    "learning_source_bound_training_stage_readback": (SERVICE,),
    "learning_original_owner_command_channel": (CLIENT, SERVICE, BOOTSTRAP),
    "learning_original_material_initial_context_check": (CLIENT,),
    "learning_original_material_dataset_context_check": (CLIENT,),
}


class OriginalTrainingReadbackClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def assert_protected_rejects(self, path, changed):
        source = (ROOT / path).read_text()
        self.assertNotEqual(source, changed)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def mutate(self, path, function, marker, replacement=""):
        source = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(source)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        body = source[start:end + 1]
        self.assertEqual(body.count(marker), 1, (path, function, marker))
        changed = body.replace(marker, replacement, 1)
        self.assert_protected_rejects(path, source[:start] + changed + source[end + 1:])

    def test_exact_read_only_edges_do_not_admit_another_typed_or_qualified_caller(self):
        paths = {
            path for identifier in EXPECTED
            for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
                (ROOT / path).read_text()
            )) for path in paths
        }
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, tuple(expected))
                self.assertIn(
                    identifier, self.manifest["privileged_inventory"]["required_boundary_ids"]
                )
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                if row.receiver_type:
                    attempts = (
                        f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}",
                        f"fn bypass(owner: &{row.receiver_type}) {{ "
                        f"{row.receiver_type}::{method}(owner); }}",
                    )
                else:
                    attempts = (f"fn bypass() {{ {row.symbol}(); }}",)
                for attempt in attempts:
                    extra = dict(sources)
                    extra[AGENT + "unregistered_training_readback_consumer.rs"] = attempt
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, row, extra, ())
                for admitted in ADMITTED[identifier]:
                    # The real adapter must remain visible to the original proof.
                    extra = dict(sources)
                    extra.pop(admitted)
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "missing"):
                        PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertEqual(
            self.boundaries["root_learning_original_stage_assembly"].product_callers, ()
        )
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_original_handoff_and_complete_dataset_training_binding_cannot_be_detached(self):
        checks = {
            "fn from_original_stream(": (
                "OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)",
                "peer.actor_id != material.initial.owners.trainer",
                "original_owner_pidfd,",
                "channel.check_peer_lifetime()?;",
                "current < started_at || after != initial_binding",
            ),
            "fn bind_original_training(": (
                "self,",
                "context.validate()? != self.material.initial",
                "self.peer.check_peer_lifetime()?;",
                "OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(",
                "current < started_at || verified_at < current || original != self.initial_binding",
                "wire::authenticate_receipt(",
                "if verified != training",
                "peer: Some(self.peer)",
                "channel: Mutex::new(None)",
            ),
        }
        for function, markers in checks.items():
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    # The initial function deliberately checks the same original
                    # context twice; deleting only its first call must still fail.
                    if function == "fn from_original_stream(" and marker.startswith(
                        "OriginalCellQ24MaterialReceiptConfigV1::"
                    ):
                        source = (ROOT / CLIENT).read_text()
                        self.assert_protected_rejects(CLIENT, source.replace(marker, "", 1))
                    else:
                        self.mutate(CLIENT, function, marker)

    def test_request_cannot_change_purpose_context_sequence_or_action(self):
        markers = (
            "observed.schema != expected.schema",
            "observed.operation != OPERATION",
            "observed.request_id != request_id",
            "!(1..=128).contains(&request_id)",
            "observed.binding != expected.binding",
            "observed.operation_id != expected.operation_id",
            "observed.dataset_head != expected.dataset_head",
            "observed.scope_binding != expected.scope_binding",
            "observed.actor_id != expected.actor_id",
            "observed.action != wire::Action::Readback",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                changed = marker.replace("!=", "==") if "!=" in marker else marker[1:]
                self.mutate(CLIENT, "fn require_request(", marker, changed)
        self.mutate(CLIENT, "fn require_request(", "|| observed.cancelled")
        self.mutate(
            CLIENT, "fn request(", "wire::Action::Readback", "wire::Action::Execute"
        )

    def test_host_admission_precedes_queue_and_connections_keep_bounded_requests(self):
        for path in (SERVICE, BOOTSTRAP):
            for marker in (".try_acquire_owned()", "original_consumer_pidfd,"):
                with self.subTest(path=path, marker=marker):
                    self.mutate(path, "fn serve_original_training_readback(", marker)
            self.mutate(
                path, "fn serve_original_training_readback_channel(",
                "1..=128_u64", "1..=129_u64",
            )
            source = (ROOT / path).read_text()
            start = source.index("        let mut channel = original_owner_command_channel_v1(")
            queued = source.index("        tokio::task::spawn_blocking(move || {", start)
            admission = source[start:queued]
            changed = source[:start] + source[queued:]
            changed = changed.replace(
                "            let _permit = permit;\n",
                "            let _permit = permit;\n" + admission,
                1,
            )
            self.assert_protected_rejects(path, changed)

    def test_host_request_is_checked_before_actual_same_stage_readback(self):
        guard = "        readonly::require_request(&request, &self.context, request_id)?;\n"
        source = (ROOT / SERVICE).read_text()
        self.assertEqual(source.count(guard), 1)
        self.assert_protected_rejects(SERVICE, source.replace(guard, "", 1))
        self.assert_protected_rejects(
            SERVICE, source.replace(guard, "        // " + guard.strip() + "\n", 1)
        )
        late = source.replace(guard, "", 1).replace(
            "        let result = self.completed_response(completed)?;\n",
            guard + "        let result = self.completed_response(completed)?;\n",
            1,
        )
        self.assert_protected_rejects(SERVICE, late)
        self.mutate(
            SERVICE, "fn original_training_readback_response(",
            "&self.context.dataset,", "&other_dataset,",
        )

    def test_readback_requires_current_complete_original_evidence_before_restoring_peer(self):
        markers = (
            "self.peer.take().ok_or(Error::Unavailable)?",
            "expected != self.training.receipt() || !(1..=128).contains(&self.next_request_id)",
            "response.require_request(&request)?;",
            "peer.check_peer_lifetime()?;",
            "OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(",
            "if current < started_at",
            "wire::decode_completed(&self.context, snapshot, evidence, current)?",
            "if completed != self.training",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                self.mutate(CLIENT, "fn readback(", marker)
        source = (ROOT / CLIENT).read_text()
        restore = "        self.peer = Some(peer);\n"
        self.assertEqual(source.count(restore), 1)
        early = source.replace(restore, "", 1).replace(
            "        let response: wire::Response = serde_json::from_slice(&bytes)?;\n",
            restore + "        let response: wire::Response = serde_json::from_slice(&bytes)?;\n",
            1,
        )
        self.assert_protected_rejects(CLIENT, early)

    def test_completed_training_cannot_become_missing_pending_or_a_reusable_unknown(self):
        for replacement in (
            "return Err(Error::Missing);",
            "return Err(Error::Pending);",
            "self.peer = Some(peer); return Err(Error::CommitUncertain);",
        ):
            with self.subTest(replacement=replacement):
                self.mutate(
                    CLIENT, "fn readback(", "return Err(Error::CommitUncertain);", replacement
                )

    def test_bootstrap_readback_only_borrows_ready_and_never_recovers_awaiting(self):
        for marker in (
            "request.operation != readonly::OPERATION",
            "request.action != wire::Action::Readback",
            "request.cancelled",
            "request.request_id != request_id",
            "!(1..=128).contains(&request_id)",
            "request.operation_id != initial.request.operation_id.as_str()",
            "request.actor_id != initial.owners.trainer.as_str()",
            "request.scope_binding != self.config.material.scope.binding().to_string()",
            "!canonical(&request.binding)",
            "!canonical(&request.dataset_head)",
        ):
            with self.subTest(marker=marker):
                self.mutate(BOOTSTRAP, "fn original_training_readback_response(", marker)
        self.mutate(
            BOOTSTRAP, "fn original_training_readback_response(",
            "None => wire::CommandResult::ReadbackRequired,",
            "None => wire::CommandResult::Missing,",
        )
        self.mutate(
            BOOTSTRAP, "fn original_training_readback_response(",
            "OriginalCellQ24TrainingCommandOwnerV1::original_training_readback_response(",
            "OriginalCellQ24TrainingCommandOwnerV1::command_response(",
        )

    def test_read_only_adapters_cannot_gain_execution_signing_reconnection_or_bootstrap(self):
        for path in (CLIENT, SERVICE, BOOTSTRAP):
            for inserted in (
                "owner.execute_training();",
                "owner.attest_original_completion();",
                "owner.build_original_owner();",
                "let state = State::Starting;",
                "let socket = UnixStream::connect(path);",
                "let evidence = SignedLearningEvidenceV1 {};",
                "let custody = Host::recover_original_custody();",
            ):
                with self.subTest(path=path, inserted=inserted):
                    source = (ROOT / path).read_text()
                    self.assert_protected_rejects(
                        path, source + "\nfn injected_readback_authority() { " + inserted + " }\n"
                    )


if __name__ == "__main__":
    unittest.main()
