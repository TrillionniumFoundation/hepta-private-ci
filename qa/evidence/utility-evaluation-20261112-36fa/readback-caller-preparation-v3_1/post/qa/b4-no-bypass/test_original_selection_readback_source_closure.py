"""Fence the original Selector's purpose-fixed read-only adapters.

The boundary test enumerates every Rust source through the original collector.
Mutation tests use the original source verifier against exact Rust preimages.
Neither test supplies owner signatures or proves deployed independent A/B/C.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_selection_readback_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CLIENT = AGENT + "circuit_selection_command_readback.rs"
SERVICE = AGENT + "circuit_selection_command_readback_service.rs"
EVALUATED = AGENT + "circuit_evaluated_selection_readback_owner.rs"
EXPECTED = {'learning_original_owner_command_channel': ('codex-rs/hepta-agentd/src/cell_q24_training_command.rs',
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
                                             'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_readback.rs',
                                             'codex-rs/hepta-agentd/src/circuit_evaluated_selection_readback_owner.rs',
                                             'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs',
                                             'codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs', 'codex-rs/hepta-agentd/src/artifact_original_head_client.rs', 'codex-rs/hepta-agentd/src/artifact_original_head_service.rs', 'codex-rs/hepta-agentd/src/artifact_original_registry_source.rs',),
 'learning_original_circuit_selection_remote_readback': ('codex-rs/hepta-agentd/src/circuit_selection_command_service.rs',
                                                         'codex-rs/hepta-agentd/src/circuit_selection_command_evidence.rs',
                                                         'codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs'),
 'learning_original_material_initial_context_check': ('codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_auth.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_retained_version_context.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_retained_version_host.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_retained_version_service.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_model_command_host.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs'),
 'learning_original_material_dataset_context_check': ('codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_training_candidate_readback.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_selection_command_stage_binding.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_next_use_command_stage_binding.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_retained_version_context.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_model_command_context.rs',
                                                      'codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs',
                                                      'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs')}
ADMITTED = {
    "learning_original_owner_command_channel": (EVALUATED, CLIENT, SERVICE),
    "learning_original_material_initial_context_check": (CLIENT,),
    "learning_original_material_dataset_context_check": (CLIENT,),
    "learning_original_circuit_selection_remote_readback": (SERVICE,),
}


class OriginalSelectionReadbackClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def assert_protected_rejects(self, path, changed):
        original = (ROOT / path).read_text()
        self.assertNotEqual(original, changed)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(original)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def mutate(self, path, function, marker, replacement=""):
        original = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(original)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        body = original[start:end + 1]
        self.assertEqual(body.count(marker), 1, (path, function, marker))
        changed = body.replace(marker, replacement, 1)
        self.assert_protected_rejects(path, original[:start] + changed + original[end + 1:])

    def test_exact_readback_edges_use_complete_rust_collection_and_reject_another_caller(self):
        roots = PROOF._string_tuple(self.manifest, "source_roots")
        ignored = PROOF._string_tuple(self.manifest, "ignored_path_fragments")
        PROOF._verify_privileged_inventory(
            self.manifest, tuple(self.boundaries.values())
        )
        # Deliberately collect the entire declared repository Rust surface.
        # A list of expected/admitted paths cannot establish a closed caller set.
        sources = {
            path.relative_to(ROOT).as_posix(): PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code(path.read_text(encoding="utf-8"))
            )
            for path in PROOF._source_files(ROOT, roots)
        }
        fields_cache = {}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, tuple(expected))
                PROOF._verify_boundary(
                    ROOT, row, sources, ignored,
                    fields_by_receiver_type=fields_cache,
                )
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
                    injected = AGENT + "unregistered_selection_readback_consumer.rs"
                    self.assertNotIn(injected, sources)
                    if row.receiver_type:
                        # Only a pure function is appended; it cannot alter the
                        # complete baseline's alias closure or typed fields.
                        self.assertNotRegex(attempt, r"\b(?:struct|type|use|enum|union|impl)\b")
                        added_fields = PROOF.authority_fields({injected: attempt}, row.receiver_type)
                        self.assertFalse(added_fields)
                        self.assertFalse(added_fields.aliases)
                        for name in (row.receiver_type, *fields_cache[row.receiver_type].aliases):
                            self.assertFalse(PROOF.typed_callers._declared_aliases(attempt, name))
                    extra[injected] = attempt
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(
                            ROOT, row, extra, ignored, fields_by_receiver_type=fields_cache
                        )
                for admitted in ADMITTED[identifier]:
                    missing = dict(sources)
                    self.assertIn(admitted, missing)
                    del missing[admitted]
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "missing"):
                        PROOF._verify_boundary(
                            ROOT, row, missing, ignored, fields_by_receiver_type={}
                        )
        self.assertEqual(
            self.boundaries["root_learning_original_stage_assembly"].product_callers, ()
        )
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_original_peer_and_initial_context_are_verified_before_and_after_binding(self):
        checks = (
            "peer.actor_id != material.initial.owners.selector",
            "original_owner_pidfd,",
            "channel.check_peer_lifetime()?;",
            "current < started_at || after != initial_binding",
        )
        for marker in checks:
            with self.subTest(marker=marker):
                if marker.startswith("peer.actor_id"):
                    self.mutate(CLIENT, "fn from_original_stream(", marker, marker.replace("!=", "=="))
                elif marker.startswith("current"):
                    self.mutate(CLIENT, "fn from_original_stream(", marker, "current > started_at || after == initial_binding")
                else:
                    self.mutate(CLIENT, "fn from_original_stream(", marker)
        original = (ROOT / CLIENT).read_text()
        marker = "OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)"
        self.assertEqual(original.count(marker), 2)
        for occurrence in (0, 1):
            start = [i for i in range(len(original)) if original.startswith(marker, i)][occurrence]
            self.assert_protected_rejects(
                CLIENT, original[:start] + "unverified_initial(&material)" + original[start + len(marker):]
            )
        for field in ("peer: HostAuthorityPeerChannel,", "initial_binding: Digest32,"):
            with self.subTest(field=field):
                self.assert_protected_rejects(CLIENT, original.replace(field, "pub " + field, 1))

    def test_opaque_dataset_training_and_selection_cannot_be_detached_or_renewed(self):
        checks = (
            "dataset.snapshot().clone(),",
            "self.material.scope.clone(),",
            "self.material.verifier.clone(),",
            "if context.initial()? != self.material.initial",
            "self.peer.check_peer_lifetime()?;",
            "OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(",
            "OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(",
            "if current < started_at || verified_at < current || original != self.initial_binding",
            "let verified = wire::authenticate_completed(",
            "selection.snapshot.clone(),",
            "selection.attestation.clone(),",
            "if verified != selection || context_binding(&context, verified_at)? != binding",
            "peer: Some(self.peer),",
            "command: Some(Mutex::new(Some(OriginalCommandEvidenceV1::Selection(",
        )
        for marker in checks:
            with self.subTest(marker=marker):
                self.mutate(CLIENT, "fn bind_original_selection(", marker)
        self.mutate(
            CLIENT, "fn bind_original_selection(",
            "if verified != selection || context_binding(&context, verified_at)? != binding",
            "if verified == selection && context_binding(&context, verified_at)? == binding",
        )
        self.mutate(CLIENT, "fn context_binding(", "context.binding(current)?.as_array()")

    def test_wire_purpose_action_sequence_and_original_context_cannot_change(self):
        original = (ROOT / CLIENT).read_text()
        purpose = '"runtime.learning.original-circuit-selection.readback.v1"'
        self.assertEqual(original.count(purpose), 1)
        self.assert_protected_rejects(
            CLIENT, original.replace(purpose, '"runtime.learning.original-circuit-selection.command.v1"', 1)
        )
        self.mutate(CLIENT, "fn request(", "wire::Action::Readback", "wire::Action::Execute")
        self.mutate(CLIENT, "fn request(", "request.operation = OPERATION.into();")
        checks = (
            "observed.schema != expected.schema",
            "observed.operation != OPERATION",
            "observed.request_id != request_id",
            "!(1..=128).contains(&request_id)",
            "observed.binding != expected.binding",
            "observed.operation_id != expected.operation_id",
            "observed.training_head != expected.training_head",
            "observed.scope_binding != expected.scope_binding",
            "observed.actor_id != expected.actor_id",
            "observed.action != wire::Action::Readback",
        )
        for marker in checks:
            with self.subTest(marker=marker):
                replacement = marker.replace("!=", "==") if "!=" in marker else marker.replace("!", "", 1)
                self.mutate(CLIENT, "fn require_request(", marker, replacement)

    def test_service_checks_read_only_request_before_the_same_original_owner(self):
        guard = "readonly::require_request(&request, &self.context, request_id, now()?)?;"
        self.mutate(SERVICE, "fn original_selection_readback_response(", guard)
        original = (ROOT / SERVICE).read_text()
        self.assertEqual(original.count(guard), 1)
        late = original.replace(guard, "", 1).replace(
            "let result = match completed {", guard + "\n        let result = match completed {", 1
        )
        self.assert_protected_rejects(SERVICE, late)
        checks = (
            "let mut owner = self.owner.try_lock().map_err(|_| Error::Busy)?;",
            "let original: &mut OriginalCircuitSelectionReceiptOwnerV1<W> = &mut owner;",
            "snapshot: &self.context.training,",
            "live: &self.live,",
            "trainer: &self.trainer,",
        )
        for marker in checks:
            with self.subTest(marker=marker):
                self.mutate(SERVICE, "fn original_selection_readback_response(", marker)
        self.mutate(
            SERVICE, "fn original_selection_readback_response(",
            "OriginalCircuitSelectionReceiptOwnerV1::readback_remote(",
            "OriginalCircuitSelectionReceiptOwnerV1::attest_original_remote_selection(",
        )

    def test_client_requires_fresh_complete_original_evidence_before_restoring_peer(self):
        checks = (
            "let mut peer = self.peer.take().ok_or(Error::Unavailable)?;",
            "if expected != self.selection.receipt() || !(1..=128).contains(&self.next_request_id)",
            ".checked_add(1)",
            "response.require_request(&request)?;",
            "peer.check_peer_lifetime()?;",
            "OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(",
            "&self.dataset,",
            "&self.material,",
            "if current < started_at || context_binding(&self.context, current)? != self.binding",
            "wire::decode_completed(&self.context, snapshot, evidence, current)?",
            "if completed != self.selection",
        )
        for marker in checks:
            with self.subTest(marker=marker):
                self.mutate(CLIENT, "fn readback(", marker)
        original = (ROOT / CLIENT).read_text()
        restore = "self.peer = Some(peer);"
        self.assertEqual(original.count(restore), 1)
        early = original.replace(restore, "", 1).replace(
            "response.require_request(&request)?;",
            restore + "\n        response.require_request(&request)?;", 1
        )
        self.assert_protected_rejects(CLIENT, early)
        self.mutate(CLIENT, "fn readback(", "if completed != self.selection", "if completed == self.selection")

    def test_missing_pending_and_unknown_are_not_reusable_completed_selection(self):
        checks = (
            "wire::CommandResult::Missing | wire::CommandResult::Pending => {\n                return Err(Error::CommitUncertain);\n            }",
            "wire::CommandResult::Busy => return Err(Error::Busy),",
            "wire::CommandResult::Expired => return Err(Error::DeadlineExceeded),",
            "wire::CommandResult::ReadbackRequired => return Err(Error::ReadbackRequired),",
            "wire::CommandResult::Uncertain => return Err(Error::CommitUncertain),",
            "wire::CommandResult::Unavailable => return Err(Error::Unavailable),",
        )
        for marker in checks:
            with self.subTest(marker=marker):
                self.mutate(CLIENT, "fn readback(", marker)
        self.mutate(
            CLIENT, "fn readback(",
            "return Err(Error::CommitUncertain);",
            "return Ok((self.selection.attestation.clone(), current));",
        )
        self.mutate(
            SERVICE, "fn original_selection_readback_response(",
            "Err(error) => original_state(error),",
            "Err(_) => wire::CommandResult::ReadbackRequired,",
        )

    def test_service_keeps_bounded_original_transport_and_final_authentication(self):
        for marker in (
            ".try_acquire_owned()",
            "original_consumer_pidfd,",
            "let _permit = permit;",
        ):
            with self.subTest(marker=marker):
                self.mutate(SERVICE, "fn serve_original_selection_readback(", marker)
        self.mutate(
            SERVICE, "fn serve_original_selection_readback_channel(",
            "for request_id in 1..=128_u64", "for request_id in 1..=129_u64",
        )
        self.mutate(
            SERVICE, "fn original_selection_readback_response(",
            "self.context.authenticate(now()?)?;",
        )
        original = (ROOT / SERVICE).read_text()
        guard = "self.context.authenticate(now()?)?;"
        earlier = original.replace(guard, "", 1).replace(
            "let completed = {", guard + "\n        let completed = {", 1
        )
        self.assert_protected_rejects(SERVICE, earlier)

    def test_read_only_adapters_cannot_gain_signing_execution_reconnection_or_new_owner(self):
        forbidden = (
            "SigningKey", "SignedLearningEvidenceV1 {", "File::open",
            "UnixStream::connect", "HostAuthorityPeerChannel::from_stream",
            "attest_original_remote_selection(", "execute_selection(",
            "commit_once(", "wire::Action::Execute", "original_response(",
            "command_response(", "recover_evaluated(", "dyn Fn", "permit_all",
        )
        for path in (CLIENT, SERVICE):
            original = (ROOT / path).read_text()
            for marker in forbidden:
                with self.subTest(path=path, marker=marker):
                    self.assert_protected_rejects(
                        path, original + "\nfn injected_authority_bypass() { " + marker + " }\n"
                    )


if __name__ == "__main__":
    unittest.main()
