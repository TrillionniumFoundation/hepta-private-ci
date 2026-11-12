"""Closure for one original Model read/execute continuation.

The same original E transfer brackets the native Model owner; pages are data
only, Finish is physical I/O, and no provisional body is an exported CURRENT.
These source mutations do not claim native execution or ordinary A/B/C.
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
    "original_model_continuation_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CLIENT = AGENT + "cell_q24_model_read_operation.rs"
HOST = AGENT + "cell_q24_model_read_host_operation.rs"
SERVICE = AGENT + "cell_q24_model_command_service.rs"
WIRE = AGENT + "cell_q24_model_command_wire.rs"
LEGACY = AGENT + "cell_q24_model_command_client.rs"
CANDIDATE = AGENT + "cell_q24_candidate_stage_model.rs"
EVIDENCE = AGENT + "cell_q24_candidate_stage_operation.rs"
EXPECTED = {
    "learning_original_model_operation_begin_read": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_publication.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_recovery.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs", "codex-rs/hepta-agentd/src/circuit_model_version_effect.rs", "codex-rs/hepta-agentd/src/circuit_model_version_state.rs",),
    "learning_original_model_operation_begin_execute": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs",),
    "learning_original_model_operation_current": ("codex-rs/hepta-agentd/src/circuit_learning_model_publication.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_recovery.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs", "codex-rs/hepta-agentd/src/circuit_model_version_effect.rs", "codex-rs/hepta-agentd/src/circuit_model_version_state.rs",),
    "learning_original_model_operation_model": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_publication.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_recovery.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs", "codex-rs/hepta-agentd/src/circuit_model_version_effect.rs", "codex-rs/hepta-agentd/src/circuit_model_version_state.rs",),
    "learning_original_model_operation_material": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_publication.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_recovery.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs", "codex-rs/hepta-agentd/src/circuit_model_version_effect.rs", "codex-rs/hepta-agentd/src/circuit_model_version_state.rs",),
    "learning_original_model_operation_finish": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_publication.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_recovery.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs", "codex-rs/hepta-agentd/src/circuit_model_version_effect.rs", "codex-rs/hepta-agentd/src/circuit_model_version_state.rs",),
    "learning_original_model_operation_completed_model": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_adoption.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_next_use.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_operation.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_publication.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_recovery.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs", "codex-rs/hepta-agentd/src/circuit_model_version_effect.rs", "codex-rs/hepta-agentd/src/circuit_model_version_state.rs",),
    "learning_original_model_operation_completed_material": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_adoption.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_next_use.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_operation.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_publication.rs", "codex-rs/hepta-agentd/src/circuit_learning_model_recovery.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs", "codex-rs/hepta-agentd/src/circuit_model_version_effect.rs", "codex-rs/hepta-agentd/src/circuit_model_version_state.rs",),
    "learning_original_model_operation_host_begin": ("codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs",),
    "learning_original_model_operation_host_started": ("codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs",),
    "learning_original_model_operation_host_page": ("codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs",),
    "learning_original_model_operation_host_finish": ("codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs",),
}
GENERIC_TOP = ("if bytes.len()", "let request: wire::Request", "request.require_initial(", "let result = (||", "if result.is_err()", "let outcome = match result", "let response = serde_json::to_vec(", "if response.len()", "Ok(response)",)


class OriginalModelContinuationClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows, path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
        if path == SERVICE:
            # The original verifier's function marker syntax excludes explicit
            # lifetime parameters. Normalize only this exact declaration for
            # its own function-local verifier; production syntax is untouched.
            marker = "fn command_response<'a>("
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            if code.count(marker) != 1:
                raise PROOF.VerificationFailure("one actual generic Model dispatcher")
            sequences = [
                sequence for row in rows for sequence in row.get("required_order", [])
                if sequence[0] == marker
            ]
            if len(sequences) != 1:
                raise PROOF.VerificationFailure("one complete Model dispatcher guard")
            normalized = source.replace(marker, "fn command_response(", 1)
            body_code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(normalized))
            PROOF._verify_function_order(
                {"required_function_order": [{
                    "function": "fn command_response(",
                    "sequence": ["fn command_response(", *sequences[0][1:]],
                    "top_level": list(GENERIC_TOP),
                }]},
                body_code, path, normalized,
            )

    def rejects(self, path, function, marker, replacement="", occurrence=0):
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        cursor = start
        for _ in range(occurrence + 1):
            first, cursor = source_marker_span(source, marker, cursor, end + 1)
        self.verifies(path, source)
        changed = source[:first] + replacement + source[cursor:]
        self.assertNotEqual(changed, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_actual_continuation_edges_and_private_receivers_remain_exact(self):
        paths = {
            path for identifier in EXPECTED for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        # Include the real field owners used by receiver inference, not a test
        # declaration that would merely claim the intended receiver type.
        paths.update(AGENT + name for name in (
            "cell_q24_model_command_client.rs",
            "circuit_model_version_host.rs",
            "circuit_model_selection_receipt_owner.rs",
        ))
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
                (ROOT / path).read_text()
            )) for path in paths
        }
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                extra = dict(sources)
                extra[AGENT + "unregistered_model_continuation.rs"] = (
                    f"fn bypass(owner: &mut {row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_begin_takes_the_original_channel_once_and_never_resets_its_budget(self):
        for marker in (
            "require_clock(self.observed_at, started)?",
            "slot.as_ref().is_some_and(|channel| channel.execution_requested)",
            "return Err(Error::ReadbackRequired)",
            "slot.take().ok_or(Error::Unavailable)?",
            "channel.execution_requested = true",
            "let transfer = channel.next",
            "channel.next.checked_add(pages as u64).is_none_or(|finish| finish > 128)",
            "self.retained.try_lock()",
            "wire::decode_completed(&self.context, &record, self.context.authenticate(started)?)?",
            "OriginalCellEvaluationModelMaterialV1::from_original_model_response(",
            "operation.require_current(fresh)?",
        ):
            self.rejects(CLIENT, "fn begin_original_operation(", marker)
        for marker in (
            "self.channel.as_ref().ok_or(Error::Unavailable)?.peer.check_peer_lifetime()?",
            "self.effect_cancellation.as_ref().is_some_and(|flag| flag.load(Ordering::Acquire))",
            "self.client.context.authenticate(self.started.max(lower))?",
            "self.material.authenticate_current(fresh)?",
            "self.material.original_evaluation() != &self.client.context.evaluation",
            "input.material_digest() != self.model.material_digest()",
        ):
            self.rejects(CLIENT, "fn require_current(", marker)

    def test_pages_require_complete_canonical_body_and_monotone_original_transfer(self):
        for marker in (
            "total == 0 || total > wire::MATERIAL_MAX_BYTES",
            "total.div_ceil(wire::MATERIAL_PAGE_BYTES)",
            "Action::ReadOriginalPage { transfer, index: index as u32 }",
            "actual != transfer || page != index as u32 || offset != body.len()",
            "size != total || canonical_digest(&hash)? != digest",
            "bytes.len() > 10_924",
            "decoded.len() != expected || STANDARD_NO_PAD.encode(&decoded) != bytes",
            "body.len() != total || Digest32::of_bytes(&body) != digest",
        ):
            self.rejects(CLIENT, "fn begin_original_operation(", marker)
        for marker in (
            "transfer != self.transfer || index != self.next_page || index as usize >= pages",
            "request.nonce != self.transfer + 1 + u64::from(index)",
            "self.next_page += 1",
        ):
            self.rejects(HOST, "fn page(", marker)
        for occurrence in (0, 1):
            self.rejects(HOST, "fn page(", "self.require_current()?", occurrence=occurrence)

    def test_execute_keeps_original_custody_cancellation_and_native_before_after(self):
        for marker in (
            "if state.fenced",
            "execute && (state.execution_requested || state.model.is_some())",
            "!execute && state.model.is_none()",
            "state.fenced = true",
            "self.original_inputs(&mut state)?",
            "OriginalCellEvaluationModelMaterialClientV1::begin_owned_model_read(",
            "context.require_qualified()?",
            "request.require_context(&context, request.nonce)?",
            "state.execution_requested = true",
            "state.custody.take().ok_or(Error::ReadbackRequired)?",
            "OriginalCellQ24TrainingCommandOwnerV1::create_original_model(",
            "OriginalCellQ24TrainingCommandOwnerV1::commit_original_model(",
            "OriginalCellQ24TrainingCommandOwnerV1::read_original_model(",
            "OriginalCellEvaluationModelReadV1::require_original_operation_current(&evaluation, inputs.started)?",
            "state.retained.as_ref().is_some_and(|previous| previous != &model)",
        ):
            self.rejects(HOST, "fn begin_original_read(", marker)
        for occurrence in (0, 1):
            self.rejects(HOST, "fn begin_original_read(",
                         "self.bootstrap.cancellation.load(Ordering::Acquire)",
                         occurrence=occurrence)
        source = (ROOT / HOST).read_text()
        for addition in (
            "fn reset(state: &mut State) { state.execution_requested = false; }",
            "fn recover() { recover_original_model(); }",
            "fn hold_lane() { owner.in_model_lane(); }",
        ):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(HOST, source + "\n" + addition + "\n")

    def test_finish_reads_actual_e_then_last_native_model_before_fresh_release(self):
        for marker in (
            "self.require_current()?",
            "transfer != self.transfer || self.next_page as usize != pages",
            "request.nonce != self.transfer + 1 + pages as u64",
            "OriginalCellEvaluationModelReadV1::finish(",
            "self.evaluation.take().ok_or(Error::CommitUncertain)?",
            "OriginalCellEvaluationModelMaterialV1::original_model_transfer_body(&after) != self.body.as_slice()",
            "after.original_evaluation() != &self.context.evaluation",
            "OriginalCellQ24TrainingCommandOwnerV1::read_original_model(",
            "after.authenticate_current(fresh)?",
            "native != self.observed || current != self.model",
            "self.state.retained.as_ref().is_some_and(|previous| previous != &current)",
            "after.authenticate_current(final_at)?",
            "self.state.retained = Some(current)",
            "self.state.fenced = false",
            "self.completed = true",
        ):
            self.rejects(HOST, "fn finish(", marker)
        self.rejects(HOST, "fn drop(", "if !self.completed { self.state.fenced = true; }")
        for marker in (
            "self.require_current(self.started)?",
            "Action::FinishOriginalRead { transfer: self.transfer }",
            "transfer != self.transfer || total != self.total",
            "canonical_digest(&digest)? != self.digest",
            "current != self.model",
            "self.require_current(lower)?",
            "*retained = Some(current)",
            "if slot.is_some()",
            "*slot = Some(channel)",
        ):
            self.rejects(CLIENT, "fn finish(", marker)

    def test_service_cancellation_and_eof_cannot_resume_a_partial_operation(self):
        for marker in (
            "original_owner_command_channel_v1(",
            "QueuedModelServiceV1::new()",
            "tokio::task::spawn_blocking(move ||",
            "channel.check_peer_lifetime()?",
        ):
            self.rejects(SERVICE, "fn serve_commands(", marker)
        for occurrence in (0, 1):
            self.rejects(SERVICE, "fn serve_commands(",
                         "cancellation.load(Ordering::Acquire)", occurrence=occurrence)
        for marker in (
            "for nonce in 1..=128",
            "operation.is_some()",
            "return Err(Error::CommitUncertain)",
        ):
            self.rejects(SERVICE, "fn serve_original_channel(", marker)
        for marker in (
            "request.require_initial(&self.bootstrap.config.material, nonce)?",
            "self.begin_original_read(&request)?",
            "OriginalModelReadHostOperation::started(&original)?",
            "*operation = Some(original)",
            "OriginalModelReadHostOperation::page(",
            "operation.as_mut().ok_or(Error::ReadbackRequired)?, &request",
            "OriginalModelReadHostOperation::finish(",
            "operation.take().ok_or(Error::ReadbackRequired)?, &request",
            "if result.is_err()",
            "drop(operation.take())",
            "Err(_) => wire::Outcome::Uncertain",
        ):
            self.rejects(SERVICE, "fn command_response<'a>(", marker)
        self.rejects(CLIENT, "fn drop(", "self.0.store(true, Ordering::Release)")
        for occurrence in (0, 1):
            self.rejects(CLIENT, "fn exchange(",
                         "channel.peer.check_peer_lifetime()?", occurrence=occurrence)

    def test_candidate_closes_actual_prefix_inside_the_same_model_operation(self):
        for marker in (
            "CandidateOriginalOperation::begin(self, snapshot).await?",
            "OriginalCellQ24CandidateStageOwnersV1::read_evaluation_in_operation(",
            "let client = {",
            "Arc::clone(lane.client.as_ref().ok_or(Error::CommitUncertain)?)",
            "OriginalCellQ24ModelCommandClientV1::begin_original_model_commit(",
            "OriginalCellQ24ModelCommandClientV1::begin_original_model_read(",
            "original.material().original_evaluation() != &before",
            "let actual = original.model().clone()",
            "CandidateOriginalOperation::close(operation)",
            "original.finish().await.map_err(|_| Error::CommitUncertain)?",
            "if &before != after",
            "current != &actual",
            "closed.model(completed)?",
            "lane.failed = false",
        ):
            self.rejects(CANDIDATE, "fn original_model(", marker)
        for marker in (
            "completed.model().clone()",
            "completed.material().original_evaluation().clone()",
            "model: Some(model), model_completion: Some(completed)",
        ):
            self.rejects(EVIDENCE, "fn model(", marker)
        for marker in (
            "self.model_completion.as_ref().ok_or(Error::CommitUncertain)?",
            "completed.model() != model",
            "completed.material().original_evaluation() != &self.evaluation",
            "completed.material().authenticate_current(fresh)",
            "completed.material().require_original_model_input(",
            "input.material_digest() != model.material_digest()",
            "self.model_completion.is_some()",
            "self.selection.is_some()", "self.next_use.is_some()",
            "self.publication.is_some()", "self.completion_read.is_some()",
            "self.evaluation.snapshot() != snapshot",
        ):
            self.rejects(EVIDENCE, "fn authenticate_result(", marker)

    def test_completed_and_provisional_proofs_cannot_be_cloned_exported_or_reconnected(self):
        for path, additions in (
            (CLIENT, (
                "impl Clone for OriginalCellQ24ModelReadV1<'_> {}",
                "impl Clone for OriginalCellQ24ModelReadCompletionV1 {}",
                "#[derive(Deserialize)] struct Forged {}",
                "struct Forged { pub(crate) model: OriginalCellQ24ModelCommandReceiptV1 }",
                "fn reconnect() { UnixStream::connect(); }",
                "fn reset(channel: &mut Channel) { channel.next = 1; }",
            )),
            (EVIDENCE, (
                "struct Forged { pub(super) model_completion: OriginalCellQ24ModelReadCompletionV1 }",
                "impl Drop for OriginalCandidateOperationEvidence<'_> {}",
            )),
        ):
            source = (ROOT / path).read_text()
            self.verifies(path, source)
            for addition in additions:
                with self.subTest(path=path, addition=addition):
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verifies(path, source + "\n" + addition + "\n")
        for marker in (
            "wire::Outcome::OriginalReadStarted { .. }",
            "wire::Outcome::OriginalReadPage { .. }",
            "wire::Outcome::OriginalReadFinished { .. }",
        ):
            self.rejects(LEGACY, "fn exchange(", marker)


if __name__ == "__main__":
    unittest.main()
