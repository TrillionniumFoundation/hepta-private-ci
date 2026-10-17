"""Checks that organization-wide peak concurrency requires real overlapping jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

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
                return {"total_count": 1, "workflow_runs": [{"id": 17}]}
            self.assertIn("/17/jobs", path)
            return {
                "total_count": 3,
                "jobs": [
                    {
                        "status": "in_progress",
                        "runner_name": "runner A",
                        "labels": ["ubuntu-24.04"],
                        "started_at": stamp(-2).isoformat(),
                    },
                    {
                        "status": "in_progress",
                        "runner_id": 45,
                        "labels": ["ubuntu-latest"],
                        "started_at": stamp(-1).isoformat(),
                    },
                    {
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


if __name__ == "__main__":
    unittest.main()
