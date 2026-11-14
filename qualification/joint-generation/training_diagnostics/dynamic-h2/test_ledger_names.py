"""Instantiate production ledger declarations without importing the H2 worker."""

import ast
from pathlib import Path
import unittest

from independent.accounting import WorkLedger


class LedgerDeclarationTests(unittest.TestCase):
    def test_actual_worker_ledger_names_and_caps_are_accepted(self):
        worker = Path(__file__).with_name("run_once.py")
        declarations = [node for node in ast.walk(ast.parse(worker.read_text()))
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "WorkLedger"]
        self.assertEqual(len(declarations), 2)
        names = set()
        def alternatives(node):
            if isinstance(node, ast.IfExp):
                yield from alternatives(node.body)
                yield from alternatives(node.orelse)
            else:
                yield node
        for declaration in declarations:
            self.assertEqual(len(declaration.args), 1)
            name_node = declaration.args[0]
            values = alternatives(name_node)
            options = {keyword.arg: ast.literal_eval(keyword.value) for keyword in declaration.keywords}
            for value in values:
                name = ast.literal_eval(value)
                with self.subTest(line=declaration.lineno, name=name):
                    ledger = WorkLedger(name, **options)
                    self.assertEqual(ledger.arm, name)
                    self.assertEqual(ledger.consumed_units, 0)
                    if options:
                        self.assertEqual(options, {"total_cap": 4_000_000_000})
                        self.assertEqual(ledger.remaining_units, 4_000_000_000)
                    names.add(name)
        self.assertEqual(names, {"H2-TRAIN-RD-not-qualification", "H3-TRAIN-RD-not-qualification",
                                "H4-TRAIN-RD-not-qualification", "service-reservation"})


if __name__ == "__main__":
    unittest.main()
