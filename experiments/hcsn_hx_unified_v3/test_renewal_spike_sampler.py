"""P2 independent sampled-event vs finite-horizon analytic count tests."""

import json
import math
import statistics
import subprocess
import sys
import unittest

from scipy.special import ndtr

from .renewal_spike_sampler import SpikeSpec, SpikeStream, UnresolvedSpike


def first_hit_discounted(d,mu,sigma,rho,t):
    """Independent closed first-passage reference (no sampler code imported)."""
    if t <= 0: return 0.0
    mag=math.hypot(mu,sigma*math.sqrt(2*rho))
    denom=sigma*sigma
    u=sigma*math.sqrt(t)
    return (math.exp((mu+mag)*d/denom)*ndtr((-d-mag*t)/u)
            +math.exp((mu-mag)*d/denom)*ndtr((-d+mag*t)/u))


def finite_series(p, horizon):
    """Exact model event-count expectation, finite sum because tau>0."""
    if p.refractory<=0: raise ValueError('positive tau required for finite sum')
    instant=p.initial>=p.boundary
    total=1.0 if instant else 0.0
    start=1 if instant else 0
    for n in range(start,1+int(horizon/p.refractory)):
        dist=(n*(p.boundary-p.reset) if instant else
              p.boundary-p.initial+n*(p.boundary-p.reset))
        t=horizon-n*p.refractory
        total+=math.exp(-p.discount*n*p.refractory)*first_hit_discounted(
            dist,p.drift,p.diffusion,p.discount,t)
    return total


class SampledRenewalTests(unittest.TestCase):
    @staticmethod
    def spec(mu=.35,tau=.5,initial=.1):
        return SpikeSpec(drift=mu,diffusion=1.2,discount=.12,cost=.5,
                         reset=-.1,refractory=tau,boundary=1.,initial=initial)

    def test_analytic_finite_horizon_vs_40k_sampled_streams(self):
        for mu in (-.35,0.,.35,1.0):
            p=self.spec(mu)
            exact=finite_series(p,4.5)
            draws=[]
            for n in range(10000):
                train=SpikeStream(p,seed=20261031+n,stream_id='cohort')
                times=train.advance_to(4.5)
                self.assertTrue(all(a<b for a,b in zip(times,times[1:])))
                draws.append(math.fsum(math.exp(-p.discount*t) for t in times))
            mean=statistics.fmean(draws)
            se=statistics.stdev(draws)/math.sqrt(len(draws))
            with self.subTest(drift=mu):
                self.assertLess(abs(mean-exact),5*se+.005)
            print('sampled vs exact',mu,'n',len(draws),'mean',mean,'exact',exact,
                  'SE',se)

    def test_deadtime_zero_time_first_fire_and_defective_absorption(self):
        p=self.spec(mu=-100.,initial=2.)
        t=SpikeStream(p,seed=9,stream_id='absorb')
        self.assertEqual(t.advance_to(0.),(0.,))
        self.assertEqual(t.advance_to(100.),())
        self.assertEqual(t.events,1)
        self.assertIsNone(t.next_time)
        p0=self.spec(mu=.3,tau=0.,initial=2.)
        a=SpikeStream(p0,seed=10,stream_id='zero')
        seq=a.advance_to(10.,max_events=100)
        self.assertGreaterEqual(len(seq),1)
        self.assertEqual(seq[0],0.)
        self.assertTrue(all(u<v for u,v in zip(seq,seq[1:])))

    def test_prefix_partition_checkpoint_and_host_process(self):
        p=self.spec(mu=.8,initial=1.2)
        full=SpikeStream(p,seed=42,stream_id='identical')
        expected=full.advance_to(8.)
        split=SpikeStream(p,seed=42,stream_id='identical')
        prefix=split.advance_to(1.1)+split.advance_to(3.3)
        snapshot=split.checkpoint()
        restored=SpikeStream.from_checkpoint(snapshot,expected_spec=p,
                                             expected_stream_id='identical')
        suffix=restored.advance_to(8.)
        self.assertEqual(prefix+suffix,expected)
        self.assertEqual(restored.checkpoint(),full.checkpoint())
        code=('import sys,json; from experiments.hcsn_hx_unified_v3.'
              'renewal_spike_sampler import SpikeStream; '
              's=SpikeStream.from_checkpoint(sys.stdin.read()); '
              't=s.advance_to(8.); print(json.dumps([t,s.checkpoint()]))')
        proc=subprocess.run([sys.executable,'-c',code],input=snapshot,text=True,
                            capture_output=True,check=True)
        external=json.loads(proc.stdout)
        self.assertEqual(tuple(external[0]),suffix)
        self.assertEqual(external[1],full.checkpoint())

    def test_fail_closed_invalid_checkpoint_and_transactional_event_cap(self):
        p=self.spec(initial=2.,mu=2.)
        s=SpikeStream(p,seed=1,stream_id='budget')
        first=s.checkpoint()
        with self.assertRaises(UnresolvedSpike):
            s.advance_to(40.,max_events=1)
        self.assertEqual(s.checkpoint(),first)
        with self.assertRaises(UnresolvedSpike):
            s.advance_to(-1.)
        with self.assertRaises(UnresolvedSpike):
            s.advance_to(1.,max_events=True)
        d=json.loads(first)
        d['spec']['boundary']+=.1
        with self.assertRaises(UnresolvedSpike):
            SpikeStream.from_checkpoint(json.dumps(d))
        with self.assertRaises(UnresolvedSpike):
            SpikeStream.from_checkpoint(first,expected_spec=self.spec())
        with self.assertRaises(UnresolvedSpike):
            SpikeStream.from_checkpoint(first,expected_stream_id='other')
        with self.assertRaises(UnresolvedSpike):
            SpikeStream.from_checkpoint('{not json}')

    def test_prefix_independent_of_future_horizon(self):
        p=self.spec(mu=-.1)
        a=SpikeStream(p,seed=1122,stream_id='P')
        b=SpikeStream(p,seed=1122,stream_id='P')
        c=SpikeStream(p,seed=1122,stream_id='different')
        a.advance_to(2.)
        b.advance_to(2.)
        self.assertEqual(a.checkpoint(),b.checkpoint())
        self.assertEqual(a.advance_to(9.),b.advance_to(5.)+b.advance_to(9.))
        self.assertEqual(a.checkpoint(),b.checkpoint())
        self.assertNotEqual(c.checkpoint(),a.checkpoint())

    def test_parameters_rejected(self):
        p=dict(drift=.2,diffusion=1.,discount=.1,cost=.5,reset=-.1,
               refractory=.2,boundary=1.,initial=.0)
        for bad in ({'diffusion':0.},{'discount':0.},{'refractory':-1.},
                    {'boundary':.4},{'reset':.7},{'drift':float('nan')},
                    {'diffusion':1e-250},{'diffusion':1e308}):
            with self.assertRaises(UnresolvedSpike):
                SpikeSpec(**(p|bad))
        with self.assertRaises(UnresolvedSpike):
            SpikeStream(SpikeSpec(**p),seed=-1,stream_id='a')
        with self.assertRaises(UnresolvedSpike):
            SpikeStream(SpikeSpec(**p),seed=1,stream_id='')

if __name__=='__main__':
    unittest.main()
