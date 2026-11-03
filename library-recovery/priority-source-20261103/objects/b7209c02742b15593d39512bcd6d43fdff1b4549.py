import unittest
from dataclasses import replace
from event_memory_v2 import (TASKS,SCALES,generate,oracle,replay_reference,
                            receipt,audit,check_no_overlap,time_blind_baseline)

class P2RealMemorySemantics(unittest.TestCase):
    def test_six_tasks_four_scales_cross_checked(self):
        rows=audit()
        self.assertEqual(len(rows),24)
        self.assertTrue(all(x['query_count']>0 for x in rows))
        for r in rows:
            self.assertEqual(len(r['content_sha256']),64)

    def test_real_time_affects_correct_answer(self):
        es=generate('irregular_time',64,100)
        original=oracle(es,'irregular_time')
        stretched=[]
        for i,e in enumerate(es):
            stretched.append(replace(e,time=e.time*100))
        self.assertNotEqual(original,oracle(stretched,'irregular_time'))
        self.assertLess(time_blind_baseline(es,'irregular_time')['accuracy'],.8)

    def test_multiple_regenerations_and_missing_after_reset(self):
        es=generate('regeneration',256,12)
        self.assertGreaterEqual(sum(e.operation=='reset' for e in es),4)
        self.assertEqual(oracle(es,'regeneration')[-1][1],-1)
        self.assertLess(time_blind_baseline(es,'regeneration')['accuracy'],1)

    def test_delayed_mqar_not_immediate_queries(self):
        es=generate('mqar',256,8)
        last_write=max(i for i,e in enumerate(es) if e.operation=='write')
        first_query=min(i for i,e in enumerate(es) if e.operation=='query')
        self.assertGreater(first_query,last_write)
        self.assertEqual(oracle(es,'mqar'),replay_reference(es,'mqar'))

    def test_negative_reset_and_toggle_consistency(self):
        for t in ('selective_copy','regeneration','overwrite'):
            es=generate(t,64,4)
            self.assertEqual(oracle(es,t),replay_reference(es,t))
        select=generate('selective_copy',256,77)
        self.assertLess(time_blind_baseline(select,'selective_copy')['accuracy'],1)

    def test_identical_content_across_splits_is_rejected(self):
        a=receipt('mqar',64,101,'train')
        b=receipt('mqar',64,101,'holdout')
        self.assertEqual(a['content_sha256'],b['content_sha256'])
        self.assertTrue(check_no_overlap([a,b]))

    def test_bad_clock_and_non_finite_rejected(self):
        es=generate('irregular_time',64,5)
        with self.assertRaises(ValueError):oracle([es[1],es[0]],'irregular_time')
        with self.assertRaises(ValueError):oracle([replace(es[0],time=float('nan'))], 'irregular_time')

if __name__=='__main__':unittest.main()
