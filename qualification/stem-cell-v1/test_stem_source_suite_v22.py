"""Mechanism regressions for V22 real source/physical test separation."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from stem_source_suite_v22 import ORIGINAL_EVIDENCE, SCHEMA, inventory, run


def fixture(tmp: str):
    root = Path(tmp)
    stem = root / "qualification/stem-cell-v1"
    stem.mkdir(parents=True)
    for module, workflow in ORIGINAL_EVIDENCE.items():
        # This MUST NOT be imported by the source-only runner: it is a genuine
        # external-original-material suite and fails if run without materials.
        (stem / (module + ".py")).write_text(
            "import unittest\nclass Original(unittest.TestCase):\n"
            "  @classmethod\n  def setUpClass(cls):\n"
            "    raise RuntimeError('original material missing')\n"
            "  def test_original(self): pass\n", encoding="utf-8")
        path = root / workflow
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "name: original-evidence\non:\n  pull_request:\n    paths: []\n"
            "steps:\n  - uses: actions/checkout@v4\n"
            "    with:\n      persist-credentials: false\n"
            "  - run: python -m unittest -q " + module + "\n", encoding="utf-8")
    (stem / "test_source_real.py").write_text(
        "import unittest\nclass Real(unittest.TestCase):\n"
        "  def test_true(self): self.assertEqual(1+1,2)\n", encoding="utf-8")
    return root, stem


class SourceSeparation(unittest.TestCase):
    def test_original_backed_suites_are_not_source_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, stem = fixture(tmp)
            got = inventory(root)
            self.assertEqual(got["source_modules"], ("test_source_real",))
            self.assertEqual(set(got["original_required"]), set(ORIGINAL_EVIDENCE))
            receipt = root / "research.json"
            self.assertEqual(run(root, receipt), 0)
            out = json.loads(receipt.read_text())
            self.assertEqual(out["source_selected_assertions"], 1)
            self.assertFalse(out["production_authorized"])
            self.assertFalse(out["original_material_ran_here"])
            self.assertEqual(out["decision"], "SOURCE_ONLY_DOES_NOT_QUALIFY_ORIGINAL_MODEL")
            self.assertEqual(out["source_skips"], [])

    def test_real_source_failure_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, stem = fixture(tmp)
            (stem / "test_source_real.py").write_text(
                "import unittest\nclass Real(unittest.TestCase):\n"
                "  def test_fail(self): self.fail('real regression')\n", encoding="utf-8")
            receipt = root / "negative.json"
            self.assertEqual(run(root, receipt), 1)
            self.assertEqual(json.loads(receipt.read_text())["source_failures"], 1)

    def test_original_required_module_cannot_disappear(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, stem = fixture(tmp)
            (stem / "test_v20_original_training.py").unlink()
            self.assertRaises(ValueError, inventory, root)

    def test_original_required_workflow_cannot_disappear(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, stem = fixture(tmp)
            (root / ORIGINAL_EVIDENCE["test_v21_banking77_original"]).unlink()
            self.assertRaises(ValueError, inventory, root)

    def test_original_workflow_must_run_test_not_merely_list_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, stem = fixture(tmp)
            p = root / ORIGINAL_EVIDENCE["test_v19_original_replay"]
            p.write_text("on:\n  pull_request:\n    paths:\n"
                         "      - test_v19_original_replay.py\n"
                         "persist-credentials: false\n", encoding="utf-8")
            self.assertRaises(ValueError, inventory, root)

    def test_unclassified_nested_test_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, stem = fixture(tmp)
            sub = stem / "nested"
            sub.mkdir()
            (sub / "test_hidden.py").write_text("import unittest\n")
            self.assertRaises(ValueError, inventory, root)

    def test_unknown_new_source_test_is_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, stem = fixture(tmp)
            (stem / "test_new_case.py").write_text(
                "import unittest\nclass Extra(unittest.TestCase):\n"
                "  def test_real(self): self.assertTrue(True)\n", encoding="utf-8")
            selected = inventory(root)["source_modules"]
            self.assertEqual(set(selected), {"test_source_real", "test_new_case"})

    def test_source_skip_is_visible_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, stem = fixture(tmp)
            (stem / "test_source_real.py").write_text(
                "import unittest\nclass Real(unittest.TestCase):\n"
                "  @unittest.skip('missing optional original weights')\n"
                "  def test_optional(self): pass\n", encoding="utf-8")
            p = root / "skipped.json"
            self.assertEqual(run(root, p), 0)
            r = json.loads(p.read_text())
            self.assertEqual(len(r["source_skips"]), 1)
            self.assertFalse(r["original_material_ran_here"])

    def test_exact_schema(self):
        self.assertEqual(SCHEMA, "hepta.stem.v22.source-and-original-coverage.v1")


if __name__ == "__main__":
    unittest.main()
