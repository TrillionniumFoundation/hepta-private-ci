"""Independent expm/quadrature and stream tests for a repeated-fire CTMC."""
import json
import math
import random
import subprocess
import sys
import unittest
from dataclasses import asdict

import numpy as np
from scipy.integrate import quad
from scipy.linalg import expm

from .renewal_event_oracle import RenewalState, advance


class RenewalEventOracleTests(unittest.TestCase):
    def test_randomized_independent_ctmc_matrix_and_event_integral(self):
        rng=random.Random(2026103017)
        for case in range(64):
            lam=rng.uniform(.1,10)
            gamma=rng.uniform(.1,10)
            t=rng.uniform(.001,3)
            a=rng.uniform(0,1)
            result=advance(RenewalState.initial(a),lam,gamma,t)
            generator=np.array([[-lam,lam],[gamma,-gamma]])
            killed=np.array([[-lam,0],[gamma,-gamma]])
            start=np.array([a,1-a])
            matrix=start @ expm(generator*t)
            survival=start @ expm(killed*t)
            count=quad(lambda u:lam*(start @ expm(generator*u))[0],0,t,
                       epsabs=1e-11,epsrel=1e-11)[0]
            self.assertAlmostEqual(result.active,matrix[0],delta=4e-12)
            self.assertAlmostEqual(result.no_fire_active,survival[0],delta=4e-12)
            self.assertAlmostEqual(result.no_fire_refractory,survival[1],delta=4e-12)
            self.assertAlmostEqual(result.ever_fired,1-sum(survival),delta=4e-12)
            self.assertAlmostEqual(result.expected_count,count,delta=4e-12)

    def test_repeat_events_are_not_first_event_probability(self):
        result=advance(RenewalState.initial(1),8.,10.,3.)
        self.assertGreater(result.expected_count,10)
        self.assertLessEqual(result.ever_fired,1)
        self.assertGreater(result.expected_count,result.ever_fired+8)

    def test_variable_step_composition_and_full_causal_state(self):
        dts=(.01,.5,.001,.7,1.2,.003)
        s=RenewalState.initial(.29)
        for dt in dts:
            s=advance(s,3.,2.,dt)
        one=advance(RenewalState.initial(.29),3.,2.,math.fsum(dts))
        for key in ('active','no_fire_active','no_fire_refractory','ever_fired','expected_count'):
            self.assertAlmostEqual(getattr(s,key),getattr(one,key),delta=2e-12)
        prefix=advance(RenewalState.initial(.29),3.,2.,.2)
        a=advance(prefix,3.,2.,.3)
        b=advance(prefix,3.,2.,.3)
        self.assertEqual(a,b)
        self.assertEqual(prefix,advance(RenewalState.initial(.29),3.,2.,.2))

    def test_small_time_refractory_first_fire_quadratic(self):
        for dt in (1e-3,1e-5,1e-7):
            result=advance(RenewalState.initial(0),3.,4.,dt)
            self.assertGreater(result.ever_fired,0)
            self.assertAlmostEqual(result.ever_fired/(.5*12*dt*dt),1.,delta=3e-3)
            self.assertGreaterEqual(result.expected_count,result.ever_fired)

    def test_equal_and_nearly_equal_rates(self):
        for gamma in (2.,2.+1e-12,2.-1e-12):
            result=advance(RenewalState.initial(.4),2.,gamma,1.)
            self.assertAlmostEqual(result.no_fire_active+result.no_fire_refractory,
                                   1-result.ever_fired,delta=2e-15)

    def test_changing_rates_preserves_killed_state_causally(self):
        segments=((1.2,2.3,.4),(4.3,.8,.06),(.7,3.2,.9))
        state=RenewalState.initial(.41)
        prob=np.array([.41,.59])
        no_fire=prob.copy()
        for lam,gamma,dt in segments:
            state=advance(state,lam,gamma,dt)
            prob=prob @ expm(np.array([[-lam,lam],[gamma,-gamma]])*dt)
            no_fire=no_fire @ expm(np.array([[-lam,0],[gamma,-gamma]])*dt)
        self.assertAlmostEqual(state.active,prob[0],delta=2e-12)
        self.assertAlmostEqual(state.no_fire_active,no_fire[0],delta=2e-12)
        self.assertAlmostEqual(state.no_fire_refractory,no_fire[1],delta=2e-12)
        self.assertAlmostEqual(state.ever_fired,1-sum(no_fire),delta=2e-12)

    def test_versioned_numeric_state_replays_in_separate_interpreter(self):
        checkpoint=advance(advance(RenewalState.initial(.37),3.,2.,.5),
                           6.,.9,.06)
        snapshot=json.dumps(asdict(checkpoint),allow_nan=False)
        local=advance(checkpoint,2.,1.5,.74)
        script=('import json; from experiments.hcsn_distributional_v2.'
                'renewal_event_oracle import RenewalState,advance; '
                's=RenewalState(**json.loads(' + repr(snapshot) + ')); '
                'print(json.dumps(vars(advance(s,2.,1.5,.74)),sort_keys=True))')
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,
                              text=True,check=True)
        self.assertEqual(json.loads(result.stdout),asdict(local))

    def test_invalid_states_and_time_refused(self):
        for lam,gamma,dt in ((0,1,1),(1,0,1),(1,1,-1),
                             (math.inf,1,1),(1,math.nan,1),(1,1,math.inf)):
            with self.assertRaises(ValueError):
                advance(RenewalState.initial(1),lam,gamma,dt)
        with self.assertRaises(ValueError):
            advance(RenewalState(0.,.5,.5,.5,.5,0.),1,2,.1)
        with self.assertRaises(ValueError):
            RenewalState.initial(1.1)
        with self.assertRaises(ValueError):
            advance(RenewalState.initial(.5).__class__(0.,.5,.5,.5,0.,0.,2),1,2,.1)


if __name__=='__main__':
    unittest.main()
