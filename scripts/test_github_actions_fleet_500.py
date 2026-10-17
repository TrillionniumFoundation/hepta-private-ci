"""Regression checks for real, non-overlapping Actions fleet shards and bounded audit."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from scripts.github_actions_fleet_500 import (
    SUPPORTED_DIRECT_COUNTS,
    collect_tests,
    plan,
    select_direct_case,
)
from scripts.github_actions_runner_audit import summarize


class TestFleetPlanner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()

    def write(self, name, content):
        file = self.root / "scripts" / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        return file

    def test_static_collection_only_picks_testcase_inheritance(self):
        self.write(
            "test_example.py",
            """
import unittest
raise RuntimeError("planning MUST NOT import this file")
class Helper:
    def test_not_unittest(self): pass
class Base(unittest.TestCase):
    def setUp(self): pass
class Real(Base):
    def test_first(self): pass
    async def test_second(self): pass
class Else:
    def test_not_selected(self): pass
""",
        )
        actual = collect_tests(self.root)
        self.assertEqual(
            actual,
            [
                "scripts.test_example.Real.test_first",
                "scripts.test_example.Real.test_second",
            ],
        )

    def test_two_cohorts_exactly_partition_500_unique_real_methods(self):
        self.write(
            "tests/test_samples.py",
            """
