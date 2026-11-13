"""Protect the exact ordinary owner/Source/loader integration and original lanes.

These are source-integrity checks. They never establish real A/B/C utility,
authorization, independent outcomes, successful native tests, or cold recovery.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SHA256 = "c7e8c29b0ad9a1c214dcabb661b4c1943b626b9a813a46da5ebf511ec27a4ac6"

def pin(body):
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

class OrdinaryLearningProductSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = (ROOT / "qa/b4-no-bypass/ORDINARY_LEARNING_PRODUCT_SOURCE_CONTRACT.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != CONTRACT_SHA256:
            raise AssertionError("complete ordinary source contract differs")
        cls.contract = json.loads(raw)
        cls.callers_raw = (ROOT / "CALLERS.toml").read_bytes()
        cls.callers = tomllib.loads(cls.callers_raw.decode())

    def test_complete_source_bytes_exclude_extra_owner_and_clock_escape(self):
        for path, expected in self.contract["source_files"].items():
            with self.subTest(path=path):
                self.assertEqual(pin((ROOT / path).read_bytes()), expected)
        self.assertFalse(self.contract["qualification"])
        self.assertEqual(self.contract["real_qualified_chains"], 0)

    def test_exact_callers_keep_original_rules_and_forbidden_fields(self):
        self.assertEqual(pin(self.callers_raw), self.contract["CALLERS"])
        self.assertEqual(len(self.callers["boundary"]), self.contract["boundary_count"])
        self.assertEqual(len(self.callers["protected_file"]), self.contract["protected_count"])
        for key, value in self.contract["original_rules"].items():
            self.assertEqual(self.callers[key], value)
        boundaries = [{k: v for k, v in row.items() if k != "product_callers"}
                      for row in self.callers["boundary"][:650]]
        guards = [{k: v for k, v in row.items() if k != "required"}
                  for row in self.callers["protected_file"][:451]]
        self.assertEqual(hashlib.sha256(canonical(boundaries)).hexdigest(),
                         self.contract["original_650_noncaller_rows_sha256"])
        self.assertEqual(hashlib.sha256(canonical(guards)).hexdigest(),
                         self.contract["original_451_nonrequired_rows_sha256"])
        ids = [row["id"] for row in self.callers["boundary"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(self.callers["privileged_inventory"]["required_boundary_ids"]))
        self.assertTrue(all(value is False for value in self.callers["authority"].values()))

    def test_original_root_selection_is_preserved_with_exact_new_names(self):
        raw = (ROOT / ".github/workflows/hepta-daemon-learning-native.yml").read_bytes()
        self.assertEqual(pin(raw), self.contract["workflow"])
        match = re.search(r"parents = (\[[\s\S]*?\n          \])", raw.decode())
        self.assertIsNotNone(match)
        parents = ast.literal_eval(match.group(1))
        self.assertEqual(parents, self.contract["workflow_parents"])
        original = self.contract["original_workflow_parents"]
        self.assertEqual(parents[:len(original)], original)
        self.assertEqual(len(parents), len(set(parents)))
        for case in self.contract["additional_root_tests"]:
            with self.subTest(case=case["name"]):
                source = (ROOT / case["path"]).read_text()
                self.assertIn("fn " + case["name"].rsplit("::", 1)[-1] + "(", source)
                self.assertIn(case["ignore_attribute"], source)
                self.assertIn(case["name"], parents)

if __name__ == "__main__":
    unittest.main()
