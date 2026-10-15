"""Real OS-process fault tests; original Granite weights are NOT used.

The fixed subprocess launcher and separate stdlib review are executed with
ephemeral fake scripts to check custody, failure, timeout and PID isolation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from group_factorial_process_driver import isolated_factorial, SCHEMA


CAMPAIGN = '''import argparse, json, os, sys, time
from pathlib import Path
p=argparse.ArgumentParser()
for option in ("snapshot", "output", "seed", "steps", "train-count",
               "heldout-count", "training-profile", "training-feedback-policy"):
    p.add_argument("--"+option,required=True)
p.add_argument("--terminal-guard",action="store_true")
a=p.parse_args()
if a.seed=="13": raise SystemExit(17)
if a.seed=="14": time.sleep(3)
r=Path(a.output); r.mkdir(parents=True,exist_ok=False)
(r/"report.json").write_text(json.dumps(dict(pid=os.getpid(),
    terminal_guard=a.terminal_guard,
    feedback_policy=a.training_feedback_policy,
    authority="DENY_ALL")))
'''

REVIEWER = '''import argparse, json, os
from pathlib import Path
p=argparse.ArgumentParser()
for item in ("legacy_oracle","legacy_no_verifier","guarded_oracle",
             "guarded_no_verifier"):
    p.add_argument("--"+item.replace("_","-"),required=True)
p.add_argument("--output",required=True)
a=p.parse_args()
rows=[json.loads((Path(getattr(a,name))/"report.json").read_text())
      for name in ("legacy_oracle","legacy_no_verifier",
                   "guarded_oracle","guarded_no_verifier")]
if len(set(x["pid"] for x in rows))!=4: raise SystemExit(3)
if any(x["authority"]!="DENY_ALL" for x in rows): raise SystemExit(4)
success=os.getenv("TEST_INVALID_REVIEW")!="1"
Path(a.output).write_text(json.dumps(dict(passed=success,authority="DENY_ALL",
    production_promotion_permitted=False,
    independently_future_tested=False)))
'''


class IsolatedFactorialProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "preloaded"
        self.snapshot.mkdir()
        self.campaign = self.root / "fake_campaign.py"
        self.campaign.write_text(CAMPAIGN)
        self.reviewer = self.root / "fake_reviewer.py"
        self.reviewer.write_text(REVIEWER)
        self.output = self.root / "result"

    def run_study(self, **kw):
        settings = dict(train_count=16, heldout_count=12, steps=1,
                        timeout_seconds=5)
        settings.update(kw)
        return isolated_factorial(
            self.snapshot, self.output,
            campaign_script=self.campaign, reviewer_script=self.reviewer,
            **settings)

    def test_four_actual_distinct_pids_and_fifth_independent_reviewer(self):
        receipt = self.run_study()
        self.assertEqual(receipt["schema"], SCHEMA)
        self.assertTrue(receipt["completed_four_isolated_model_processes"])
        self.assertTrue(receipt["separate_independent_audit_process"])
        pids = {x["pid"] for x in receipt["model_arms"].values()}
        self.assertEqual(len(pids), 4)
        self.assertNotIn(os.getpid(), pids)
        self.assertNotIn(receipt["independent_review_process"]["pid"], pids)
        self.assertFalse(receipt["production_promotion_permitted"])
        self.assertFalse(receipt["physical_host_provenance_independently_attested"])
        self.assertEqual(len(receipt["original_campaign_source_sha256"]), 64)
        for name, record in receipt["model_arms"].items():
            self.assertEqual(record["exit_code"], 0)
            self.assertGreater(record["wall_ns"], 0)
            self.assertGreaterEqual(record["waited_child_cpu_ns"], 0)
            self.assertEqual(record["terminal_guard"], name.startswith("guarded"))
            self.assertEqual(record["training_feedback_policy"],
                             "no_verifier_v1" if name.endswith("no_verifier")
                             else "legacy_oracle_v1")
            self.assertEqual(record["log_bytes"],
                             (self.output / (name + ".log")).stat().st_size)
        self.assertTrue((self.output / "factorial-independent-review.json").is_file())
        self.assertTrue((self.output / "isolation-receipt.json").is_file())

    def test_fail_closed_on_original_arm_nonzero(self):
        with self.assertRaisesRegex(ValueError, "exit 17"):
            self.run_study(seed=13)
        self.assertFalse((self.output / "isolation-receipt.json").exists())
        self.assertFalse((self.output / "guarded_oracle").exists())

    def test_no_success_after_child_process_timeout(self):
        with self.assertRaisesRegex(ValueError, "timed out"):
            self.run_study(seed=14, timeout_seconds=1)
        self.assertFalse((self.output / "isolation-receipt.json").exists())

    def test_reject_corrupted_or_denied_independent_review(self):
        old = os.environ.get("TEST_INVALID_REVIEW")
        try:
            os.environ["TEST_INVALID_REVIEW"] = "1"
            with self.assertRaisesRegex(ValueError, "not research-admissible"):
                self.run_study()
        finally:
            if old is None:
                os.environ.pop("TEST_INVALID_REVIEW", None)
            else:
                os.environ["TEST_INVALID_REVIEW"] = old
        self.assertFalse((self.output / "isolation-receipt.json").exists())

    def test_reject_existing_or_symlinked_inputs_before_any_effect(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, "create-only"):
            self.run_study()
        self.output.rmdir()
        link = self.root / "link.py"
        link.symlink_to(self.campaign)
        with self.assertRaisesRegex(ValueError, "symlink"):
            isolated_factorial(self.snapshot, self.output,
                campaign_script=link, reviewer_script=self.reviewer)

    def test_reject_invalid_training_parameters_before_creating_output(self):
        for kw in (dict(seed=True), dict(steps=0), dict(seed=-1),
                   dict(profile="unknown"), dict(timeout_seconds=0),
                   dict(train_count=1), dict(heldout_count=1)):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.run_study(**kw)
            self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
