import runpy
from pathlib import Path
import unittest

MODULE = runpy.run_path(str(Path(__file__).with_name("ui-control-rust-receipt.py")))


class ReceiptTests(unittest.TestCase):
    def test_exact_head_and_ordered_merge(self):
        a, b, c = "a" * 40, "b" * 40, "c" * 40
        MODULE["verify_subject"]("head", a, a, b, [a, b])
        MODULE["verify_subject"]("merge", c, a, b, [c, b, a])
        for kind, evaluated, parents in [("head", c, [c, b]), ("merge", c, [c, a, b]), ("merge", c, [c, b, a, a])]:
            with self.assertRaises(ValueError):
                MODULE["verify_subject"](kind, evaluated, a, b, parents)

    def test_requires_nonempty_complete_unambiguous_execution(self):
        text = "Summary [ 1.2s] 64 tests run: 64 passed, 0 skipped"
        self.assertEqual(MODULE["summary"](text), {"run": 64, "passed": 64, "skipped": 0})
        with self.assertRaises(ValueError):
            MODULE["summary"](text, minimum=65)
        for invalid in ["", text + "\n" + text, text.replace("64 passed", "63 passed"), text.replace("0 skipped", "1 skipped"), "Summary [1s] 0 tests run: 0 passed, 0 skipped"]:
            with self.assertRaises(ValueError):
                MODULE["summary"](invalid)
