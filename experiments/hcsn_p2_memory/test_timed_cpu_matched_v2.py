"""P2 follow-up accounting contract, not causal/mechanistic acceptance."""
import copy
import unittest
from .event_content import UnresolvedContent
from .timed_cpu_matched_v2 import validate_pair,run,SEEDS,BUDGET,MAX_STEPS

class CPUBudgetFollowupTests(unittest.TestCase):
    @staticmethod
    def pair():
        p=lambda arm,steps: dict(schema='hcsn-p2-timed-cpu-matched-followup-v2',
          task='copy',seed=2,arm=arm,params=5186,
          reached_step_cap=False,reached_cpu_budget=True,training_cpu_seconds=25.01,
          optimizer_steps=steps,initial_model_sha256='f'*64,
          train_data_sha256='e'*64,
          id=dict(data_sha256='a'*64,total_events=20,queries=128,
                  multi_fire_streams=128,accuracy=.7),
          ood=dict(data_sha256='b'*64,total_events=30,queries=128,
                   multi_fire_streams=128,accuracy=.6),
          production_activation=False,all_scientific_blockers_closed=False)
        return p('aggregate_count',4200),p('physical_event_timestamp',2500)

    def test_valid_cpu_matched_evidence_never_closes_scientific_gates(self):
        a,b=self.pair()
        x=validate_pair(a,b)
        self.assertTrue(x['equal_cpu_within_five_percent'])
        self.assertFalse(x['all_scientific_blockers_closed'])
        self.assertEqual(x['training_cpu_relative_gap'],0.)
        self.assertEqual((x['aggregate_steps'],x['timed_steps']),(4200,2500))

    def test_fail_closed_cpu_overshoot_or_step_cap(self):
        for k,v in (('training_cpu_seconds',26.5),('training_cpu_seconds',20.0),
                    ('reached_step_cap',True),('reached_cpu_budget',False)):
            with self.subTest(k=k,v=v):
                a,b=self.pair();b[k]=v
                with self.assertRaises(UnresolvedContent):validate_pair(a,b)
        a,b=self.pair();b['training_cpu_seconds']=26.0
        self.assertTrue(validate_pair(a,b)['equal_cpu_within_five_percent'])  # 3.8% is admissible; 5% is the frozen tolerance

    def test_fail_closed_nonidentical_streams_seeds_weights(self):
        for field,value in (('train_data_sha256','f'*64),('initial_model_sha256','a'*64),
                            ('seed',3),('production_activation',True),('params',4)):
            a,b=self.pair();b[field]=value
            with self.subTest(field=field),self.assertRaises(UnresolvedContent):validate_pair(a,b)
        a,b=self.pair();b['id']['total_events']=44
        with self.assertRaises(UnresolvedContent):validate_pair(a,b)
        self.assertEqual(SEEDS,(2,3,4));self.assertEqual(BUDGET,25.0);self.assertEqual(MAX_STEPS,8000)

    def test_no_unregistered_seeds_or_task(self):
        for args in [('copy',1,'aggregate_count'),('copy',5,'aggregate_count'),('bogus',2,'aggregate_count'),('copy',2,'bogus')]:
            with self.subTest(args=args),self.assertRaises(UnresolvedContent):run(*args)

if __name__=='__main__':unittest.main()
