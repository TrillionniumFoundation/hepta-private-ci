"""Actual stopping execution under frozen plan, source and provenance bindings."""

from dataclasses import replace
import unittest
import torch

from development_ablation import RecurrentClassifier
from development_quality import RiskPlan, Selection
from development_quality_checks import census, history
from development_quality_runtime import (bind_policy, collect_observations, execute_policy,
                                         input_digests, run_selected)
from development_stopping import ContinuationCritic
from development_tensors import parameter_digest


class GuardedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.rng = torch.random.fork_rng(devices=[])
        self.rng.__enter__()
        self.threads = torch.get_num_threads()
        torch.set_num_threads(1)
        torch.manual_seed(811)
        self.model = RecurrentClassifier(4, 2, depth=4)
        self.critic = ContinuationCritic(torch.zeros(3,7,dtype=torch.float64), parameter_digest(self.model), .02)
        self.base = bind_policy(self.model, {'mode':'fixed', 'depth':2})
        self.child = bind_policy(self.model, {'mode':'learned', 'depth':4}, self.critic)
        self.plan = RiskPlan(self.base, (self.child,), ('slice',))
        self.x = torch.randn(40,3,4)
        self.risk = census('risk',512,3)
        self.test = census('heldout',40,4,inputs=input_digests(self.x))
        self.selection = Selection(self.plan.identity(), tuple(c.identity() for c in history()),
                                   self.risk.identity(), self.base.identity())
        self.calls = []
        self.hook = self.model.recurrence.cell.register_forward_hook(lambda m,a,o: self.calls.append(len(a[0])))

    def tearDown(self):
        self.hook.remove()
        torch.set_num_threads(self.threads)
        self.rng.__exit__(None,None,None)

    def test_selected_baseline_really_executes_only_its_own_prefix(self):
        result = run_selected(self.model, self.x, self.test, plan=self.plan, selection=self.selection,
                              priors=history(), risk_census=self.risk, critic=self.critic)
        self.assertEqual(result['depths'], (2,)*40)
        self.assertEqual(self.calls, [32,32,8,8])
        self.assertEqual(result['cell_transitions'], 80)

    def test_model_drift_refused_before_any_recurrence(self):
        with torch.no_grad():
            self.model.output.bias.add_(.01)
        with self.assertRaises(ValueError):
            execute_policy(self.model, self.x, self.test, self.base)
        self.assertEqual(self.calls, [])

    def test_critic_weight_and_profile_drift_refused_before_execution(self):
        for field in ('weights','unit_cost'):
            original = self.critic.weights.clone(), self.critic.unit_cost
            if field == 'weights':
                self.critic.weights.add_(.1)
            else:
                self.critic.unit_cost = .03
            with self.assertRaises(ValueError):
                execute_policy(self.model,self.x,self.test,self.child,self.critic)
            self.critic.weights.copy_(original[0])
            self.critic.unit_cost = original[1]
        self.assertEqual(self.calls, [])

    def test_threshold_plan_and_source_drift_rejected(self):
        altered = replace(self.plan, maximum_harm=.03)
        with self.assertRaises(ValueError):
            run_selected(self.model,self.x,self.test,plan=altered,selection=self.selection,
                         priors=history(),risk_census=self.risk,critic=self.critic)
        with self.assertRaises(ValueError):
            execute_policy(self.model,self.x,self.test,replace(self.base,source_digest='f'*64))
        self.assertEqual(self.calls, [])

    def test_bad_last_microbatch_never_partially_dispatches(self):
        bad = self.x.clone()
        bad[-1,0,0] += .1
        with self.assertRaises(ValueError):
            execute_policy(self.model,bad,self.test,self.base)
        self.assertEqual(self.calls, [])

    def test_unregistered_stratum_and_wrong_class_count_refused(self):
        cases = ((replace(self.test, strata=('unknown',)*40), self.plan, self.selection),
                 (self.test, replace(self.plan, classes=3), replace(self.selection,
                  plan_digest=replace(self.plan, classes=3).identity())))
        for data,plan,selection in cases:
            with self.assertRaises(ValueError):
                run_selected(self.model,self.x,data,plan=plan,selection=selection,
                             priors=history(),risk_census=self.risk,critic=self.critic)
        self.assertEqual(self.calls, [])

    def test_failed_inference_is_not_retried_using_the_baseline(self):
        def fail(module, arguments):
            raise RuntimeError('injected inference failure')
        h = self.model.recurrence.cell.register_forward_pre_hook(fail)
        try:
            with self.assertRaisesRegex(RuntimeError, 'injected inference failure'):
                run_selected(self.model,self.x,self.test,plan=self.plan,selection=self.selection,
                             priors=history(),risk_census=self.risk,critic=self.critic)
        finally:
            h.remove()
        self.assertEqual(self.calls, [])

    def test_repeated_portfolio_charges_all_real_work(self):
        observed, receipt = collect_observations(self.model,self.x,self.test,
                                                (self.base,self.child),self.critic)
        self.assertEqual([sum(o.depths) for o in observed], [80,40])
        self.assertEqual(receipt['actual_cell_transitions'], 360)
        self.assertEqual(sum(self.calls), 360)
        self.assertEqual([len(o.wall_ns) for o in observed], [3,3])

    def test_holdout_cannot_reuse_risk_or_training_groups(self):
        changed = replace(self.test, groups=(self.risk.groups[0],)*40)
        with self.assertRaises(ValueError):
            run_selected(self.model,self.x,changed,plan=self.plan,selection=self.selection,
                         priors=history(),risk_census=self.risk,critic=self.critic)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
