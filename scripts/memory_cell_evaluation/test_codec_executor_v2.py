"""Codec profile qualification: exposed historical controls, no model or future data."""

import argparse
from collections import Counter
from pathlib import Path
import shutil
import unittest

from bounded_process import digest, save
from codec_executor_v2 import evaluate
from ruff_executor import inventory
from runtime_profile import load_runtime
from task_contract_v2 import CODEC_SHA256, codec_contract, export_inputs

GOLD_SHA256 = "9e98fd63845da16eed5aed1401c6de22ab3ee010f413eb5f79362be32d2b1f6a"


class CodecQualification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = codec_contract()
        cls.runtime = load_runtime(
            cls.spec,
            CODEC_SHA256,
            cls.runtime_options["runtime_profile"],
            cls.runtime_options["runtime_profile_sha256"],
        )
        if digest(cls.known_fix)["sha256"] != GOLD_SHA256:
            raise ValueError("historical positive runner hash mismatch")
        cls.runner = cls.known_fix.read_text()
        cls.workflow = (cls.fixture / cls.spec["workflow"]).read_text()

    def files(self, runner=None):
        if runner is None:
            return []
        return [
            {
                "path": self.spec["workflow"],
                "content": self.workflow.replace(
                    self.spec["original_command"], self.spec["runner_command"]
                ),
            },
            {"path": self.spec["runner"], "content": runner},
        ]

    def attempt(self, name, files, fixture=None, runtime_options=None):
        candidate = self.output / f"{name}.json"
        save(
            candidate,
            {"schema": "hepta.memory-cell.implementation-candidate.v1", "files": files},
        )
        return evaluate(
            fixture or self.fixture,
            candidate,
            self.output / name,
            self.python,
            self.ffmpeg,
            self.ffprobe,
            self.openssl,
            **(self.runtime_options if runtime_options is None else runtime_options),
        )

    def test_original_false_green(self):
        result = self.attempt("original", [])
        self.assertFalse(result["accepted"], result.get("error"))
        for name in ("missing_ffmpeg", "missing_ffprobe"):
            row = result["profiles"][name]
            self.assertEqual(
                (
                    row["passed"],
                    row["semantic"]["tests_run"],
                    Counter(x["status"] for x in row["semantic"]["outcomes"]),
                ),
                (False, 21, Counter(skip=21)),
            )
        self.assertTrue(result["profiles"]["provisioned"]["semantic_full_pass"])

    def test_known_fix_actual21(self):
        result = self.attempt("known-fix", self.files(self.runner))
        self.assertEqual(
            (result["accepted"], result["status"]),
            (True, "passed"),
            result.get("error"),
        )
        self.assertEqual(result["profiles"]["provisioned"]["semantic"]["tests_run"], 21)
        for name in ("missing_ffmpeg", "missing_ffprobe"):
            self.assertEqual(result["profiles"][name]["semantic"]["tests_run"], 0)
        self.assertFalse(result["cost_ledger"]["whole_system_cost_complete"])
        self.assertIsNone(result["cost_ledger"]["external"]["input"]["input_tokens"])

    def test_zero_execution_cannot_pass(self):
        result = self.attempt("empty-runner", self.files("raise SystemExit(0)\n"))
        self.assertEqual((result["accepted"], result["status"]), (False, "task_failed"))
        self.assertEqual(result["profiles"]["provisioned"]["semantic"]["tests_run"], 0)

    def test_partial_suite_cannot_pass(self):
        runner = self.runner.replace(
            "return run_acceptance(suite)",
            "return run_acceptance(unittest.TestSuite([list(list(list(suite)[0])[0])[0]]))",
        )
        result = self.attempt("partial-suite", self.files(runner))
        self.assertEqual((result["accepted"], result["status"]), (False, "task_failed"))
        self.assertEqual(result["profiles"]["provisioned"]["semantic"]["tests_run"], 1)
        self.assertTrue(
            result["profiles"]["provisioned"]["semantic"]["unittest_success"]
        )

    def test_source_and_candidate_boundaries(self):
        original_test = next(
            path for path in self.spec["files"] if Path(path).name.startswith("test_")
        )
        cases = {
            "test-edit": [{"path": original_test, "content": "pass\n"}],
            "path-escape": [{"path": "../escape.py", "content": "pass\n"}],
            "wrong-workflow": [
                {
                    "path": self.spec["workflow"],
                    "content": self.workflow + "\n# changed\n",
                }
            ],
        }
        for name, files in cases.items():
            with self.subTest(name=name):
                result = self.attempt(name, files)
                self.assertEqual((result["accepted"], result["processes"]), (False, []))
        fixture = self.output / "drift-input"
        shutil.copytree(self.fixture, fixture)
        (fixture / original_test).unlink()
        result = self.attempt("source-drift", self.files(self.runner), fixture=fixture)
        self.assertEqual((result["accepted"], result["processes"]), (False, []))

    def test_profile_binding_and_source_only_view(self):
        profile = self.output / "controller-profile.json"
        save(
            profile,
            {
                "schema": "hepta.memory-cell.runtime-profile.v1",
                "task_contract_sha256": CODEC_SHA256,
                "tools": self.runtime["tools"],
            },
        )
        result = self.attempt(
            "profile-hash-refusal",
            self.files(self.runner),
            runtime_options={
                "runtime_profile": profile,
                "runtime_profile_sha256": "0" * 64,
            },
        )
        self.assertEqual((result["accepted"], result["processes"]), (False, []))
        target = self.output / "model-inputs"
        export_inputs(self.fixture, target, **self.runtime_options)
        self.assertEqual(inventory(target / "source"), self.spec["files"])
        self.assertFalse((target / "source" / self.spec["runner"]).exists())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "fixture",
        "known-fix",
        "output",
        "python",
        "ffmpeg",
        "ffprobe",
        "openssl",
    ):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--runtime-profile", type=Path)
    parser.add_argument("--runtime-profile-sha256")
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    for name, value in vars(args).items():
        setattr(
            CodecQualification,
            name,
            value.resolve() if isinstance(value, Path) else value,
        )
    CodecQualification.runtime_options = {
        "runtime_profile": args.runtime_profile,
        "runtime_profile_sha256": args.runtime_profile_sha256,
    }
    save(
        args.output / "qualification-inputs.json",
        {
            name: str(value) if isinstance(value, Path) else value
            for name, value in vars(args).items()
        },
    )
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CodecQualification)
    )
    save(
        args.output / "qualification.json",
        {
            "accepted": result.wasSuccessful() and not result.skipped,
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skips": len(result.skipped),
            "runtime": getattr(CodecQualification, "runtime", None),
            "contract_sha256": CODEC_SHA256,
            "gold_scope": "explicit historical runner positive control only; source-only export excludes it",
            "model_queries": 0,
            "training_updates": 0,
            "future_cases": 0,
        },
    )
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
