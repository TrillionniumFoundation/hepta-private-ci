"""Close original Published Circuit read capabilities to live typed owners.

These source gates do not qualify external-UID deployment or a learning loop.
Native tests separately exercise actual publication, C, source files and windows.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_published_read_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
MAIN = AGENT + "circuit_learning_read_capability.rs"
SERVICE = AGENT + "circuit_learning_read_service.rs"
WIRE = AGENT + "circuit_learning_read_wire.rs"
SOURCE = AGENT + "circuit_task_source_readback.rs"
JOURNAL = AGENT + "circuit_task_source_journal.rs"
SELECTOR = AGENT + "circuit_selection_receipt_owner.rs"
OBSERVER = AGENT + "circuit_next_use_receipt_owner.rs"
EXPECTED = {
    "learning_original_published_read_client_create": (),
    "learning_original_published_read_client_current": (SELECTOR, OBSERVER, AGENT + "circuit_evaluated_selection_remote.rs"),
    "learning_original_published_read_client_context": ("codex-rs/hepta-agentd/src/circuit_selection_receipt_owner.rs", "codex-rs/hepta-agentd/src/circuit_next_use_receipt_owner.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_service.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs"),
    "learning_original_published_read_owner_create": ('codex-rs/hepta-agentd/src/circuit_retained_version_state.rs',),
    "learning_original_published_read_owner_serve": (),
    "learning_original_source_input_current": ('codex-rs/hepta-agentd/src/circuit_learning_read_service.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_c_task.rs'),
    "learning_original_circuit_selection_remote_attest": ("codex-rs/hepta-agentd/src/circuit_selection_command_service.rs",),
    "learning_original_circuit_selection_remote_readback": ("codex-rs/hepta-agentd/src/circuit_selection_command_service.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_evidence.rs"),
    "learning_original_circuit_next_use_remote_attest": ("codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs",),
    "learning_original_circuit_next_use_remote_readback": ("codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_evidence.rs"),
    "learning_original_owner_physical_current": ("codex-rs/hepta-agentd/src/learning_owner_journal.rs", "codex-rs/hepta-agentd/src/cell_composed_q24_training_owner.rs", "codex-rs/hepta-agentd/src/cell_q24_model_proposal.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_execution_store.rs", "codex-rs/hepta-agentd/src/circuit_task_source_journal.rs",),
}


class OriginalPublishedReadClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def rejects(self, path, function, marker, replacement=""):
        source = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(source)
        self.assertEqual(code.count(function), 1, (path, function))
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        rows = [
            row for row in self.manifest["protected_file"] if row["path"] == path
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + replacement + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_concrete_live_read_edges_are_exact_and_external_factories_stay_closed(self):
        paths = {
            path
            for identifier in EXPECTED
            for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(
                    identifier,
                    self.manifest["privileged_inventory"]["required_boundary_ids"],
                )
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                changed = dict(sources)
                changed[AGENT + "unregistered_published_read.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())
                if expected:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(
                            ROOT, replace(row, product_callers=()), sources, ()
                        )
        self.assertEqual(
            self.boundaries["root_learning_original_stage_assembly"].product_callers,
            (),
        )
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_source_current_keeps_original_handle_two_witnesses_and_permanent_fence(self):
        for marker in (
            "if self.fenced",
            "let before = self.witness.current()",
            ".read_current_anchor()",
            "let after = self.witness.current()",
            "before != Some(current) || after != Some(current)",
            "if result.is_err()",
            "self.fenced = true",
        ):
            with self.subTest(marker=marker):
                self.rejects(JOURNAL, "fn require_current(", marker)
        for marker in (
            "owner.require_current()?;",
            "identity != &owner.identity",
            "owner.sources.get(input.scope.run_id.as_str()) != Some(input)",
            "owner.require_active(input.scope.run_id.as_str())?",
        ):
            self.rejects(SOURCE, "fn require_original_input(", marker)

    def test_mode_frozen_scope_cut_and_complete_original_signatures_are_bound(self):
        for marker in (
            "LearningIterationObservationV1::TrainingNoUpdateV2(_)",
            "coordinator.next_task_bundle() != Some(&context.prefix.request.selected_bundle)",
            "(3, Some(LearningIterationStageV1::Selection), None)",
            "(4, Some(LearningIterationStageV1::NextUse), Some(_))",
        ):
            self.rejects(WIRE, "fn mode(", marker)
        for marker in (
            "LearningEvidenceRoleV1::Generator",
            "LearningEvidenceRoleV1::Selector",
            "context.training_evidence.signing_bytes()",
            "&context.training_evidence.signature",
            "original.signing_bytes()",
            "&original.signature",
            "verify_signed_actor_separation(&training, &selection, at)?",
            "encode_original_owner_snapshot_v1(snapshot)?",
            "mode.name()",
            "context.scope.binding().as_array()",
        ):
            self.rejects(WIRE, "fn context_binding(", marker)

    def test_no_historical_read_replaces_remote_io_or_fresh_window_validation(self):
        for marker in (
            ".take()",
            "channel.next_request_id > 128",
            "channel.peer.request(&bytes)?",
            "response.require_request(&request)?",
            "self.context.decode(response.read)?",
            "self.context.binding(fresh)? != self.binding",
            "retained.as_ref().is_some_and(|prior| prior != &current)",
            "channel.peer.check_peer_lifetime()?",
        ):
            self.rejects(MAIN, "fn read_current(", marker)
        for marker in (
            "timeout > Duration::from_millis(500)",
            "lifetime > Duration::from_secs(300)",
        ):
            self.rejects(MAIN, "fn require_timing(", marker)
        self.rejects(MAIN, "fn from_original_stream(", "original_task_pidfd")
        self.rejects(SERVICE, "fn serve_readback(", "original_consumer_pidfd")

    def test_actual_task_source_selection_and_c_completion_precede_wire_response(self):
        for marker in (
            "input.scope.run_id == request.source_run_id",
            "input.scope.principal_digest.to_string() != request.principal_id.as_str()",
            "source.require_original_input(&self.identity, input)?",
        ):
            self.rejects(SERVICE, "fn require_task_input_current(", marker)
        for marker in (
            "cell.read_learning_selection(&coordinator)?",
            "self.require_original_selection(&selection)?",
            "wire::Mode::Selection => (selection.clone(), None)",
            "wire::Mode::NextUse",
            "cell.read_learning_next_use(",
            "before.publication_digest()",
            "cell.read_learning_selection(&coordinator)? != selection",
        ):
            self.rejects(SERVICE, "fn read_original(", marker)
        for marker in (
            "self.context\n            .require_request(&request, self.binding, request_id)?",
            "let read = self.read_original()?;",
            "self.context.binding(fresh)? != self.binding",
            "wire::OriginalRead::from_original(read)?",
            "bytes.is_empty() || bytes.len() > 16_384",
        ):
            self.rejects(SERVICE, "fn response(", marker)

    def test_remote_receipt_owners_keep_real_predecessor_reads_on_both_sides(self):
        for path, function, predecessor, verifier in (
            (SELECTOR, "fn read_remote_selection(", "training_evidence", "authenticate_training"),
            (OBSERVER, "fn read_remote_next_use(", "predecessors", "evaluated::authenticate_predecessors"),
        ):
            for marker in (
                "live.require_original_context(",
                "live.read_current().await?",
            ):
                self.rejects(path, function, marker)
            for marker in (
                "ObservationLocation::RemoteOwner | ObservationLocation::EvaluatedOwner",
                f"self.{predecessor}(&source).await?",
                f"{verifier}(&self.config, &self.profile, &before, now()?)?",
                "let bytes = self.journal.read(&self.saved)?;",
            ):
                self.rejects(path, "fn readback_source(", marker)
            for replacement in ("ObservationLocation::RemoteOwner", "ObservationLocation::EvaluatedOwner"):
                self.rejects(
                    path, "fn readback_source(",
                    "ObservationLocation::RemoteOwner | ObservationLocation::EvaluatedOwner",
                    replacement,
                )
            for marker in (
                "if self.prepare(source).await? != *observed",
                f"self.{predecessor}(source).await?",
                "if self.journal.read(&self.saved)? != bytes",
                "self.authenticate_completed(completed, &evidence, started_at, current, new_attestation)",
            ):
                self.rejects(path, "fn finish_original_readback(", marker)
            self.rejects(path, "fn authenticate_completed(", f"{verifier}(&self.config, &self.profile, evidence, current)?")
            for marker in (
                "self.config.scope.validate_snapshot(source.snapshot())?",
                "source.observe(&self.config).await?",
            ):
                self.rejects(path, "fn prepare(", marker)
        self.rejects(SELECTOR, "fn attest_original_remote_selection(", "self.attest_source(source).await")
        self.rejects(OBSERVER, "fn attest_original_remote_completion(", "self.attest_source(source).await")

    def test_private_wire_is_bounded_mode_exact_and_has_no_writer_or_signer_factory(self):
        for marker in (
            "self.request.request_id != original.request_id",
            "self.request.binding != original.binding",
            "self.request.mode != original.mode",
        ):
            self.rejects(WIRE, "fn require_request(", marker)
        for marker in (
            "digest(&bundle)? != baseline",
            "source_publication.is_none()",
            "state_partition.run_id == prefix.request.source_run_id",
            "*candidate_bundle == baseline && *selection_digest == selection",
            "scope.validate_observation(&observation)?",
        ):
            self.rejects(WIRE, "fn decode_original(", marker)
        self.rejects(WIRE, "fn digest(", "digest.is_zero() || digest.to_string() != text")
        for path in (MAIN, SERVICE, WIRE):
            source = (ROOT / path).read_text()
            rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / path
                target.parent.mkdir(parents=True)
                for marker in (
                    "SigningKey", "File::open", "UnixStream::connect",
                    ".commit_once(", ".publish(", ".compare_and_swap(",
                    "with_root_learning_stage_owners(",
                ):
                    target.write_text(source + "\n" + marker + "\n")
                    with self.subTest(path=path, marker=marker):
                        with self.assertRaises(PROOF.VerificationFailure):
                            PROOF._verify_protected_files(root, {"protected_file": rows})


if __name__ == "__main__":
    unittest.main()
