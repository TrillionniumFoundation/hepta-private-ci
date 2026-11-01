"""Independent endpoint enumeration and causal actor isolation tests."""

import copy
import unittest

import numpy as np

from .audit import (audit_prefix, choose_actor, clone_actor, q_pi,
                    state_identity)
from .upstream.cell import Cell
from .upstream.data import encode_observation
from .upstream.estimators import HXFilter
from .upstream.recurrent import RecurrentEstimator
from .upstream.task_value import ExactBeliefDP


class ActualPolicyTests(unittest.TestCase):
    def setUp(self):
        self.hx = HXFilter(seed=41)
        self.fit = self.hx.build_cell()
        self.planner = ExactBeliefDP(self.fit)
        self.world = ExactBeliefDP(Cell())
        self.model = RecurrentEstimator("continuous_diagonal_ssm", seed=31)
        self.model.start(self.fit.prior)
        self.prior = Cell().prior

    def test_independent_endpoint_enumeration_with_mismatched_world(self):
        dt=.45
        measured=q_pi(self.world,self.model,self.prior,(dt,),1,self.planner,"value")
        self.assertNotEqual(self.world.model_identity,self.planner.model_identity)
        for action in ("WAIT","READ","RESET"):
            expected=0.
            trans=self.world._transition(dt)
            matrix=self.world.R@trans if action=="RESET" else trans
            for token in (range(7) if action=="READ" else (-1,)):
                actor=copy.deepcopy(self.model)
                actor.step(encode_observation(token,dt,action=="RESET"))
                answer=int(choose_actor(actor,self.planner,(),0,"value")[-1])
                for initial in range(20):
                    for endpoint in range(20):
                        mass=self.prior[initial]*matrix[initial,endpoint]
                        if token>=0:
                            mass*=self.world.E[endpoint,token]
                        fee=.01*dt+(.04 if action=="RESET" else 0.)
                        if action=="READ":
                            fee+=self.world.read_cost[endpoint]
                        expected+=mass*(self.world.reward[endpoint,answer]-fee)
            self.assertAlmostEqual(expected,measured["q"][action],places=12)

    def test_same_model_hx_actual_policy_matches_bayes_dp(self):
        self.hx.start(self.fit.prior)
        actual=q_pi(self.planner,self.hx,self.fit.prior,(.15,.45),2,self.planner,"value")
        optimum=self.planner.action_values(self.fit.prior,(.15,.45),2)
        np.testing.assert_allclose(list(actual["q"].values()),list(optimum.values()),rtol=0,atol=2e-12)

    def test_actual_counterfactual_preserves_all_recurrent_state(self):
        for kind in ("gru","continuous_diagonal_ssm"):
            model=RecurrentEstimator(kind,seed=19)
            model.start(self.fit.prior)
            model.step(encode_observation(0,.15))
            before=state_identity(model)
            result=q_pi(self.world,model,self.prior,(.15,.45),2,self.planner,"value",True)
            self.assertEqual(before,state_identity(model))
            self.assertLess(max(abs(x-1) for x in result["leaf_mass"].values()),2e-12)
            for action,nodes in result["trees"].items():
                trace=sum(n.get("reward",0)-n.get("read_fee",0)-n.get("time_fee",0)-n.get("reset_fee",0) for n in nodes)
                self.assertAlmostEqual(trace,result["q"][action],places=12)

    def test_evaluator_changes_cannot_change_actor_decision(self):
        before=state_identity(self.model)
        original=choose_actor(self.model,self.planner,(.15,.45),1,"value")
        left=q_pi(self.world,self.model,self.prior,(.15,.45),1,self.planner,"value")
        other=np.zeros(20);other[1]=1.
        right=q_pi(self.world,self.model,other,(.15,.45),1,self.planner,"value")
        self.assertEqual(original,choose_actor(self.model,self.planner,(.15,.45),1,"value"))
        self.assertEqual(before,state_identity(self.model))
        self.assertGreater(abs(left["q"]["STOP1"]-right["q"]["STOP1"]),.1)

    def test_decomposition_and_initial_stop_are_explicit(self):
        row=audit_prefix(self.world,self.planner,self.model,self.prior,self.fit.prior,(.15,.45),1,self.planner,"value")
        self.assertLess(row["decomposition_max_error"],2e-12)
        self.assertIn("STOP0",row["true_qpi"]["q"])
        self.assertIn("STOP1",row["true_qpi"]["q"])
        self.assertGreaterEqual(row["one_step_regret"],0.)
        self.assertGreaterEqual(row["stop_deficit"],0.)
        self.assertGreater(max(map(abs,row["decomposition"]["world_model"].values())),1e-6)

    def test_clone_hidden_memory_is_independent(self):
        branch=clone_actor(self.model)
        branch.hidden[0]+=100
        branch.current[0]+=.1
        self.assertFalse(np.array_equal(branch.hidden,self.model.hidden))
        self.assertFalse(np.array_equal(branch.current,self.model.current))


if __name__=="__main__":
    unittest.main()
