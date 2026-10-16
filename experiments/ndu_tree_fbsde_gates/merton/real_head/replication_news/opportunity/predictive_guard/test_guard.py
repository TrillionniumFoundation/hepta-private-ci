"""Exact-law, adversarial and original-input tests; no assertion removed by -O."""
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from fractions import Fraction as Q
from pathlib import Path
from unittest.mock import Mock

from guard import Monitor, GuardedLookup, curves_checked
from exact_null import certificate, trace

CURVES=((3,15,14,14),(5,10,10,10),(4,11,11,11),(5,10,9,9))
IDS=tuple(f'original-{i}' for i in range(32))
SCOPE='a'*64


class Algebra(unittest.TestCase):
    def test_normalization_and_maximal_probability(self):
        c=certificate(CURVES)
        self.assertEqual(c['terminal_paths'],1377)
        self.assertEqual(c['conditional_identities'],91)
        self.assertEqual(c['total_probability'],'1')
        self.assertLessEqual(Q(c['probability_ever_alarm']),Q(1,20))

    def test_incremental_equals_separate_joint_law(self):
        for h in ((7,7,12),(8,8,16),(4,4,8),(2,3,5)):
            m=Monitor(CURVES,SCOPE,IDS)
            for j,k in enumerate(h):
                start=sum((8,8,16)[:j]);n=(8,8,16)[j]
                if m.alarm:break
                actual=m.observe(k,IDS[start:start+n]);expected=trace(CURVES,h[:j+1])[-1]
                self.assertEqual({k:actual[k] for k in expected},expected)

    def test_zero_of_eight_rejects(self):
        r=Monitor(CURVES,SCOPE,IDS).observe(0,IDS[:8])
        self.assertTrue(r['alarm']);self.assertGreater(Q(r['e_value']),370)

    def test_one_of_eight_rejects(self):
        self.assertTrue(Monitor(CURVES,SCOPE,IDS).observe(1,IDS[:8])['alarm'])

    def test_seven_of_eight_does_not_reject(self):
        r=Monitor(CURVES,SCOPE,IDS).observe(7,IDS[:8])
        self.assertFalse(r['alarm']);self.assertLess(Q(r['e_value']),1)

    def test_alternative_model_can_reject_with_probability_one(self):
        # A point mass at all-zero counts is NOT the binomial-mixture null.
        rejection=int(Monitor(CURVES,SCOPE,IDS).observe(0,IDS[:8])['alarm'])
        self.assertEqual(rejection,1);self.assertGreater(rejection,Q(1,20))

    def test_latent_type_not_independently_redrawn(self):
        from exact_null import joint
        self.assertNotEqual(joint(CURVES,(8,8)),joint(CURVES,(8,))*joint(CURVES,(8,)))

    def test_same_stream_repetition_not_independent_evidence(self):
        r=trace(CURVES,(0,))[-1]
        e=Q(r['e_value'])
        self.assertNotEqual(e,e**2)
        self.assertFalse(certificate(CURVES)['fleet_wide_bound'])

    def test_null_certificate_never_certifies_real_accuracy(self):
        c=certificate(CURVES)
        self.assertFalse(c['validates_real_observation_model'])
        self.assertFalse(c['nonrejection_proves_accuracy'])


