import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import unittest

from hepta_learning_eval_projection import BEGIN, END, canonical, projection, replace_projection


def status():
    return {"module": "learning.eval", "claims": {"productionImplementation": False},
            "sourceFacts": {"recoverySource": {"processKillFixtureCutCount": 7},
                            "outcomeSource": {"maximumChannels": 32, "maximumBatchRows": 100000},
                            "capacitySource": {"configuredAttempts": 4096,
                                               "expectedLifecycleEvents": 24576,
                                               "anchoredRestartInterval": 128}}}


class ProjectionTests(unittest.TestCase):
    def test_canonical_key_order_is_stable(self):
        self.assertEqual(canonical({"b": 2, "a": 1}), canonical({"a": 1, "b": 2}))

    def test_missing_block_preserves_all_design_text(self):
        original = "# Design\n\nDetailed protocol and historical evidence.\n"
        result = replace_projection(original, projection(status()))
        self.assertTrue(result.startswith(original))
        self.assertEqual(result.count(BEGIN), 1)

    def test_replacement_is_idempotent_and_preserves_both_sides(self):
        document = "prefix\n" + BEGIN + "\nold\n" + END + "\nsuffix\n"
        block = projection(status())
        result = replace_projection(document, block)
        self.assertEqual(result, "prefix\n" + block + "suffix\n")
        self.assertEqual(replace_projection(result, block), result)

    def test_malformed_markers_fail_closed(self):
        for document in [BEGIN, END, END + BEGIN, BEGIN + END + BEGIN + END]:
            with self.subTest(document=document), self.assertRaises(ValueError):
                replace_projection(document, projection(status()))

    def test_changed_inventory_changes_projection(self):
        value = status()
        before = projection(value)
        value["sourceFacts"]["recoverySource"]["processKillFixtureCutCount"] = 8
        self.assertNotEqual(before, projection(value))

    def test_capacity_inventory_changes_projection(self):
        value = status()
        before = projection(value)
        value["sourceFacts"]["capacitySource"]["configuredAttempts"] = 8192
        self.assertNotEqual(before, projection(value))

    def test_source_cannot_issue_acceptance(self):
        value = status()
        value["claims"]["productionImplementation"] = True
        with self.assertRaises(ValueError):
            projection(value)


# Owner-reader diff classification uses isolated real-Git fixtures only.
SCRIPTS = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "learning_eval_status", SCRIPTS / "hepta-learning-eval-status.py"
)
STATUS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(STATUS)

VALIDATE_FIXTURE = """
import importlib.util
import json
from pathlib import Path
spec = importlib.util.spec_from_file_location(
    "fixture_status", Path("scripts/hepta-learning-eval-status.py")
)
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)
status.validate_map(json.loads(Path("fixture-model.json").read_text()))
"""


