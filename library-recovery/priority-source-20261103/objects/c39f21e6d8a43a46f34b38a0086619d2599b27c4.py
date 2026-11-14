"""P2 deterministic refractory renewal / causal checkpoint tests."""
from dataclasses import asdict, replace
import json
import math
import random
import subprocess
import sys
import unittest

from .deterministic_refractory_reference import (
    PathState, RenewalDomainError, constant_rate_stats, advance_path)


class DeterministicRefractoryTests(unittest.TestCase):
    def test_tau_zero_is_poisson_and_analytical_first_fire_independent_tau(self):
        for lam,T in ((.1,.01),(.8,3),(7.,2),(.01,10)):
            poisson=constant_rate_stats(lam,0,T)
            self.assertAlmostEqual(poisson.expected_event_count,lam*T)
            for tau in (.01,.2,1,20):
                v=constant_rate_stats(lam,tau,T)
                self.assertAlmostEqual(v.first_fire_probability,
                                       poisson.first_fire_probability,places=13)
                self.assertLessEqual(v.expected_event_count,poisson.expected_event_count+1e-12)
                self.assertLessEqual(v.three_or_more_probability,v.two_or_more_probability)

    def test_expected_repeated_events_differ_from_one_event_probability(self):
        r=constant_rate_stats(5,.1,6)
        self.assertGreater(r.expected_event_count,10)
        self.assertLessEqual(r.first_fire_probability,1)
        self.assertGreater(r.expected_event_count,r.first_fire_probability+8)
        self.assertGreater(r.three_or_more_probability,.9)

    def test_monte_carlo_independent_exp_plus_deterministic_refractory(self):
        rng=random.Random(2026103103)
        for lam,tau,T in ((1.2,.3,4),(.5,1,3),(3,.1,2)):
            n=20_000
            counts=[]
            for _ in range(n):
                t=0.;count=0
                while True:
                    t+=rng.expovariate(lam)
                    if t>T:
                        break
                    count+=1
                    t+=tau
                counts.append(count)
            expected=constant_rate_stats(lam,tau,T)
            empirical_count=sum(counts)/n
            empirical_fired=sum(x>=1 for x in counts)/n
            self.assertLess(abs(empirical_count-expected.expected_event_count),.065)
            self.assertLess(abs(empirical_fired-expected.first_fire_probability),.02)
            self.assertLess(abs(sum(x>=2 for x in counts)/n-
                                expected.two_or_more_probability),.025)

    def test_refractory_suppresses_repeated_not_first_event(self):
        fixed=[constant_rate_stats(1.,tau,8.) for tau in (0,.1,.5,2,10)]
        self.assertTrue(all(abs(f.first_fire_probability-fixed[0].first_fire_probability)<1e-15
                            for f in fixed))
        self.assertTrue(all(fixed[i+1].expected_event_count<=fixed[i].expected_event_count+1e-14
                            for i in range(len(fixed)-1)))

    def test_stream_split_matches_unsplit_event_count_and_state(self):
        rng=random.Random(2026103104)
        for case in range(400):
            seed=rng.randrange(2**32);lam=rng.uniform(.1,5)
            tau=rng.uniform(.01,.7);a=rng.uniform(.01,2);b=rng.uniform(.01,2)
            init=PathState.initial(seed,tau)
            split=advance_path(advance_path(init,lam,a),lam,b)
            full=advance_path(init,lam,a+b)
            with self.subTest(case=case):
                self.assertEqual(split.fired_count,full.fired_count)
                self.assertEqual(split.rng_counter,full.rng_counter)
                self.assertLess(abs(split.active_hazard_remaining-full.active_hazard_remaining),2e-12)
                self.assertLess(abs(split.refractory_remaining-full.refractory_remaining),2e-12)

    def test_segmented_rate_switch_and_json_process_replay(self):
        segs=[(1.3,.41),(2.1,1.2),(.7,.56),(3.5,1.7),(.4,.8)]
        prefix=PathState.initial(20261031,.31)
        for lam,dt in segs[:3]:
            prefix=advance_path(prefix,lam,dt)
        encoded=json.dumps(asdict(prefix),sort_keys=True)
        restored=PathState(**json.loads(encoded))
        self.assertEqual(prefix,restored)
        local=restored
        for lam,dt in segs[3:]:
            local=advance_path(local,lam,dt)
        # Another Python process proves the checkpoint includes the RNG budget,
        # not merely event counts or the active/refractory flag.
        source=("import json; from dataclasses import asdict; "
            "from experiments.hcsn_distributional_v2.deterministic_refractory_reference "
            "import PathState,advance_path; "
            "s=PathState(**json.loads("+repr(encoded)+")); "
            "s=advance_path(s,3.5,1.7); s=advance_path(s,.4,.8); "
            "print(json.dumps(asdict(s),sort_keys=True))")
        remote=subprocess.check_output([sys.executable,'-c',source],text=True)
        self.assertEqual(json.loads(remote),asdict(local))
        sibling=advance_path(restored,1.3,2.5)
        self.assertNotEqual(sibling.fired_count,local.fired_count)
        self.assertEqual(restored,PathState(**json.loads(encoded)))

    def test_causal_prefix_does_not_depend_on_future_rate(self):
        init=PathState.initial(23,.04)
        one=advance_path(init,1.,.125)
        two=advance_path(init,1.,.125)
        self.assertEqual(one,two)
        left=advance_path(one,.2,4)
        right=advance_path(two,3.,4)
        self.assertNotEqual(left.fired_count,right.fired_count)

    def test_invalid_checkpoint_and_numerical_budgets_refuse(self):
        init=PathState.initial(11,.5)
        with self.assertRaises(RenewalDomainError):
            advance_path(replace(init,version=2),1,.5)
        with self.assertRaises(RenewalDomainError):
            advance_path(replace(init,fired_count=2),1,.5)
        with self.assertRaises(RenewalDomainError):
            advance_path(replace(init,physical_time=0.,fired_count=1,rng_counter=2),1,.5)
        with self.assertRaises(RenewalDomainError):
            advance_path(replace(init,active_hazard_remaining=init.active_hazard_remaining/2),1,.5)
        with self.assertRaises(RenewalDomainError):
            constant_rate_stats(10,.0001,10,max_terms=100)
        with self.assertRaises(RenewalDomainError):
            constant_rate_stats(0,.5,1)
        with self.assertRaises(ArithmeticError):
            advance_path(init,10**10,20,max_events=3)


if __name__=='__main__':
    unittest.main()
