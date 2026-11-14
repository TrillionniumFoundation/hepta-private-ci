"""Independent, focused reproduction of Hepta P4 zero-fit comparator rules.

Not a run of the repository's full 72-method suite. No production weights,
model forwards, externally authenticated task utility, or target-host proofs.
"""
import unittest

ONE_TIME = ("load_ms", "training_ms", "jit_ms", "evaluation_ms", "migration_ms")

class Invalid(ValueError):
    pass

def arm(name, *, steps, cases, parameters, train_ms, budget=100.0, solver_ms=3.0):
    return {"name": name, "train_steps": steps, "train_cases": cases,
            "trainable_parameters": parameters, "compute_budget_ms": budget,
            "solver_ms": solver_ms, "data_sha": "common-source-identity",
            "costs": {"load_ms": 2.0, "training_ms": train_ms,
                      "jit_ms": 2.0, "evaluation_ms": 2.0, "migration_ms": 2.0, "ndu_ms": 0.0}}

def check_arm(a):
    if a["name"] in ("no_search", "bellman") and a["train_steps"] != 0:
        raise Invalid("P4 no-fit cheap control cannot report training steps")
    if a["name"] in ("no_search", "bellman") and a["costs"]["ndu_ms"] != 0:
        raise Invalid("P4 no-fit cheap control cannot claim NDU solver charges")
    if a["name"] == "no_search" and a["solver_ms"] != 0:
        raise Invalid("P4 no-search baseline cannot claim solver execution")
    if a["train_steps"] == 0:
        if a["train_cases"] != 0 or a["trainable_parameters"] != 0 or a["costs"]["training_ms"] != 0:
            raise Invalid("P4 zero-step control claims training exposure or cost")
    elif a["train_cases"] <= 0 or a["trainable_parameters"] <= 0 or a["costs"]["training_ms"] <= 0:
        raise Invalid("P4 trained algorithm omitted training exposure or cost")
    if a["solver_ms"] > a["compute_budget_ms"]:
        raise Invalid("actual P4 compute exceeded matched budget")

def paired(a, b, n=80):
    check_arm(a); check_arm(b)
    if a["compute_budget_ms"] != b["compute_budget_ms"]:
        raise Invalid("different NDU and cheap-control compute budgets")
    if a["train_steps"] > 0 and b["train_steps"] > 0 and (a["data_sha"] != b["data_sha"] or a["train_cases"] != b["train_cases"]):
        raise Invalid("P4 both-trained controls have unmatched training exposure")
    # No forced optimizer-step equality for semantically different algorithms.
    charge = lambda v: sum(v["costs"][k] for k in ONE_TIME)/n
    return {"per_case_budget": a["compute_budget_ms"],
            "cost_a_ms_per_evaluation": charge(a),
            "cost_b_ms_per_evaluation": charge(b),
            "equal_training_exposure": a["train_steps"] == b["train_steps"] and a["train_cases"] == b["train_cases"],
            "production_promotion_permitted": False}

class P4Controls(unittest.TestCase):
    def setUp(self):
        self.bellman = arm("bellman", steps=0, cases=0, parameters=0, train_ms=0)
        self.ndu = arm("ndu_solver", steps=24, cases=64, parameters=9744, train_ms=2)
        self.critic = arm("critic", steps=24, cases=64, parameters=9744, train_ms=2)

    def test_zero_fit_bellman_v_trained_ndu_is_valid_and_denied(self):
        p=paired(self.ndu,self.bellman)
        self.assertFalse(p["equal_training_exposure"])
        self.assertEqual(p["per_case_budget"],100)
        self.assertFalse(p["production_promotion_permitted"])
    def test_learned_expense_not_waived_for_bellman(self):
        p=paired(self.ndu,self.bellman)
        self.assertGreater(p["cost_a_ms_per_evaluation"],p["cost_b_ms_per_evaluation"])
    def test_zero_fit_no_search_is_allowed(self):
        base=arm("no_search",steps=0,cases=0,parameters=0,train_ms=0,solver_ms=0)
        self.assertEqual(paired(self.ndu,base)["per_case_budget"],100)
    def test_no_search_faked_solver_is_rejected(self):
        baseline=arm("no_search", steps=0, cases=0, parameters=0, train_ms=0, solver_ms=1)
        with self.assertRaisesRegex(Invalid,"no-search baseline"):
            paired(self.ndu,baseline)
    def test_bellman_cannot_claim_ndu_cost(self):
        self.bellman["costs"]["ndu_ms"]=3
        with self.assertRaisesRegex(Invalid,"no-fit cheap control"):
            paired(self.ndu,self.bellman)
    def test_fake_bellman_training_is_rejected(self):
        self.bellman["train_steps"]=1
        with self.assertRaisesRegex(Invalid,"no-fit"):paired(self.ndu,self.bellman)
    def test_no_fit_cannot_hide_training_milliseconds(self):
        self.bellman["costs"]["training_ms"]=2
        with self.assertRaisesRegex(Invalid,"zero-step"):paired(self.ndu,self.bellman)
    def test_no_fit_cannot_claim_trainable_parameters(self):
        self.bellman["trainable_parameters"]=1
        with self.assertRaisesRegex(Invalid,"zero-step"):paired(self.ndu,self.bellman)
    def test_no_fit_cannot_claim_fit_examples(self):
        self.bellman["train_cases"]=64
        with self.assertRaisesRegex(Invalid,"zero-step"):paired(self.ndu,self.bellman)
    def test_ndu_cannot_hide_training_cost(self):
        self.ndu["costs"]["training_ms"]=0
        with self.assertRaisesRegex(Invalid,"omitted training"):paired(self.ndu,self.bellman)
    def test_ndu_cannot_hide_training_exposure(self):
        self.ndu["train_cases"]=0
        with self.assertRaisesRegex(Invalid,"omitted training"):paired(self.ndu,self.bellman)
    def test_ndu_and_critic_data_exposure_match_when_both_fit(self):
        self.critic["data_sha"]="different"
        with self.assertRaisesRegex(Invalid,"unmatched training exposure"):paired(self.ndu,self.critic)
    def test_ndu_and_critic_step_mismatch_may_be_compared_after_cost(self):
        self.critic["train_steps"]=25
        self.critic["costs"]["training_ms"]=5
        p=paired(self.ndu,self.critic)
        self.assertFalse(p["equal_training_exposure"])
        self.assertGreater(p["cost_b_ms_per_evaluation"],p["cost_a_ms_per_evaluation"])
    def test_per_request_budget_is_still_equal(self):
        self.critic["compute_budget_ms"]=101
        with self.assertRaisesRegex(Invalid,"compute budgets"):paired(self.ndu,self.critic)
    def test_per_request_solver_overrun_still_fails(self):
        self.ndu["solver_ms"]=101
        with self.assertRaisesRegex(Invalid,"compute exceeded"):paired(self.ndu,self.bellman)

if __name__=="__main__": unittest.main(verbosity=2)
