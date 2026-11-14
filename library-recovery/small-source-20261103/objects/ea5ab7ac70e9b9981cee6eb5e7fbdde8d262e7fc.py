"""No network or real GitHub Actions writes. Strict simulated-read tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from hepta_actions_queue_audit import CURRENT_SHA, SCHEMA, InvalidQueue, screen, get_inventory, gh_get

OLD_SHA = "a" * 40
ANOTHER_PR = 4000


def run(id: int, name: str, sha: str=CURRENT_SHA, pr: int=2366,
        status: str="queued", event: str="pull_request", attempt: int=1) -> dict:
    return {"id": id, "name": name, "status": status, "head_sha": sha,
            "event": event, "run_attempt": attempt,
            "pull_requests": [{"number": pr}],
            "created_at": "2026-10-15T12:00:00Z",
            "html_url": f"https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/{id}"}


def data():
    granite = "Hepta Cell Meta pinned Granite retrospective physical study (DENY_ALL)"
    cpu = "Hepta Cell Meta physical Router CPU research"
    return {"queued":{"total_count":10, "workflow_runs":[
        run(1,granite), run(2,granite,sha=OLD_SHA), run(3,cpu),
        run(4,"blocking-ci",sha=OLD_SHA),
        run(5,"Hepta architecture convergence",sha=OLD_SHA),
        run(6,granite,sha=OLD_SHA,pr=ANOTHER_PR),
        run(7,granite,sha=OLD_SHA,status="queued",event="workflow_dispatch"),
        run(8,granite,sha=OLD_SHA,attempt=2),
        run(9,"Hepta Cell Meta Execution A-F shadow",sha=OLD_SHA),
        run(10,granite,sha=OLD_SHA,status="queued")
    ]},"in_progress":{"total_count":1,"workflow_runs":[
        run(11,granite,sha=OLD_SHA,status="in_progress")
    ]}}


class QueueAuditTests(unittest.TestCase):
    def test_current_head_kept_and_only_research_older_marked_review(self):
        out=screen(data())
        self.assertTrue(out["latest_head_observed"])
        self.assertFalse(out["latest_head_running"])
        self.assertEqual({x["run_id"] for x in out["review_only_possible_supersessions"]},
                         {2,10})
        self.assertEqual(out["cancelled_runs"],[])
        self.assertFalse(out["any_mutation_performed"])

    def test_security_and_architecture_not_reviewable(self):
        out=screen(data())
        ids={x["run_id"] for x in out["review_only_possible_supersessions"]}
        self.assertNotIn(4,ids);self.assertNotIn(5,ids);self.assertNotIn(9,ids)

    def test_other_pr_not_reviewable(self):
        self.assertNotIn(6,{x["run_id"] for x in screen(data())[
            "review_only_possible_supersessions"]})

    def test_running_never_reviewed(self):
        self.assertNotIn(11,{x["run_id"] for x in screen(data())[
            "review_only_possible_supersessions"]})

    def test_manual_and_retry_not_reviewable(self):
        ids={x["run_id"] for x in screen(data())[
            "review_only_possible_supersessions"]}
        self.assertNotIn(7,ids);self.assertNotIn(8,ids)

    def test_no_present_current_head_gives_zero_recommendations(self):
        d=data();d["queued"]["workflow_runs"]=[x for x in d["queued"]["workflow_runs"]
                                             if x["head_sha"]!=CURRENT_SHA]
        self.assertFalse(screen(d)["latest_head_observed"])
        self.assertEqual(screen(d)["review_only_possible_supersessions"],[])

    def test_partial_inventory_not_falsely_complete(self):
        d=data();d["queued"]["total_count"]=1457
        x=screen(d)
        self.assertTrue(x["source_inventory"]["partial_inventory"])
        self.assertEqual(x["source_inventory"]["observed_count"]["queued"],10)
        self.assertEqual(x["source_inventory"]["reported_count"]["queued"],1457)

    def test_wrong_status_bucket_rejected(self):
        d=data();d["queued"]["workflow_runs"][0]["status"]="in_progress"
        with self.assertRaises(InvalidQueue): screen(d)

    def test_duplicate_id_across_status_rejected(self):
        d=data();d["in_progress"]["workflow_runs"][0]["id"]=1
        with self.assertRaises(InvalidQueue): screen(d)

    def test_malformed_sha_rejected(self):
        d=data();d["queued"]["workflow_runs"][0]["head_sha"]="G"*40
        with self.assertRaises(InvalidQueue):screen(d)

    def test_missing_unknown_pr_not_inferred_from_name(self):
        d=data();d["queued"]["workflow_runs"][1]["pull_requests"]=[]
        self.assertNotIn(2,{x["run_id"] for x in screen(d)[
            "review_only_possible_supersessions"]})

    def test_permission_flags_stay_denied(self):
        r=screen(data())
        self.assertEqual(r["authority_posture"],"DENY_ALL")
        self.assertEqual(r["production_admission"],"BLOCKED")
        self.assertFalse(r["github_wide_outage_established"])
        self.assertFalse(r["independent_runner_capacity_verified"])

    def test_read_only_cli_offline_fixture_is_create_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);fixture=p/"fixture.json";out=p/"report.json"
            fixture.write_text(json.dumps(data()))
            script=Path(__file__).with_name("hepta_actions_queue_audit.py")
            cmd=[sys.executable,str(script),"--fixture",str(fixture),
                 "--output",str(out)]
            a=subprocess.run(cmd,capture_output=True,text=True,timeout=8)
            self.assertEqual(a.returncode,0,a.stderr)
            j=json.loads(out.read_text())
            self.assertEqual(j["schema"],SCHEMA)
            self.assertFalse(j["any_mutation_performed"])
            second=subprocess.run(cmd,capture_output=True,text=True,timeout=8)
            self.assertEqual(second.returncode,2)
            self.assertEqual(out.read_text(),json.dumps(j,sort_keys=True,
                ensure_ascii=True,separators=(",", ":"))+"\n")

    def test_paginated_inventory_remains_partial_when_api_caps_at_1000(self):
        def mocked(repo, status, page, token):
            self.assertEqual(status,"queued")
            self.assertLessEqual(page,10)
            return {"total_count":1472,
                    "workflow_runs":[run(1000 * page + i,
                        "Hepta Cell Meta physical Router CPU research") for i in range(100)]}
        with mock.patch("hepta_actions_queue_audit.gh_get", side_effect=mocked):
            queued=get_inventory("TrillionniumFoundation/hepta-private-ci",
                                 "queued",10,None)
        self.assertEqual(queued["total_count"],1472)
        self.assertEqual(len(queued["workflow_runs"]),1000)
        result=screen({"queued":queued,
                       "in_progress":{"total_count":7,"workflow_runs":[]}})
        self.assertTrue(result["source_inventory"]["partial_inventory"])
        self.assertEqual(result["source_inventory"]["observed_count"]["queued"],1000)

    def test_network_reader_issues_only_get(self):
        class DummyResponse:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,n): return b'{"total_count":0,"workflow_runs":[]}'
        def inspect_request(req,timeout):
            self.assertEqual(req.get_method(),"GET")
            self.assertTrue(req.full_url.startswith("https://api.github.com/repos/"))
            self.assertEqual(timeout,25)
            return DummyResponse()
        with mock.patch("hepta_actions_queue_audit.urlopen",side_effect=inspect_request):
            result=gh_get("TrillionniumFoundation/hepta-private-ci","queued",1,None)
        self.assertEqual(result,{"total_count":0,"workflow_runs":[]})

    def test_duplicate_json_keys_denied(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);fixture=p/"duplicate.json";out=p/"report.json"
            fixture.write_text('{"queued":{},"queued":{},"in_progress":{}}')
            script=Path(__file__).with_name("hepta_actions_queue_audit.py")
            x=subprocess.run([sys.executable,str(script),"--fixture",str(fixture),
                              "--output",str(out)],capture_output=True,text=True,timeout=8)
            self.assertEqual(x.returncode,2)
            self.assertFalse(out.exists())


if __name__=="__main__":unittest.main()
