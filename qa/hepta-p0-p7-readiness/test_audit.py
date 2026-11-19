"""Synthetic mechanism tests. No fixture is a real Hepta qualification result."""
import copy
import json
import os
import stat
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from audit import AuditError, REPO, SCHEMA, STAGES, WORKFLOW_PATHS, audit, read_json, validate_plan


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
                            {"workflow": "Hepta architecture convergence", "jobs": ["task-check"]},
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
            runs.append({"name": requirement["workflow"],
                         "path": WORKFLOW_PATHS[requirement["workflow"]],
                         "head_sha": s["head_sha"],
                         "event": "pull_request", "status": "completed", "conclusion": "success",
                         "id": ident, "run_attempt": 1, "run_started_at": "2026-10-22T10:00:00Z",
                         "pull_requests": [{"number": s["pr"],
                                            "head": {"sha": s["head_sha"]}}]})
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

    def test_same_sha_other_pr_cannot_qualify_target(self):
        plan, db = fixtures()
        sha = plan["stages"]["P2"]["head_sha"]
        path = f"/repos/{REPO}/actions/runs?head_sha={sha}&per_page=100"
        db[path]["workflow_runs"][0]["pull_requests"] = [
            {"number": 99999, "head": {"sha": sha}}]
        report = audit(plan, MockGitHub(db).get)
        self.assertEqual(report["stages"][2]["ci_preflight"], "BLOCKED")
        self.assertIn("missing exact-SHA workflow",
                      " ".join(report["stages"][2]["ci_blockers"]))

    def test_missing_or_malformed_pr_link_fails_closed(self):
        plan, original = fixtures()
        sha = plan["stages"]["P0"]["head_sha"]
        path = f"/repos/{REPO}/actions/runs?head_sha={sha}&per_page=100"
        malformed = (
            [],
            [{"number": True, "head": {"sha": sha}}],
            [{"number": 101, "head": {"sha": "f" * 40}}],
            [{"number": "101", "head": {"sha": sha}}],
            [{"number": 101}],
            [{"head": {"sha": sha}}],
            None,
        )
        for links in malformed:
            db = copy.deepcopy(original)
            db[path]["workflow_runs"][0]["pull_requests"] = links
            with self.subTest(links=links):
                report = audit(plan, MockGitHub(db).get)
                self.assertEqual(report["stages"][0]["ci_preflight"], "BLOCKED")

    def test_newer_other_pr_run_does_not_override_own_success(self):
        plan, db = fixtures()
        sha = plan["stages"]["P0"]["head_sha"]
        path = f"/repos/{REPO}/actions/runs?head_sha={sha}&per_page=100"
        foreign = copy.deepcopy(db[path]["workflow_runs"][0])
        foreign.update(id=99999, run_started_at="2026-10-23T10:00:00Z",
                       status="completed", conclusion="failure",
                       pull_requests=[{"number": 202, "head": {"sha": sha}}])
        db[path]["workflow_runs"].append(foreign)
        db[path]["total_count"] += 1
        report = audit(plan, MockGitHub(db).get)
        self.assertEqual(report["stages"][0]["ci_preflight"], "PASS")
        self.assertFalse(report["all_blockers_closed"])


    def test_same_name_different_yaml_cannot_forge_p0_success(self):
        plan, db = fixtures()
        sha = plan["stages"]["P0"]["head_sha"]
        path = f"/repos/{REPO}/actions/runs?head_sha={sha}&per_page=100"
        db[path]["workflow_runs"][0]["path"] = ".github/workflows/lookalike.yml"
        result = audit(plan, MockGitHub(db).get)
        self.assertEqual(result["stages"][0]["ci_preflight"], "BLOCKED")
        self.assertIn("missing exact-SHA workflow",
                      " ".join(result["stages"][0]["ci_blockers"]))

    def test_missing_or_ambiguous_workflow_path_is_not_a_pass(self):
        plan, original = fixtures()
        sha = plan["stages"]["P2"]["head_sha"]
        path = f"/repos/{REPO}/actions/runs?head_sha={sha}&per_page=100"
        for wrong in (None, "", True, 42, ".github/workflows/blocking-ci.yaml",
                      ".github/workflows/../blocking-ci.yml",
                      ".github/workflows/fake.yml"):
            db = copy.deepcopy(original)
            db[path]["workflow_runs"][0]["path"] = wrong
            with self.subTest(wrong=wrong):
                report = audit(plan, MockGitHub(db).get)
                self.assertEqual(report["stages"][2]["ci_preflight"], "BLOCKED")

    def test_newer_name_collision_does_not_replace_authentic_workflow(self):
        plan, db = fixtures()
        sha = plan["stages"]["P1"]["head_sha"]
        path = f"/repos/{REPO}/actions/runs?head_sha={sha}&per_page=100"
        newer = copy.deepcopy(db[path]["workflow_runs"][0])
        newer.update(id=99999, path=".github/workflows/lookalike.yml",
                     run_started_at="2026-10-24T10:00:00Z")
        db[path]["workflow_runs"].append(newer)
        db[path]["total_count"] += 1
        result = audit(plan, MockGitHub(db).get)
        self.assertEqual(result["stages"][1]["ci_preflight"], "PASS")
        self.assertFalse(result["all_blockers_closed"])

    def test_unknown_workflow_name_fails_even_if_blocking_ci_remains(self):
        plan, _ = fixtures()
        plan["stages"]["P0"]["checks"][1]["workflow"] = "blocking-ci-lookalike"
        with self.assertRaises(AuditError):
            validate_plan(plan)

    def test_pinned_candidate_plan_has_only_approved_workflow_names(self):
        plan = read_json(Path(__file__).with_name("candidate_plan.json"))
        validate_plan(plan)
        self.assertTrue(all(
            requirement["workflow"] in WORKFLOW_PATHS
            for stage in plan["stages"].values()
            for requirement in stage["checks"]))

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


    def test_source_closure_detected_on_second_read(self):
        plan, db = fixtures()
        class Closing(MockGitHub):
            def __init__(self, data):
                super().__init__(data)
                self.n = 0
            def get(self, path):
                result = super().get(path)
                if path == f"/repos/{REPO}/pulls/101":
                    self.n += 1
                    if self.n == 2:
                        result["state"] = "closed"
                return result
        result = audit(plan, Closing(db).get)
        self.assertEqual(result["ci_preflight_count"], 7)
        self.assertEqual(result["stages"][0]["ci_preflight"], "BLOCKED")
        self.assertIn("not open during audit", " ".join(result["stages"][0]["ci_blockers"]))
        self.assertFalse(result["all_blockers_closed"])
        self.assertFalse(result["model_promotion_authorized"])

    def test_json_byte_limit_applies_to_the_opened_file(self):
        with tempfile.TemporaryDirectory() as dirname:
            p = Path(dirname) / "plan.json"
            value = b'{"ok":true}'
            p.write_bytes(value + b" " * (256_000 - len(value)))
            self.assertEqual(read_json(p), {"ok": True})
            p.write_bytes(p.read_bytes() + b" ")
            with self.assertRaisesRegex(AuditError, "exceeds 256000"):
                read_json(p)

            # Simulate growth after the descriptor's size check, with ordinary
            # file bytes and a spy that forbids an unbounded underlying read.
            read_sizes = []
            real_fdopen = os.fdopen
            def tracked_fdopen(*args, **kwargs):
                stream = real_fdopen(*args, **kwargs)
                original_read = stream.read
                def bounded_read(size=-1):
                    self.assertGreater(size, 0)
                    self.assertLessEqual(size, 256_001)
                    read_sizes.append(size)
                    return original_read(size)
                stream.read = bounded_read
                return stream
            small = SimpleNamespace(st_mode=stat.S_IFREG, st_size=0)
            with patch("audit.os.fstat", return_value=small), \
                    patch("audit.os.fdopen", side_effect=tracked_fdopen):
                with self.assertRaisesRegex(AuditError, "exceeds 256000"):
                    read_json(p)
            self.assertTrue(read_sizes)
            self.assertLessEqual(sum(read_sizes), 256_001)

    def test_nonregular_opened_file_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as dirname:
            p = Path(dirname) / "plan.json"
            p.write_bytes(b"{}")
            special = SimpleNamespace(st_mode=stat.S_IFIFO, st_size=0)
            with patch("audit.os.fstat", return_value=special), \
                    patch("audit.os.fdopen") as opened:
                with self.assertRaisesRegex(AuditError, "regular file"):
                    read_json(p)
                opened.assert_not_called()

    def test_recursive_json_failure_is_an_audit_error(self):
        with tempfile.TemporaryDirectory() as dirname:
            p = Path(dirname) / "plan.json"
            p.write_bytes(b"{}")
            with patch("audit.json.loads", side_effect=RecursionError("fixture")):
                with self.assertRaisesRegex(AuditError, "invalid JSON"):
                    read_json(p)


if __name__ == "__main__":
    unittest.main()
