"""Status receipts cannot turn missing, skipped, or zero-test runs green."""
import tempfile
from pathlib import Path
import unittest

from scripts.hepta_inference_status import REQUIRED, read_junit, summarize


class ReceiptTests(unittest.TestCase):
    def test_missing_and_non_success_steps_block(self):
        good = {name: {"outcome": "success"} for name in REQUIRED}
        self.assertTrue(summarize(good)[1])
        for name in REQUIRED:
            for outcome in ("skipped", "failure", "cancelled", "neutral", True, {}):
                with self.subTest(name=name, outcome=outcome):
                    self.assertFalse(summarize({**good, name: {"outcome": outcome}})[1])
            incomplete = dict(good)
            incomplete.pop(name)
            self.assertFalse(summarize(incomplete)[1])

    def test_junit_requires_real_non_skipped_successful_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("infer_core", "worker", "agentd"):
                (root / f"{name}.xml").write_text(
                    '<testsuites><testsuite><testcase name="observed"/></testsuite></testsuites>'
                )
            self.assertTrue(read_junit(root)[1])
            for invalid in (
                '<testsuites/>',
                '<testsuite><testcase><skipped/></testcase></testsuite>',
                '<testsuite><testcase><failure/></testcase></testsuite>',
                '<testsuite><error/><testcase/></testsuite>',
                'not xml',
            ):
                (root / "worker.xml").write_text(invalid)
                self.assertFalse(read_junit(root)[1])
            (root / "worker.xml").unlink()
            self.assertFalse(read_junit(root)[1])


if __name__ == "__main__":
    unittest.main()
