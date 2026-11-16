import unittest
import sys
import numpy as np
from types import SimpleNamespace
from cell_field_fixed_census import run_synthetic_census, encoded

class CensusTests(unittest.TestCase):
    def fixture(self):
        ref=SimpleNamespace(state=SimpleNamespace(parameter_count=36),horizon=3,dt=.02,
                            A=np.zeros((3,108,108)),C=np.zeros((4,4,108)),
                            states=np.zeros((4,108)),scales=np.ones(108))
        return {'synthetic':ref}
    def run_census(self,**kwargs):
        identities={'synthetic':{k:'a'*64 for k in ('source_sha256','protocol_sha256','features_sha256','checkpoint_sha256')}}
        options=dict(identities=identities,attempt_limit=147,wall_seconds=10,rss_bytes=1000,evidence_bytes=200000,
                     observer=lambda:{'monotonic_seconds':1.,'process_peak_rss_bytes':100},
                     predictor=lambda *a,**k:{'fields':np.zeros((4,2))})
        options.update(kwargs)
        return run_synthetic_census(self.fixture(),**options)
    def test_complete_census_and_stable_identity(self):
        one=self.run_census();two=self.run_census()
        self.assertEqual(one,two);self.assertEqual(len(one['records']),147)
        self.assertEqual(one['attempted'],147);self.assertTrue(one['all_succeeded'])
        self.assertFalse(one['provenance_verified']);self.assertFalse(one['crash_durable'])
        self.assertEqual(len({(r['anchor'],r['action'],r['mode']) for r in one['records']}),147)
    def test_attempt_cap_counts_errors_no_retry(self):
        calls=[]
        def fail(*args,**kwargs):calls.append(1);raise RuntimeError('known failure\noriginal reason')
        out=self.run_census(attempt_limit=2,predictor=fail)
        self.assertEqual(len(calls),2);self.assertEqual(out['attempted'],2)
        self.assertEqual([r['status'] for r in out['records'][:2]],['error']*2)
        self.assertTrue(all(r['status']=='not_run_budget' for r in out['records'][2:]))
        self.assertEqual(out['records'][0]['error_message'],'known failure original reason')
    def test_zero_cap_has_complete_not_run_plan(self):
        out=self.run_census(attempt_limit=0)
        self.assertEqual(out['attempted'],0);self.assertEqual(len(out['records']),147)
        self.assertFalse(out['all_succeeded'])
    def test_missing_or_nonfinite_output_is_error_not_zero(self):
        for predictor in (lambda *a,**k:{},lambda *a,**k:{'fields':np.full((4,2),np.nan)}):
            out=self.run_census(attempt_limit=1,predictor=predictor)
            self.assertEqual(out['records'][0]['status'],'error');self.assertNotIn('fields',out['records'][0])
    def test_post_call_wall_crossing_is_not_success(self):
        samples=iter([0.,0.,11.])
        out=self.run_census(observer=lambda:{'monotonic_seconds':next(samples),'process_peak_rss_bytes':100})
        self.assertEqual(out['attempted'],1);self.assertEqual(out['records'][0]['status'],'over_budget')
        self.assertEqual(out['stop_reason'],'wall_seconds');self.assertFalse(out['all_succeeded'])
    def test_initial_rss_aborts_before_prediction(self):
        out=self.run_census(rss_bytes=99)
        self.assertEqual(out['attempted'],0);self.assertEqual(out['stop_reason'],'rss_bytes')
    def test_observation_failure_and_clock_regression(self):
        for samples in ([2.,1.],[0.,0.]):
            it=iter(samples)
            out=self.run_census(observer=lambda:{'monotonic_seconds':next(it),'process_peak_rss_bytes':100})
            self.assertEqual(out['stop_reason'],'observation_error');self.assertFalse(out['all_succeeded'])
    def test_insufficient_metadata_budget_rejects_before_calls(self):
        with self.assertRaises(ValueError):self.run_census(evidence_bytes=100)
    def test_identity_required_and_budget_affects_request_digest(self):
        with self.assertRaises(ValueError):self.run_census(identities={})
        self.assertNotEqual(self.run_census(attempt_limit=1)['request_sha256'],self.run_census(attempt_limit=2)['request_sha256'])
    def test_evidence_output_budget_is_not_silent_success(self):
        # Larger synthetic horizon creates enough output to exceed a metadata-safe payload limit.
        refs=self.fixture();refs['synthetic'].horizon=256
        ids={'synthetic':{k:'a'*64 for k in ('source_sha256','protocol_sha256','features_sha256','checkpoint_sha256')}}
        out=run_synthetic_census(refs,identities=ids,attempt_limit=147,wall_seconds=10,rss_bytes=1000,evidence_bytes=150000,
             observer=lambda:{'monotonic_seconds':1.,'process_peak_rss_bytes':100},
             predictor=lambda *a,**k:{'fields':np.ones((257,2))})
        self.assertLessEqual(len(encoded(out)),150000);self.assertEqual(out['stop_reason'],'evidence_bytes')
        self.assertFalse(out['all_succeeded']);self.assertEqual(len(out['records']),147)
        self.assertTrue(any(r.get('output_status')=='omitted_budget' for r in out['records']))

    @unittest.skipUnless(sys.platform=='linux','direct process RSS observation is Linux-only')
    def test_actual_adapter_integration_on_synthetic_head_reference(self):
        from cell_field_fixed_fixture import build_synthetic_references
        ref=build_synthetic_references(('linear',))['linear']
        ids={'real_class_synthetic':{k:'a'*64 for k in ('source_sha256','protocol_sha256','features_sha256','checkpoint_sha256')}}
        out=run_synthetic_census({'real_class_synthetic':ref},identities=ids,
             attempt_limit=6,wall_seconds=10,rss_bytes=2*1024**3,evidence_bytes=200000)
        self.assertEqual(out['attempted'],6)
        self.assertTrue(all(r['status']=='success' for r in out['records'][:6]))
        self.assertTrue(all(r['status']=='not_run_budget' for r in out['records'][6:]))
        self.assertFalse(out['all_succeeded']);self.assertFalse(out['fixture_hooks'])
        self.assertTrue(any(np.any(r['fields']) for r in out['records'][3:6]))

    def test_unicode_escaped_failure_preserves_complete_census(self):
        def fail(*args,**kwargs):raise RuntimeError('💥'*256+'\\"\n')
        out=self.run_census(predictor=fail,evidence_bytes=150000)
        self.assertEqual(len(out['records']),147)
        self.assertEqual(out['attempted'],147)
        self.assertTrue(all(r['status']=='error' for r in out['records']))
        self.assertLessEqual(len(encoded(out)),150000)
        self.assertTrue(all(len(encoded(r['error_message']))<=258 for r in out['records']))

    def test_broken_exception_string_and_resource_error_preserve_failure(self):
        class BadError(Exception):
            def __str__(self):raise ValueError('broken diagnostic')
        def fail(*args,**kwargs):raise BadError()
        samples=iter([0.,0.,11.])
        out=self.run_census(predictor=fail,observer=lambda:{'monotonic_seconds':next(samples),'process_peak_rss_bytes':100})
        r=out['records'][0]
        self.assertEqual(r['status'],'over_budget');self.assertEqual(r['execution_status'],'error')
        self.assertEqual(r['error_type'],'BadError')
        self.assertEqual(r['error_message'],'<exception message unavailable>')

    def test_oversized_observer_integer_retains_plan(self):
        for sample in ({'monotonic_seconds':1.,'process_peak_rss_bytes':10**5000},
                       {'monotonic_seconds':10**5000,'process_peak_rss_bytes':1}):
            out=self.run_census(observer=lambda:sample)
            self.assertEqual(out['stop_reason'],'observation_error')
            self.assertEqual(out['attempted'],0);self.assertEqual(len(out['records']),147)

if __name__=='__main__':unittest.main()
