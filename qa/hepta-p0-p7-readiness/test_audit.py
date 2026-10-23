"""Synthetic mechanism tests. No fixture is a real Hepta qualification result."""
import copy
import json
import tempfile
from pathlib import Path
import unittest

from audit import AuditError, REPO, SCHEMA, STAGES, audit, read_json, validate_plan


class MockGitHub:
    def __init__(self, responses):
        self.responses = responses

    def get(self, path):
        return copy.deepcopy(self.responses[path])


def fixtures():
    specs = {}
    for k, stage in enumerate(STAGES):
        sha = f"{k + 1:040x}"
        specs[stage] = {"pr": k + 101, "head_sha": sha,
                        "checks": [
                            {"workflow": "blocking-ci", "jobs": ["native-security"]},
                            {"workflow": "focused", "jobs": ["task-check"]},
                        ]}
    plan = {"schema": SCHEMA, "repository": REPO, "stages": specs}
    db = {}
    base = f"/repos/{REPO}"
    for k, stage in enumerate(STAGES):
        s = specs[stage]
        pr_path = f"{base}/pulls/{s['pr']}"
        db[pr_path] = {"state": "open", "head": {"sha": s["head_sha"]}}
        runs = []
        for idx, requirement in enumerate(s["checks"]):
            ident = 1000 + k * 10 + idx
            runs.append({"name": requirement["workflow"], "head_sha": s["head_sha"],
                         "event": "pull_request", "status": "completed", "conclusion": "success",
                         "id": ident, "run_attempt": 1, "run_started_at": "2026-10-22T10:00:00Z"})
            db[f"{base}/actions/runs/{ident}/jobs?per_page=100"] = {
                "total_count": 1,
                "jobs": [{"name": requirement["jobs"][0],
                          "status": "completed", "conclusion": "success"}]}
        db[f"{base}/actions/runs?head_sha={s['head_sha']}&per_page=100"] = {
            "total_count": len(runs), "workflow_runs": runs}
    return plan, db


