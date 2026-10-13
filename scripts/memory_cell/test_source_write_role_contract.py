"""Fail early if the source-effects executable and integration test swap paths.

This statically checks source ownership before loading models, original
evidence or an owner environment. It does not judge learned task quality.
"""

import ast
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent


def definitions(name):
    path = HERE / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("source-effects file must be a regular owned file")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    classes = {
        node.name for node in tree.body if isinstance(node, ast.ClassDef)
    }
    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if node.module == "source_write_effects"
    }
    self_import = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "source_write_effects"
        for node in tree.body
    )
    return tree, functions, classes, imports, self_import


class SourceWriteModuleRoleTests(unittest.TestCase):
    def test_production_module_not_replaced_by_its_integration_test(self):
        tree, funcs, classes, imported, self_import = definitions(
            "source_write_effects.py"
        )
        self.assertTrue(
            {"number", "procedure_equal", "align_records", "effects", "audit"}
            <= funcs
        )
        self.assertNotIn("SourceWriteAuditTests", classes)
        self.assertFalse(self_import)
        self.assertEqual(imported, set())
        # The production module must still declare its seven-arm controls.
        self.assertTrue(
            any(
                isinstance(node, ast.Assign)
                and any(
                    isinstance(name, ast.Name) and name.id == "ARMS"
                    for name in node.targets
                )
                for node in tree.body
            )
        )

    def test_integration_suite_imports_production_without_defining_audit(self):
        _, funcs, classes, imported, self_import = definitions(
            "test_source_write_audit.py"
        )
        self.assertIn("SourceWriteAuditTests", classes)
        self.assertTrue(self_import)
        self.assertTrue({"ARMS", "audit", "procedure_equal"} <= imported)
        self.assertNotIn("audit", funcs)
        self.assertNotIn("effects", funcs)

    def test_runtime_source_effect_contract_exports_are_callable(self):
        from source_write_effects import ARMS, audit, align_records, effects

        self.assertEqual(
            tuple(ARMS),
            (
                "hybrid",
                "organized",
                "knowledge",
                "parameter_only",
                "empty",
                "policy_initial",
                "policy",
            ),
        )
        for function in (audit, align_records, effects):
            self.assertTrue(callable(function))


if __name__ == "__main__":
    unittest.main()
