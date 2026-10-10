"""Behavioral coverage for changing module sets through existing consumers."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest

from hepta_module_catalog import (
    covers_module_ids,
    has_module_count,
    has_unique_module_ids,
)

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ModuleCatalogTests(unittest.TestCase):
    def setUp(self):
        self.modules = [
            row["id"]
            for row in json.loads((ROOT / "docs/modules/MODULES.json").read_text())[
                "modules"
            ]
        ]
        self.cns = load_script("hepta-cns")
        self.architecture = json.loads(
            (ROOT / "docs/cns/CNS_ARCHITECTURE.json").read_text()
        )

    def test_current_added_and_retired_modules_use_the_same_validator(self):
        variants = [
            self.modules,
            self.modules + ["extension.optional"],
            self.modules[1:],
        ]
        for identities in variants:
            with self.subTest(count=len(identities)):
                self.assertTrue(has_unique_module_ids(identities))
                self.assertTrue(has_module_count(len(identities), identities))
                self.assertTrue(
                    covers_module_ids(tuple(reversed(identities)), identities)
                )

    def test_equal_cardinality_never_substitutes_for_exact_identity(self):
        substituted = self.modules[:-1] + ["extension.substituted"]
        self.assertFalse(covers_module_ids(substituted, self.modules))
        self.assertFalse(
            covers_module_ids(self.modules + [self.modules[0]], self.modules)
        )
        self.assertFalse(covers_module_ids(self.modules[:-1], self.modules))
        self.assertFalse(
            covers_module_ids(self.modules, self.modules + [self.modules[0]])
        )

    def test_malformed_empty_and_unbounded_catalogs_reject(self):
        for values in (
            [],
            "module.name",
            [None],
            [True],
            [1],
            [["module.name"]],
            ["bad"],
            ["Module.name"],
            ["a.b\n"],
            ["a." + "b" * 128],
            ["a.b"] * 4097,
            {"a.b": 1},
        ):
            with self.subTest(values=str(values)[:60]):
                self.assertFalse(has_unique_module_ids(values))
        self.assertFalse(has_module_count(True, ["a.b"]))
        self.assertFalse(has_module_count(1.0, ["a.b"]))
        self.assertFalse(has_module_count(2, ["a.b"]))

    def test_actual_cns_binding_consumer_accepts_added_then_retired_module(self):
        architecture = copy.deepcopy(self.architecture)
        organs, refs = architecture["organs"], architecture["qualificationReferences"]
        organs[0]["moduleBindings"].append("extension.optional")
        registered, _ = self.cns.validate_module_bindings(
            organs, self.modules + ["extension.optional"], refs
        )
        self.assertIn("extension.optional", registered)
        organs[0]["moduleBindings"].remove("extension.optional")
        registered, _ = self.cns.validate_module_bindings(organs, self.modules, refs)
        self.assertEqual(registered, set(self.modules))
        removed = self.modules[-1]
        for organ in organs:
            organ["moduleBindings"] = [
                mid for mid in organ["moduleBindings"] if mid != removed
            ]
        registered, _ = self.cns.validate_module_bindings(
            organs, self.modules[:-1], refs
        )
        self.assertNotIn(removed, registered)

    def test_actual_cns_consumer_rejects_dangling_and_unbound_changes(self):
        organs, refs = (
            self.architecture["organs"],
            self.architecture["qualificationReferences"],
        )
        with self.assertRaises(SystemExit):
            self.cns.validate_module_bindings(
                organs, self.modules + ["extension.optional"], refs
            )
        with self.assertRaises(SystemExit):
            self.cns.validate_module_bindings(organs, self.modules[:-1], refs)
        with self.assertRaises(SystemExit):
            self.cns.validate_module_bindings(
                organs, self.modules + [self.modules[0]], refs
            )
        with self.assertRaises(SystemExit):
            self.cns.validate_module_bindings(
                organs, self.modules + [refs[0]["id"]], refs
            )


if __name__ == "__main__":
    unittest.main()
