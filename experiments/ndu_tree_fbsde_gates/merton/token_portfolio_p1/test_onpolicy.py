"""P2 synthetic protocol tests only; never stand in for real Reader outcomes."""
from __future__ import annotations

import copy
import unittest

from onpolicy import Meter, Response, execute, packet, score_postseal
from portfolio import Invalid
from test_portfolio import panel


class ProspectiveTests(unittest.TestCase):
    def setUp(self):
        self.m, self.t, self.p, self.truth = panel()
        self.prompts = {"schema": "hepta.p2.public-prompts.v1", "prompts": [
            {"task_id": c["task_id"], "prompt": "synthetic input for " + c["task_id"]}
            for c in self.p["cases"]
        ]}
        self.seen = []
        self.zero = "a" * 64

    def reader(self, task_id, prompt, action):
        self.assertIn("synthetic input", prompt)
        self.seen.append((task_id, action))
        tokens = {"direct":0, "reason":4, "verify":2}[action]
        duration = {"direct":0, "reason":3, "verify":1}[action]
        return Response(action, Meter(10, 0, tokens, 3, duration, 7+duration), self.zero)

    def run(self, policy="ndu_discrete", reader=None):
        return execute(self.m, self.t, self.p, self.prompts, reader or self.reader,
                       policy=policy, model_digest=self.zero, adapter_digest=self.zero)

    def test_real_selected_only_and_no_gold_argument(self):
        out=self.run()
        self.assertEqual(len(self.seen), len(self.p["cases"]))
        self.assertEqual(len(out["attempt"]["records"]),len(self.p["cases"]))
        self.assertEqual({a for _,a in self.seen}, set(r["selected_action"] for r in out["attempt"]["records"]))
        self.assertEqual(out["attempt"]["observed_full_input_tokens"],40)
        self.assertEqual(out["attempt"]["observed_full_output_tokens"],12)
        self.assertGreater(out["attempt"]["observed_full_model_latency_ms"], 0)
        self.assertNotIn("gold", str(out))
        self.assertLessEqual(out["attempt"]["observed_additional_reasoning_tokens"], self.m["token_budget"])

    def test_all_seven_policies_are_callable(self):
        for policy in ("direct","fixed_reason","greedy","neutral","fixed_risk","ndu_discrete","ordinary_same_profile"):
            self.seen.clear()
            out=self.run(policy)
            self.assertEqual(len(self.seen),4)
            self.assertEqual(out["attempt"]["policy"],policy)

    def test_direct_still_charges_baseline_latency(self):
        out=self.run("direct")
        self.assertEqual(out["attempt"]["observed_additional_latency_ms"],0)
        self.assertEqual(out["attempt"]["observed_full_model_latency_ms"],28)

    def test_no_future_answers_in_prompt_packet(self):
        self.prompts["prompts"][0]["answer"]="gold"
        with self.assertRaises(Invalid):
            self.run()

    def test_future_group_overlap_denied_before_reader(self):
        self.p["cases"][0]["group"]="past-A"
        with self.assertRaises(Invalid):
            self.run()
        self.assertEqual(self.seen,[])

    def test_future_label_denied_before_reader(self):
        self.p["cases"][0]["gold"]=1
        with self.assertRaises(Invalid):
            self.run()
        self.assertEqual(self.seen,[])

    def test_duplicate_prompt_denied(self):
        self.prompts["prompts"][1]["task_id"]=self.prompts["prompts"][0]["task_id"]
        with self.assertRaises(Invalid):
            self.run()

    def test_reader_token_overrun_refused(self):
        def bad(t,p,a):
            return Response("x",Meter(10,0,999,1,0,8),self.zero)
        with self.assertRaises(Invalid):
            self.run(reader=bad)

    def test_reader_time_overrun_refused(self):
        def bad(t,p,a):
            return Response("x",Meter(10,0,0,1,999,1000),self.zero)
        with self.assertRaises(Invalid):
            self.run(reader=bad)

    def test_cache_count_overrun_refused(self):
        def bad(t,p,a):
            return Response("x",Meter(10,11,0,1,0,9),self.zero)
        with self.assertRaises(Invalid):
            self.run(reader=bad)

    def test_nontyped_reader_output_refused(self):
        with self.assertRaises(Invalid):
            self.run(reader=lambda *_: {"answer":"fake"})

    def test_wrong_adapter_digest_refused(self):
        with self.assertRaises(Invalid):
            execute(self.m,self.t,self.p,self.prompts,self.reader,policy="direct",
                    model_digest=self.zero,adapter_digest="fake")
        self.assertEqual(self.seen,[])

    def test_review_exact_match(self):
        out=self.run("direct")
        gold={"schema":"hepta.p2.gold.v1","answers":[{"task_id":r["task_id"],"answer":r["answer"]} for r in out["attempt"]["records"]]}
        scored=score_postseal(out,gold)
        self.assertEqual(scored["correct"],4)
        self.assertEqual(scored["total"],4)

    def test_review_mixed_answers(self):
        out=self.run("direct")
        gold={"schema":"hepta.p2.gold.v1","answers":[{"task_id":r["task_id"],"answer":"direct" if i%2 else "wrong"} for i,r in enumerate(out["attempt"]["records"])]}
        self.assertEqual(score_postseal(out,gold)["correct"],2)

    def test_review_missing_truth_denied(self):
        out=self.run("direct")
        gold={"schema":"hepta.p2.gold.v1","answers":[{"task_id":out["attempt"]["records"][0]["task_id"],"answer":"direct"}]}
        with self.assertRaises(Invalid):
            score_postseal(out,gold)

    def test_review_tampered_truth_keys_denied(self):
        out=self.run("direct")
        gold={"schema":"hepta.p2.gold.v1","answers":[{"task_id":r["task_id"],"answer":"direct"} for r in out["attempt"]["records"]]}
        gold["answers"][0]["leaked"]=1
        with self.assertRaises(Invalid):
            score_postseal(out,gold)


if __name__=="__main__":
    unittest.main()
