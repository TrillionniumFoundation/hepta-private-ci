"""Behavior and non-oracle-tail checks for the registered rollout candidate."""

import copy
import unittest

import numpy as np

from ..audit import choose_actor,state_identity,q_pi
from ..upstream.cell import Cell
from ..upstream.data import encode_observation
from ..upstream.estimators import HXFilter
from ..upstream.recurrent import RecurrentEstimator
from ..upstream.task_value import ExactBeliefDP,choose_values
from .controller import choose_rollout
from .full_clock import expected_policy


class RolloutTests(unittest.TestCase):
    def test_hx_equals_its_fitted_bayes_dp_including_ties(self):
        for seed in (3,11):
            model=HXFilter(seed)
            cell=model.build_cell()
            planner=ExactBeliefDP(cell)
            model.start(cell.prior)
            for token,dt in ((-1,.15),(0,.45),(6,.15)):
                model.step(encode_observation(token,dt))
                action,scores=choose_rollout(model,planner,(.15,.45),1)
                reference=planner.action_values(model.current,(.15,.45),1)
                np.testing.assert_allclose(list(scores.values()),list(reference.values()),rtol=0,atol=2e-12)
                self.assertEqual(action,choose_values(reference))

    def test_retains_the_real_recurrent_tail(self):
        reference=HXFilter(7)
        cell=reference.build_cell()
        planner=ExactBeliefDP(cell)
        model=RecurrentEstimator("gru",seed=23)
        model.start(cell.prior)
        model.step(encode_observation(0,.15))
        before=state_identity(model)
        _,scores=choose_rollout(model,planner,(.45,),1)
        successor=model.current@cell.transition(.45)
        expected=-.0045-successor@cell.read_cost
        for token in range(7):
            mass=successor*cell.E[:,token]
            if mass.sum()>0:
                branch=copy.deepcopy(model)
                branch.step(encode_observation(token,.45))
                action=choose_actor(branch,planner,(),0,"value")
                expected+=mass@cell.reward[:,int(action[-1])]
        self.assertAlmostEqual(expected,scores["READ"],places=12)
        self.assertEqual(before,state_identity(model))

    def test_each_local_fitted_choice_beats_the_original_first_action(self):
        model=RecurrentEstimator("continuous_diagonal_ssm",seed=19)
        cell=HXFilter(5).build_cell()
        planner=ExactBeliefDP(cell)
        model.start(cell.prior)
        for token,dt in ((0,.15),(1,.45),(-1,.15)):
            model.step(encode_observation(token,dt))
            old=choose_actor(model,planner,(.45,.15),1,"value")
            new,scores=choose_rollout(model,planner,(.45,.15),1)
            self.assertGreaterEqual(scores[new]-scores[old],-1e-12)

    def test_no_time_or_read_budget_keeps_initial_stop_actions(self):
        model=HXFilter(9)
        cell=model.build_cell()
        planner=ExactBeliefDP(cell)
        model.start(cell.prior)
        _,scores=choose_rollout(model,planner,(),0)
        self.assertEqual(set(scores),{"STOP0","STOP1"})
        _,scores=choose_rollout(model,planner,(.15,),0)
        self.assertEqual(set(scores),{"STOP0","STOP1","WAIT","RESET"})

    def test_full_policy_evaluator_matches_independent_original_qpi(self):
        model=RecurrentEstimator("continuous_diagonal_ssm",seed=31)
        fitted=HXFilter(5).build_cell();truth=Cell()
        planner=ExactBeliefDP(fitted);world=ExactBeliefDP(truth)
        model.start(fitted.prior)
        selector=lambda actor,p,clock,reads:choose_actor(actor,p,clock,reads,"value")
        actual=expected_policy(world,model,truth.prior,(.15,.45),1,planner,selector)
        checked=q_pi(world,model,truth.prior,(.15,.45),1,planner,"value")
        choice=selector(model,planner,(.15,.45),1)
        self.assertAlmostEqual(actual["utility"],checked["q"][choice],places=12)

    def test_full_policy_evaluator_reinvokes_its_selector_after_observation(self):
        model=HXFilter(5);fitted=model.build_cell();truth=Cell()
        planner=ExactBeliefDP(fitted);world=ExactBeliefDP(truth)
        model.start(fitted.prior)
        calls=[]
        def selector(actor,p,clock,reads):
            calls.append((len(clock),reads))
            return "READ" if clock else "STOP1"
        actual=expected_policy(world,model,truth.prior,(.45,),1,planner,selector)
        successor=truth.prior@truth.transition(.45)
        expected=float(successor@truth.reward[:,1]-successor@truth.read_cost-.0045)
        self.assertAlmostEqual(actual["utility"],expected,places=12)
        self.assertEqual(calls[0],(1,1))
        self.assertGreater(sum(clock==0 and reads==0 for clock,reads in calls),1)


if __name__=="__main__":
    unittest.main()
