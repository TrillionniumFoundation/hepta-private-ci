"""Checks that organization-wide peak concurrency requires real overlapping jobs."""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from scripts.github_actions_org_capacity import (
    collect,
    job_intervals,
    parse_time,
    provable_peak,
)


def stamp(minutes: int = 0, seconds: int = 0) -> datetime:
    return datetime(2026, 10, 17, 4, tzinfo=timezone.utc) + timedelta(
        minutes=minutes, seconds=seconds
    )


class OrgPeakProofTests(unittest.TestCase):
    def test_parse_timestamp_is_strict_and_timezone_aware(self):
        self.assertEqual(parse_time("2026-10-17T04:00:00Z"), stamp())
        self.assertIsNone(parse_time("2026-10-17T04:00:00"))
        self.assertIsNone(parse_time("not-a-time"))
        self.assertIsNone(parse_time(None))

    def test_queued_and_unassigned_jobs_never_become_running_intervals(self):
        data = [
            {
                "status": "queued",
                "started_at": stamp().isoformat(),
                "runner_name": "misleading queued runner",
            },
            {
                "status": "in_progress",
                "started_at": stamp().isoformat(),
                "runner_name": None,
                "runner_id": None,
            },
            {
                "status": "completed",
                "conclusion": "skipped",
                "started_at": stamp().isoformat(),
                "completed_at": stamp(4).isoformat(),
            },
            {
                "status": "in_progress",
                "started_at": stamp().isoformat(),
                "runner_name": "GitHub Actions 1234",
            },
        ]
        periods = job_intervals(data, stamp(3), stamp())
        self.assertEqual(periods, [(stamp(), stamp(3))])
        self.assertEqual(provable_peak(periods), (1, stamp()))

    def test_asynchronous_samples_still_prove_true_overlap(self):
        # Job A observed later than B; their conservative existence windows
        # still overlap in UTC. Do not simply add counts from different reads.
        a = job_intervals(
            [
                {
                    "status": "in_progress",
                    "started_at": stamp(-2).isoformat(),
                    "runner_id": 9,
                }
            ],
            stamp(4),
            stamp(),
        )
        b = job_intervals(
            [
                {
                    "status": "in_progress",
                    "started_at": stamp(1).isoformat(),
                    "runner_name": "runner-b",
                }
            ],
            stamp(5),
            stamp(),
        )
        self.assertEqual(provable_peak(a + b), (2, stamp(1)))

    def test_nonoverlap_and_equal_boundaries_do_not_overstate_peak(self):
        self.assertEqual(
            provable_peak([(stamp(), stamp(2)), (stamp(2), stamp(4))]),
            (1, stamp()),
        )
        self.assertEqual(provable_peak([]), (0, None))

    def test_completed_job_intervals_add_only_real_execution(self):
        data = [
            {
                "status": "completed",
                "conclusion": "success",
                "runner_name": "runner",
                "started_at": stamp(1).isoformat(),
                "completed_at": stamp(2).isoformat(),
            },
            {
                "status": "completed",
                "conclusion": "failure",
                "runner_id": 42,
                "started_at": stamp().isoformat(),
                "completed_at": stamp(3).isoformat(),
            },
            {
                "status": "completed",
                "conclusion": "skipped",
                "runner_name": None,
                "started_at": stamp().isoformat(),
                "completed_at": stamp(3).isoformat(),
            },
        ]
        self.assertEqual(
            provable_peak(job_intervals(data, stamp(4), stamp())), (2, stamp(1))
        )

    def test_network_collector_produces_only_verified_lower_bound(self):
        def query(path, params):
            if path.endswith("/repos"):
                return [
                    {"name": "hepta-private-ci", "archived": False},
                    {"name": "archived-old", "archived": True},
                ]
            if path.endswith("/runs"):
                self.assertEqual(params["status"], "in_progress")
                return {"total_count": 1, "workflow_runs": [{"id": 17}]}
            self.assertIn("/17/jobs", path)
            return {
                "total_count": 3,
                "jobs": [
                    {
                        "id": 101,
                        "status": "in_progress",
                        "runner_name": "runner A",
                        "labels": ["ubuntu-24.04"],
                        "started_at": stamp(-2).isoformat(),
                    },
                    {
                        "id": 102,
                        "status": "in_progress",
                        "runner_id": 45,
                        "labels": ["ubuntu-latest"],
                        "started_at": stamp(-1).isoformat(),
                    },
                    {
                        "id": 103,
                        "status": "queued",
                        "runner_name": None,
                        "started_at": stamp().isoformat(),
                    },
                ],
            }

        times = iter([stamp(), stamp(1), stamp(2)])
        result = collect(
            "TrillionniumFoundation", query, clock=lambda: next(times), workers=1
        )
        self.assertTrue(result["all_read_paths_complete"])
        self.assertEqual(result["repositories_visible"], 1)
        self.assertEqual(result["sampled_job_records"], 3)
        self.assertEqual(result["job_states_seen_nonatomic"]["in_progress"], 2)
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 2)
        self.assertEqual(result["peak_proof_timestamp"], stamp().isoformat())
        self.assertFalse(result["verified_500_running"])

    def test_queued_parent_running_child_is_counted_without_duplicate_run_reads(self):
        job_reads = []

        def query(path, params):
            if path.endswith("/repos"):
                return [{"name": "one", "archived": False}]
            if path.endswith("/runs"):
                # Run 17 transitions between the two separately observed lists.
                ids = [17] if params["status"] == "in_progress" else [17, 18]
                return {
                    "total_count": len(ids),
                    "workflow_runs": [{"id": value} for value in ids],
                }
            run_id = int(path.split("/")[-2])
            job_reads.append(run_id)
            return {
                "total_count": 1,
                "jobs": [
                    {
                        "id": run_id * 100,
                        "status": "in_progress",
                        "runner_id": run_id,
                        "labels": ["ubuntu-24.04"],
                        "started_at": stamp(-1).isoformat(),
                    }
                ],
            }

        ticks = iter(range(10))
        result = collect(
            "Sample-Org",
            query,
            clock=lambda: stamp(next(ticks)),
            workers=1,
            include_queued=True,
        )
        self.assertEqual(job_reads, [17, 18])
        self.assertEqual(
            {
                key: result[key]
                for key in (
                    "provider_active_workflow_runs_by_repository",
                    "provider_workflow_run_counts_by_status_and_repository",
                    "unique_parent_runs_discovered",
                    "workflow_runs_sampled",
                    "sampled_job_records",
                    "job_states_seen_nonatomic",
                    "peak_provable_concurrent_jobs_lower_bound",
                    "all_read_paths_complete",
                )
            },
            {
                "provider_active_workflow_runs_by_repository": {"one": 1},
                "provider_workflow_run_counts_by_status_and_repository": {
                    "in_progress": {"one": 1},
                    "queued": {"one": 2},
                },
                "unique_parent_runs_discovered": 2,
                "workflow_runs_sampled": 2,
                "sampled_job_records": 2,
                "job_states_seen_nonatomic": {"in_progress": 2},
                "peak_provable_concurrent_jobs_lower_bound": 2,
                "all_read_paths_complete": True,
            },
        )

    def test_queued_runs_share_global_limit_without_displacing_active_parents(self):
        job_reads = []

        def query(path, params):
            if path.endswith("/repos"):
                return [{"name": "one", "archived": False}]
            if path.endswith("/runs"):
                ids = [99] if params["status"] == "in_progress" else [1, 2]
                return {
                    "total_count": len(ids),
                    "workflow_runs": [{"id": value} for value in ids],
                }
            job_reads.append(int(path.split("/")[-2]))
            return {"total_count": 0, "jobs": []}

        ticks = iter(range(10))
        result = collect(
            "Sample-Org",
            query,
            clock=lambda: stamp(next(ticks)),
            workers=1,
            include_queued=True,
            max_runs=1,
        )
        self.assertEqual(job_reads, [99])
        self.assertEqual(
            {
                key: result[key]
                for key in (
                    "unique_parent_runs_discovered",
                    "parent_runs_omitted_by_max_runs",
                    "sampled_parent_run_query_statuses",
                    "all_read_paths_complete",
                    "errors",
                )
            },
            {
                "unique_parent_runs_discovered": 3,
                "parent_runs_omitted_by_max_runs": 2,
                "sampled_parent_run_query_statuses": {"in_progress": 1},
                "all_read_paths_complete": False,
                "errors": [
                    {
                        "stage": "active_runs",
                        "reason": "max_runs_exceeded",
                        "available": 3,
                        "limit": 1,
                    }
                ],
            },
        )

    def test_queued_query_failure_keeps_active_job_evidence_and_reports_unknown_count(
        self,
    ):
        def query(path, params):
            if path.endswith("/repos"):
                return [{"name": "one", "archived": False}]
            if path.endswith("/runs"):
                if params["status"] == "queued":
                    raise OSError("fixture read failure")
                return {"total_count": 1, "workflow_runs": [{"id": 17}]}
            return {
                "total_count": 1,
                "jobs": [
                    {
                        "id": 1700,
                        "status": "in_progress",
                        "runner_id": 17,
                        "started_at": stamp(-1).isoformat(),
                    }
                ],
            }

        ticks = iter(range(10))
        result = collect(
            "Sample-Org",
            query,
            clock=lambda: stamp(next(ticks)),
            workers=1,
            include_queued=True,
        )
        self.assertEqual(
            {
                key: result[key]
                for key in (
                    "provider_workflow_run_counts_by_status_and_repository",
                    "peak_provable_concurrent_jobs_lower_bound",
                    "all_read_paths_complete",
                    "errors",
                )
            },
            {
                "provider_workflow_run_counts_by_status_and_repository": {
                    "in_progress": {"one": 1},
                    "queued": {"one": None},
                },
                "peak_provable_concurrent_jobs_lower_bound": 1,
                "all_read_paths_complete": False,
                "errors": [
                    {
                        "stage": "active_runs",
                        "repo": "one",
                        "status": "queued",
                        "reason": "OSError",
                    }
                ],
            },
        )

    def test_queued_pagination_limit_is_explicitly_incomplete(self):
        pages = []

        def query(path, params):
            if path.endswith("/repos"):
                return [{"name": "one", "archived": False}]
            if path.endswith("/runs"):
                pages.append((params["status"], params["page"]))
                if params["status"] == "in_progress":
                    return {"total_count": 0, "workflow_runs": []}
                return {
                    "total_count": 101,
                    "workflow_runs": [{"id": value} for value in range(100)],
                }
            return {"total_count": 0, "jobs": []}

        ticks = iter(range(10))
        result = collect(
            "Sample-Org",
            query,
            clock=lambda: stamp(next(ticks)),
            workers=1,
            include_queued=True,
            max_run_pages=1,
            max_runs=1,
        )
        self.assertEqual(pages, [("in_progress", 1), ("queued", 1)])
        self.assertEqual(result["unique_parent_runs_discovered"], 100)
        self.assertEqual(
            result["sampling_limits"]["max_run_pages_per_repository_status"], 1
        )
        self.assertFalse(result["all_read_paths_complete"])
        self.assertIn(
            {
                "stage": "active_runs",
                "repo": "one",
                "status": "queued",
                "reason": "truncated",
            },
            result["errors"],
        )

    def test_parent_run_total_decrease_does_not_hide_missing_run(self):
        pages = []

        def query(path, params):
            if path.endswith("/repos"):
                return [{"name": "one"}]
            if path.endswith("/runs"):
                pages.append(params["page"])
                if params["page"] == 1:
                    return {
                        "total_count": 102,
                        "workflow_runs": [{"id": value} for value in range(1, 101)],
                    }
                return {"total_count": 101, "workflow_runs": [{"id": 101}]}
            return {"total_count": 0, "jobs": []}

        result = collect("Sample-Org", query, clock=stamp, workers=1, max_run_pages=2)
        self.assertEqual(pages, [1, 2])
        self.assertEqual(result["unique_parent_runs_discovered"], 101)
        self.assertEqual(
            result["provider_active_workflow_runs_by_repository"], {"one": 101}
        )
        self.assertFalse(result["all_read_paths_complete"])
        self.assertIn(
            {
                "stage": "active_runs",
                "repo": "one",
                "status": "in_progress",
                "reason": "truncated",
            },
            result["errors"],
        )

    def test_incomplete_run_list_never_claims_complete_read(self):
        def query(path, params):
            if path.endswith("/repos"):
                return [{"name": "one", "archived": False}]
            if path.endswith("/runs"):
                return {"total_count": 2, "workflow_runs": [{"id": 4}, {"id": 5}]}
            return {"total_count": 0, "jobs": []}

        times = iter([stamp(), stamp(1), stamp(2)])
        result = collect(
            "Sample-Org", query, clock=lambda: next(times), workers=1, max_runs=1
        )
        self.assertFalse(result["all_read_paths_complete"])
        self.assertTrue(
            any(x["reason"] == "max_runs_exceeded" for x in result["errors"])
        )

    def test_invalid_org_name_rejected_without_network(self):
        with self.assertRaises(ValueError):
            collect("../org", lambda *args: self.fail("network must not run"))


