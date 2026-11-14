import copy
import unittest

from hepta_ci_gate import REQUIRED_WORKFLOWS, InvalidSnapshot, evaluate

SHA = "a" * 40
OLD_SHA = "b" * 40


def sample():
    return {
        "branch_sha": SHA,
        "workflow_runs": [
            {"id": i + 1, "name": name, "head_sha": SHA, "event": "pull_request", "status": "completed", "conclusion": "success", "run_attempt": 1}
            for i, name in enumerate(REQUIRED_WORKFLOWS)
        ],
    }


class GateTest(unittest.TestCase):
    def test_all_green_is_diagnostic_not_promotion(self):
        result = evaluate(sample(), SHA)
        self.assertTrue(result["ci_all_required_success"])
        self.assertFalse(result["promotion_authorized"])
        self.assertFalse(result["production_route_verified"])

    def test_missing_workflow_fails_closed(self):
        record = sample()
        record["workflow_runs"].pop()
        self.assertFalse(evaluate(record, SHA)["ci_all_required_success"])

    def test_old_green_cannot_substitute(self):
        record = sample()
        record["workflow_runs"][0]["head_sha"] = OLD_SHA
        self.assertFalse(evaluate(record, SHA)["ci_all_required_success"])

    def test_queued_and_cancelled_fail(self):
        for status, conclusion in (("queued", None), ("completed", "cancelled"), ("completed", "skipped"), ("completed", "failure")):
            with self.subTest(status=status, conclusion=conclusion):
                record = sample()
                record["workflow_runs"][1].update(status=status, conclusion=conclusion)
                self.assertFalse(evaluate(record, SHA)["ci_all_required_success"])

    def test_newer_attempt_supersedes_prior_success(self):
        record = sample()
        bad = copy.deepcopy(record["workflow_runs"][0])
        bad["id"] = 10000
        bad["status"] = "in_progress"
        bad["conclusion"] = None
        record["workflow_runs"].append(bad)
        self.assertFalse(evaluate(record, SHA)["ci_all_required_success"])

    def test_newer_run_attempt_supersedes_success(self):
        record = sample()
        bad = copy.deepcopy(record["workflow_runs"][0])
        bad["run_attempt"] = 2
        bad["status"] = "completed"
        bad["conclusion"] = "failure"
        record["workflow_runs"].append(bad)
        self.assertFalse(evaluate(record, SHA)["ci_all_required_success"])

    def test_duplicate_conflicting_attempt_rejected(self):
        record = sample()
        bad = copy.deepcopy(record["workflow_runs"][0])
        bad["status"] = "queued"
        bad["conclusion"] = None
        record["workflow_runs"].append(bad)
        with self.assertRaises(InvalidSnapshot):
            evaluate(record, SHA)

    def test_wrong_branch_and_invalid_sha_rejected(self):
        with self.assertRaises(InvalidSnapshot):
            evaluate(sample(), OLD_SHA)
        with self.assertRaises(InvalidSnapshot):
            evaluate(sample(), "HEAD")

    def test_missing_event_or_attempt_fails_closed(self):
        for field in ("event", "run_attempt"):
            with self.subTest(field=field):
                record = sample()
                del record["workflow_runs"][0][field]
                with self.assertRaises(InvalidSnapshot):
                    evaluate(record, SHA)

    def test_run_id_is_not_reused_for_multiple_workflows(self):
        record = sample()
        record["workflow_runs"][1]["id"] = record["workflow_runs"][0]["id"]
        with self.assertRaises(InvalidSnapshot):
            evaluate(record, SHA)

    def test_manual_dispatch_cannot_substitute_pr(self):
        record = sample()
        record["workflow_runs"][0]["event"] = "workflow_dispatch"
        self.assertFalse(evaluate(record, SHA)["ci_all_required_success"])

    def test_non_accepting_security_probe_does_not_fake_green(self):
        record = sample()
        record["workflow_runs"].append({"id": 100, "name": "Hepta Matrix advisory upgrade probe (non-accepting)", "head_sha": SHA, "status": "completed", "conclusion": "failure", "event": "pull_request", "run_attempt": 1})
        result = evaluate(record, SHA)
        self.assertTrue(result["ci_all_required_success"])
        self.assertEqual(result["non_accepting_probes"]["Hepta Matrix advisory upgrade probe (non-accepting)"]["conclusion"], "failure")
        self.assertFalse(result["promotion_authorized"])

    def test_invalid_or_oversized_snapshot_rejected(self):
        record = sample()
        record["workflow_runs"][0]["id"] = "1"
        with self.assertRaises(InvalidSnapshot):
            evaluate(record, SHA)
        record = sample()
        record["workflow_runs"] = record["workflow_runs"] * 30
        with self.assertRaises(InvalidSnapshot):
            evaluate(record, SHA)


if __name__ == "__main__":
    unittest.main()
