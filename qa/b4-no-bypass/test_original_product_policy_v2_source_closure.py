"""Pre-B Product policy closure and raw comparison, without runtime authority.

These source mutations preserve the original statistical and owner domains.
They do not prove a real preregistration, fit, B task, adoption or restart.
"""
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

from rust_source_marker_support import source_marker_span

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "qualification/learn-ordinary-ce434/pre-b-product-policy-v2-20261112/guard-contract.json"
SPEC = importlib.util.spec_from_file_location(
    "original_product_policy_v2_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


class OriginalProductPolicyV2SourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / CONTRACT).read_text())
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = cls.contract["rows"]

    def source_scope(self, source, marker):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        if marker is None:
            return 0, len(code), code
        self.assertEqual(code.count(marker), 1, marker)
        start = code.index(marker)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        self.assertEqual(code[end], "}")
        return start, end + 1, code[start:end + 1]

    def verifies(self, path, source):
        rows = [row for row in self.rows if row["path"] == path]
        self.assertTrue(rows, path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
        for literal in self.contract["literal_markers"]:
            if literal["path"] != path:
                continue
            start, end, code = self.source_scope(source, literal["function"])
            try:
                first, after = source_marker_span(source, literal["marker"], start, end)
            except ValueError as error:
                raise AssertionError(("missing actual policy literal", literal)) from error
            self.assertLessEqual(after, end)
            self.assertTrue(code[first - start].strip(), literal)
            self.assertEqual(code[first - start], source[first])
        return rows

    def rejects(self, case):
        source = (ROOT / case["path"]).read_text()
        start, end, _ = self.source_scope(source, case["function"])
        first, after = source_marker_span(source, case["marker"], start, end)
        self.verifies(case["path"], source)
        with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
            self.verifies(case["path"], source[:first] + source[after:])

    def test_complete_records_and_exact_policy_edges_are_installed(self):
        for row in self.rows:
            with self.subTest(path=row["path"]):
                self.assertEqual(self.manifest["protected_file"].count(row), 1)
                for sequence in [
                    *row["required_order"],
                    *[item["sequence"] for item in row["required_function_order"]],
                ]:
                    self.assertIsInstance(sequence, list)
                    self.assertGreaterEqual(len(sequence), 2)
                self.verifies(row["path"], (ROOT / row["path"]).read_text())
        expected = {
            row["id"]: row for row in self.contract["boundary"]["additions"]
        }
        expected.update({
            item["after"]["id"]: item["after"]
            for item in self.contract["boundary"]["replacements"]
        })
        actual = {row["id"]: row for row in self.manifest["boundary"]}
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        loaded = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        paths = {row["path"] for row in self.rows}
        for row in expected.values():
            paths.add(row["definition_path"])
            paths.update(row["product_callers"])
        index = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
                (ROOT / path).read_text())) for path in paths
        }
        for identifier, row in expected.items():
            with self.subTest(boundary=identifier):
                self.assertEqual(actual[identifier], row)
                self.assertEqual(inventory.count(identifier), 1)
                boundary = loaded[identifier]
                PROOF._verify_boundary(ROOT, boundary, index, ())
                unexpected = dict(index)
                unexpected["codex-rs/hepta-intelligence-eval/src/unregistered_policy.rs"] = (
                    "fn bypass() { " + row["symbol"] + "(); }"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, boundary, unexpected, ())

    def test_complete_pre_b_policy_and_original_normalization_cannot_be_removed(self):
        for case in self.contract["mutations"]:
            if case["category"] == "pre_b_contract":
                with self.subTest(case=case):
                    self.rejects(case)

    def test_raw_comparison_and_original_seal_bindings_cannot_be_removed(self):
        for case in self.contract["mutations"]:
            if case["category"] in ("raw_comparison", "original_seal"):
                with self.subTest(case=case):
                    self.rejects(case)
        forbidden = (
            "frozen_plan_from_commitments", "frozen_plan_receipt_seal",
            "freeze_cross_fold_plan", "freeze_cross_fold_plan_v2",
            "freeze_paired_on_policy_product_evaluation_plan_v1", "receipt_seal",
            "CrossFoldPlanReceiptV1", "ProductFrozenEvaluationPlanV1",
        )
        for member in self.contract["remote_metadata_functions"]:
            source = (ROOT / member["path"]).read_text()
            _, _, body = self.source_scope(source, member["function"])
            for name in forbidden:
                with self.subTest(member=member, forbidden=name):
                    self.assertNotRegex(body, r"\b" + re.escape(name) + r"\b")

    def test_strict_bounded_codec_and_canonical_full_values_cannot_be_removed(self):
        for case in self.contract["mutations"]:
            if case["category"] == "strict_codec":
                with self.subTest(case=case):
                    self.rejects(case)

    def test_original_domains_and_limits_are_actual_code(self):
        for literal in self.contract["literal_markers"]:
            source = (ROOT / literal["path"]).read_text()
            start, end, _ = self.source_scope(source, literal["function"])
            first, after = source_marker_span(source, literal["marker"], start, end)
            changed = source[:first] + literal["replacement"] + source[after:]
            with self.subTest(literal=literal):
                self.assertNotEqual(changed, source)
                self.verifies(literal["path"], source)
                with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
                    self.verifies(literal["path"], changed)
                decoy = "// " + literal["marker"] + "\n" + changed
                with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
                    self.verifies(literal["path"], decoy)

    def test_only_the_two_original_freezers_call_the_receipt_seal_helper(self):
        symbol = "frozen_plan_from_commitments("
        for original in self.contract["seal_helper"]["allowed_functions"]:
            source = (ROOT / original["path"]).read_text()
            _, _, body = self.source_scope(source, original["function"])
            self.assertEqual(body.count(symbol), 1, original)
        # The original verifier excludes a boundary's own definition file.
        # Account explicitly for its local original V1 call as well as V2.
        for original in self.contract["seal_helper"]["files"]:
            source = (ROOT / original["path"]).read_text()
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            spans = []
            for allowed in self.contract["seal_helper"]["allowed_functions"]:
                if allowed["path"] == original["path"]:
                    start, end, _ = self.source_scope(source, allowed["function"])
                    spans.append((start, end))
            for match in re.finditer(re.escape(symbol), code):
                if re.search(r"\bfn\s+$", code[:match.start()]):
                    continue
                self.assertTrue(any(start <= match.start() < end for start, end in spans))
            self.assertEqual(
                len([match for match in re.finditer(re.escape(symbol), code)
                     if not re.search(r"\bfn\s+$", code[:match.start()])]),
                original["calls"],
            )

    def test_policy_metadata_cannot_mint_keys_or_runtime_authority(self):
        for row in self.rows:
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
