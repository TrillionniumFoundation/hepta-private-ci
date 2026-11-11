"""Immutable actual CPU-LoRA V2 evidence checks. Does not retrain or attest owner."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import collections
import json
import unittest

from clock_pairing_v2 import PairPlan, PlannedStep, PlanError, verify_pair

HERE=Path(__file__).resolve().parent
R=json.loads((HERE/"real_cpu_clock_v2_RESULT.json").read_text())
PLANS=json.loads((HERE/"real_cpu_clock_v2_PLAN.json").read_text())

def digest(p):
    return sha256(p.read_bytes()).hexdigest()

def plan(d):
    args=dict(d)
    args["arm_order"]=tuple(args["arm_order"])
    for arm in ("interleaved","bursty"):
        args[arm]=tuple(PlannedStep(**s) for s in args[arm])
    return PairPlan(**args)

class RealClockEvidenceV2Tests(unittest.TestCase):
    def test_exact_source_and_archive_binding(self):
        self.assertEqual(R["schema"],"HPCA-REAL-CPU-LORA-CLOCK-V2-MATCHED")
        self.assertEqual(R["authority"],"CANDIDATE_ONLY_DENY_ALL_HOLD_NO_GO")
        self.assertEqual(R["decision"],"HOLD_NO_GO")
        self.assertEqual(R["identities"]["script_sha256"],digest(HERE/"native_lora_clock_v2.py"))
        self.assertEqual(R["clock_module_sha256"],digest(HERE/"clock_pairing_v2.py"))
        self.assertEqual(R["clock_plan_sha256"],digest(HERE/"real_cpu_clock_v2_PLAN.json"))
        self.assertEqual(PLANS["source_script_sha256"],R["identities"]["script_sha256"])
        self.assertEqual(PLANS["clock_module_sha256"],R["clock_module_sha256"])
        self.assertEqual(PLANS["parent_git_head"],"ba243385e821f5722612ffb7129d479c49d34c17")

    def test_real_optimizer_equal_group_opportunity_and_source(self):
        self.assertEqual(len(R["runs"]),8)
        self.assertEqual(len(PLANS["cohort"]),4)
        order=collections.Counter()
        for item in PLANS["cohort"]:
            p=plan(item); verify_pair(p)
            order[p.arm_order]+=1
            rows={arm:next(r for r in R["runs"]
                           if r["arm"]==arm and r["seed"]==p.seed)
                  for arm in p.arm_order}
            for arm in p.arm_order:
                obs=rows[arm]; steps=getattr(p,arm)
                self.assertEqual(obs["plan_digest"],p.plan_digest)
                self.assertEqual(obs["arm_order"],list(p.arm_order))
                self.assertEqual(obs["schedule"],[z.group for z in steps])
                self.assertEqual(obs["actual_updated_parameter_elements"],829440)
                self.assertEqual(len(obs["step_log"]),12)
                self.assertEqual(sum(x["input_tokens"] for x in obs["step_log"]),
                                 obs["input_tokens_train"])
                for s,t in zip(obs["step_log"],steps):
                    self.assertEqual((s["group"],s["source_id"],s["source_sha256"],s["input_tokens"]),
                                     (t.group,t.event_id,t.source_sha256,t.input_tokens))
                self.assertLessEqual(obs["cold_reload_max_p_yes_difference"],1e-5)
                for metric in ("B_exposed_eval","C_operator_constructed"):
                    score=obs["scores"][metric]
                    self.assertEqual(sum(x["correct"] for x in score["rows"])/len(score["rows"]),
                                     score["accuracy"])
            for g in (0,1):
                def ids(arm):
                    return tuple((x["source_id"],x["source_sha256"],x["input_tokens"])
                                 for x in rows[arm]["step_log"] if x["group"]==g)
                self.assertEqual(len(ids("interleaved")),6)
                self.assertEqual(ids("interleaved"),ids("bursty"))
        self.assertEqual(order,{("interleaved","bursty"):2,("bursty","interleaved"):2})

    def test_result_is_negative_and_not_equivalence(self):
        self.assertEqual(R["B_descriptive_mean_delta"],0.0)
        self.assertEqual(R["C_descriptive_mean_delta"],0.0)
        self.assertEqual(len(R["paired_seed_deltas"]),4)
        self.assertTrue(all(x["bursty_minus_interleaved_B_accuracy"]==0.0
                            and x["bursty_minus_interleaved_C_accuracy"]==0.0
                            for x in R["paired_seed_deltas"]))
        self.assertEqual(R["parent_scores"]["B_exposed_eval"]["accuracy"],0.75)
        self.assertEqual(R["parent_scores"]["C_operator_constructed"]["accuracy"],0.375)
        self.assertEqual(sum(x["actual_updated_parameter_elements"] for x in R["runs"]),
                         6635520)

    def test_plan_tampering_fails(self):
        p=plan(PLANS["cohort"][0])
        a=replace(p,model_digest="0"*64)
        with self.assertRaises(PlanError): verify_pair(a)
        bad=list(p.bursty)
        bad[0]=replace(bad[0],input_tokens=bad[0].input_tokens+1)
        with self.assertRaises(PlanError): verify_pair(replace(p,bursty=tuple(bad)))

if __name__=="__main__":
    unittest.main()