import unittest
class Examples(unittest.TestCase):
"""
            + "".join(f"    def test_{i:03d}(self): pass\n" for i in range(520)),
        )
        tests = collect_tests(self.root)
        self.assertEqual(len(tests), 520)
        a, b = plan(tests, "A", 250), plan(tests, "B", 250)
        a_ids = [row["case"] for row in a["matrix"]["include"]]
        b_ids = [row["case"] for row in b["matrix"]["include"]]
        self.assertEqual(len(a_ids), 250)
        self.assertEqual(len(b_ids), 250)
        self.assertTrue(set(a_ids).isdisjoint(b_ids))
        self.assertEqual(set(a_ids) | set(b_ids), set(tests[:500]))
        self.assertEqual(a["manifest_sha256"], b["manifest_sha256"])
        self.assertTrue(a["full_two_cohort_ready"])

    def test_shortage_never_creates_empty_jobs(self):
        a = plan(["scripts.t.C.test_a"], "A", 2)
        self.assertFalse(a["full_two_cohort_ready"])
        self.assertEqual(a["selected_count"], 0)
        self.assertEqual(a["matrix"], {"include": []})

    def test_malformed_inputs_rejected(self):
        for batch, size in (("C", 1), ("A", 0), ("A", 251), ("A", True)):
            with self.subTest(batch=batch, size=size), self.assertRaises(ValueError):
                plan([], batch, size)
        with self.assertRaises(ValueError):
            plan(["same", "same"], "A", 1)

    def test_direct_matrix_indexes_exact_unique_testcases_for_every_ramp(self):
        cases = [f"scripts.example.Tests.test_{index:04d}" for index in range(520)]
        for count in sorted(SUPPORTED_DIRECT_COUNTS):
            with self.subTest(count=count):
                a = plan(cases, "A", count)
                b = plan(cases, "B", count)
                actual_a = {select_direct_case(a, i) for i in range(count)}
                actual_b = {select_direct_case(b, i) for i in range(count)}
                self.assertEqual(len(actual_a), count)
                self.assertEqual(len(actual_b), count)
                self.assertTrue(actual_a.isdisjoint(actual_b))
                self.assertEqual(actual_a | actual_b, set(cases[: 2 * count]))

    def test_direct_index_and_unsupported_counts_fail_closed(self):
        cases = [f"scripts.example.T.test_{i}" for i in range(520)]
        good = plan(cases, "A", 16)
        for index in (-1, 16, True, "0", 1.5):
            with self.subTest(index=index), self.assertRaises(ValueError):
                select_direct_case(good, index)
        with self.assertRaises(ValueError):
            select_direct_case(plan(cases, "A", 12), 0)
        with self.assertRaises(ValueError):
            select_direct_case(plan(cases[:6], "B", 8), 0)

    def test_direct_workflow_has_no_preflight_runner_dependency(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/github-actions-fleet-500.yml").read_text()
        direct = workflow.split("\n  real-test:\n", 1)[1]
        self.assertNotIn("    needs: plan", direct)
        self.assertIn("matrix.shard", direct)
        self.assertIn("fromJSON(", direct)
        self.assertIn("--case-index", direct)


class TestFleetAudit(unittest.TestCase):
    def test_distinguish_run_backlog_from_actual_running_jobs(self):
        now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        active = {
            "id": 3,
            "status": "in_progress",
            "created_at": "2026-10-16T00:00:00Z",
            "html_url": "https://example.invalid/3",
        }
        queued = {
            "id": 4,
            "status": "queued",
            "created_at": "2026-10-16T00:00:00Z",
            "html_url": "https://example.invalid/4",
        }
        old = {
            "id": 2,
            "status": "queued",
            "created_at": "2026-09-18T00:00:00Z",
            "html_url": "https://example.invalid/2",
        }

        def query(path, params):
            if path.endswith("/runs"):
                if "created" in params:
                    return {"total_count": 300, "workflow_runs": [old]}
                status = params["status"]
                values = {
                    "in_progress": (1, [active]),
                    "queued": (500, [queued]),
                    "pending": (20, []),
                    "waiting": (0, []),
                    "completed": (
                        1000,
                        [{"conclusion": "cancelled"}, {"conclusion": "success"}],
                    ),
                }
                count, runs = values[status]
                return {"total_count": count, "workflow_runs": runs}
            if path.endswith("/3/jobs"):
                return {
                    "total_count": 2,
                    "jobs": [
                        {
                            "status": "in_progress",
                            "labels": ["ubuntu-24.04"],
                            "created_at": "2026-10-16T00:01:00Z",
                            "started_at": "2026-10-16T00:02:00Z",
                        },
                        {
                            "status": "completed",
                            "labels": ["ubuntu-24.04"],
                            "created_at": "2026-10-16T00:01:00Z",
                            "started_at": "2026-10-16T00:01:30Z",
                        },
                    ],
                }
            return {"total_count": 0, "jobs": []}

        result = summarize("TrillionniumFoundation/hepta-private-ci", query, now=now)
        self.assertEqual(result["workflow_run_counts"]["queued"], 500)
        self.assertEqual(
            result["job_observation"]["currently_running_jobs_lower_bound"], 1
        )
        self.assertEqual(result["old_queued_runs"]["provider_reported_count"], 300)
        self.assertEqual(result["old_queued_runs"]["old_without_jobs_in_sample"], 1)
        self.assertTrue(result["job_observation"]["sampled_all_in_progress_runs"])
        self.assertEqual(result["completed_run_sample"]["conclusions"]["cancelled"], 1)
        self.assertFalse(result["organization_job_concurrency_limit_known"])

    def test_active_sample_limit_is_not_extrapolated(self):
        def query(path, params):
            if path.endswith("/runs"):
                status = params["status"]
                if "created" in params:
                    return {"total_count": 0, "workflow_runs": []}
                runs = (
                    [
                        {
                            "id": 1,
                            "status": "in_progress",
                            "created_at": "2026-10-16T00:00:00Z",
                        }
                    ]
                    if status == "in_progress"
                    else []
                )
                return {
                    "total_count": 200 if status == "in_progress" else 0,
                    "workflow_runs": runs,
                }
            return {
                "total_count": 1,
                "jobs": [{"status": "in_progress", "labels": ["self-hosted"]}],
            }

        r = summarize("owner/repo", query, max_active_runs=1, max_queued_runs=0)
        self.assertEqual(r["job_observation"]["currently_running_jobs_lower_bound"], 1)
        self.assertFalse(r["job_observation"]["sampled_all_in_progress_runs"])
        self.assertEqual(
            r["job_observation"]["running_job_runner_types_lower_bound"]["self-hosted"],
            1,
        )

    def test_queue_delay_ignores_queued_and_skipped_job_timestamps(self):
        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        run = {
            "id": 123,
            "status": "in_progress",
            "created_at": "2026-10-17T04:00:00Z",
        }

        def query(path, params):
            if path.endswith("/runs"):
                if "created" in params:
                    return {"total_count": 0, "workflow_runs": []}
                if params["status"] == "in_progress":
                    return {"total_count": 1, "workflow_runs": [run]}
                return {"total_count": 0, "workflow_runs": []}
            return {
                "total_count": 3,
                "jobs": [
                    {
                        "status": "queued",
                        "created_at": "2026-10-17T04:00:00Z",
                        "started_at": "2026-10-17T04:00:00Z",
                        "runner_name": None,
                    },
                    {
                        "status": "completed",
                        "conclusion": "skipped",
                        "created_at": "2026-10-17T04:00:00Z",
                        "started_at": "2026-10-17T04:00:00Z",
                        "runner_name": None,
                    },
                    {
                        "status": "in_progress",
                        "created_at": "2026-10-17T04:00:00Z",
                        "started_at": "2026-10-17T04:03:00Z",
                        "runner_name": "GitHub Actions 123",
                        "labels": ["ubuntu-24.04"],
                    },
                ],
            }

        result = summarize("owner/repo", query, now=now)
        observed = result["job_observation"]
        self.assertEqual(observed["observed_started_jobs"], 1)
        self.assertEqual(observed["median_started_job_queue_seconds"], 180)
        self.assertEqual(observed["currently_running_jobs_lower_bound"], 1)

    def test_workflow_retains_fifo_pending_runs(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/github-actions-fleet-500.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("  queue: max\n", workflow)
        self.assertIn("inputs.per_cohort || 'none'", workflow)
        self.assertIn("  cancel-in-progress: false\n", workflow)


if __name__ == "__main__":
    unittest.main()
