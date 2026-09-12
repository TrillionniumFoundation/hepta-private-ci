"""Regression tests for the split source-location and production status facts."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ModuleStatusFactsTests(unittest.TestCase):
    def test_all_module_projections_are_explicit_and_consistent(self):
        modules = json.loads((ROOT / "docs/modules/MODULES.json").read_text())["modules"]
        bindings = json.loads((ROOT / "docs/modules/SOURCE_BINDINGS.json").read_text())["bindings"]
        documents = json.loads((ROOT / "docs/modules/MODULE_DOCS.json").read_text())["modules"]
        by_id = {row["id"]: row for row in modules}
        by_binding = {row["module"]: row for row in bindings}
        by_document = {row["module"]: row for row in documents}
        self.assertEqual(len(by_id), 40)
        self.assertEqual(set(by_id), set(by_binding))
        self.assertEqual(set(by_id), set(by_document))
        for module_id, module in by_id.items():
            projected = [module, by_binding[module_id], by_document[module_id]]
            self.assertTrue(all(type(row["source_root_present"]) is bool for row in projected))
            self.assertTrue(all(type(row["production_implementation"]) is bool for row in projected))
            self.assertEqual({row["source_root_present"] for row in projected}, {True})
            self.assertEqual({row["production_implementation"] for row in projected}, {False})
            self.assertFalse(
                module["production_implementation"] and not module["source_root_present"]
            )

    def test_status_model_declares_the_split_facts(self):
        model = json.loads((ROOT / "docs/readiness/STATUS_MODEL.json").read_text())
        facts = model["moduleFacts"]
        self.assertEqual(
            set(facts), {"source_root_present", "production_implementation", "invariant"}
        )
        self.assertEqual(facts["source_root_present"]["type"], "boolean")
        self.assertEqual(facts["production_implementation"]["type"], "boolean")
        self.assertIn("source_root_present", facts["invariant"])


if __name__ == "__main__":
    unittest.main()