class StatusDiffTests(unittest.TestCase):
    SOURCE = "a_source.rs"
    TEST = "b_witness.rs"
    CALLER = "z_caller.rs"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        empty = self.root / "empty"
        empty.mkdir()
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_") and key not in {"PYTHONPATH", "PYTHONHOME"}
        }
        self.env.update({
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": str(empty),
            "GIT_CONFIG_KEY_1": "protocol.allow",
            "GIT_CONFIG_VALUE_1": "never",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(self.root / "scripts"),
            "LC_ALL": "C",
        })
        self.git("init", "--template=" + str(empty))
        scripts = self.root / "scripts"
        scripts.mkdir()
        for name in ("hepta-learning-eval-status.py", "hepta_rust_identifiers.py"):
            shutil.copyfile(SCRIPTS / name, scripts / name)
        self.write(self.SOURCE, "\n".join(
            symbol.rsplit("::", 1)[-1] for symbol in sorted(STATUS.REQUIRED_SYMBOLS)
        ) + "\n")
        self.write(self.TEST, "// fixture witness\n")
        callers = [{"sourcePath": path} for path in (
            "c_caller.rs", "d_caller.rs", "e_caller.rs", self.CALLER
        )]
        for caller in callers:
            self.write(caller["sourcePath"], "// " + caller["sourcePath"] + "\n")
        self.git("add", "--", self.SOURCE, self.TEST, *(row["sourcePath"] for row in callers))
        self.commit("fixture observation")
        self.anchor = self.git("rev-parse", "HEAD").stdout.strip()
        self.tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        model = {"sourceFacts": {"callers": callers}, "repositoryControlledGaps": []}
        value = {
            "schema": "hepta.module-implementation-map.v3",
            "module": "learning.eval",
            "operations": [{
                "nativeSymbol": symbol, "sourcePath": self.SOURCE, "tests": [self.TEST],
            } for symbol in sorted(STATUS.REQUIRED_SYMBOLS)],
            "productCallers": callers,
            "repositoryControlledGaps": [],
            "claimBoundary": {
                **dict.fromkeys(STATUS.TRUE_SOURCE, True),
                **dict.fromkeys(STATUS.FALSE_CLAIMS, False),
            },
            "sourceBase": {"commit": self.anchor, "tree": self.tree},
        }
        self.write("fixture-model.json", json.dumps(model))
        self.write("docs/modules/learning.eval/IMPLEMENTATION_MAP.json", json.dumps(value))
        self.assertEqual(self.git("remote").stdout, "")
        self.assertEqual(self.git(
            "config", "--local", "--get-regexp", "promisor|partialclone", check=False
        ).returncode, 1)
        self.assertEqual(list((self.root / ".git").rglob("*.promisor")), [])
        self.assertFalse((self.root / ".git/objects/info/alternates").exists())

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def git(self, *args, check=True):
        return subprocess.run(
            ["git", "-C", str(self.root), *args], env=self.env,
            text=True, capture_output=True, check=check,
        )

    def commit(self, message):
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-m", message)

    def diff(self, path):
        return self.git("diff", "--quiet", self.anchor, "--", path, check=False)

    def change(self, path):
        target = self.root / path
        target.write_text(target.read_text(encoding="utf-8") + "// changed\n", encoding="utf-8")

    def remove_historical_blob(self, path):
        blob = self.git("rev-parse", self.anchor + ":" + path).stdout.strip()
        self.change(path)
        self.git("add", "--", path)
        self.commit("fixture changed path")
        (self.root / ".git/objects" / blob[:2] / blob[2:]).unlink()
        self.assertEqual(self.git("cat-file", "-t", self.anchor).stdout.strip(), "commit")
        self.assertEqual(self.git("cat-file", "-t", self.tree).stdout.strip(), "tree")
        self.assertIn(blob, self.git("ls-tree", self.anchor, "--", path).stdout)
        self.assertNotEqual(self.git("cat-file", "-e", blob, check=False).returncode, 0)
        result = self.diff(path)
        self.assertEqual(result.returncode, 128, result.stderr)
        return blob

    def validate(self):
        return subprocess.run(
            [sys.executable, "-c", VALIDATE_FIXTURE], cwd=self.root,
            env=self.env, text=True, capture_output=True,
        )

    def test_unchanged_exit_zero_is_accepted(self):
        self.assertEqual(self.diff(self.SOURCE).returncode, 0)
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_drift_exit_one_is_rejected_for_every_path_kind(self):
        for path in (self.SOURCE, self.TEST, self.CALLER):
            with self.subTest(path=path):
                original = (self.root / path).read_text(encoding="utf-8")
                self.change(path)
                self.assertEqual(self.diff(path).returncode, 1)
                result = self.validate()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mapped executable source changed after observation: " + path, result.stderr)
                self.write(path, original)

    def test_multiple_drift_paths_are_reported_in_sorted_order(self):
        paths = (self.CALLER, self.TEST, self.SOURCE)
        for path in paths:
            self.change(path)
            self.assertEqual(self.diff(path).returncode, 1)
        result = self.validate()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            result.stderr,
            "mapped executable source changed after observation: " + ", ".join(sorted(paths)) + "\n",
        )

    def assert_missing_blob_rejected(self, path):
        blob = self.remove_historical_blob(path)
        result = self.validate()
        self.assertNotEqual(result.returncode, 0, "Git exit 128 was silently accepted")
        self.assertIn("mapped source comparison failed for " + path, result.stderr)
        self.assertIn("git diff exit 128", result.stderr)
        self.assertNotIn(blob, result.stderr)
        self.assertNotIn("fatal:", result.stderr)

    def test_missing_source_blob_is_a_hard_error(self):
        self.assert_missing_blob_rejected(self.SOURCE)

    def test_missing_test_blob_is_a_hard_error(self):
        self.assert_missing_blob_rejected(self.TEST)

    def test_missing_caller_blob_is_a_hard_error(self):
        self.assert_missing_blob_rejected(self.CALLER)

    def test_late_git_error_is_not_hidden_by_earlier_drift(self):
        self.change(self.SOURCE)
        self.assertEqual(self.diff(self.SOURCE).returncode, 1)
        self.assert_missing_blob_rejected(self.CALLER)


if __name__ == "__main__":
    unittest.main()
