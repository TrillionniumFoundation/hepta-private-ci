import unittest

from control_engineering_v2.workflow_gate import select_exact_run, verify_required_jobs


class WorkflowGateTests(unittest.TestCase):
    def test_selects_latest_attempt_for_exact_sha_and_event(self):
        runs = [
            {"id": 1, "head_sha": "a" * 40, "event": "pull_request", "run_attempt": 1, "created_at": "2026-01-01T00:00:00Z"},
            {"id": 2, "head_sha": "a" * 40, "event": "pull_request", "run_attempt": 2, "created_at": "2026-01-01T00:00:00Z"},
            {"id": 3, "head_sha": "b" * 40, "event": "pull_request", "run_attempt": 1, "created_at": "2026-01-02T00:00:00Z"},
        ]
        self.assertEqual(
            select_exact_run(runs, head_sha="a" * 40, expected_event="pull_request")["id"],
            2,
        )

    def test_required_job_failure_is_not_reinterpreted(self):
        names = (
            "Engineering strong sandbox (source-head)",
            "control.engineering product caller (source-head)",
            "Engineering strong sandbox (base-merge)",
            "control.engineering product caller (base-merge)",
            "control.engineering dual-lane product evidence",
        )
        jobs = [
            {"id": index, "name": name, "status": "completed", "conclusion": "success"}
            for index, name in enumerate(names)
        ]
        self.assertEqual(len(verify_required_jobs(jobs, pull_request=True)["requiredJobs"]), 5)
        jobs[-1]["conclusion"] = "failure"
        with self.assertRaisesRegex(ValueError, "workflow_required_job_not_success"):
            verify_required_jobs(jobs, pull_request=True)


if __name__ == "__main__":
    unittest.main()
