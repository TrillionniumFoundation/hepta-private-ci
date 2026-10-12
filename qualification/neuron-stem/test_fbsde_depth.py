"""Typed model-only depth decisions and failure contracts, no neural efficacy."""
import copy
import unittest
from unittest.mock import patch
from four_gate_common import digest
from fbsde_depth_policy import features, allocate, scalar_score, select_threshold
from fbsde_depth_data import numeric_inputs, construct

def teacher_row(row):
    problem=construct(row,"test","test");one=plan(problem,horizon=1);two=plan(problem,horizon=2)
    return {"input":row,"features":features(problem,(),one),"gain":max(0.,two["value"]-one["value"])}
from fbsde_tracking_control import plan, PlanningBudgetError


def weights():
    return {'value.weight':[[0.]*15 for _ in range(8)],'value.bias':[0.]*8,
            'gate.weight':[[0.]*15 for _ in range(8)],'gate.bias':[0.]*8,
            'out.weight':[[0.]*8],'out.bias':[0.]}


class DepthContractTests(unittest.TestCase):
    def setUp(self):
        self.row=numeric_inputs(31,1,'test')[0]
        self.p=construct(self.row,'m','c')
        self.bundle={'model':'m','calibration':'c',
            'context':{'source':digest(self.row),'model':'m','calibration':'c','scope':'depth-research','generation':3},
            'problem_binding':self.p.binding,'state':weights(),'initial':weights(),
            'threshold':.25,'confidence_threshold':.75}

    def test_fixed_and_always_escalate_match(self):
        actual,route=allocate(self.p,(),2,'learned',self.bundle)
        expected=plan(self.p,horizon=2)
        self.assertEqual((actual['action'],actual['value']),(expected['action'],expected['value']))
        self.assertEqual(route['selected_depth'],2)
        self.assertGreater(route['one_step_cpu_ns'],0)
        self.assertGreaterEqual(route['planner_cpu_ns'],route['one_step_cpu_ns'])

    def test_remaining_budget_never_resets(self):
        for remaining in (0,1):
            actual,route=allocate(self.p,(),remaining,'learned',self.bundle)
            self.assertEqual(actual['remaining_checks'],remaining)
            self.assertIsNone(route['features'])

    def test_mismatched_model_or_scope_rejected(self):
        for key in ('model','scope','generation'):
            b=copy.deepcopy(self.bundle);b['context'][key]='changed'
            with self.assertRaisesRegex(ValueError,'binding'): allocate(self.p,(),2,'full',b)

    def test_teacher_never_uses_future_labels(self):
        a=numeric_inputs(71,6,'train');b=numeric_inputs(71,6,'train')
        self.assertEqual(a,b)
        for row in a:self.assertNotIn('label',row)
        r=teacher_row(a[2]);self.assertGreaterEqual(r['gain'],0.)
        self.assertEqual(len(r['features']),15)

    def test_forged_one_step_snapshot_rejected(self):
        one=plan(self.p,horizon=1);one['problem_sha256']=digest('other')
        with self.assertRaises(ValueError):features(self.p,(),one)

    def test_nonfinite_or_extra_parameters_rejected(self):
        for v in (float('nan'),float('inf'),True):
            w=weights();w['value.weight'][0][0]=v
            with self.assertRaises(ValueError):scalar_score(w,[0.]*15)
        w=weights();w['unknown']=[0.]
        with self.assertRaises(ValueError):scalar_score(w,[0.]*15)

    def test_selection_does_not_read_test_sources(self):
        rows=[teacher_row(r) for r in numeric_inputs(5,3,'model_test')]
        with self.assertRaisesRegex(ValueError,'selection-only'):
            select_threshold(rows,weights(),'learned')

    def test_duplicate_selection_sources_reject(self):
        rows=[teacher_row(r) for r in numeric_inputs(5,1,'selection')]
        with self.assertRaisesRegex(ValueError,'selection-only'):
            select_threshold(rows*2,weights(),'learned')

    def test_total_planning_cost_is_admitted_not_each_call_alone(self):
        d=plan(self.p,horizon=2)
        with patch('fbsde_depth_policy.plan',return_value=d), patch('time.process_time_ns',side_effect=[0,100000001,100000001]):
            with self.assertRaises(PlanningBudgetError) as error:
                allocate(self.p,(),2,'full',self.bundle)
            self.assertFalse(error.exception.evidence['returned'])
            self.assertNotIn('action',error.exception.evidence)

    def test_zero_remaining_does_not_accept_invalid_horizon(self):
        for n in (-1,3,True):
            with self.assertRaises(ValueError):allocate(self.p,(),n,'learned',self.bundle)


    def test_complete_validation_breakpoints_dominate_coarse_grid(self):
        w=weights();w['value.weight'][0][0]=1.;w['out.weight'][0][0]=1.;w['out.bias'][0]=-2.
        rows=[{'input':{'source_id':'selection:0'},'features':[.5]+[0.]*14,'gain':.6},
              {'input':{'source_id':'selection:1'},'features':[0.]*15,'gain':0.}]
        coarse=select_threshold(rows,w,'learned')
        exact=select_threshold(rows,w,'learned','validation_breakpoints_v2')
        self.assertEqual(min(x['deep_calls'] for x in exact['grid'] if x['model_regret_plus_price']==min(z['model_regret_plus_price'] for z in exact['grid'])),1)
        self.assertLess(min(x['model_regret_plus_price'] for x in exact['grid']),min(x['model_regret_plus_price'] for x in coarse['grid']))

    def test_deep_call_gets_only_remaining_node_budget(self):
        one=plan(self.p,horizon=1);two=plan(self.p,horizon=2);one['nodes']=7
        with patch('fbsde_depth_policy.plan',side_effect=[one,two]) as mock:
            _,r=allocate(self.p,(),2,'learned',self.bundle)
            self.assertEqual(mock.call_args_list[1].kwargs['max_nodes'],19993)
            self.assertEqual(r['planner_nodes'],7+two['nodes'])

    def test_no_second_call_after_pilot_exhausts_nodes(self):
        one=plan(self.p,horizon=1);one['nodes']=20000
        with patch('fbsde_depth_policy.plan',return_value=one) as mock:
            with self.assertRaisesRegex(PlanningBudgetError,'node budget'):
                allocate(self.p,(),2,'learned',self.bundle)
            self.assertEqual(mock.call_count,1)

    def test_unknown_threshold_profile_rejects(self):
        rows=[teacher_row(r) for r in numeric_inputs(5,1,'selection')]
        with self.assertRaises(ValueError):select_threshold(rows,weights(),'learned','test_tuned')


if __name__=='__main__':unittest.main()
