"""Keep original Candidate bytes on one read-only Begin/Pages/Finish session.

These mutations protect source boundaries. Native cases separately exercise
actual Source/Material/Training owners; neither suite grants model adoption.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_candidate_material_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
MATERIAL = AGENT + "cell_q24_candidate_material.rs"
CLIENT = AGENT + "cell_q24_training_candidate_readback.rs"
WIRE = AGENT + "cell_q24_training_candidate_wire.rs"
TRANSFER = AGENT + "cell_q24_training_candidate_transfer.rs"
SERVICE = AGENT + "cell_q24_training_candidate_service.rs"
BOOTSTRAP = AGENT + "cell_q24_training_bootstrap_candidate.rs"
CONNECTION = AGENT + "cell_q24_training_command_connection.rs"
MODEL = AGENT + "cell_q24_training_model_lane.rs"
BOUND = AGENT + "cell_q24_source_bound_stage.rs"
EXPECTED = {
    "learning_original_candidate_material_native": (MODEL,),
    "learning_original_candidate_material_verified": (CLIENT,),
    "learning_original_training_candidate_material": (BOUND,),
    "learning_source_bound_training_candidate_material": (SERVICE,),
    "learning_original_candidate_initial_binding": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_readback.rs",),
    "learning_original_candidate_client_binding": (CONNECTION,),
    "learning_original_candidate_client_readback": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_readback.rs",),
    "learning_original_candidate_command_serve": (),
    "learning_original_candidate_command_response": (BOOTSTRAP,),
    "learning_original_candidate_bootstrap_serve": (),
}


class OriginalCandidateMaterialClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def verifies(self, path, source):
        rows = [
            row for row in self.manifest["protected_file"] if row["path"] == path
        ]
        self.assertTrue(rows)
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

    def test_original_source_lane_and_complete_model_binding_cannot_be_bypassed(self):
        paths = {
            path for identifier in EXPECTED for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        sources = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                extra = dict(sources)
                extra[AGENT + "unregistered_candidate_reader.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        for path, function, marker in (
            (MODEL, "fn read_candidate_material(", "SourceLaneProof::require_original(source, training)?"),
            (MODEL, "fn read_candidate_material(", "CellQ24TrainingOwnerV1::readback(training)?"),
            (MODEL, "fn read_candidate_material(", "completed.attestation.clone()"),
            (MODEL, "fn in_model_lane<", "OriginalCellQ24TrainingSourceV1::begin_source_operation(source)"),
            (MODEL, "fn in_model_lane<", "OriginalCellQ24TrainingSourceOperationV1::read_after_native("),
            (MODEL, "fn in_model_lane<", "OriginalCellQ24TrainingSourceOperationV1::finish(operation, source)"),
            (MODEL, "fn in_model_lane<", "current.receipt != original.receipt || current.attestation != original.attestation"),
            (BOUND, "fn read_candidate_material(", "self.original.require_dataset(dataset)?"),
            (MATERIAL, "fn from_original_candidate(", "candidate.bundle != *signed"),
            (MATERIAL, "fn from_verified_readback(", "baseline.components() != &dataset.request.selected_bundle.components"),
            (MATERIAL, "fn from_verified_readback(", "if changed.next().is_some()"),
            (MATERIAL, "fn from_verified_readback(", "baseline.validate_single_head_candidate(candidate, head)?"),
            (MATERIAL, "fn require_rebuilt_bundle(", "Digest32::of_bytes(heads)"),
            (MATERIAL, "fn require_rebuilt_bundle(", "components.heads = head_digest"),
            (MATERIAL, "fn require_rebuilt_bundle(", "if signed != &expected"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker)
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_one_session_pins_original_windows_pages_and_full_training_signature(self):
        for path, function, marker in (
            (CONNECTION, "fn bind_original_candidate_material(", "self,"),
            (CONNECTION, "fn bind_original_candidate_material(", "OriginalCellQ24TrainingCommandConnectionV1::bind_original_dataset("),
            (CLIENT, "fn from_original_connection(", "channel.execution_requested = true"),
            (CLIENT, "fn from_original_connection(", "pin != &expected"),
            (CLIENT, "fn from_original_connection(", "context.dataset != *dataset.snapshot()"),
            (CLIENT, "fn readback(", ".take()"),
            (CLIENT, "fn readback(", "for page in 0..pages"),
            (CLIENT, "fn exchange(", "&response.request != request"),
            (CLIENT, "fn readback(", "total as usize != length"),
            (CLIENT, "fn readback(", "heads.len() != offset_expected"),
            (CLIENT, "fn readback(", "STANDARD_NO_PAD.encode(&part) != encoded_heads"),
            (CLIENT, "fn readback(", "OriginalCellQ24CandidateMaterialV1::from_verified_readback("),
            (CLIENT, "fn verify_original_context(", "OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context("),
            (CLIENT, "fn verify_original_context(", "let fresh_now = now()?"),
            (CLIENT, "fn verify_original_context(", "checked_at < minimum_now || fresh_now < checked_at"),
            (CLIENT, "fn verify_original_context(", "expected.attestation().clone()"),
            (CLIENT, "fn verify_original_context(", "&verified != expected"),
            (WIRE, "fn require_common(", "self.operation != OPERATION"),
            (WIRE, "fn require_common(", "usize::from(self.page) >= MAX_PAGES"),
            (TRANSFER, "fn check_request(", "request.page == original.next_page"),
            (TRANSFER, "fn check_request(", "prior != &request.completion"),
            (WIRE, "fn completion_digest(", "&attestation.signing_bytes()"),
            (WIRE, "fn completion_digest(", "&attestation.signature"),
            (WIRE, "fn original_page(", "completion_digest(material.receipt(), material.attestation())?"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker)
        for path, declaration in (
            (WIRE, "const PAGE_BYTES: usize = 2_048"),
            (WIRE, "const MAX_PAGES: usize = 17"),
            (WIRE, "const FRAME_BYTES: usize = 16_384"),
            (MATERIAL, "const ORIGINAL_Q24_CANDIDATE_HEAD_BYTES: usize = 12 + 64 * 64 * 8"),
        ):
            with self.subTest(bound=declaration):
                source = (ROOT / path).read_text()
                self.verifies(path, source)
                self.assertEqual(source.count(declaration), 1)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, source.replace(declaration, declaration + " + 1", 1))
        source = (ROOT / CLIENT).read_text()
        start = self.code(source).index("fn readback(")
        end = PROOF._rust_item_end(self.code(source), start)
        self.assertIsNotNone(end)
        # Removing the last peer I/O must not be masked by the per-page check.
        offset = source.rindex("check_peer_lifetime()", start, end + 1)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(CLIENT, source[:offset] + source[offset + len("check_peer_lifetime()"):])

    def test_readback_cannot_initialize_recover_fit_sign_or_promote_missing(self):
        for path, function, marker in (
            (BOOTSTRAP, "fn candidate_material_response(", "request.require_initial(&self.config.material, request_id)?"),
            (BOOTSTRAP, "fn candidate_material_response(", "session.require_request(&request)?"),
            (BOOTSTRAP, "fn candidate_material_response(", "if let Some(original) = self.ready()?"),
            (BOOTSTRAP, "fn candidate_material_response(", "OriginalCellQ24TrainingCommandOwnerV1::candidate_material_response("),
            (BOOTSTRAP, "fn candidate_material_response(", "candidate_wire::MaterialResult::ReadbackRequired"),
            (SERVICE, "fn candidate_material_response(", "SourceBoundCellQ24TrainingStageV1::read_candidate_material("),
            (SERVICE, "fn candidate_material_response(", "wire::authenticate_receipt("),
            (SERVICE, "fn candidate_material_response(", "wire::CommandResult::Missing => candidate_wire::MaterialResult::Missing"),
            (SERVICE, "fn candidate_material_response(", "wire::CommandResult::Pending => candidate_wire::MaterialResult::Pending"),
            (TRANSFER, "fn encode_response(", "SessionDisposition::CloseReadback"),
            (MATERIAL, "fn authority(", "AuthorityPosture::DENY_ALL"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker)
        for path, declaration in (
            (MATERIAL, "impl Clone for OriginalCellQ24CandidateMaterialV1 {}"),
            (MATERIAL, "use serde::Deserialize;"),
            (CLIENT, "fn bypass() { original_owner_command_channel_v1(); }"),
            (CLIENT, "fn bypass() { channel.execution_requested = false; }"),
            (BOOTSTRAP, "fn bypass() { owner.build_original_owner(); }"),
            (BOOTSTRAP, "fn bypass() { State::Starting; }"),
            (SERVICE, "fn bypass() { owner.execute_training(); }"),
            (SERVICE, "fn bypass() { key.sign(); }"),
            (WIRE, "enum Action { Execute }"),
        ):
            with self.subTest(path=path, declaration=declaration):
                source = (ROOT / path).read_text()
                self.verifies(path, source)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, source + "\n" + declaration + "\n")


    def test_begin_and_finish_require_actual_owner_and_complete_current_tail(self):
        for path, function, marker in (
            (SERVICE, "fn candidate_material_response(", "session.require_owner(self as *const Self as usize)?"),
            (SERVICE, "fn candidate_material_response(", "request.phase == candidate_wire::Phase::Page"),
            (SERVICE, "fn candidate_material_response(", "session.require_current(&self.context, started_at)?"),
            (SERVICE, "fn candidate_material_response(", "Phase::Begin => session.begin(&request, material, fresh_now)?"),
            (SERVICE, "fn candidate_material_response(", "Phase::Finish => session.finish(&request, material)?"),
            (SERVICE, "fn candidate_material_response(", "session.encode_response(request, result)"),
            (TRANSFER, "fn require_current(", "current < lower || current < original.last_at"),
            (TRANSFER, "fn require_current(", "super::super::wire::authenticate_receipt("),
            (TRANSFER, "fn require_current(", "checked.receipt() != original.material.receipt()"),
            (TRANSFER, "fn require_current(", "checked.attestation() != original.material.attestation()"),
            (TRANSFER, "fn finish(", "request.phase != Phase::Finish"),
            (TRANSFER, "fn finish(", "current.heads() != original.heads()"),
            (TRANSFER, "fn finish(", "current.bundle() != original.bundle()"),
            (TRANSFER, "fn finish(", "current.model().components() != original.model().components()"),
            (TRANSFER, "fn finish(", "current.receipt() != original.receipt()"),
            (TRANSFER, "fn finish(", "current.attestation() != original.attestation()"),
            (TRANSFER, "fn finish(", "current.authority() != codex_hepta_types::AuthorityPosture::DENY_ALL"),
            (CLIENT, "fn readback(", "candidate_wire::Request::finish("),
            (CLIENT, "fn readback(", "exchange(&mut channel, &finish, &cancellation)?"),
            (CLIENT, "fn readback(", "total as usize == length && digest == heads_digest.to_string()"),
            (CLIENT, "fn readback(", "if retained_channel.is_some()"),
            (CLIENT, "fn readback(", "*retained_channel = Some(channel)"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker)

    def test_transfer_nonce_and_next_independent_begin_cannot_reuse_current(self):
        for path, function, marker in (
            (WIRE, "fn require_common(", "!(1..=128).contains(&request_id)"),
            (WIRE, "fn require_common(", "self.transfer == 0 || self.transfer > request_id"),
            (WIRE, "fn finish(", "request.transfer = transfer"),
            (WIRE, "fn finish(", "request.phase = Phase::Finish"),
            (TRANSFER, "fn require_owner(", "self.failed || self.owner.is_some_and(|original| original != owner)"),
            (TRANSFER, "fn require_request(", "self.check_request(request)"),
            (TRANSFER, "fn require_request(", "self.fail()"),
            (TRANSFER, "fn check_request(", "Phase::Begin if self.original.is_none()"),
            (TRANSFER, "fn check_request(", "request.page == 0 && request.transfer == request.request_id"),
            (TRANSFER, "fn check_request(", "request.transfer != original.transfer"),
            (TRANSFER, "fn check_request(", "request.request_id == original.transfer + u64::from(request.page)"),
            (TRANSFER, "fn check_request(", "usize::from(original.next_page) == pages"),
            (TRANSFER, "fn check_request(", "request.request_id == original.transfer + pages as u64"),
            (TRANSFER, "fn begin(", "request.transfer.checked_add(pages as u64).is_none_or(|last| last > 128)"),
            (TRANSFER, "fn encode_response(", "original.next_page += 1"),
            (TRANSFER, "fn encode_response(", "self.completion = Some(request.completion.clone())"),
            (TRANSFER, "fn encode_response(", "self.original = None"),
            (TRANSFER, "fn fail(", "self.failed = true"),
            (TRANSFER, "fn fail(", "self.original = None"),
            (CLIENT, "fn readback(", "transfer.checked_add(pages as u64).is_none_or(|last| last > 128)"),
            (CLIENT, "fn exchange(", "channel.next_request_id += 1"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker)
        for declaration in (
            "impl Clone for Session {}",
            "use serde::Deserialize;",
            "fn bypass(stage: SourceBoundCellQ24TrainingStageV1) {}",
            "fn bypass(permit: OwnedSemaphorePermit) {}",
            "fn bypass() { owner.fit_or_readback(); }",
            "fn bypass() { key.sign(); }",
        ):
            with self.subTest(declaration=declaration):
                source = (ROOT / TRANSFER).read_text()
                self.verifies(TRANSFER, source)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(TRANSFER, source + "\n" + declaration + "\n")

    def test_cancelled_or_unfinished_transfer_consumes_the_original_channel(self):
        for path, function, marker in (
            (CLIENT, "fn readback(", "CancelledCandidateRead(Arc::new(AtomicBool::new(false)))"),
            (CLIENT, "fn readback(", "cancellation.load(Ordering::Acquire)"),
            (CLIENT, "fn exchange(", "channel.peer.request(&encoded)"),
            (CLIENT, "fn exchange(", "cancelled.load(Ordering::Acquire)"),
            (CLIENT, "fn exchange(", "encoded.len() > 16_384"),
            (CLIENT, "fn exchange(", "bytes.len() > 16_384"),
            (CLIENT, "fn drop(", "self.0.store(true, Ordering::Release)"),
            (SERVICE, "fn candidate_material_response(", "if result.is_err() { session.fail(); }"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker)
        for path in (SERVICE, BOOTSTRAP):
            for function, marker in (
                ("fn serve_candidate_material_readback(", "original_owner_command_channel_v1("),
                ("fn serve_candidate_material_readback(", "let _permit = permit"),
                ("fn serve_candidate_material_readback(", "channel.check_peer_lifetime()"),
                ("fn serve_candidate_material_readback(", "cancelled.load(Ordering::Acquire)"),
                ("fn serve_candidate_material_channel(", "for request_id in 1..=128_u64"),
                ("fn serve_candidate_material_channel(", "session.unfinished()"),
                ("fn drop(", "self.0.store(true, Ordering::Release)"),
            ):
                with self.subTest(path=path, marker=marker):
                    self.rejects(path, function, marker)
        source = (ROOT / CLIENT).read_text()
        code = self.code(source)
        start = code.index("fn exchange(")
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        for marker in ("channel.peer.check_peer_lifetime()", "cancelled.load(Ordering::Acquire)"):
            with self.subTest(last_actual_exchange_check=marker):
                # The second check must survive independently of the first.
                offset = source.rindex(marker, start, end + 1)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(CLIENT, source[:offset] + source[offset + len(marker):])



if __name__ == "__main__":
    unittest.main()
