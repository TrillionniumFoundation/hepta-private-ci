"""Pinned gated Root/Candidate suffix closure; no native or ordinary claim.

The fixed Model proof contains five receipts and four original role signatures.
Selection and NextUse extend that proof through distinct original owners.
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

from rust_source_marker_support import source_marker_span

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    "qualification/learn-ordinary-ce434/positive-root-route-20261112/guard-contract.json"
)
SPEC = importlib.util.spec_from_file_location(
    "positive_root_suffix_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


class OriginalPositiveRootSuffixClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / CONTRACT_PATH).read_text())
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def verifies(self, path, source):
        rows = [row for row in self.contract["rows"] if row["path"] == path]
        self.assertEqual(len(rows), 1, path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, case):
        path, function = case["path"], case["function"]
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        first, after = source_marker_span(source, case["marker"], start, end + 1)
        self.verifies(path, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, source[:first] + source[after:])

    def test_complete_guard_records_and_exact_caller_delta_are_installed(self):
        for row in self.contract["rows"]:
            with self.subTest(path=row["path"]):
                self.assertEqual(self.manifest["protected_file"].count(row), 1)
                self.verifies(row["path"], (ROOT / row["path"]).read_text())
        actual = {row["id"]: row for row in self.manifest["boundary"]}
        expected = [
            *[change["after"] for change in self.contract["boundary"]["changes"]],
            *self.contract["boundary"]["additions"],
        ]
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for row in expected:
            with self.subTest(boundary=row["id"]):
                self.assertEqual(actual[row["id"]], row)
                self.assertEqual(inventory.count(row["id"]), 1)

    def test_fixed_model_prefix_cannot_absorb_unsigned_suffix_or_another_model(self):
        for case in self.contract["mutations"]:
            if "authority_host_learning_resident_" in case["path"]:
                with self.subTest(case=case):
                    self.rejects(case)

    def test_original_channels_model_finish_and_owner_effects_remain_real(self):
        for case in self.contract["mutations"]:
            if any(name in case["path"] for name in (
                "cell_q24_no_update_stage_state.rs",
                "cell_q24_candidate_stage_model.rs",
                "cell_q24_candidate_stage_adoption.rs",
            )):
                with self.subTest(case=case):
                    self.rejects(case)

    def test_readiness_and_full_original_s_c_evidence_remain_separate(self):
        for case in self.contract["mutations"]:
            if any(name in case["path"] for name in (
                "cell_q24_candidate_stage_next_use.rs",
                "cell_q24_candidate_stage_suffix.rs",
                "cell_q24_candidate_stage_operation.rs",
            )):
                with self.subTest(case=case):
                    self.rejects(case)

    def test_verifier_uses_original_evidence_scope_and_all_three_context_pins(self):
        for case in self.contract["mutations"]:
            if case["path"].endswith("circuit_learning_model_context.rs"):
                with self.subTest(case=case):
                    self.rejects(case)

    def test_private_adoption_data_cannot_create_signers_or_reconnect(self):
        for row in self.contract["additions"]:
            source = (ROOT / row["path"]).read_text()
            self.verifies(row["path"], source)
            for injection in (
                "\nfn bypass() { UnixStream::connect(); }\n",
                "\nfn bypass() { SigningKey::generate(); }\n",
                "\nfn bypass() { channel.next = 1; }\n",
                "\nfn bypass() { execution_requested = false; }\n",
            ):
                with self.subTest(path=row["path"], injection=injection):
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verifies(row["path"], source + injection)


if __name__ == "__main__":
    unittest.main()
