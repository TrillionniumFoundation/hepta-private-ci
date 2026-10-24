import tempfile
import unittest
from pathlib import Path

from operational_cohort_plan import command_specs, decode, properties


class OperationalPlanTests(unittest.TestCase):
    def test_upstream_commands_preserve_independent_selectors(self):
        self.assertEqual(command_specs("python -m unittest -q test.foo.C.test_a test.foo.C.test_b\npytest -q -s tests/a.py::C::test_x"), [
            {"original": "python -m unittest -q test.foo.C.test_a test.foo.C.test_b", "runner": "unittest", "nodes": ["test.foo.C.test_a", "test.foo.C.test_b"]},
            {"original": "pytest -q -s tests/a.py::C::test_x", "runner": "pytest", "nodes": ["tests/a.py::C::test_x"]}])

    def test_shell_and_unapproved_runner_are_rejected(self):
        for text in ("pytest tests/a.py; touch nope", "pytest --override-ini=x a.py", "tox a.py", "pytest", "python -c malicious"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                command_specs(text)

    def test_real_metadata_whitespace_and_utf16(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "metadata"
            p.write_text('fixed_commit_id ="abc"\npython_version="3.8.1"\n')
            self.assertEqual(properties(p), {"fixed_commit_id": "abc", "python_version": "3.8.1"})
            p.write_bytes("pytest==5.4.3\r\n".encode("utf-16"))
            self.assertEqual(decode(p), "pytest==5.4.3\r\n")


if __name__ == "__main__":
    unittest.main()
