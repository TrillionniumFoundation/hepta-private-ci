import ast
import unittest

from operational_case_views import selector_location, test_nodes, test_view


class OperationalViewTests(unittest.TestCase):
    def test_selector_binds_actual_file_not_guessed_module(self):
        files = ["tests/test_a.py", "tests/settings/__init__.py"]
        self.assertEqual(selector_location("tests.test_a.T.test_b", "unittest", files), ("tests/test_a.py", ["T", "test_b"]))
        self.assertEqual(selector_location("tests.settings.T.test_b", "unittest", files), ("tests/settings/__init__.py", ["T", "test_b"]))
        self.assertEqual(selector_location("tests/test_a.py::T::test_b", "pytest", files), ("tests/test_a.py", ["T", "test_b"]))
        with self.assertRaises(ValueError):
            selector_location("missing.T.test_b", "unittest", files)

    def test_actual_helper_fixture_closure_omits_other_test_bodies(self):
        raw = b"import unittest\nLIMIT=4\ndef read_data(name): return name\nclass T(unittest.TestCase):\n def setUp(self): self.x=LIMIT\n def assertOk(self,x): self.assertTrue(x)\n def test_a(self):\n  self.assertOk(read_data('fixture'))\n def test_b(self):\n  raise RuntimeError('unrelated_body')\n"
        files = ["tests/test_a.py", "tests/data/fixture.py"]
        view = test_view(raw, ["T", "test_a"], files[0], files, lambda path: b"actual fixture bytes\n")
        for expected in ("import unittest", "LIMIT=4", "def setUp", "def assertOk", "def read_data", "actual fixture bytes"):
            self.assertIn(expected, view["text"])
        self.assertNotIn("unrelated_body", view["text"])
        self.assertEqual(set(view["source_files"]), set(files))

    def test_comparators_are_existing_nodes_and_unresolved_inheritance_is_explicit(self):
        raw = b"def helper(): pass\ndef test_one(): pass\nclass T:\n def test_two(self): pass\n"
        self.assertEqual(test_nodes(ast.parse(raw), "tests/a.py", "pytest"), ["tests/a.py::T::test_two", "tests/a.py::test_one"])
        with self.assertRaisesRegex(ValueError, "inherited/dynamic"):
            test_view(raw, ["T", "test_absent"], "tests/a.py", ["tests/a.py"], lambda path: raw)


if __name__ == "__main__":
    unittest.main()
