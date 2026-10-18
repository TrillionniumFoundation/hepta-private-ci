"""Real-case batching tests; fail-closed evidence without fake runner passes."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

from scripts.github_actions_fleet_500 import collect_tests, plan
from scripts.github_actions_packed_ci import (
    run_cases,
    select_cases,
    verify_source,
)


class PackedPartitionTests(unittest.TestCase):
    def test_whole_500_case_source_set_is_partitioned_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "test_mass.py").write_text(
                "import unittest\nclass Many(unittest.TestCase):\n"
                + "".join(f"    def test_{i:04d}(self): pass\n" for i in range(540)),
                encoding="utf-8",
            )
            manifest = sorted(collect_tests(root))
            assert len(manifest) == 540
            all_cases = []
            fingerprints = set()
            for cohort in ("A", "B"):
                cohort_expected = {
                    x["case"] for x in plan(manifest, cohort, 250)["matrix"]["include"]
                }
                for count in (8, 16, 32):
                    cases = []
                    for index in range(count):
                        selected = select_cases(root, cohort, count, index)
                        fingerprints.add(selected["manifest_sha256"])
                        self.assertEqual(selected["all_case_count"], 250)
                        self.assertEqual(selected["worker_count"], count)
                        cases.extend(selected["selected_cases"])
                    self.assertEqual(len(cases), 250)
                    self.assertEqual(len(set(cases)), 250)
                    self.assertEqual(set(cases), cohort_expected)
                    if count == 16:
                        all_cases.extend(cases)
            self.assertEqual(len(fingerprints), 1)
            self.assertEqual(len(all_cases), 500)
            self.assertEqual(len(set(all_cases)), 500)

    def test_all_cohort_is_exact_original_A_B_union_for_each_worker_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "test_mass.py").write_text(
                "import unittest\nclass Many(unittest.TestCase):\n"
                + "".join(f"    def test_{i:04d}(self): pass\n" for i in range(540))
            )
            all_tests = collect_tests(root)
            expected_a = {
                entry["case"]
                for entry in plan(all_tests, "A", 250)["matrix"]["include"]
            }
            expected_b = {
                entry["case"]
                for entry in plan(all_tests, "B", 250)["matrix"]["include"]
            }
            self.assertEqual(len(expected_a), 250)
            self.assertEqual(len(expected_b), 250)
            self.assertTrue(expected_a.isdisjoint(expected_b))
            for workers in (8, 16, 32):
                with self.subTest(workers=workers):
                    union = set()
                    fingerprints = set()
                    for index in range(workers):
                        shard = select_cases(root, "ALL", workers, index)
                        self.assertEqual(shard["all_case_count"], 500)
                        self.assertEqual(shard["cohort"], "ALL")
                        self.assertIn(
                            len(shard["selected_cases"]),
                            (500 // workers, 500 // workers + 1),
                        )
                        self.assertFalse(union.intersection(shard["selected_cases"]))
                        union.update(shard["selected_cases"])
                        fingerprints.add(shard["manifest_sha256"])
                    self.assertEqual(union, expected_a | expected_b)
                    self.assertEqual(len(fingerprints), 1)

    def test_all_cohort_invalid_or_insufficient_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "test_mass.py").write_text(
                "import unittest\nclass Many(unittest.TestCase):\n"
                + "".join(f"    def test_{i:04d}(self): pass\n" for i in range(499))
            )
            for cohort in ("A", "B", "ALL", "INVALID"):
                with self.subTest(cohort=cohort), self.assertRaises(ValueError):
                    select_cases(root, cohort, 16, 0)

    def test_invalid_workers_and_worker_index_do_not_create_empty_shards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "test_mass.py").write_text(
                "import unittest\nclass Many(unittest.TestCase):\n"
                + "".join(f"    def test_{i:04d}(self): pass\n" for i in range(510))
            )
            for workers, index in (
                (0, 0),
                (3, 0),
                (64, 0),
                (True, 0),
                (16, -1),
                (16, 16),
                (16, "1"),
                (16, True),
            ):
                with self.subTest(workers=workers, index=index):
                    with self.assertRaises(ValueError):
                        select_cases(root, "A", workers, index)

    def test_missing_half_of_source_never_reports_a_complete_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "test_only.py").write_text(
                "import unittest\nclass Small(unittest.TestCase):\n"
                + "".join(f"    def test_{i:04d}(self): pass\n" for i in range(200))
            )
            with self.assertRaises(ValueError):
                select_cases(root, "A", 16, 0)

    def test_workflow_only_dispatches_source_pinned_opt_in_real_workers(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / ".github/workflows/github-actions-fleet-packed.yml").read_text()
        real = text.split("  packed-real-test:", 1)[1]
        self.assertIn("  pull_request:", text)
        self.assertIn("  workflow_dispatch:", text)
        self.assertIn("  contents: read", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("pull_request_target:", text)
        self.assertIn("ref: ${{ github.sha }}", real)
        self.assertIn("--expected-sha", real)
        self.assertIn("--execute", real)
        self.assertIn("matrix.worker", real)
        self.assertIn("options: [A, B, ALL]", text)
        self.assertNotIn("ref:  + chr(36) + {{ inputs.source_sha", text)
        self.assertIn("fail-fast: false", real)
        self.assertIn("if: always()", real)
        self.assertNotIn("    needs:", real)


class PackedExecutionFixture(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix="gha-packed-")
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name) / "repo"
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "scripts" / "__init__.py").write_text("")
        (self.root / "scripts" / "test_fixture.py").write_text(
            textwrap.dedent("""\
                import os
                import sys
                import time
                import unittest

                class Fixtures(unittest.TestCase):
                    def test_pass(self): self.assertTrue(True)
                    def test_pass_second(self): self.assertTrue(True)
                    def test_fail(self): self.assertEqual(1, 2)
                    @unittest.skip("fixture skip")
                    def test_skip(self): self.fail("must not run")
                    @unittest.expectedFailure
                    def test_expected_failure(self): self.fail("expected")
                    @unittest.expectedFailure
                    def test_unexpected_success(self): pass
                    def test_error(self): raise RuntimeError("fixture error")
                    def test_exit_zero(self): sys.exit(0)
                    def test_hard_exit_zero(self): os._exit(0)
                    def test_sleep(self): time.sleep(5)
                    def test_subtests(self):
                        for value in (1, 2):
                            with self.subTest(value=value): self.assertGreater(value, 0)
                    def test_subtest_failure(self):
                        with self.subTest(value=1): self.assertEqual(1, 2)
                    def test_noise(self):
                        print('{"status":"failed","tests_run":999}')
                        print("arbitrary stderr", file=sys.stderr)

                class TearDownSkip(unittest.TestCase):
                    @classmethod
                    def tearDownClass(cls): raise unittest.SkipTest("teardown skipped")
                    def test_pass(self): pass

                class MissingCompletion(unittest.TestCase):
                    def test_pass(self): pass
                    def run(self, result):
                        result.startTest(self)
                        result.addSuccess(self)
                        return result

                class Redirected(unittest.TestCase):
                    def test_pass(self): pass
                    def run(self, result):
                        Fixtures("test_pass")(result)
                        return result

                def empty_suite(): return unittest.TestSuite()
                def extra_suite():
                    return unittest.TestSuite([
                        Fixtures("test_pass"), Fixtures("test_pass_second")])
            """),
            encoding="utf-8",
        )
        (self.root / "scripts" / "test_import_exit.py").write_text(
            'import sys\nprint(\'{"status":"passed"}\', flush=True)\nsys.exit(0)\n'
        )
        (self.root / "scripts" / "test_import_hardexit.py").write_text(
            "import os\nos._exit(0)\n"
        )
        for args in (
            ("init", "-q"),
            ("config", "user.email", "fixture@invalid"),
            ("config", "user.name", "Packed Test"),
            ("add", "."),
            ("commit", "-qm", "fixture"),
        ):
            subprocess.run(
                ["git", "-C", str(self.root), *args], check=True, capture_output=True
            )
        self.sha = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True
        ).strip()
        self.receipt = Path(holder.name) / "receipt.json"

    def schedule(self, *names):
        cases = [
            name
            if name.startswith("scripts.")
            else f"scripts.test_fixture.Fixtures.test_{name}"
            for name in names
        ]
        return {
            "selected_cases": cases,
            "cohort": "A",
            "worker_count": 8,
            "worker_index": 0,
            "manifest_sha256": "f" * 64,
            "case_set_sha256": hashlib.sha256("\n".join(cases).encode()).hexdigest(),
        }

    def test_actual_successful_unittest_creates_exact_source_receipt(self):
        x = run_cases(self.root, self.sha, self.schedule("pass"), self.receipt)
        self.assertEqual(x["status"], "passed")
        self.assertEqual(x["expected_cases"], 1)
        self.assertEqual([j["status"] for j in x["cases"]], ["passed"])
        raw = json.loads(self.receipt.read_text())
        self.assertEqual(raw["source_sha"], self.sha)
        self.assertEqual(raw["status"], "passed")
        self.assertEqual(
            raw["cases"][0]["case"], "scripts.test_fixture.Fixtures.test_pass"
        )
        self.assertNotIn("stdout", raw["cases"][0])
        self.assertEqual(
            raw["case_set_sha256"], self.schedule("pass")["case_set_sha256"]
        )

    def test_failure_is_retained_and_does_not_hide_other_case_execution(self):
        x = run_cases(self.root, self.sha, self.schedule("fail", "pass"), self.receipt)
        self.assertEqual(x["status"], "failed")
        self.assertEqual([j["status"] for j in x["cases"]], ["failed", "passed"])
        self.assertEqual([j["exit_code"] for j in x["cases"]][-1], 0)
        self.assertEqual(json.loads(self.receipt.read_text())["status"], "failed")

    def test_real_unittest_outcomes_are_distinct_and_only_success_passes(self):
        x = run_cases(
            self.root,
            self.sha,
            self.schedule(
                "skip",
                "expected_failure",
                "unexpected_success",
                "error",
                "subtest_failure",
                "exit_zero",
                "pass",
            ),
            self.receipt,
        )
        self.assertEqual(x["status"], "failed")
        self.assertEqual(
            [case["status"] for case in x["cases"]],
            [
                "skipped",
                "expected_failure",
                "unexpected_success",
                "test_error",
                "failed",
                "test_error",
                "passed",
            ],
        )
        self.assertEqual(
            [case["exit_code"] for case in x["cases"]], [0, 0, 1, 1, 1, 1, 0]
        )
        self.assertEqual(json.loads(self.receipt.read_text()), x)

    def test_teardown_class_skip_rejects_a_recorded_success(self):
        target = "scripts.test_fixture.TearDownSkip.test_pass"
        x = run_cases(self.root, self.sha, self.schedule(target), self.receipt)
        result = x["cases"][0]
        self.assertEqual(
            (x["status"], result["status"], result["exit_code"]),
            ("failed", "skipped", 0),
        )
        self.assertEqual(
            result["unittest_result"],
            {
                "version": 1,
                "case": target,
                "tests_run": 1,
                "started": [target],
                "completed": [target],
                "successes": [target],
                "skipped": 1,
                "expected_failures": 0,
                "unexpected_successes": 0,
                "errors": 0,
                "failures": 0,
            },
        )

    def test_successful_subtests_and_noisy_output_keep_structured_success(self):
        x = run_cases(
            self.root, self.sha, self.schedule("subtests", "noise"), self.receipt
        )
        self.assertEqual(
            (x["status"], [case["status"] for case in x["cases"]]),
            ("passed", ["passed", "passed"]),
        )
        for case in x["cases"]:
            self.assertEqual(case["unittest_result"]["successes"], [case["case"]])
            self.assertEqual(case["unittest_result"]["tests_run"], 1)

    def test_early_clean_exit_and_stdout_claims_cannot_replace_a_report(self):
        x = run_cases(
            self.root,
            self.sha,
            self.schedule(
                "scripts.test_import_exit.Never.test_case",
                "scripts.test_import_hardexit.Never.test_case",
                "hard_exit_zero",
                "pass",
            ),
            self.receipt,
        )
        self.assertEqual(x["status"], "failed")
        self.assertEqual(
            [(case["status"], case["exit_code"]) for case in x["cases"]],
            [
                ("missing_report", 0),
                ("missing_report", 0),
                ("missing_report", 0),
                ("passed", 0),
            ],
        )

    def test_single_target_must_start_finish_and_be_the_recorded_success(self):
        x = run_cases(
            self.root,
            self.sha,
            self.schedule(
                "scripts.test_fixture.empty_suite",
                "scripts.test_fixture.extra_suite",
                "scripts.test_fixture.MissingCompletion.test_pass",
                "scripts.test_fixture.Redirected.test_pass",
                "pass",
            ),
            self.receipt,
        )
        self.assertEqual(x["status"], "failed")
        self.assertEqual(
            [case["status"] for case in x["cases"]],
            ["incomplete_test"] * 4 + ["passed"],
        )
        self.assertEqual(
            [case["unittest_result"]["tests_run"] for case in x["cases"]],
            [0, 2, 1, 1, 1],
        )

    def test_real_timeout_still_runs_the_following_case(self):
        x = run_cases(
            self.root,
            self.sha,
            self.schedule("sleep", "pass"),
            self.receipt,
            timeout_seconds=1,
        )
        self.assertEqual(
            (x["status"], [case["status"] for case in x["cases"]]),
            ("failed", ["timed_out", "passed"]),
        )

    def test_successful_report_does_not_override_nonzero_process_exit(self):
        def nonzero_runner(command, **kwargs):
            completed = subprocess.run(command, **kwargs)
            self.assertEqual(completed.returncode, 0)
            completed.returncode = 7
            return completed

        x = run_cases(
            self.root,
            self.sha,
            self.schedule("pass"),
            self.receipt,
            runner=nonzero_runner,
        )
        self.assertEqual(
            (x["status"], x["cases"][0]["status"], x["cases"][0]["exit_code"]),
            ("failed", "failed", 7),
        )
        self.assertEqual(x["cases"][0]["unittest_result"]["tests_run"], 1)

    def test_sha_mismatch_or_dirty_checkout_prevents_execution(self):
        with self.assertRaises(ValueError):
            verify_source(self.root, "0" * 40)
        with self.assertRaises(ValueError):
            verify_source(self.root, "--foo")
        (self.root / "bad.txt").write_text("untracked")
        with self.assertRaises(ValueError):
            run_cases(self.root, self.sha, self.schedule("pass"), self.receipt)
        self.assertFalse(self.receipt.exists())

    def test_timeout_cannot_be_recast_as_success(self):
        def timeout_runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        x = run_cases(
            self.root,
            self.sha,
            self.schedule("pass"),
            self.receipt,
            timeout_seconds=1,
            runner=timeout_runner,
        )
        self.assertEqual(x["status"], "failed")
        self.assertEqual(x["cases"][0]["status"], "timed_out")
        self.assertIsNone(x["cases"][0]["exit_code"])

    def test_source_mutation_is_detected_and_stops_unsafe_reuse(self):
        def dirty_runner(command, **kwargs):
            (self.root / "contamination.txt").write_text("dirty")
            return subprocess.CompletedProcess(command, 0, "ok", "")

        x = run_cases(
            self.root,
            self.sha,
            self.schedule("pass", "pass_second"),
            self.receipt,
            runner=dirty_runner,
        )
        self.assertEqual(x["status"], "source_changed")
        self.assertEqual(len(x["cases"]), 1)
        self.assertEqual(
            json.loads(self.receipt.read_text())["status"], "source_changed"
        )


if __name__ == "__main__":
    unittest.main()
