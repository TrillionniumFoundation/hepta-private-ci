import copy
import json
import tempfile
import unittest
from pathlib import Path

import hepta_ci_convergence as subject

BRANCH = "codex/neuron-external-model-trials-20261011"
SHA = "a" * 40
OLD = "b" * 40
REPO = "TrillionniumFoundation/hepta-private-ci"


def fixtures():
    pr = {"number": 1494, "state": "open", "draft": True, "head": {"sha": SHA}, "base": {"repo": {"full_name": REPO}}}
    ref = {"ref": "refs/heads/"+BRANCH, "object": {"sha": SHA}}
    runs = {"workflow_runs": [
        {"id": i+1, "name": name, "head_sha": SHA,
         "event": "pull_request", "status": "completed", "conclusion": "success",
         "created_at": "2026-10-13T06:20:00Z", "run_attempt": 1}
        for i, name in enumerate(subject.REQUIRED)
    ]}
    return pr, ref, runs


def classify(*f):
    return subject.classify(*f, repo=REPO, pr_number=1494, expected_sha=SHA, expected_branch=BRANCH)

class Convergence(unittest.TestCase):
    def test_all_workflows_success_means_only_observed_ci_success(self):
        result = classify(*fixtures())
        self.assertTrue(result["all_required_workflows_success_at_observed_head"])
        self.assertFalse(result["promotion_authorized"])
        self.assertFalse(result["matrix_production_upgrade_verified"])

    def test_missing_check(self):
        p,r,rs=fixtures()
        rs["workflow_runs"].pop()
        report=classify(p,r,rs)
        self.assertFalse(report["all_required_workflows_success_at_observed_head"])
        self.assertEqual(report["checks"][subject.REQUIRED[-1]]["state"],"missing")

    def test_old_sha_success_does_not_count(self):
        p,r,rs=fixtures()
        rs["workflow_runs"][0]["head_sha"]=OLD
        self.assertFalse(classify(p,r,rs)["all_required_workflows_success_at_observed_head"])

    def test_queued_newer_run_beats_old_success(self):
        p,r,rs=fixtures()
        rs["workflow_runs"].append({**rs["workflow_runs"][0],"id":100,"created_at":"2026-10-13T06:21:00Z","status":"queued","conclusion":None})
        self.assertEqual(classify(p,r,rs)["checks"][subject.REQUIRED[0]]["state"],"incomplete")

    def test_later_failure_beats_old_success(self):
        p,r,rs=fixtures()
        rs["workflow_runs"].append({**rs["workflow_runs"][0],"id":101,"created_at":"2026-10-13T06:22:00Z","status":"completed","conclusion":"failure"})
        self.assertFalse(classify(p,r,rs)["all_required_workflows_success_at_observed_head"])

    def test_old_manual_dispatch_does_not_count(self):
        p,r,rs=fixtures()
        rs["workflow_runs"][0]["event"]="workflow_dispatch"
        self.assertEqual(classify(p,r,rs)["checks"][subject.REQUIRED[0]]["state"],"missing")

    def test_drifted_ref_and_pr_fails(self):
        p,r,rs=fixtures()
        r["object"]["sha"]=OLD
        self.assertFalse(classify(p,r,rs)["head_consistent"])
        r["object"]["sha"]=SHA
        p["head"]["sha"]=OLD
        self.assertFalse(classify(p,r,rs)["head_consistent"])

    def test_matrix_probe_success_never_authorizes(self):
        p,r,rs=fixtures()
        rs["workflow_runs"].append({"id":123,"name":subject.MATRIX,"head_sha":SHA,"event":"pull_request", "status":"completed","conclusion":"success","created_at":"2026-10-13T06:20:00Z"})
        result=classify(p,r,rs)
        self.assertFalse(result["matrix_production_upgrade_verified"])
        self.assertFalse(result["promotion_authorized"])

    def test_unknown_conclusion_or_invalid_sha_fails_closed(self):
        p,r,rs=fixtures()
        rs["workflow_runs"][0]["conclusion"]="something"
        with self.assertRaises(subject.EvidenceError): classify(p,r,rs)
        rs["workflow_runs"][0]["conclusion"]="success"
        rs["workflow_runs"][0]["head_sha"]="aaa"
        with self.assertRaises(subject.EvidenceError): classify(p,r,rs)

    def test_wrong_branch_is_invalid(self):
        p,r,rs=fixtures()
        r["ref"]="refs/heads/other"
        with self.assertRaises(subject.EvidenceError): classify(p,r,rs)

    def test_missing_draft_refusal(self):
        p,r,rs=fixtures()
        p["draft"]=False
        with self.assertRaises(subject.EvidenceError): classify(p,r,rs)

    def test_cli_creates_once_and_returns_status(self):
        p,r,rs=fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            for name,value in (("pr",p),("ref",r),("runs",rs)):
                (tmp/f"{name}.json").write_text(json.dumps(value))
            dest=tmp/"result.json"
            args=["--pr",str(tmp/"pr.json"),"--ref",str(tmp/"ref.json"),"--runs",str(tmp/"runs.json"),"--repo",REPO,"--number","1494","--expected-sha",SHA,"--branch",BRANCH,"--output",str(dest)]
            self.assertEqual(subject.main(args),0)
            self.assertEqual(subject.main(args),2)
            self.assertFalse(json.loads(dest.read_text())["promotion_authorized"])

if __name__=="__main__": unittest.main()