class AdmissionTests(unittest.TestCase):
    def test_successful_ci_is_not_scientific_or_production_qualification(self):
        plan, db = fixtures()
        result = audit(plan, MockGitHub(db).get)
        self.assertEqual(result["ci_preflight_count"], 8)
        self.assertEqual(len(result["stages"]), 8)
        self.assertFalse(result["all_blockers_closed"])
        self.assertFalse(result["model_promotion_authorized"])
        self.assertTrue(all(not s["stage_qualified"] for s in result["stages"]))
        self.assertTrue(all(s["scientific_and_authority_blockers"] for s in result["stages"]))

    def test_invalid_plan_cannot_hide_required_stages_or_blocking_ci(self):
        plan, _ = fixtures()
        bad = copy.deepcopy(plan)
        del bad["stages"]["P7"]
        with self.assertRaises(AuditError):
            validate_plan(bad)
        bad = copy.deepcopy(plan)
        bad["stages"]["P2"]["checks"] = [{"workflow": "focused", "jobs": ["ok"]}]
        with self.assertRaises(AuditError):
            validate_plan(bad)
        bad = copy.deepcopy(plan)
        bad["stages"]["P0"]["fake_external_approval"] = True
        with self.assertRaises(AuditError):
            validate_plan(bad)

    def test_invalid_shas_prs_and_duplicate_workflow_names_rejected(self):
        for field, bad_value in (("pr", True), ("pr", 0), ("head_sha", "ab"),
                                 ("head_sha", "F"*40)):
            plan, _ = fixtures()
            plan["stages"]["P0"][field] = bad_value
            with self.subTest(field=field, value=str(bad_value)):
                with self.assertRaises(AuditError):
                    validate_plan(plan)
        plan, _ = fixtures()
        plan["stages"]["P0"]["checks"].append(
            copy.deepcopy(plan["stages"]["P0"]["checks"][0]))
        with self.assertRaises(AuditError):
            validate_plan(plan)

    def test_current_head_mismatch_overrules_old_green_evidence(self):
        plan, db = fixtures()
        db[f"/repos/{REPO}/pulls/101"]["head"]["sha"] = "e"*40
        result = audit(plan, MockGitHub(db).get)
        self.assertEqual(result["ci_preflight_count"], 7)
        self.assertIn("drift", " ".join(result["stages"][0]["ci_blockers"]))

    def test_skipped_native_job_is_not_a_pass(self):
        plan, db = fixtures()
        db[f"/repos/{REPO}/actions/runs/1040/jobs?per_page=100"]["jobs"][0]["conclusion"] = "skipped"
        result = audit(plan, MockGitHub(db).get)
        self.assertEqual(result["stages"][4]["ci_preflight"], "BLOCKED")
        self.assertIn("not actually passed", " ".join(result["stages"][4]["ci_blockers"]))

    def test_more_recent_cancelled_run_cannot_be_hidden_by_old_green(self):
        plan, db = fixtures()
        path = f"/repos/{REPO}/actions/runs?head_sha={plan['stages']['P3']['head_sha']}&per_page=100"
        original = db[path]["workflow_runs"][0]
        newer = dict(original, id=9999, status="completed", conclusion="cancelled",
                     run_started_at="2026-10-23T10:00:00Z")
        db[path]["workflow_runs"].append(newer)
        db[path]["total_count"] += 1
        result = audit(plan, MockGitHub(db).get)
        self.assertEqual(result["stages"][3]["ci_preflight"], "BLOCKED")
        self.assertIn("cancelled", " ".join(result["stages"][3]["ci_blockers"]))

    def test_other_sha_workflow_is_not_reused(self):
        plan, db = fixtures()
        path = f"/repos/{REPO}/actions/runs?head_sha={plan['stages']['P5']['head_sha']}&per_page=100"
        db[path]["workflow_runs"][0]["head_sha"] = "f"*40
        result = audit(plan, MockGitHub(db).get)
        self.assertEqual(result["stages"][5]["ci_preflight"], "BLOCKED")
        self.assertIn("missing exact-SHA", " ".join(result["stages"][5]["ci_blockers"]))

    def test_truncated_github_results_fail_closed(self):
        plan, db = fixtures()
        path = f"/repos/{REPO}/actions/runs?head_sha={plan['stages']['P6']['head_sha']}&per_page=100"
        db[path]["total_count"] = 300
        result = audit(plan, MockGitHub(db).get)
        self.assertEqual(result["stages"][6]["ci_preflight"], "BLOCKED")
        self.assertIn("incomplete", " ".join(result["stages"][6]["ci_blockers"]))

    def test_source_race_detected_on_second_read(self):
        plan, db = fixtures()
        class Racing(MockGitHub):
            def __init__(self, data):
                super().__init__(data)
                self.n = 0
            def get(self, path):
                if path == f"/repos/{REPO}/pulls/101":
                    self.n += 1
                    if self.n == 2:
                        return {"state": "open", "head": {"sha": "f"*40}}
                return super().get(path)
        result = audit(plan, Racing(db).get)
        self.assertEqual(result["stages"][0]["ci_preflight"], "BLOCKED")
        self.assertIn("during audit", " ".join(result["stages"][0]["ci_blockers"]))

    def test_missing_api_record_fails_closed_without_stopping_all_stages(self):
        plan, db = fixtures()
        del db[f"/repos/{REPO}/pulls/102"]
        result = audit(plan, MockGitHub(db).get)
        self.assertEqual(result["ci_preflight_count"], 7)
        self.assertEqual(result["stages"][1]["ci_preflight"], "BLOCKED")
        self.assertFalse(result["all_blockers_closed"])

    def test_duplicate_and_nonfinite_json_disallowed(self):
        with tempfile.TemporaryDirectory() as dirname:
            p = Path(dirname) / "plan.json"
            for value in ('{"schema":1,"schema":2}', '{"x":NaN}', '[1,2,3]'):
                p.write_text(value)
                with self.subTest(value=value):
                    with self.assertRaises(AuditError):
                        read_json(p)


if __name__ == "__main__":
    unittest.main()
