import math
import unittest
from dataclasses import replace
import numpy as np
from mpmath import mp
from fpt_reference import FPT,formula,transformed_integral,float_diagnostic,boundary_derivatives
from qvi_toy import audit,value_iteration
from event_memory_tasks import TASKS,make_events,oracle_incremental,oracle_independent,dataset
from gate_contract import empty_ledger,assess,REQUIREMENTS
from stress_envelope import run_stress


class FirstPassage(unittest.TestCase):
    def test_frozen_near_boundary_gap_representability(self):
        sigma=1.8581469732429565
        rate=.007595780582070804
        p=FPT(x=math.log(1.000000000000002),
              drift=rate-3.5072936797757205e-07-sigma*sigma/2,
              sigma=sigma,horizon=2.2216211523554883e-08,
              discount=rate)
        diag=float_diagnostic(p,120)
        with mp.workdps(60):
            self.assertGreater(mp.mpf(diag['reference']['F_minus_G']),0)
        self.assertIn(diag['classification'],
                      ('DENY_F64_UNRESOLVED_GAP','DENY_NUMERIC_ORDER'))
        self.assertLess(diag['gap_ulp'],1.)

    def test_cdf_vs_independent_density_integral(self):
        for p in [FPT(.8,-.3,.7,.9,.05),FPT(.2,.2,.6,1.2,0),
                  FPT(1.4,.4,.5,1.1,.11)]:
            with self.subTest(p=p):
                closed=formula(p,75)
                integrated=transformed_integral(p,65)
                for name in ('F','G'):
                    with mp.workdps(60):
                        self.assertLess(abs(mp.mpf(closed[name])-mp.mpf(integrated[name])),mp.mpf('1e-45'))

    def test_gradient_independent(self):
        result=boundary_derivatives(FPT(.8,-.3,.7,.9,.05),90)
        self.assertLess(float(result['abs_delta']),1e-60)

    def test_domain_and_endpoints(self):
        base=FPT(.5,-.2,.7,.9,.05)
        for k,v in [('sigma',0.),('x',-1.),('horizon',-1.),('discount',-1.),('x',float('nan'))]:
            with self.assertRaises(ValueError):formula(replace(base,**{k:v}))
        self.assertEqual(formula(replace(base,x=0))['F'],'1.0')
        self.assertEqual(formula(replace(base,horizon=0))['G'],'0.0')

    def test_deterministic_stress_policy(self):
        result=run_stress(n=240,seed=20261030)
        self.assertEqual(result["total"],240)
        self.assertEqual(result["fatal_unexpected"],0)
        self.assertEqual(result["reference_ordered"],240)
        self.assertGreater(result["binary64_resolution_denied"],0)

    def test_monotone_discount_positive(self):
        p=FPT(.9,-.2,.6,1.3,.01)
        f1=formula(p)
        f2=formula(replace(p,discount=1.))
        with mp.workdps(50):
            self.assertLess(mp.mpf(f2['G']),mp.mpf(f1['G']))
            self.assertLess(abs(mp.mpf(f1['F'])-mp.mpf(f2['F'])),mp.mpf('1e-55'))


class RegenerativeToyQvi(unittest.TestCase):
    def test_exhaustive_policy_independent_oracle(self):
        diag=audit()
        self.assertLess(diag['max_policy_gap'],1e-11)
        self.assertLess(diag['max_bellman_residual'],1e-11)
        self.assertGreater(diag['iterations'],0)
        self.assertIn(True,diag['intervention'])
        self.assertIn(False,diag['intervention'])

    def test_bad_probabilities_rejected(self):
        with self.assertRaises(ValueError):
            value_iteration(np.array([[.9,.8],[.2,.8]]),[0,1],[1,0],.9)


class EventMemory(unittest.TestCase):
    def test_every_task_and_holdout_length(self):
        for t in TASKS:
            for n in (64,256,1024,4096):
                with self.subTest(task=t,length=n):
                    es=make_events(t,n,89+n)
                    fast=oracle_incremental(es,t)
                    self.assertTrue(fast)
                    # Full oracle for smaller sequences and sampled long ones.
                    if n<=256:
                        self.assertEqual(fast,oracle_independent(es,t))
                    else:
                        prefix=es[:300]
                        self.assertEqual(oracle_incremental(prefix,t),
                                         oracle_independent(prefix,t))
                    obj=dataset(t,n,89+n,'holdout')
                    self.assertEqual(len(obj['sha256']),64)
                    self.assertEqual(obj['query_count'],len(fast))

    def test_no_future_leak_in_long_range(self):
        es=make_events('long_range',4096,42)
        expected=oracle_incremental(es,'long_range')
        self.assertEqual(len(expected),1)
        self.assertEqual(expected[0][1],es[0].value)

    def test_regeneration_clears_old_memory(self):
        es=make_events('regeneration',256,42)
        self.assertEqual(oracle_incremental(es,'regeneration')[-1][1],-1)

    def test_bad_clock_rejected(self):
        es=make_events('mqar',20,42)
        with self.assertRaises(ValueError):
            oracle_incremental([es[1],es[0]],'mqar')


class FailingClosedGates(unittest.TestCase):
    def test_all_six_denied_without_provenance(self):
        ret=assess(empty_ledger())
        self.assertFalse(ret['all_blockers_closed'])
        self.assertFalse(ret['production_activation_allowed'])
        self.assertEqual(set(ret['results']),set(REQUIREMENTS))
        self.assertTrue(all(x['status']=='OPEN' for x in ret['results'].values()))

    def test_fake_pass_without_artifact_rejected(self):
        sample=empty_ledger()
        for evidence in sample['stage_evidence']['P0'].values():
            evidence['status']='PASS'
        self.assertEqual(assess(sample)['results']['P0']['status'],'OPEN')

if __name__=='__main__':unittest.main()
