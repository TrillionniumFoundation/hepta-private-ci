"""Regression tests for the split source-location and production status facts."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hepta_module_docs_status", ROOT / "scripts/hepta-module-docs.py"
)
MODULE_DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_DOCS)


class ImplementationStatusValidationTests(unittest.TestCase):
    def setUp(self):
        self.module = {
            "id": "fixture.owner",
            "source_root_present": True,
            "production_implementation": False,
        }
        self.mapping = {
            "module": "fixture.owner",
            "sourceRootPresent": True,
            "productionImplementation": False,
            "claimBoundary": {
                "sourceRootPresent": True,
                "productionImplementation": False,
                "activation": False,
                "release": False,
            },
        }

    def test_matching_product_facts_do_not_require_activation(self):
        for production in (False, True):
            with self.subTest(production=production):
                self.module["production_implementation"] = production
                self.mapping["productionImplementation"] = production
                self.mapping["claimBoundary"]["productionImplementation"] = production
                MODULE_DOCS.verify_implementation_status(self.module, self.mapping)

    def test_conflicting_registry_map_or_claim_facts_are_rejected(self):
        for field in ("sourceRootPresent", "productionImplementation"):
            for location in ("map", "claim"):
                with self.subTest(field=field, location=location):
                    mapping = copy.deepcopy(self.mapping)
                    target = mapping if location == "map" else mapping["claimBoundary"]
                    target[field] = not target[field]
                    with self.assertRaisesRegex(SystemExit, "status agreement"):
                        MODULE_DOCS.verify_implementation_status(self.module, mapping)

    def test_missing_untyped_or_foreign_map_is_rejected(self):
        mutations = [
            {"module": "other.owner"},
            {"productionImplementation": 0},
            {"sourceRootPresent": None},
            {"claimBoundary": None},
            {"claimBoundary": {}},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(SystemExit):
                    MODULE_DOCS.verify_implementation_status(
                        self.module, self.mapping | mutation
                    )


class ModuleStatusFactsTests(unittest.TestCase):
    def test_all_module_projections_are_explicit_and_consistent(self):
        modules = json.loads((ROOT / "docs/modules/MODULES.json").read_text())[
            "modules"
        ]
        bindings = json.loads((ROOT / "docs/modules/SOURCE_BINDINGS.json").read_text())[
            "bindings"
        ]
        documents = json.loads((ROOT / "docs/modules/MODULE_DOCS.json").read_text())[
            "modules"
        ]
        by_id = {row["id"]: row for row in modules}
        by_binding = {row["module"]: row for row in bindings}
        by_document = {row["module"]: row for row in documents}
        self.assertTrue(by_id)
        self.assertEqual(len(by_id), len(modules))
        self.assertEqual(len(by_binding), len(bindings))
        self.assertEqual(len(by_document), len(documents))
        self.assertEqual(set(by_id), set(by_binding))
        self.assertEqual(set(by_id), set(by_document))
        for module_id, module in by_id.items():
            projected = [module, by_binding[module_id], by_document[module_id]]
            self.assertTrue(
                all(type(row["source_root_present"]) is bool for row in projected)
            )
            self.assertTrue(
                all(type(row["production_implementation"]) is bool for row in projected)
            )
            self.assertEqual({row["source_root_present"] for row in projected}, {True})
            self.assertEqual(
                len({row["production_implementation"] for row in projected}), 1
            )
            self.assertFalse(
                module["production_implementation"]
                and not module["source_root_present"]
            )

    def test_status_model_declares_the_split_facts(self):
        model = json.loads((ROOT / "docs/readiness/STATUS_MODEL.json").read_text())
        facts = model["moduleFacts"]
        self.assertEqual(
            set(facts),
            {"source_root_present", "production_implementation", "invariant"},
        )
        self.assertEqual(facts["source_root_present"]["type"], "boolean")
        self.assertEqual(facts["production_implementation"]["type"], "boolean")
        self.assertIn("source_root_present", facts["invariant"])


if __name__ == "__main__":
    unittest.main()
