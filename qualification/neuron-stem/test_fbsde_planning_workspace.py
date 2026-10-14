"""Exact continuation, ownership and one-allocation budgets; no efficacy claims."""
import copy
import gc
import unittest
import weakref
from unittest.mock import patch
from four_gate_common import digest
from fbsde_tracking_control import BeliefProblem, PlanningBudgetError, plan
from fbsde_planning_workspace import PlanningWorkspace
from fbsde_depth_data import numeric_inputs, construct
from fbsde_depth_policy import allocate
from test_fbsde_depth import weights


def comparable(result):
    return {k:v for k,v in result.items() if k not in ('cpu_ns','nodes','max_bsde_residual')}


class WorkspaceTests(unittest.TestCase):
    def problem(self):
        return construct(numeric_inputs(31,1,'workspace')[0],'m','c')

    def test_new_horizon_reuses_paid_values_but_does_not_reuse_wrong_horizon(self):
        for row in numeric_inputs(911,24,'mechanism'):
            p=construct(row,'m','c')
            expected=plan(p,horizon=2)
            with PlanningWorkspace(p) as work:
                one=work.solve(horizon=1); two=work.solve(horizon=2)
                self.assertEqual(comparable(two),comparable(expected))
                self.assertEqual(work.nodes,one['nodes']+two['nodes'])
                self.assertLessEqual(one['nodes']+two['nodes'],one['nodes']+expected['nodes'])
                self.assertEqual(work.solve(horizon=2)['nodes'],0)
                self.assertGreater(work.counters()['value_cache_hits'],0)
            self.assertTrue(work.closed)
            self.assertIsNone(work.problem)
            self.assertEqual(work.counters()['retained_value_rows'],0)

    def test_common_problem_not_retained_after_public_plan(self):
        p=self.problem(); ref=weakref.ref(p)
        result=plan(p); del p
        # No GC disable/threshold change/collect is used to make this pass.
        self.assertIsNone(ref())
        self.assertFalse(result['semantic_certificate'])

    def test_mutating_returned_list_cannot_rewrite_cached_value(self):
        with PlanningWorkspace(self.problem()) as work:
            a=work.solve(horizon=1); expected=copy.deepcopy(a)
            a['probabilities'][0]=99.; a['alternatives'].clear()
            self.assertEqual(comparable(work.solve(horizon=1)),comparable(expected))

    def test_new_observation_needs_new_workspace(self):
        p=self.problem()
        with PlanningWorkspace(p) as work:
            work.solve(horizon=1)
            j=next(j for j,p in enumerate(p.outcome_law(0)) if p>0)
            with self.assertRaisesRegex(ValueError,'revealed observation'):
                work.solve(((0,j),),horizon=1)

    def test_closed_and_cross_identity_uses_reject(self):
        p=self.problem(); work=PlanningWorkspace(p)
        with work:
            p.identity=digest('changed')
            with self.assertRaisesRegex(ValueError,'identity changed'): work.solve()
        with self.assertRaisesRegex(ValueError,'closed'): work.solve()

    def test_combined_node_budget_does_not_reset_on_escalation(self):
        p=self.problem(); first=plan(p,horizon=1)
        with PlanningWorkspace(p,max_nodes=first['nodes']) as work:
            work.solve(horizon=1)
            with self.assertRaises(PlanningBudgetError) as caught:work.solve(horizon=2)
            self.assertFalse(caught.exception.evidence['returned'])
            self.assertNotIn('action',caught.exception.evidence)
        self.assertEqual(work.counters()['retained_state_rows'],0)

    def test_between_solve_cpu_counts_even_when_it_did_not_expand_nodes(self):
        clock=[0]
        with patch('time.process_time_ns',side_effect=lambda:clock[0]):
            p=self.problem()
            with PlanningWorkspace(p) as work:
                work.solve(horizon=1);clock[0]=100_000_001
                with self.assertRaises(PlanningBudgetError):work.solve(horizon=2)
            self.assertIsNone(work.problem)

    def test_exception_releases_scratch_without_global_gc(self):
        p=self.problem()
        with PlanningWorkspace(p) as work:
            with patch.object(p,'information_state',side_effect=RuntimeError('failed belief')):
                with self.assertRaisesRegex(RuntimeError,'failed belief'):work.solve()
            self.assertTrue(work.closed)
            self.assertEqual(work.states,{})

    def test_all_depth_modes_have_identical_frozen_decisions(self):
        for row in numeric_inputs(919,12,'checks'):
            p=construct(row,'m','c');bundle={'model':'m','calibration':'c',
                'context':dict(source=digest(row),model='m',calibration='c',scope='depth-research',generation=3),
                'problem_binding':p.binding,'state':weights(),'initial':weights(),
                'threshold':.25,'confidence_threshold':.75,'complete_threshold':.4,'complete_confidence_threshold':.8}
            for mode in ('myopic','full','confidence','learned','frozen','learned_complete','confidence_complete'):
                a,ar=allocate(p,(),2,mode,bundle)
                b,br=allocate(p,(),2,mode,bundle,engine='shared_continuation_v2')
                self.assertEqual(comparable(a),comparable(b))
                self.assertEqual((ar['probability'],ar['features'],ar['selected_depth']),
                                 (br['probability'],br['features'],br['selected_depth']))
                self.assertTrue(br['workspace']['closed'])
                self.assertEqual(br['planner_nodes'],br['workspace']['new_value_nodes'])
                self.assertLessEqual(br['planner_nodes'],ar['planner_nodes'])

    def test_conditional_snapshot_matches_each_original_port(self):
        for row in numeric_inputs(931,18,'snapshot'):
            p=construct(row,'m','c')
            for h in ((), ((0,next(j for j,v in enumerate(p.outcome_law(0)) if v>0)),)):
                s=p.information_state(h)
                self.assertEqual(s['history'],p.history(h))
                self.assertEqual(s['probabilities'],tuple(p.marginal(h)))
                self.assertEqual(s['posterior'],tuple(p.member_posterior(h)))
                self.assertEqual(s['available'],tuple(p.available_events(h)))
                self.assertEqual(s['outcomes'],{i:tuple(p.outcome_law(i,h)) for i in p.available_events(h)})

    def test_invalid_horizon_and_engine_fail(self):
        p=self.problem()
        with PlanningWorkspace(p) as work:
            for horizon in (-1,3,True):
                with self.assertRaises(ValueError):work.solve(horizon=horizon)


if __name__=='__main__':unittest.main()
