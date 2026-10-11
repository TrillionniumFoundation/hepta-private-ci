"""Closed-world organ/module projection fixtures."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("cns_verifier", ROOT / "scripts/hepta-cns.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class ModuleBindingClosedWorldTests(unittest.TestCase):
    def setUp(self):
        architecture = json.loads((ROOT / VERIFIER.ARCH_PATH).read_text())
        modules = json.loads((ROOT / "docs/modules/MODULES.json").read_text())["modules"]
        self.organs = architecture["organs"]
        self.module_ids = {row["id"] for row in modules}
        self.references = architecture["qualificationReferences"]

    def test_real_registry_projects_all_modules_and_reference_only_binding(self):
        registered, references = VERIFIER.validate_module_bindings(
            self.organs, self.module_ids, self.references
        )
        self.assertEqual(len(registered), 40)
        self.assertEqual(references, {"hnmf.reference"})

    def test_unknown_binding_is_rejected(self):
        organs = copy.deepcopy(self.organs)
        organs[0]["moduleBindings"].append("ghost.module")
        with self.assertRaisesRegex(SystemExit, "unknown organ module binding"):
            VERIFIER.validate_module_bindings(organs, self.module_ids, self.references)

    def test_missing_registered_module_is_rejected(self):
        organs = copy.deepcopy(self.organs)
        for organ in organs:
            organ["moduleBindings"] = [
                module
                for module in organ["moduleBindings"]
                if module != "kernel.authority"
            ]
        with self.assertRaisesRegex(SystemExit, "unbound registered module"):
            VERIFIER.validate_module_bindings(organs, self.module_ids, self.references)

    def test_reference_must_be_declared_and_bound(self):
        refs = copy.deepcopy(self.references)
        refs.append(
            {
                "id": "unbound.reference",
                "root": "qualification/unbound-reference",
                "scope": "qualification_only_not_production_module",
            }
        )
        with self.assertRaisesRegex(SystemExit, "unbound qualification reference"):
            VERIFIER.validate_module_bindings(self.organs, self.module_ids, refs)

        refs = copy.deepcopy(self.references)
        self.organs[9]["moduleBindings"].remove("hnmf.reference")
        with self.assertRaisesRegex(SystemExit, "unbound qualification reference"):
            VERIFIER.validate_module_bindings(self.organs, self.module_ids, refs)


if __name__ == "__main__":
    unittest.main()
