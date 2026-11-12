"""Original paired Product closure, with unchanged legacy estimators and owners.

Source proof only. Synthetic mechanisms, statistical reachability and actual
ordinary B/retention/selection authority are separate evidence domains.
"""
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

from rust_source_marker_support import _tokens, source_marker_span

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = (
    "qualification/learn-ordinary-ce434/paired-product-domain-20261112/guard-contract.json"
)
SPEC = importlib.util.spec_from_file_location(
    "paired_product_original_source_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


class OriginalPairedProductSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / CONTRACT).read_text())
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def function(self, source, marker):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(marker), 1, marker)
        start = code.index(marker)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        self.assertEqual(code[end], "}")
        body = code[start:end + 1]
        cursor = len(marker)
        while nested := re.search(r"\bfn\s+(?:r#)?\w+", body[cursor:]):
            first = cursor + nested.start()
            after = PROOF._rust_item_end(body, first)
            self.assertIsNotNone(after)
            body = body[:first] + "".join(
                "\n" if char == "\n" else " " for char in body[first:after + 1]
            ) + body[after + 1:]
            cursor = after + 1
        return start, end, body

    def verifies(self, path, source):
        rows = [row for row in self.contract["rows"] if row["path"] == path]
        self.assertEqual(len(rows), 1, path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
        for literal in self.contract["literal_markers"]:
            if literal["path"] != path:
                continue
            start, end, body = self.function(source, literal["function"])
            try:
                first, after = source_marker_span(source, literal["marker"], start, end + 1)
            except ValueError as error:
                raise AssertionError(("missing original code literal", literal)) from error
            self.assertLessEqual(after, end + 1)
            self.assertEqual(body[first - start], source[first])
            self.assertTrue(body[first - start].strip(), literal)
        return rows

    def rejects(self, case):
        source = (ROOT / case["path"]).read_text()
        start, end, _ = self.function(source, case["function"])
        first, after = source_marker_span(source, case["marker"], start, end + 1)
        self.verifies(case["path"], source)
        with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
            self.verifies(case["path"], source[:first] + source[after:])

    def test_complete_records_and_actual_composed_callers_are_installed(self):
        for row in self.contract["rows"]:
            with self.subTest(path=row["path"]):
                self.assertEqual(self.manifest["protected_file"].count(row), 1)
                for sequence in [
                    *row["required_order"],
                    *[item["sequence"] for item in row["required_function_order"]],
                ]:
                    self.assertIsInstance(sequence, list)
                    self.assertGreaterEqual(len(sequence), 2)
                self.verifies(row["path"], (ROOT / row["path"]).read_text())
        actual = {row["id"]: row for row in self.manifest["boundary"]}
        expected = {row["id"]: row for row in self.contract["boundary"]["additions"]}
        producer = ROOT / "codex-rs/hepta-agentd/src/neuron_cell_evaluation_on_policy.rs"
        if producer.is_file():
            for change in self.contract["boundary"]["composition_extensions"]:
                for path in change["new_actual_callers"]:
                    self.assertTrue((ROOT / path).is_file())
                expected[change["after"]["id"]] = change["after"]
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for identifier, row in expected.items():
            with self.subTest(boundary=identifier):
                self.assertEqual(actual[identifier], row)
                self.assertEqual(inventory.count(identifier), 1)
                for path in row["product_callers"]:
                    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
                        (ROOT / path).read_text()))
                    pattern = row.get("call_pattern", re.escape(row["symbol"]) + r"\s*\(")
                    self.assertRegex(code, pattern)

    def test_frozen_protocol_and_temporal_parameters_cannot_drift(self):
        for case in self.contract["mutations"]:
            if case["category"] == "frozen_protocol":
                with self.subTest(case=case):
                    self.rejects(case)

    def test_original_run_source_outcome_and_principal_identities_cannot_merge(self):
        for case in self.contract["mutations"]:
            if case["category"] == "actual_identities":
                with self.subTest(case=case):
                    self.rejects(case)

    def test_single_original_consumption_and_signed_qualification_path_remain(self):
        for case in self.contract["mutations"]:
            if case["category"] == "original_owner":
                with self.subTest(case=case):
                    self.rejects(case)

    def test_complete_paired_body_and_legacy_mode_are_not_interchangeable(self):
        for case in self.contract["mutations"]:
            if case["category"] == "mode_and_codec":
                with self.subTest(case=case):
                    self.rejects(case)

    def test_original_confidence_bounds_and_strict_roles_cannot_be_softened(self):
        for case in self.contract["mutations"]:
            if case["category"] == "original_statistics":
                with self.subTest(case=case):
                    self.rejects(case)

    def test_domains_are_actual_literals_in_the_original_functions(self):
        for literal in self.contract["literal_markers"]:
            source = (ROOT / literal["path"]).read_text()
            start, end, _ = self.function(source, literal["function"])
            first, after = source_marker_span(source, literal["marker"], start, end + 1)
            with self.subTest(literal=literal):
                self.verifies(literal["path"], source)
                mutated = source[:first] + source[first:after].replace(
                    "v1", "v9"
                ).replace("HPEXRP01", "HPEXRP09").replace(
                    "HPEXR001", "HPEXR009"
                ).replace("HPEXEV01", "HPEXEV09") + source[after:]
                self.assertNotEqual(mutated, source)
                with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
                    self.verifies(literal["path"], mutated)
                # The correct old text hidden in a comment is not an actual
                # code literal and cannot repair the changed original domain.
                decoy = mutated[:start] + "// " + literal["marker"] + "\n" + mutated[start:]
                with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
                    self.verifies(literal["path"], decoy)

    def test_original_shared_function_code_is_preserved(self):
        for original in self.contract["legacy_functions"]:
            source = (ROOT / original["path"]).read_text()
            _, _, body = self.function(source, original["function"])
            with self.subTest(function=original["function"]):
                self.assertEqual([token[0] for token in _tokens(body)],
                                 original["masked_code_tokens"])

    def test_pure_pair_metadata_cannot_mint_authority_or_reconnect(self):
        for row in self.contract["rows"]:
            source = (ROOT / row["path"]).read_text()
            for injection in (
                "\nfn bypass() { SigningKey::generate(); }\n",
                "\nfn bypass() { UnixStream::connect(); }\n",
                "\nfn bypass() { LearningEvidenceVerifierV1::new(); }\n",
                "\nfn bypass() { original.maximum_weight = replacement; }\n",
                "\nfn bypass() { original.family_alpha_ppm = replacement; }\n",
            ):
                with self.subTest(path=row["path"], injection=injection):
                    with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
                        self.verifies(row["path"], source + injection)


if __name__ == "__main__":
    unittest.main()
