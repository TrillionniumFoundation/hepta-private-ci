import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from operational_cohort_plan import canonical, digest
from prospective_action_execution import observe, run_case, validate_case
from prospective_action_inputs import freeze_inputs, sha_file
from test_prospective_action_inputs import example


def fixture(root):
    checkout = root / "repository"
    checkout.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-c", "user.name=Fixture", "-c",
            "user.email=fixture@example.invalid", *args], cwd=checkout, stderr=subprocess.DEVNULL).decode().strip()
    git("init", "-q")
    (checkout / "value.py").write_text("def value():\n    return 0\n")
    (checkout / "test_support.txt").write_text("old")
    (checkout / "tests").mkdir()
    (checkout / "tests/__init__.py").write_text("")
    test_source = '''import unittest
from pathlib import Path
from value import value
class TestValue(unittest.TestCase):
    def test_first(self):
        Path("side-effect.txt").write_text("must be reset")
        self.assertEqual(value(), 1)
    def test_control(self):
        self.assertFalse(Path("side-effect.txt").exists())
        self.assertEqual(Path("test_support.txt").read_text(), "fixed")
        self.assertGreaterEqual(value(), 0)
class TestUnavailable(unittest.TestCase):
    def setUp(self):
        raise RuntimeError("fixture setup unavailable")
    def test_missing(self):
        self.fail("must not execute")
'''
    (checkout / "tests/test_value.py").write_text(test_source)
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (checkout / "value.py").write_text("def value():\n    return 1\n")
    (checkout / "test_support.txt").write_text("fixed")
    git("commit", "-qam", "candidate")
    candidate = git("rev-parse", "HEAD")
    case = example()
    case["bug"]["revisions"] = {"base": base, "candidate": candidate}
    case["fixed_test_paths"] = ["tests/__init__.py", "tests/test_value.py", "test_support.txt"]
    case["declared_test_files"] = ["tests/test_value.py"]
    case["test_tree_roots"] = ["tests"]
    case["commands"] = []
    for name in ("TestValue.test_first", "TestValue.test_control", "TestUnavailable.test_missing"):
        case["commands"].append({"id": name, "runner": "unittest", "args": ["tests.test_value." + name],
            "comparators": [], "view": {"text": "TEST SOURCE tests/test_value.py\n" + test_source,
                                       "source_files": {"tests/test_value.py": digest(test_source.encode())}}})
    prepared, protocol = root / "case.json", root / "protocol.md"
    prepared.write_bytes(canonical(case))
    protocol.write_text("fixture frozen before commands")
    freeze_inputs([prepared], root / "inputs", protocol)
    data = json.loads((root / "inputs/inputs.json").read_bytes())
    binding = next(iter(data["case_bindings"].values()))
    # This explicit fixture order makes the informative action first; the executor
    # must still run both following actions, including the setup error.
    binding["actions"].sort(key=lambda a: 0 if a["args"][0].endswith("test_first") else 1)
    return checkout / ".git", binding


class ProspectiveExecutionTests(unittest.TestCase):
    def test_normal_exit_cannot_leave_an_active_owned_descendant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_orphan.py").write_text('''import subprocess,sys,unittest
class Checks(unittest.TestCase):
    def test_spawn(self):
        subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
''')
            limits = {"cpu_seconds": 10, "wall_timeout_seconds": 15,
                      "address_space_bytes": 1024 ** 3, "log_file_bytes": 1024 ** 2}
            result = observe({"key": "fixture", "runner": "unittest", "args": ["test_orphan.Checks.test_spawn"]},
                {"python": sys.executable, "plain_pytest": True}, root, root / "output", limits)
            self.assertEqual(result["observation"]["outcome"], "pass")
            self.assertEqual(result["outcome"], "infrastructure_error")
            cleanup = result["owned_process_group_cleanup"]
            self.assertTrue(cleanup["group_present_after_leader_exit"])
            self.assertFalse(cleanup["process_group_still_present"])
            self.assertTrue(cleanup["reaped_descendants"])
            self.assertFalse(cleanup["orphan_cpu_unmeasured"])
            self.assertTrue(Path(result["environment"]["PYTHONPYCACHEPREFIX"]).is_absolute())

    def test_all_candidates_execute_and_source_resets_after_an_informative_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store, binding = fixture(root)
            profile = {"python": sys.executable, "plain_pytest": True, "source_paths": []}
            limits = {"cpu_seconds": 10, "wall_timeout_seconds": 15,
                      "address_space_bytes": 1024 ** 3, "log_file_bytes": 1024 ** 2}
            result = run_case(binding, store, profile, root / "out", root / "work", limits, "a" * 64)
            self.assertEqual(result["physical_command_executions"], 6)
            self.assertFalse(result["errors"])
            pairs = {a["args"][0].rsplit(".", 1)[-1]: result["pairs"][a["key"]] for a in binding["actions"]}
            self.assertEqual([pairs["test_first"][r]["outcome"] for r in ("base", "candidate")], ["test_failure", "pass"])
            self.assertEqual([pairs["test_control"][r]["outcome"] for r in ("base", "candidate")], ["pass", "pass"])
            self.assertEqual([pairs["test_missing"][r]["outcome"] for r in ("base", "candidate")], ["infrastructure_error"] * 2)
            self.assertFalse(any((root / "work").iterdir()))
            self.assertEqual(validate_case(root / "out", binding, "a" * 64), result)
            self.assertEqual(run_case(binding, store, profile, root / "out", root / "work", limits, "a" * 64), result)
            with self.assertRaisesRegex(ValueError, "different frozen"):
                validate_case(root / "out", binding, "b" * 64)
            evidence = next((root / "out").rglob("stdout.log"))
            evidence.write_bytes(evidence.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                validate_case(root / "out", binding, "a" * 64)


if __name__ == "__main__":
    unittest.main()