class Boundaries(unittest.TestCase):
    def test_bad_counts(self):
        for k in (True,-1,9,1.5,float('nan')):
            with self.subTest(k=k),self.assertRaises(ValueError):Monitor(CURVES,SCOPE,IDS).observe(k,IDS[:8])

    def test_bad_models(self):
        for rows in ([],[[True,1,2,3]],[[0,0,0,17]],[[0,1]]):
            with self.assertRaises(ValueError):curves_checked(rows)

    def test_scope_digest(self):
        for scope in ('','A'*64,'a'*63,None):
            with self.assertRaises(ValueError):Monitor(CURVES,scope,IDS)

    def test_rational_level_required(self):
        for level in (0.05,Q(0),Q(1),True):
            with self.assertRaises(ValueError):Monitor(CURVES,SCOPE,IDS,level)

    def test_duplicate_source_ids(self):
        with self.assertRaises(ValueError):Monitor(CURVES,SCOPE,IDS[:-1]+(IDS[0],))

    def test_reordered_and_foreign_ids(self):
        for ids in (IDS[:8][::-1],('foreign',)+IDS[1:8],list(IDS[:8])):
            with self.assertRaises(ValueError):Monitor(CURVES,SCOPE,IDS).observe(7,ids)

    def test_no_repeated_evidence(self):
        m=Monitor(CURVES,SCOPE,IDS);m.observe(7,IDS[:8])
        with self.assertRaises(ValueError):m.observe(7,IDS[:8])

    def test_invalid_call_is_atomic(self):
        m=Monitor(CURVES,SCOPE,IDS)
        with self.assertRaises(ValueError):m.observe(9,IDS[:8])
        self.assertEqual((m.history,m.e,m.records),((),Q(1),[]))

    def test_no_observation_after_alarm(self):
        m=Monitor(CURVES,SCOPE,IDS);m.observe(0,IDS[:8])
        with self.assertRaises(ValueError):m.observe(7,IDS[8:16])

    def test_return_record_cannot_mutate_owned_record(self):
        m=Monitor(CURVES,SCOPE,IDS);r=m.observe(7,IDS[:8]);r['ids'][0]='forged'
        self.assertEqual(m.records[0]['ids'][0],IDS[0])

    def test_complete_stream_is_terminal(self):
        m=Monitor(CURVES,SCOPE,IDS)
        for k,ids in ((7,IDS[:8]),(7,IDS[8:16]),(12,IDS[16:])):m.observe(k,ids)
        with self.assertRaises(ValueError):m.observe(1,())


class Lookup(unittest.TestCase):
    def make(self):
        u=Mock();u.decision.return_value={'action':'continue','to_step':8,'selected_steps':0,'posterior':[1]}
        return u,GuardedLookup(u,Monitor(CURVES,SCOPE,IDS))

    def test_root_has_no_observation(self):
        u,g=self.make();g.decision([],0)
        self.assertEqual(g.monitor.records,[]);u.decision.assert_called_once_with((),0)

    def test_rejection_precedes_old_lookup(self):
        u,g=self.make();g.decision([],0);u.decision.side_effect=AssertionError('old model used after rejection')
        r=g.decision([0],8)
        self.assertEqual((r['action'],r['selected_steps']),('stop',8))
        self.assertTrue(r['model_value_unavailable'])

    def test_rejection_retains_sunk_progress(self):
        u,g=self.make();g.decision([],0);g.decision([7],8)
        r=g.decision([7,0],32)
        self.assertEqual(r['selected_steps'],8);self.assertTrue(g.monitor.alarm)

    def test_missing_observation_rejected(self):
        _,g=self.make()
        with self.assertRaises(ValueError):g.decision([7,7],32)

    def test_progress_mismatch_rejected(self):
        _,g=self.make()
        for h,t in (([],8),([7],32),([7],True)):
            with self.assertRaises(ValueError):g.decision(h,t)

    def test_idempotent_call_not_new_test(self):
        u,g=self.make();g.decision([],0);g.decision([7],8)
        before=g.monitor.e;calls=u.decision.call_count
        g.decision([7],8)
        self.assertEqual(g.monitor.e,before);self.assertEqual(u.decision.call_count,calls)
        self.assertEqual(len(g.monitor.records),1)

    def test_history_rewrite_or_reset_rejected(self):
        _,g=self.make();g.decision([],0);g.decision([7],8)
        for h,t in (([6],8),([],0)):
            with self.assertRaises(ValueError):g.decision(h,t)

    def test_returned_decision_does_not_mutate_idempotent_result(self):
        _,g=self.make();r=g.decision([],0);r['posterior'][0]=100
        self.assertEqual(g.decision([],0)['posterior'],[1])


class OriginalSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from trial_guard import run
        from material_news import prepare
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)
        cls.archive=Path(os.environ['NEWS_ARCHIVE'])
        cls.material=cls.path/'material';cls.out=cls.path/'run'
        with contextlib.redirect_stdout(io.StringIO()):
            prepare(cls.archive,cls.material);cls.seal=run(cls.material,cls.out)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_actual_source_full_independent_replay(self):
        from audit_guard import audit
        r=audit(self.archive,self.material,self.out,self.path/'audit.json')
        self.assertEqual(r['verified_lifecycles'],72)
        self.assertEqual(r['guard_vs_shared_pairs'],24)
        self.assertEqual(r['online_updates'],264)
        self.assertTrue(all(not x['alarm'] for x in r['rows']))

    def test_guard_does_not_add_optimizer_calls_or_calibration(self):
        rows=self.seal['rows']
        for r in rows:
            if r['arm'].startswith('guarded_'):
                b=next(b for b in rows if b['repeat']==r['repeat'] and b['scenario']==r['scenario'] and b['arm']=='shared_'+r['arm'][8:])
                self.assertEqual(r['actual_steps'],b['actual_steps']);self.assertEqual(r['calibration_ids'],b['calibration_ids'])
                self.assertEqual(r['weights'],b['weights']);self.assertEqual(r['probabilities'],b['probabilities'])

    def test_fake_accuracy_guarantee_rejected(self):
        from audit_guard import audit
        from material_news import encode
        p=self.out/'sealed.json';old=p.read_bytes();s=json.loads(old);s['guard_is_accuracy_guarantee']=True
        try:
            p.write_bytes(encode(s))
            with self.assertRaises(ValueError):audit(self.archive,self.material,self.out,self.path/'bad.json')
        finally:p.write_bytes(old)

    def test_source_drift_rejected(self):
        from audit_guard import audit
        from material_news import encode
        p=self.out/'sealed.json';old=p.read_bytes();s=json.loads(old);s['source_sha256']['guard.py']='0'*64
        try:
            p.write_bytes(encode(s))
            with self.assertRaises(ValueError):audit(self.archive,self.material,self.out,self.path/'bad2.json')
        finally:p.write_bytes(old)

    def test_forged_resealed_e_value_rejected(self):
        from audit_guard import audit
        from material_news import encode
        p=self.out/'sealed.json';old=p.read_bytes();s=json.loads(old)
        row=next(r for r in s['rows'] if r['predictive_records'])
        row['predictive_records'][0]['e_value']='1'
        try:
            p.write_bytes(encode(s))
            with self.assertRaises(ValueError):audit(self.archive,self.material,self.out,self.path/'bad3.json')
        finally:p.write_bytes(old)

    def test_missing_lifecycle_rejected(self):
        from audit_guard import audit
        from material_news import encode
        p=self.out/'sealed.json';old=p.read_bytes();s=json.loads(old);s['rows'].pop()
        try:
            p.write_bytes(encode(s))
            with self.assertRaises(ValueError):audit(self.archive,self.material,self.out,self.path/'bad4.json')
        finally:p.write_bytes(old)

    def test_failure_leaves_no_success_seal(self):
        from unittest.mock import patch
        from trial_guard import run
        path=self.path/'failed-run'
        with contextlib.redirect_stdout(io.StringIO()),patch('trial_guard.lifecycle',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):run(self.material,path)
        self.assertFalse((path/'sealed.json').exists())
        self.assertEqual(json.loads((path/'journal.jsonl').read_text())['kind'],'failure')

    def test_cross_run_scope_cannot_be_substituted(self):
        from audit_guard import audit
        from material_news import encode
        p=self.out/'sealed.json';old=p.read_bytes();s=json.loads(old)
        row=next(r for r in s['rows'] if r['guard_scope']);row['guard_scope']='b'*64
        try:
            p.write_bytes(encode(s))
            with self.assertRaises(ValueError):audit(self.archive,self.material,self.out,self.path/'bad5.json')
        finally:p.write_bytes(old)

    def test_prior_is_not_free(self):
        self.assertEqual(self.seal['prior_updates'],512)
        self.assertEqual(self.seal['prior_fits_physically_executed'],1)

    def test_no_held_labels_in_worker(self):
        import numpy as np
        with np.load(self.material/'worker.npz',allow_pickle=False) as a:
            self.assertNotIn('y_holdout',a.files)
        self.assertFalse(self.seal['heldout_labels_loaded'])


if __name__=='__main__':unittest.main()
