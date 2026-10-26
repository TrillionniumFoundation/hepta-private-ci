"""Fail-closed census, matched completion, exact parity identity and paid fallback."""

import copy
from itertools import product
import unittest

import numpy as np

from v8_audit_records import check_portfolio
from v8_audit_statistics import POLICIES, configuration_summary, recompute


PLAN = {"versions":["v5","v6"],"tasks":["agnews","dbpedia"],"head_modes":["linear","gated"],
    "seeds":[7,17,29],"primary_policies":list(POLICIES),
    "configurations":[{"index":i,"configuration":{"old_weight":old,"commit_stride":stride}}
        for i,(old,stride) in enumerate(product((0.,.25,.5),(1,2,4,8)))]}


def fixture(index=0):
    cases,parity = {},[]
    for v,t,h,s in product(PLAN["versions"],PLAN["tasks"],PLAN["head_modes"],PLAN["seeds"]):
        parity.append({"fit_id":f"{v}-{t}-seed{s}-{h}","configuration_index":index,"passed":True})
        for p in POLICIES:
            cases[v,t,h,s,p] = {"available":True,"actual_errors":[],
                "header":{"status":"completed","completed_steps":32,"error":None,"audit_passed":True,
                    "cpu_ns":2 if p=="future_field_h8" else 1,"selection_sources_sha256":v+t},
                "future_losses":np.full(512,.98 if p=="future_field_h8" else 1.),
                "old_differences":np.full(512,-.03)}
    return cases,parity


class AuditBoundaryTests(unittest.TestCase):
    def test_finite_but_stopped_baseline_is_not_32step_comparable(self):
        cases,parity=fixture()
        self.assertTrue(configuration_summary(PLAN,0,cases,parity)["plausible"])
        key=("v5","agnews","linear",7,"myopic_h1")
        cases[key]["header"].update(status="not_executed_rejected",completed_steps=31)
        cases[key]["future_losses"][:]=100.
        result=configuration_summary(PLAN,0,cases,parity)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["invalid"],[list(key)])
        self.assertEqual(result["groups"][0]["future"],[])
        self.assertEqual(result["observed"],96)

    def test_parity_requires_exact_fit_and_config_not_only24_booleans(self):
        cases,parity=fixture()
        for mutation in ("duplicate","wrong_index"):
            bad=copy.deepcopy(parity)
            if mutation=="duplicate":bad[0]=copy.deepcopy(bad[1])
            else:bad[0]["configuration_index"]=1
            self.assertFalse(configuration_summary(PLAN,0,cases,bad)["eligible"])
        del cases[next(iter(cases))]
        with self.assertRaisesRegex(ValueError,"exact96"):
            configuration_summary(PLAN,0,cases,parity)

    def test_plausible_subset_precedes_more_favorable_ineligible_old_screen(self):
        cases,parity={},[]
        for index in range(12):
            local,paired=fixture(index)
            for key,value in local.items():
                if key[-1]=="future_field_h8" and index==1:
                    value["future_losses"][:]=.90
                    value["old_differences"][:]=-.01
                elif key[-1]=="future_field_h8" and index>1:
                    value["future_losses"][:]=.995
                cases[index,*key]=value
            parity.extend(paired)
        _,selection,_=recompute(PLAN,cases,parity)
        self.assertEqual(selection["eligible_indices"],list(range(12)))
        self.assertEqual(selection["plausible_indices"],[0])
        self.assertEqual(selection["selected_index"],0)

    def test_fallback_must_pay_failed_work_and_preserve_same_origin(self):
        common={"initial_state_sha256":"origin","original_old_anchors":[1.]*4,"threshold_slack":0.,
            "horizon":8,"dt":.02,"action_bound":4.,"verified_optimizer_steps":3,"panel_head_evaluations":28,
            "cpu_ns":10,"wall_ns":11,"prospective_safe_steps":2}
        old={**common,"certified":False,"status":"rejected","returned_state_sha256":"origin","certified_optimizer_steps":0}
        joint={**common,"certified":True,"status":"certified","returned_state_sha256":"terminal","certified_optimizer_steps":8}
        record={**joint,"schema":"hepta.cell-field-fixed-portfolio.v8","attempt_order":["single_ray_v7","joint_actual_old_v8"],
            "attempts":[{"filter":"single_ray_v7","record":old},{"filter":"joint_actual_old_v8","record":joint}],
            "selected_filter":"joint_actual_old_v8","verified_optimizer_steps":6,"panel_head_evaluations":56,
            "cpu_ns":21,"wall_ns":23,"discarded_safe_prefix_steps":2}
        self.assertEqual(check_portfolio(record)["attempts"],2)
        for mutation in ("unpaid","reanchored","first_safe"):
            bad=copy.deepcopy(record)
            if mutation=="unpaid":bad["panel_head_evaluations"]-=1
            elif mutation=="reanchored":bad["attempts"][0]["record"]["initial_state_sha256"]="other"
            else:bad["attempts"][0]["record"]["certified"]=True
            with self.assertRaises(ValueError):check_portfolio(bad)


if __name__=="__main__":unittest.main()
