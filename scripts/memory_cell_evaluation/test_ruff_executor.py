"""Real exposed-incident controls and focused executor refusal qualification."""

import argparse
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from bounded_process import digest, run, save
from ruff_executor import contract, evaluate, inventory

GOLD_SHA256 = "bb1509df8d9a4c40ed6154005e75b9a6176e36482ffb5f284bd3c52844804f3b"


class Qualification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = contract()
        cls.target = cls.spec["target"]
        cls.original = (cls.fixture / cls.target).read_text()
        if digest(cls.known_fix)["sha256"] != GOLD_SHA256:
            raise ValueError("explicit historical positive-control hash mismatch")
        cls.fixed = cls.known_fix.read_text()

    def candidate(self, name, content, path=None):
        target = self.output / f"{name}.json"
        save(
            target,
            {
                "schema": "hepta.memory-cell.implementation-candidate.v1",
                "files": [{"path": path or self.target, "content": content}],
            },
        )
        return target

    def evaluate(self, name, content, fixture=None, path=None):
        return evaluate(
            fixture or self.fixture,
            self.candidate(name, content, path),
            self.output / name,
            self.ruff,
            self.python,
        )

    def test_original_failure(self):
        result = self.evaluate("original-failure", self.original)
        self.assertEqual(
            (result["accepted"], result["status"], result.get("baseline_codes")),
            (False, "lint_failed", ["E731", "F401"]),
        )
        self.assertEqual(len(result["processes"]), 2)

    def test_known_fix_positive_control(self):
        result = self.evaluate("known-fix", self.fixed)
        self.assertEqual(
            (result["accepted"], result["status"]),
            (True, "passed"),
            result.get("error"),
        )
        self.assertEqual(result["semantic"]["tests_run"], 76)

    def test_lint_clean_semantic_failure(self):
        self.assertEqual(self.fixed.count("return feedback.solve(s)[0]"), 1)
        broken = self.fixed.replace("return feedback.solve(s)[0]", "return STOP")
        result = self.evaluate("semantic-failure", broken)
        self.assertEqual(
            (result["accepted"], result["status"]),
            (False, "semantic_failed"),
            result.get("error"),
        )
        self.assertEqual(result["semantic"]["tests_run"], 76)
        self.assertTrue(
            any(row["status"] != "success" for row in result["semantic"]["outcomes"])
        )

    def test_skip_cannot_pass(self):
        skipped = self.fixed.replace(
            "from itertools import product",
            "import unittest\nfrom itertools import product",
        )
        skipped = skipped.replace(
            "\ndef check_joint_law(",
            '\nraise unittest.SkipTest("qualification skip")\n\n\ndef check_joint_law(',
        )
        result = self.evaluate("skip-failure", skipped)
        self.assertEqual(
            (result["accepted"], result["status"]),
            (False, "semantic_failed"),
            result.get("error"),
        )
        self.assertTrue(
            any(row["status"] == "skip" for row in result["semantic"]["outcomes"])
        )

    def test_candidate_boundaries(self):
        test_path = next(
            name for name in self.spec["files"] if Path(name).name.startswith("test_")
        )
        cases = [
            ("test-edit", test_path, self.fixed),
            ("path-escape", "../counterfactual_audit.py", self.fixed),
            ("extra-suppression", self.target, self.fixed + "\n# ruff: noqa\n"),
            ("content-limit", self.target, self.fixed + "\n" * 65536),
        ]
        for name, path, content in cases:
            with self.subTest(name=name):
                result = self.evaluate(name, content, path=path)
                self.assertEqual(
                    (result["accepted"], result["status"], result["processes"]),
                    (False, "rejected", []),
                )

    def test_source_boundaries(self):
        test_path = next(
            name for name in self.spec["files"] if Path(name).name.startswith("test_")
        )
        for name in ("source-drift", "missing-test", "source-symlink", "extra-module"):
            with self.subTest(name=name):
                fixture = self.output / f"{name}-input"
                shutil.copytree(self.fixture, fixture)
                path = fixture / test_path
                if name == "source-drift":
                    path.write_text(path.read_text() + "\n# changed\n")
                elif name == "missing-test":
                    path.unlink()
                elif name == "source-symlink":
                    path.unlink()
                    path.symlink_to(self.fixture / test_path)
                else:
                    (fixture / "extra.py").write_text("pass\n")
                result = self.evaluate(name, self.fixed, fixture=fixture)
                self.assertEqual(
                    (result["accepted"], result["status"], result["processes"]),
                    (False, "rejected", []),
                )

    def test_duplicate_output_is_untouched(self):
        candidate = self.candidate("duplicate", self.fixed, "not-allowed.py")
        output = self.output / "duplicate"
        evaluate(self.fixture, candidate, output, self.ruff, self.python)
        before = inventory(output)
        with self.assertRaises(FileExistsError):
            evaluate(self.fixture, candidate, output, self.ruff, self.python)
        self.assertEqual(inventory(output), before)

    def test_bounded_process_timeout(self):
        limits = dict(self.spec["limits"], wall_seconds=0.1)
        result = run(
            [str(self.python), "-I", "-B", "-c", "while True: pass"],
            self.output,
            self.output / "timeout-control",
            limits,
        )
        self.assertTrue(result["timeout"])
        self.assertEqual(result["returncode"], -9)

    def test_missing_stderr_preserves_process_receipt(self):
        original_open = Path.open

        def failed_stderr(path, *args, **kwargs):
            if path.name == "stderr":
                raise OSError("qualification injected stderr open failure")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", failed_stderr):
            result = run(
                [str(self.python), "-I", "-B", "-c", "pass"],
                self.output,
                self.output / "stderr-open-failure",
                self.spec["limits"],
            )
        receipt = json.loads(
            (self.output / "stderr-open-failure/process.json").read_text()
        )
        self.assertEqual(result, receipt)
        self.assertIsNone(result["returncode"])
        self.assertIn("qualification injected", result["spawn_error"])
        self.assertIn("error", result["stderr"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("fixture", "known-fix", "output", "ruff", "python"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    for key, value in vars(args).items():
        setattr(Qualification, key.replace("-", "_"), value.resolve())
    save(
        args.output / "qualification-inputs.json",
        {
            **{k: str(v) for k, v in vars(args).items()},
            "gold_scope": "explicit exposed historical positive control only; never predictor/source-only input",
        },
    )
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Qualification)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    receipts = {
        str(path.relative_to(args.output)): json.loads(path.read_text())
        for path in args.output.rglob("process.json")
    }
    save(
        args.output / "qualification.json",
        {
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skips": len(result.skipped),
            "accepted": result.wasSuccessful(),
            "process_receipts": receipts,
            "new_model_queries": 0,
            "training_updates": 0,
            "future_cases": 0,
        },
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
