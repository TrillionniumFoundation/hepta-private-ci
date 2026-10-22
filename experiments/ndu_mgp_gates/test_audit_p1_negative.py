"""Synthetic perturbation regressions; actual frozen-source cross-check runs in CI."""
import copy
import unittest
from audit_p1_negative import audit

class PriorEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.p = {"protocol_id":"hepta-output-portfolio-pilot-v1.1-20261021",
                  "seeds":[17,29,43],
                  "primary_comparison":{"contrast":"ndu_recursive_dp minus validation_selected_fixed_portfolio",
                                        "budget":4,"scenario":"test_iid","minimum_reduction":0.02}}
        self.s = {"protocol_id":self.p["protocol_id"],"execution_tier":"local-preflight","seeds":[17,29,43],
                  "audit_count":32,"primary_claim_passed":False,
                  "primary_budget4_iid_contrasts":{"validation_selected_fixed_portfolio":{
                   "cvar90":{"estimate":-0.01516596092898844,"ci_low":-0.04259009600785926,
                             "ci_high":0.009442706859393244,"n_seeds":3,"n_worlds_per_seed":1536}}},
                  "primary_gates":{"cvar_reduction_at_least_0_02":False,
                                   "cvar_95pct_interval_below_zero":False,
                                   "verified_dedicated_cloud":False}}
        self.r = {"primary_claim_passed_recorded":False,"validity_assessment":{
                   "scientific_claim_confirmed_on_fresh_holdout":False},
                  "violations":{},"counts":{"unique_worlds":8064,"oracle_augmented_states_checked":403712},
                  "oracle":{"value_action_stop_portfolio_mismatches":0},
                  "contrasts_budget4_iid":{"validation_selected_fixed_portfolio":{
                   "cvar90":{"estimate":-0.01516596092898844,"ci_low":-0.04259009600785926,
                             "ci_high":0.009442706859393244}}},
                  "primary_gates_recomputed":copy.deepcopy(self.s["primary_gates"]),
                  "key_findings":{"incremental_ndu_preference":{"incremental_superiority_demonstrated":False},
                                  "recursion":{"primary_recursive_benefit_demonstrated":False}},
                  "amendment_checks":{"amendment_published_before_runtime":True},
                  "integrity":{"remote_source_commit":{"sha":"f44540ab59a0a8f013437ccbe8579db607fac03e"}}}
    def test_frozen_negative_valid(self):
        self.assertEqual(audit(self.p,self.s,self.r)["qualification"],"P1_HOLD_NO_GO")
    def test_mismatched_independent_interval_denied(self):
        self.r["contrasts_budget4_iid"]["validation_selected_fixed_portfolio"]["cvar90"]["ci_high"]=-0.01
        with self.assertRaises(ValueError): audit(self.p,self.s,self.r)
    def test_fake_favorable_effect_denied(self):
        self.s["primary_budget4_iid_contrasts"]["validation_selected_fixed_portfolio"]["cvar90"]["estimate"]=-0.03
        with self.assertRaises(ValueError): audit(self.p,self.s,self.r)
    def test_fake_cloud_claim_denied(self):
        self.s["primary_gates"]["verified_dedicated_cloud"]=True
        with self.assertRaises(ValueError): audit(self.p,self.s,self.r)
    def test_changed_margin_denied(self):
        self.p["primary_comparison"]["minimum_reduction"]=0.01
        with self.assertRaises(ValueError): audit(self.p,self.s,self.r)
if __name__=="__main__":unittest.main()
