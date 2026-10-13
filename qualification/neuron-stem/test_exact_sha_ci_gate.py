"""Offline tests for the exact-commit GitHub Actions security gate."""
import copy
import unittest

from exact_sha_ci_gate import REQUIRED_WORKFLOWS, qualify

SHA = "a" * 40
STALE = "b" * 40


def fixture():
    runs, jobs = [], {}
    for i, name in enumerate(REQUIRED_WORKFLOWS, 1):
        run_id = i * 100
        runs.append({
            "id": run_id, "name": name, "head_sha": SHA,
            "event": "pull_request", "status": "completed",
            "conclusion": "success", "run_number": 5, "run_attempt": 1,
        })
        one = {"name": "qualified-contract", "status": "completed",
               "conclusion": "success"}
        if name == "blocking-ci":
            jobs[str(run_id)] = {"jobs": [
                {"name": "Select blocking CI scope", "status": "completed",
                 "conclusion": "success"},
                {"name": "cargo-deny / cargo-deny", "status": "completed",
                 "conclusion": "success"},
            ]}
        else:
            jobs[str(run_id)] = {"jobs": [one]}
    return {"workflow_runs": runs}, jobs


class ExactShaGateTests(unittest.TestCase):
    def test_all_true_receipts_pass_but_never_promote(self):
        runs, jobs = fixture()
        r = qualify(SHA, runs, jobs)
        self.assertTrue(r["exact_sha_ci_gate_passed"])
        self.assertEqual(r["status"], "all_required_ci_passed_shadow_only")
        self.assertEqual(len(r["workflow_evidence"]), len(REQUIRED_WORKFLOWS))
        for key in ("production_promotion_permitted",
                    "independent_signed_final_use_verified",
                    "real_jina_weights_executed",
                    "target_host_4096_cell_qualified",
                    "source_artifact_CAS_recovery_verified"):
            self.assertFalse(r[key])

    def test_prior_sha_success_is_not_transferable(self):
        runs, jobs = fixture()
        runs["workflow_runs"][0]["head_sha"] = STALE
        r = qualify(SHA, runs, jobs)
        self.assertFalse(r["exact_sha_ci_gate_passed"])
        self.assertTrue(any("missing exact-head" in x for x in r["blocking_reasons"]))

    def test_newer_failure_wins_over_old_success(self):
        runs, jobs = fixture()
        original = copy.deepcopy(runs["workflow_runs"][-1])
        newer = copy.deepcopy(original)
        newer.update(id=12345, run_number=6, status="completed",
                     conclusion="failure")
        runs["workflow_runs"].append(newer)
        jobs[str(newer["id"])] = {"jobs": [
            {"name": "cargo-deny / cargo-deny",
             "status": "completed", "conclusion": "failure"},
        ]}
        r = qualify(SHA, runs, jobs)
        self.assertFalse(r["exact_sha_ci_gate_passed"])
        self.assertTrue(any("cargo-deny" in x for x in r["blocking_reasons"]))

    def test_missing_or_cancelled_security_job_blocks(self):
        runs, jobs = fixture()
        security = jobs["500"]["jobs"][1]
        security["conclusion"] = "cancelled"
        r = qualify(SHA, runs, jobs)
        self.assertFalse(r["exact_sha_ci_gate_passed"])
        self.assertTrue(any("cargo-deny" in x for x in r["blocking_reasons"]))
        security["conclusion"] = "skipped"
        self.assertFalse(qualify(SHA, runs, jobs)["exact_sha_ci_gate_passed"])
        jobs["500"]["jobs"] = [jobs["500"]["jobs"][0]]
        self.assertFalse(qualify(SHA, runs, jobs)["exact_sha_ci_gate_passed"])

    def test_pending_and_hidden_child_failure_block(self):
        runs, jobs = fixture()
        runs["workflow_runs"][1]["status"] = "in_progress"
        runs["workflow_runs"][1]["conclusion"] = None
        jobs["100"]["jobs"].append({
            "name": "Windows Bazel", "status": "completed", "conclusion": "failure",
        })
        r = qualify(SHA, runs, jobs)
        self.assertFalse(r["exact_sha_ci_gate_passed"])
        self.assertTrue(any("Windows Bazel" in x for x in r["blocking_reasons"]))
        self.assertTrue(any("in_progress" in x for x in r["blocking_reasons"]))

    def test_push_only_result_and_missing_jobs_rejected(self):
        runs, jobs = fixture()
        runs["workflow_runs"][2]["event"] = "push"
        jobs.pop("400")
        r = qualify(SHA, runs, jobs)
        self.assertFalse(r["exact_sha_ci_gate_passed"])
        self.assertTrue(any("missing exact-head" in x for x in r["blocking_reasons"]))
        self.assertTrue(any("missing authoritative jobs" in x for x in r["blocking_reasons"]))

    def test_reused_run_name_or_malformed_inputs_rejected(self):
        runs, jobs = fixture()
        jobs["100"]["jobs"].append(copy.deepcopy(jobs["100"]["jobs"][0]))
        self.assertTrue(any(
            "duplicate job name" in x
            for x in qualify(SHA, runs, jobs)["blocking_reasons"]
        ))
        with self.assertRaises(ValueError):
            qualify("not-a-real-sha", runs, jobs)
        with self.assertRaises(ValueError):
            qualify(SHA, {"workflow_runs": {}}, jobs)
        with self.assertRaises(ValueError):
            qualify(SHA, runs, [])
        runs["workflow_runs"][0]["id"] = 0
        with self.assertRaises(ValueError):
            qualify(SHA, runs, jobs)

    def test_incomplete_github_pagination_does_not_masquerade_as_green(self):
        runs, jobs = fixture()
        runs["total_count"] = len(runs["workflow_runs"]) + 1
        with self.assertRaisesRegex(ValueError, "pagination incomplete"):
            qualify(SHA, runs, jobs)
        runs["total_count"] = len(runs["workflow_runs"])
        jobs["500"]["total_count"] = len(jobs["500"]["jobs"]) + 1
        result = qualify(SHA, runs, jobs)
        self.assertFalse(result["exact_sha_ci_gate_passed"])
        self.assertTrue(any("pagination incomplete" in b for b in result["blocking_reasons"]))

    def test_missing_final_use_or_model_evidence_not_implied(self):
        runs, jobs = fixture()
        extra = {"production_promotion_permitted": True,
                 "independent_signed_final_use_verified": True}
        runs.update(extra)
        result = qualify(SHA, runs, jobs)
        self.assertFalse(result["production_promotion_permitted"])
        self.assertFalse(result["independent_signed_final_use_verified"])


if __name__ == "__main__":
    unittest.main()
