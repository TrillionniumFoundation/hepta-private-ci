"""Real-case batching tests; fail-closed evidence without fake runner passes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
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
        self.assertIn("ref: ${{ inputs.source_sha }}", real)
        self.assertIn("--expected-sha", real)
        self.assertIn("--execute", real)
        self.assertIn("matrix.worker", real)
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
            "import unittest\nclass Fixtures(unittest.TestCase):\n"
            "    def test_pass(self): self.assertTrue(True)\n"
            "    def test_pass_second(self): self.assertTrue(True)\n"
            "    def test_fail(self): self.assertEqual(1, 2)\n"
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
        cases = [f"scripts.test_fixture.Fixtures.test_{name}" for name in names]
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
