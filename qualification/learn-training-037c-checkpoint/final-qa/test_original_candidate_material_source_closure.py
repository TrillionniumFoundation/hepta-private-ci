"""Keep original Candidate bytes on one read-only SourceBound owner session.

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
SERVICE = AGENT + "cell_q24_training_candidate_service.rs"
BOOTSTRAP = AGENT + "cell_q24_training_bootstrap_candidate.rs"
CONNECTION = AGENT + "cell_q24_training_command_connection.rs"
MODEL = AGENT + "cell_q24_training_model_lane.rs"
READ_LANE = AGENT + "cell_q24_training_source_read_lane.rs"
BOUND = AGENT + "cell_q24_source_bound_stage.rs"
EXPECTED = {
    "learning_original_candidate_material_native": (READ_LANE,),
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
            (MODEL, "fn read_candidate_material(", "OriginalCellQ24TrainingStageV1::read_original_source_candidate(self)"),
            (READ_LANE, "fn read_original_source_candidate(", "SourceRequirement::Required"),
            (READ_LANE, "fn read_original_source_candidate(", "CellQ24TrainingOwnerV1::readback(training)?"),
            (READ_LANE, "fn read_original_source_candidate(", "completed.attestation.clone()"),
            (MODEL, "fn in_model_lane<", "training.require_live_source_if_captured()?"),
            (MODEL, "fn in_model_lane<", "CellQ24TrainingOwnerV1::require_live_source_if_captured(&mut owners.training)"),
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
            (CLIENT, "fn readback(", "response.request != request"),
            (CLIENT, "fn readback(", "total as usize != length"),
            (CLIENT, "fn readback(", "heads.len() != expected_offset"),
            (CLIENT, "fn readback(", "STANDARD_NO_PAD.encode(&part) != encoded_heads"),
            (CLIENT, "fn readback(", "OriginalCellQ24CandidateMaterialV1::from_verified_readback("),
            (CLIENT, "fn verify_original_context(", "OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context("),
            (CLIENT, "fn verify_original_context(", "let fresh_now = now()?"),
            (CLIENT, "fn verify_original_context(", "checked_at < minimum_now || fresh_now < checked_at"),
            (CLIENT, "fn verify_original_context(", "expected.attestation().clone()"),
            (CLIENT, "fn verify_original_context(", "&verified != expected"),
            (WIRE, "fn require_common(", "self.operation != OPERATION"),
            (WIRE, "fn require_common(", "usize::from(self.page) >= MAX_PAGES"),
            (WIRE, "fn require_request(", "request.page != self.next_page"),
            (WIRE, "fn require_request(", "pin != &request.completion"),
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
            (BOOTSTRAP, "fn candidate_material_response(", "session.require_request(request)?"),
            (BOOTSTRAP, "fn candidate_material_response(", "if let Some(original) = self.ready()?"),
            (BOOTSTRAP, "fn candidate_material_response(", "OriginalCellQ24TrainingCommandOwnerV1::candidate_material_response("),
            (BOOTSTRAP, "fn candidate_material_response(", "candidate_wire::MaterialResult::ReadbackRequired"),
            (SERVICE, "fn candidate_material_response(", "SourceBoundCellQ24TrainingStageV1::read_candidate_material("),
            (SERVICE, "fn candidate_material_response(", "wire::authenticate_receipt("),
            (SERVICE, "fn candidate_material_response(", "wire::CommandResult::Missing => candidate_wire::MaterialResult::Missing"),
            (SERVICE, "fn candidate_material_response(", "wire::CommandResult::Pending => candidate_wire::MaterialResult::Pending"),
            (WIRE, "fn encode_response(", "SessionDisposition::CloseReadback"),
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


if __name__ == "__main__":
    unittest.main()
