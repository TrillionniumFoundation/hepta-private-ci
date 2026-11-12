"""Keep Candidate Current on the same bounded original material connection.

The native cases separately read real Source, Trainer and Generator journals.
These mutations protect the retained-page admission and actual read edges.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_candidate_current_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CLIENT = AGENT + "cell_q24_training_candidate_readback.rs"
WIRE = AGENT + "cell_q24_training_candidate_wire.rs"
CURRENT = AGENT + "cell_q24_training_candidate_current.rs"
SERVICE = AGENT + "cell_q24_training_candidate_service.rs"
BOOTSTRAP = AGENT + "cell_q24_training_bootstrap_candidate.rs"
PATHS = (CLIENT, WIRE, CURRENT, SERVICE, BOOTSTRAP)


class OriginalCandidateCurrentClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def code(self, text):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(text))

    def verifies(self, path, text):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(text)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        code = self.code(source)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = code.index(marker, start, end + 1)
        self.verifies(path, source)
        changed = source[:offset] + source[offset + len(marker):]
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_actual_current_proof_has_one_registered_original_host_caller(self):
        identifier = "learning_original_candidate_current_proof"
        row = next(row for row in PROOF._boundary_rows(self.manifest) if row.identifier == identifier)
        self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
        self.assertEqual(row.product_callers, (SERVICE,))
        sources = {path: self.code((ROOT / path).read_text()) for path in PATHS}
        PROOF._verify_boundary(ROOT, row, sources, ())
        sources[AGENT + "unregistered_candidate_current.rs"] = (
            "fn bypass(request: &Request, material: &Material) {"
            "candidate_current::original_candidate_current_proof_v1(request, material); }"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, row, sources, ())

    def test_cached_heads_cannot_skip_same_channel_io_or_fresh_original_checks(self):
        for marker in (
            ".take()",
            "let heads = if let Some(heads) = retained_heads",
            "heads.len() != length",
            "candidate_current::Request::new(",
            ".request(&encoded)",
            "if response.request != request",
            "completion == request.completion",
            "heads == request.heads",
            "total == request.total",
            "check_peer_lifetime()",
            "OriginalCellQ24CandidateMaterialV1::from_verified_readback(",
            "if retained.is_none()",
            "Some(candidate.heads().to_vec())",
        ):
            with self.subTest(marker=marker):
                self.rejects(CLIENT, "fn readback(", marker)

    def test_current_cannot_precede_full_pages_or_mutate_the_original_pin(self):
        for function, marker in (
            ("fn encode_response(", "self.pages.len() != *offset as usize"),
            ("fn encode_response(", "self.pages.extend_from_slice(&bytes)"),
            ("fn encode_response(", "candidate_current::Pin::from_heads("),
            ("fn encode_response(", "original != &pin"),
            ("fn require_current(", "self.next_page != 0"),
            ("fn require_current(", "!self.pages.is_empty()"),
            ("fn require_current(", "self.current.as_ref() != Some(&request.pin())"),
            ("fn encode_current(", "self.require_current(&request)?"),
            ("fn encode_current(", "*completion == request.completion"),
            ("fn encode_current(", "*heads == request.heads"),
            ("fn encode_current(", "*total == request.total"),
            ("fn encode_current(", "bytes.len() > FRAME_BYTES"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(WIRE, function, marker)

    def test_current_keeps_its_distinct_profile_and_full_actual_training_signature(self):
        for function, marker in (
            ("fn original_context(", "self.operation != OPERATION"),
            ("fn original_context(", "!(1..=128).contains(&self.request_id)"),
            ("fn original_context(", "!(12..=32_780).contains(&self.total)"),
            ("fn original_context(", "canonical(&self.heads)?"),
            ("fn require_context(", "self.original_context()?"),
            ("fn require_initial(", "self.original_context()?"),
            ("fn original_candidate_current_proof_v1(", "candidate_wire::completion_digest(material.receipt(), material.attestation())?"),
            ("fn original_candidate_current_proof_v1(", "material.heads()"),
            ("fn original_candidate_current_proof_v1(", "request.pin() != pin"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(CURRENT, function, marker)

    def test_both_original_handlers_require_the_pin_before_actual_current(self):
        for path, marker in (
            (SERVICE, "session.require_current(request)?"),
            (SERVICE, "SourceBoundCellQ24TrainingStageV1::read_candidate_material("),
            (SERVICE, "wire::authenticate_receipt("),
            (SERVICE, "candidate_current::original_candidate_current_proof_v1(request, &material)?"),
            (BOOTSTRAP, "session.require_current(request)?"),
            (BOOTSTRAP, "if let Some(original) = self.ready()?"),
            (BOOTSTRAP, "OriginalCellQ24TrainingCommandOwnerV1::candidate_material_response("),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, "fn candidate_material_response(", marker)
        for path, injected in (
            (CURRENT, "fn bypass() { request.execute_training(); }"),
            (CURRENT, "struct OptionalCurrent { pin: Option<Pin> }"),
            (CLIENT, "fn bypass() { channel.execution_requested = false; }"),
            (SERVICE, "fn bypass() { owner.build_original_owner(); }"),
            (BOOTSTRAP, "fn bypass() { owner.execute_training(); }"),
        ):
            with self.subTest(path=path, injected=injected):
                source = (ROOT / path).read_text()
                self.verifies(path, source)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, source + "\n" + injected + "\n")


if __name__ == "__main__":
    unittest.main()
