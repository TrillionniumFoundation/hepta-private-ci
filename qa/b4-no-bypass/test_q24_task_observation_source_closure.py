"""The live original task exposes data through its existing controlled owner."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "q24_task_observation_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "cell_q24_task_observation_control.rs"
STATE = AGENT + "state_q24_outcome.rs"
CLIENT = AGENT + "client_q24_outcome.rs"


class OriginalQ24TaskObservationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def rejects(self, path, function, marker, occurrence=0):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        assert end is not None
        body = source[start:end + 1]
        offset = -len(marker)
        for _ in range(occurrence + 1):
            offset = body.index(marker, offset + len(marker))
        offset += start
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_actual_control_and_original_owner_are_the_only_callers(self):
        rows = {r.identifier: r for r in PROOF._boundary_rows(self.manifest)}
        expected = {
            "q24_original_task_observation_owner": (STATE,),
            "q24_original_task_observation_state": (AGENT + "state_control.rs",),
            "q24_original_task_observation_client": (),
        }
        paths = {OWNER, STATE, CLIENT, AGENT + "state_control.rs"}
        index = {p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / p).read_text())) for p in paths}
        for identifier, callers in expected.items():
            row = rows[identifier]
            with self.subTest(identifier=identifier):
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, index, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), index, ())

    def test_query_requires_live_cell_current_and_original_source_twice(self):
        for marker in (
            "OriginalTaskCustodyV1::Active { cell, .. }",
            "let captured = self.capture(&mut state)?",
            "let before = cell",
            "if cell.committed(&captured.publication)",
            "})? != before",
        ):
            with self.subTest(marker=marker):
                self.rejects(OWNER, "fn read_original_task_observation(", marker)
        for occurrence in (0, 1):
            self.rejects(OWNER, "fn read_original_task_observation(",
                         "self.require_source(&captured)?", occurrence)

    def test_exact_signed_decision_and_current_observer_are_mandatory(self):
        for marker in (
            "let status = self.status(&mut state, &ledger, &captured)?",
            "decision_signing_payload_v2(&captured.decision)?",
            "payload.len() > MAX_Q24_DECISION_PREIMAGE_BYTES",
            "source_publication_digest: captured.publication.publication_digest().to_string()",
            "decision_preimage_hex: control::hex(&payload)",
            "self.status(&mut state, &ledger, &captured)? != status",
        ):
            with self.subTest(marker=marker):
                self.rejects(OWNER, "fn read_original_task_observation(", marker)
        for occurrence in (0, 1):
            self.rejects(OWNER, "fn read_original_task_observation(",
                         "ledger.verifier().require_signer_binding(", occurrence)

    def test_same_installed_identity_and_current_state_bracket_query(self):
        for marker in (
            "self.original_q24_outcome_control.get().ok_or_else(",
            "producer.require_original_control_identity(&self.identity)?",
            "let observed = producer.read_original_task_observation()",
        ):
            with self.subTest(marker=marker):
                self.rejects(STATE, "fn read_original_q24_control_task(", marker)
        for occurrence in (0, 1):
            self.rejects(STATE, "fn read_original_q24_control_task(",
                         "self.require_original_q24_outcome_current()?", occurrence)

    def test_client_cannot_select_another_run_owner_or_generation(self):
        for marker in (
            "spawn_generation: self.spawn_generation",
            "method: crate::AgentdMethod::Q24OriginalTaskObservation {}",
            "AgentdPayload::Q24OriginalTaskObservation(observed) => Ok(observed)",
            "payload => unexpected(payload)",
        ):
            with self.subTest(marker=marker):
                self.rejects(CLIENT, "fn original_q24_task_observation(", marker)


if __name__ == "__main__":
    unittest.main()