class JobPaginationTests(unittest.TestCase):
    def job(self, job_id, **changes):
        return {
            "id": job_id,
            "run_id": 17,
            "status": "completed",
            "conclusion": "success",
            "runner_id": job_id,
            "started_at": stamp().isoformat(),
            "completed_at": stamp(3).isoformat(),
            **changes,
        }

    def collect_pages(self, pages, **options):
        reads = []

        def query(path, params):
            if path.endswith("/repos"):
                return [{"name": "one"}]
            if path.endswith("/runs"):
                return {"total_count": 1, "workflow_runs": [{"id": 17}]}
            page = params["page"]
            reads.append(page)
            self.assertLessEqual(page, len(pages))
            return pages[page - 1]

        ticks = iter([stamp(), stamp(1), stamp(4)])
        result = collect(
            "Sample-Org", query, clock=lambda: next(ticks), workers=1, **options
        )
        return result, reads

    def test_cross_page_duplicate_counts_one_job_and_keeps_missing_job(self):
        result, reads = self.collect_pages(
            [
                {"total_count": 101, "jobs": [self.job(i) for i in range(1, 101)]},
                {"total_count": 101, "jobs": [self.job(100), self.job(101)]},
            ]
        )
        self.assertEqual(reads, [1, 2])
        self.assertEqual(result["sampled_job_records"], 102)
        self.assertEqual(result["unique_sampled_job_records"], 101)
        self.assertEqual(result["duplicate_job_records"], 1)
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 101)
        self.assertEqual(result["job_states_seen_nonatomic"], {"completed": 101})
        self.assertTrue(result["all_read_paths_complete"])

    def test_repeated_page_cannot_end_read_before_new_ids_are_seen(self):
        first = {"total_count": 101, "jobs": [self.job(i) for i in range(1, 101)]}
        result, reads = self.collect_pages(
            [first, first, {"total_count": 101, "jobs": [self.job(101)]}]
        )
        self.assertEqual(reads, [1, 2, 3])
        self.assertEqual(result["sampled_job_records"], 201)
        self.assertEqual(result["unique_sampled_job_records"], 101)
        self.assertEqual(result["duplicate_job_records"], 100)
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 101)
        self.assertTrue(result["all_read_paths_complete"])

    def test_repeated_pages_exhaust_budget_without_claiming_complete_read(self):
        page = {"total_count": 101, "jobs": [self.job(i) for i in range(1, 101)]}
        result, reads = self.collect_pages([page, page], max_job_pages=2)
        self.assertEqual(reads, [1, 2])
        self.assertEqual(result["unique_sampled_job_records"], 100)
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 100)
        self.assertEqual(result["complete_job_pages"], 0)
        self.assertFalse(result["all_read_paths_complete"])
        self.assertIn("truncated", [problem["reason"] for problem in result["errors"]])

    def test_repeated_pages_cannot_falsely_certify_500_runners(self):
        page = {"total_count": 500, "jobs": [self.job(i) for i in range(1, 101)]}
        result, reads = self.collect_pages([page] * 5, max_job_pages=5)
        self.assertEqual(reads, [1, 2, 3, 4, 5])
        self.assertEqual(result["sampled_job_records"], 500)
        self.assertEqual(result["unique_sampled_job_records"], 100)
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 100)
        self.assertFalse(result["verified_500_running"])
        self.assertFalse(result["all_read_paths_complete"])

    def test_500_in_progress_jobs_are_observed_without_terminal_verification(self):
        jobs = [
            self.job(i, status="in_progress", completed_at=None, conclusion=None)
            for i in range(1, 501)
        ]
        result, _ = self.collect_pages(
            [
                {"total_count": 500, "jobs": jobs[offset : offset + 100]}
                for offset in range(0, 500, 100)
            ]
        )
        self.assertFalse(result["verified_500_running"])
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 500)
        self.assertEqual(result["peak_terminal_concurrent_jobs_lower_bound"], 0)
        self.assertIsNone(result["peak_terminal_proof_timestamp"])
        self.assertTrue(result["all_read_paths_complete"])

    def test_500_completed_jobs_verify_overlapping_terminal_intervals(self):
        jobs = [self.job(i) for i in range(1, 501)]
        result, _ = self.collect_pages(
            [
                {"total_count": 500, "jobs": jobs[offset : offset + 100]}
                for offset in range(0, 500, 100)
            ]
        )
        self.assertTrue(result["verified_500_running"])
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 500)
        self.assertEqual(result["peak_terminal_concurrent_jobs_lower_bound"], 500)
        self.assertEqual(result["peak_terminal_proof_timestamp"], stamp().isoformat())
        self.assertTrue(result["all_read_paths_complete"])

    def test_mixed_500_jobs_cannot_verify_499_terminal_intervals(self):
        jobs = [self.job(i) for i in range(1, 500)]
        jobs.append(
            self.job(500, status="in_progress", completed_at=None, conclusion=None)
        )
        result, _ = self.collect_pages(
            [
                {"total_count": 500, "jobs": jobs[offset : offset + 100]}
                for offset in range(0, 500, 100)
            ]
        )
        self.assertFalse(result["verified_500_running"])
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 500)
        self.assertEqual(result["peak_terminal_concurrent_jobs_lower_bound"], 499)
        self.assertEqual(result["peak_terminal_proof_timestamp"], stamp().isoformat())
        self.assertTrue(result["all_read_paths_complete"])

    def test_missing_or_invalid_runner_id_cannot_supply_500th_terminal_runner(self):
        for runner_id in (None, 0, -99, True, "99"):
            for runner_name in ("known-runner", "other-runner"):
                with self.subTest(runner_id=runner_id, runner_name=runner_name):
                    jobs = [self.job(i) for i in range(2, 501)]
                    jobs[0]["runner_name"] = "known-runner"
                    jobs.append(
                        self.job(1, runner_id=runner_id, runner_name=runner_name)
                    )
                    result, _ = self.collect_pages(
                        [
                            {"total_count": 500, "jobs": jobs[offset : offset + 100]}
                            for offset in range(0, 500, 100)
                        ]
                    )
                    self.assertFalse(result["verified_500_running"])
                    self.assertEqual(
                        result["peak_provable_concurrent_jobs_lower_bound"], 500
                    )
                    self.assertEqual(
                        result["peak_terminal_concurrent_jobs_lower_bound"], 499
                    )
                    self.assertTrue(result["all_read_paths_complete"])

    def test_job_with_mismatched_parent_cannot_supply_500th_terminal_job(self):
        for reported_run_id in (18, "17", True):
            with self.subTest(reported_run_id=reported_run_id):
                jobs = [self.job(i) for i in range(2, 501)]
                jobs.append(self.job(1, run_id=reported_run_id))
                result, _ = self.collect_pages(
                    [
                        {"total_count": 500, "jobs": jobs[offset : offset + 100]}
                        for offset in range(0, 500, 100)
                    ]
                )
                self.assertFalse(result["verified_500_running"])
                self.assertEqual(result["unique_sampled_job_records"], 499)
                self.assertEqual(
                    result["peak_terminal_concurrent_jobs_lower_bound"], 499
                )
                self.assertFalse(result["all_read_paths_complete"])
                self.assertIn(
                    "job_parent_mismatch",
                    [problem["reason"] for problem in result["errors"]],
                )

    def test_normal_pagination_preserves_counts_and_execution_peak(self):
        result, reads = self.collect_pages(
            [
                {"total_count": 101, "jobs": [self.job(i) for i in range(1, 101)]},
                {"total_count": 101, "jobs": [self.job(101)]},
            ]
        )
        self.assertEqual(reads, [1, 2])
        self.assertEqual(result["sampled_job_records"], 101)
        self.assertEqual(result["unique_sampled_job_records"], 101)
        self.assertEqual(result["duplicate_job_records"], 0)
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 101)
        self.assertTrue(result["all_read_paths_complete"])

    def test_exact_full_page_can_complete_at_the_declared_page_budget(self):
        result, reads = self.collect_pages(
            [
                {"total_count": 100, "jobs": [self.job(i) for i in range(1, 101)]},
            ],
            max_job_pages=1,
        )
        self.assertEqual(reads, [1])
        self.assertEqual(result["unique_sampled_job_records"], 100)
        self.assertTrue(result["all_read_paths_complete"])

    def test_short_page_with_missing_ids_remains_incomplete(self):
        result, reads = self.collect_pages(
            [{"total_count": 2, "jobs": [self.job(1), self.job(1)]}]
        )
        self.assertEqual(reads, [1])
        self.assertEqual(result["unique_sampled_job_records"], 1)
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 1)
        self.assertFalse(result["all_read_paths_complete"])

    def test_total_decrease_does_not_hide_an_earlier_missing_job(self):
        result, _ = self.collect_pages(
            [
                {"total_count": 102, "jobs": [self.job(i) for i in range(1, 101)]},
                {"total_count": 101, "jobs": [self.job(101)]},
            ]
        )
        self.assertEqual(result["unique_sampled_job_records"], 101)
        self.assertFalse(result["all_read_paths_complete"])

    def test_state_refresh_keeps_terminal_identity_even_after_stale_page(self):
        queued = self.job(
            1, status="queued", runner_id=0, started_at=stamp(-2).isoformat()
        )
        running = self.job(1, status="in_progress", completed_at=None, conclusion=None)
        result, _ = self.collect_pages(
            [{"total_count": 1, "jobs": [queued, running, self.job(1), running]}]
        )
        self.assertEqual(result["unique_sampled_job_records"], 1)
        self.assertEqual(result["duplicate_job_records"], 3)
        self.assertEqual(result["job_states_seen_nonatomic"], {"completed": 1})
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 1)
        self.assertTrue(result["all_read_paths_complete"])

    def test_changed_execution_identity_is_excluded_and_cannot_reappear(self):
        for changes in (
            {"runner_id": 77},
            {"started_at": stamp(-2).isoformat()},
            {"completed_at": stamp(5).isoformat()},
            {"conclusion": "failure"},
            {"run_id": 99},
        ):
            with self.subTest(changes=changes):
                result, _ = self.collect_pages(
                    [
                        {
                            "total_count": 2,
                            "jobs": [
                                self.job(1),
                                self.job(1, **changes),
                                self.job(1),
                                self.job(2),
                            ],
                        }
                    ]
                )
                self.assertEqual(result["unique_sampled_job_records"], 1)
                self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 1)
                self.assertFalse(result["all_read_paths_complete"])
                self.assertIn(
                    "job_parent_mismatch"
                    if "run_id" in changes
                    else "conflicting_job_observations",
                    [problem["reason"] for problem in result["errors"]],
                )

    def test_unidentified_records_cannot_masquerade_as_distinct_jobs(self):
        unidentified = self.job(1)
        del unidentified["id"]
        result, _ = self.collect_pages(
            [{"total_count": 3, "jobs": [self.job(1), self.job(True), unidentified]}]
        )
        self.assertEqual(result["sampled_job_records"], 3)
        self.assertEqual(result["unique_sampled_job_records"], 1)
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 1)
        self.assertFalse(result["all_read_paths_complete"])

    def test_one_runner_cannot_inflate_peak_with_overlapping_jobs(self):
        result, _ = self.collect_pages(
            [
                {
                    "total_count": 3,
                    "jobs": [
                        self.job(1, completed_at=stamp(2).isoformat()),
                        self.job(2, runner_id=1, started_at=stamp(1).isoformat()),
                        self.job(3),
                    ],
                }
            ]
        )
        self.assertEqual(result["unique_sampled_job_records"], 3)
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 2)
        self.assertIn(
            "overlapping_runner_jobs",
            [problem["reason"] for problem in result["errors"]],
        )

    def test_sequential_runner_reuse_does_not_create_a_conflict(self):
        result, _ = self.collect_pages(
            [
                {
                    "total_count": 2,
                    "jobs": [
                        self.job(1, completed_at=stamp(1).isoformat()),
                        self.job(2, runner_id=1, started_at=stamp(1).isoformat()),
                    ],
                }
            ]
        )
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 1)
        self.assertTrue(result["all_read_paths_complete"])

    def test_same_job_under_different_parent_runs_is_not_additional_capacity(self):
        def query(path, params):
            if path.endswith("/repos"):
                return [{"name": "one"}]
            if path.endswith("/runs"):
                return {"total_count": 2, "workflow_runs": [{"id": 17}, {"id": 18}]}
            return {
                "total_count": 1,
                "jobs": [self.job(1, run_id=int(path.split("/")[-2]))],
            }

        ticks = iter(range(5))
        result = collect(
            "Sample-Org", query, clock=lambda: stamp(next(ticks)), workers=1
        )
        self.assertEqual(result["sampled_job_records"], 2)
        self.assertEqual(result["unique_sampled_job_records"], 0)
        self.assertEqual(result["peak_provable_concurrent_jobs_lower_bound"], 0)
        self.assertFalse(result["all_read_paths_complete"])
        self.assertIn(
            "job_in_multiple_runs", [problem["reason"] for problem in result["errors"]]
        )

    def test_local_job_conflict_cannot_reappear_from_another_parent(self):
        first_run_pages = [
            {
                "total_count": 101,
                "jobs": [self.job(1)] + [self.job(i) for i in range(1001, 1100)],
            },
            {"total_count": 101, "jobs": [self.job(1, runner_id=999), self.job(1100)]},
        ]
        second_run_jobs = [self.job(i, run_id=18) for i in range(1, 401)]
        second_run_pages = [
            {"total_count": 400, "jobs": second_run_jobs[offset : offset + 100]}
            for offset in range(0, 400, 100)
        ]

        def query(path, params):
            if path.endswith("/repos"):
                return [{"name": "one"}]
            if path.endswith("/runs"):
                return {"total_count": 2, "workflow_runs": [{"id": 17}, {"id": 18}]}
            pages = first_run_pages if "/17/jobs" in path else second_run_pages
            return pages[params["page"] - 1]

        # Consume the conflicted parent's future first and last. A completion
        # order change must neither revive the ID nor preserve an earlier copy.
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                ticks = iter([stamp(), stamp(1), stamp(1), stamp(4)])
                with patch(
                    "scripts.github_actions_org_capacity.as_completed",
                    side_effect=lambda futures: (
                        reversed(futures) if reverse else iter(futures)
                    ),
                ):
                    result = collect(
                        "Sample-Org", query, clock=lambda: next(ticks), workers=1
                    )
                self.assertFalse(result["verified_500_running"])
                self.assertEqual(result["sampled_job_records"], 502)
                self.assertEqual(result["unique_sampled_job_records"], 499)
                self.assertEqual(
                    result["peak_terminal_concurrent_jobs_lower_bound"], 499
                )
                self.assertFalse(result["all_read_paths_complete"])
                self.assertIn(
                    "conflicting_job_observations",
                    [problem["reason"] for problem in result["errors"]],
                )


if __name__ == "__main__":
    unittest.main()
