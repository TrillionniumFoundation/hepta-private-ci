"""Bind a complete immutable policy before T and recheck the actual B plan.

Source deletion controls and metadata mechanisms do not establish an Evaluator
execution grant, an A-before-launcher invocation, or a Qualified ordinary panel.
"""
from collections import Counter
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
CONTRACT = ROOT / "qualification/learn-ordinary-ce434/pre-b-agentd-policy-v2-20261112/closure-contract.json"
SPEC = importlib.util.spec_from_file_location(
    "original_pre_b_policy_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"


def function(source, marker):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if code.count(marker) != 1:
        raise AssertionError(("one actual function", marker))
    first = code.index(marker)
    opening = code.index("{", first)
    depth = 1
    end = opening + 1
    while end < len(code) and depth:
        depth += (code[end] == "{") - (code[end] == "}")
        end += 1
    if depth:
        raise AssertionError(("complete actual function", marker))
    return first, end, code[first:end]


def actual_marker(source, marker, method=None):
    start, end = (0, len(source)) if method is None else function(source, method)[:2]
    try:
        first, last = source_marker_span(source, marker, start, end)
    except ValueError as error:
        raise AssertionError(("actual policy marker", marker)) from error
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    masked = PROOF._strip_rust_non_code(marker)
    if not masked.strip() or re.sub(r"\s+", "", code[first:last]) != re.sub(r"\s+", "", masked):
        raise AssertionError(("marker must be actual executable syntax", marker))
    return first, last


class OriginalPreBPolicyClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text())
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = cls.contract["added_protected_records"] + [
            edit["after"] for edit in cls.contract["protected_record_replacements"]
        ]
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def verifies(self, row, source):
        for sequence in row.get("required_order", []):
            if sequence[0].startswith("fn "):
                body = function(source, sequence[0])[2]
                cursor = 0
                for marker in sequence:
                    found = body.find(marker, cursor)
                    if found < cursor:
                        raise AssertionError(("guard outside original function", marker))
                    cursor = found + len(marker)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / row["path"]
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": [row]})

    def rejects(self, row, source):
        with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
            self.verifies(row, source)

    def test_complete_records_are_preserved_as_a_multiset(self):
        canonical = lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"))
        actual = Counter(map(canonical, self.manifest["protected_file"]))
        expected = Counter(map(canonical, self.rows))
        self.assertFalse(expected - actual)
        for row in self.rows:
            with self.subTest(path=row["path"]):
                self.verifies(row, (ROOT / row["path"]).read_text())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_original_v2_callers_are_closed(self):
        paths = {row["path"] for row in self.rows}
        for expected in self.contract["added_boundaries"]:
            paths.add(expected["definition_path"])
            paths.update(expected["product_callers"])
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in paths
        }
        for expected in self.contract["added_boundaries"]:
            row = self.boundaries[expected["id"]]
            with self.subTest(boundary=row.identifier):
                self.assertEqual(row.product_callers, tuple(expected["product_callers"]))
                self.assertIn(row.identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                extra = dict(sources)
                method = row.symbol.rsplit("::", 1)[-1]
                extra[AGENT + "unregistered_pre_b_policy.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                    if row.receiver_type else f"fn bypass() {{ {row.symbol}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_actual_policy_guards_cannot_move_to_comments(self):
        for row in self.rows:
            source = (ROOT / row["path"]).read_text()
            scopes = [
                (item["function"], item["sequence"])
                for item in row.get("required_function_order", [])
            ] + [
                (sequence[0], sequence)
                for sequence in row.get("required_order", [])
                if sequence[0].startswith("fn ")
            ]
            for method, sequence in scopes:
                first, _, body = function(source, method)
                markers = [value for value in sequence
                           if body.count(value) == 1 and not value.startswith("fn ")
                           and value not in ("Ok(())", "&self")]
                self.assertTrue(markers, (row["path"], method))
                marker = max(markers, key=len)
                offset = first + body.index(marker)
                with self.subTest(path=row["path"], method=method):
                    self.rejects(row, source[:offset] + source[offset + len(marker):]
                                 + "\n/* " + marker + " */\n")

    def test_complete_policy_domains_and_json_fields_are_actual_syntax(self):
        for check in self.contract["actual_literal_markers"]:
            source = (ROOT / check["path"]).read_text()
            with self.subTest(path=check["path"], marker=check["marker"]):
                first, last = actual_marker(source, check["marker"], check["function"])
                changed = source[:first] + source[last:]
                changed += "\n/* " + check["marker"] + " */\n"
                with self.assertRaises(AssertionError):
                    actual_marker(changed, check["marker"], check["function"])

    def test_no_legacy_upgrade_or_post_b_policy_substitution(self):
        for check in self.contract["semantic_mutations"]:
            rows = [row for row in self.rows if row["path"] == check["path"]]
            source = (ROOT / check["path"]).read_text()
            start, end, _ = function(source, check["function"])
            first, last = source_marker_span(source, check["marker"], start, end)
            changed = source[:first] + check["replacement"] + source[last:]
            with self.subTest(path=check["path"], marker=check["marker"]):
                self.assertNotEqual(changed, source)
                self.assertTrue(rows)
                for row in rows:
                    self.verifies(row, source)
                rejected = False
                for row in rows:
                    try:
                        self.verifies(row, changed)
                    except (PROOF.VerificationFailure, AssertionError):
                        rejected = True
                self.assertTrue(rejected, check)

    def test_metadata_never_creates_original_owner_authority(self):
        for row in self.contract["added_protected_records"]:
            source = (ROOT / row["path"]).read_text()
            for marker in row["forbidden"]:
                with self.subTest(path=row["path"], forbidden=marker):
                    self.rejects(row, source + "\n" + marker + "\n")


if __name__ == "__main__":
    unittest.main()
