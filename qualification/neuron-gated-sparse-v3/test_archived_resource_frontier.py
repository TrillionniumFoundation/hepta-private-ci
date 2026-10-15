"""Source-only negative tests; full original ZIPs supplied separately on local replay."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

import archived_resource_frontier as g


def h(s):
    return hashlib.sha256(s.encode('ascii')).hexdigest()


def synthetic_weights():
    rows = []
    for arm in g.TEMPORAL:
        for cap in g.CAPS:
            geometry = 'small' if arm == 'min_gru' and cap == 2048 else 'large'
            if arm != 'min_gru': geometry = 'constant'
            rows.append({'arm':arm,'private_parameter_cap':cap,
                         'physical_artifact_sha256':h(arm+geometry),
                         'fresh_process_count':2,
                         'independent_rust_processes_bit_identical':True,
                         'q24_head_integer_oracle':{
                             'all_native_head_logits_match_independent_integer_oracle':True,
                             'all_native_head_sign_margins_match_independent_integer_oracle':True,
                             'full_original_f32_policy_execution_verified':False}})
    doc = {'schema':'hepta.neuron.twenty-physical-q24-mechanism-matrix.v1',
           'evidence_class':'SYNTHETIC_NATIVE_RESEARCH_ONLY',
           'decision':'NO_MODEL_PROMOTION',
           'frozen_a0_owner_revalidation':{'a0_rechecked':False},
           'twenty_native_physical_model_executions':20,
           'forty_fresh_native_process_invocations':40,
           'results':rows,'realized_budget_audit':{
               'five_tier_exact_realized_parameter_design_valid':False,
               'production_qualification':False,
               'effective_independent_physical_model_comparisons':5}}
    for key in ('production_qualification', 'ndu_eligible','real_target_host_attested',
                'floating_torch_native_q24_prediction_parity_verified',
                'full_selected_model_head_executed','crash_durable_recovery_verified'):
        doc[key] = False
    return doc


def synthetic_mechanism():
    rows = []
    for n,c in enumerate(g.SCALES):
        for k,a in enumerate(g.ARMS):
            rows.append({'arm':a,'cells':c,'trace_sha256':h('frozen trace'),
                         'p99_tick_nanos':100+k*20+n*5,
                         'process_peak_rss_bytes':10**6 + k*100_000+n*10,
                         'mechanism_tick_throughput_per_second_milli':10000-k*1000,
                         'trained_model':False,'artifact_provenance_verified':False,
                         'production_qualification':False,'ndu_eligible':False})
    m={'schema':'hepta.neuron.mechanism-only-matrix.v1',
       'source_evidence_kind':'UNVERIFIED_KERNEL_ONLY_NOT_TARGET_HOST_ACCEPTANCE',
       'arms':list(g.ARMS),'scales':list(g.SCALES),
       'trace_sha256':h('frozen trace'),'results':rows}
    for key in ('target_host_qualified','trained_artifacts_qualified',
                'parameter_budgets_matched','ndu_eligible'):m[key]=False
    s={'schema':'hepta.neuron.five-arm-mechanism-cost-summary.v1',
       'decision':'NO_MODEL_PROMOTION','original_trace_sha256':h('frozen trace'),
       'comparisons':[],}
    for key in ('qualified_target_host','qualified_p99_sla',
                'verified_same_budget_full_model_execution','verified_real_training',
                'verified_independent_evaluator','production_qualification','ndu_eligible'):
        s[key]=False
    for cells in g.SCALES:
        refs=[]
        for row in rows:
            if row['cells'] == cells:
                refs.append({key:row[key] for key in ('arm','p99_tick_nanos',
                             'process_peak_rss_bytes',
                             'mechanism_tick_throughput_per_second_milli')})
        s['comparisons'].append({'cells':cells,'arms':refs})
    return m,s


class ArchivedEvidenceReviewTests(unittest.TestCase):
    def assert_bad(self, fn, message=None):
        with self.assertRaises(g.Invalid) as e:fn()
        if message:self.assertIn(message,str(e.exception))

    def test_synthetic_original_shape_deduplicates_to_five(self):
        x=g.archived_weights(synthetic_weights())
        self.assertEqual(x['distinct_weight_digests'],5)
        self.assertEqual(x['distinct_weight_digests_by_arm'],
                         {'v2':1,'v3':1,'ssm':1,'min_gru':2})

    def test_cannot_claim_signed_a0(self):
        x=synthetic_weights();x['frozen_a0_owner_revalidation']['a0_rechecked']=True
        self.assert_bad(lambda:g.archived_weights(x),'production A0')

    def test_cannot_claim_full_f32_native_policy_parity(self):
        x=synthetic_weights();x['floating_torch_native_q24_prediction_parity_verified']=True
        self.assert_bad(lambda:g.archived_weights(x),'qualification')

    def test_missing_physical_process_or_head_integer_oracle_rejected(self):
        x=synthetic_weights();x['results'][0]['fresh_process_count']=1
        self.assert_bad(lambda:g.archived_weights(x),'native process replays')
        x=synthetic_weights();x['results'][0]['q24_head_integer_oracle'][
            'all_native_head_logits_match_independent_integer_oracle']=False
        self.assert_bad(lambda:g.archived_weights(x),'oracle')

    def test_twenty_slots_cannot_masquerade_as_twenty_distinct_weights(self):
        x=synthetic_weights();x['realized_budget_audit'][
            'effective_independent_physical_model_comparisons']=20
        self.assert_bad(lambda:g.archived_weights(x),'measured weight census')
        x=synthetic_weights();x['results'][1]['physical_artifact_sha256']=h('fake extra')
        self.assert_bad(lambda:g.archived_weights(x),'measured weight census')

    def test_duplicate_budget_slot_rejected_even_if_row_count_is_twenty(self):
        x=synthetic_weights();x['results'][1]['private_parameter_cap']=2048
        self.assert_bad(lambda:g.archived_weights(x),'duplicated physical')

    def test_valid_synthetic_cost_source_and_denial(self):
        m,s=synthetic_mechanism();rows=g.mechanism_costs(m,s)
        self.assertEqual(len(rows),20)
        d=g.resource_dominators(rows,cells=4096)
        self.assertEqual(d['v1'],[])
        self.assertIn('v1',d['v3'])

    def test_attested_target_host_must_not_be_inferred(self):
        m,s=synthetic_mechanism();m['target_host_qualified']=True
        self.assert_bad(lambda:g.mechanism_costs(m,s),'target_host_qualified')
        m,s=synthetic_mechanism();s['qualified_p99_sla']=True
        self.assert_bad(lambda:g.mechanism_costs(m,s),'qualified_p99_sla')

    def test_matrix_vs_archived_analysis_cost_drifts_rejected(self):
        m,s=synthetic_mechanism()
        s['comparisons'][0]['arms'][0]['p99_tick_nanos']+=1
        self.assert_bad(lambda:g.mechanism_costs(m,s),'cost mismatch')

    def test_duplicate_summary_scale_cannot_hide_other_scale(self):
        m,s=synthetic_mechanism()
        s['comparisons'][3]['cells'] = 1024
        self.assert_bad(lambda:g.mechanism_costs(m,s),
                        'duplicated archived cost-comparison scale')

    def test_missing_scale_and_swapped_input_trace_rejected(self):
        m,s=synthetic_mechanism();m['results'].pop()
        self.assert_bad(lambda:g.mechanism_costs(m,s),'20 mechanism-only')
        m,s=synthetic_mechanism();m['results'][0]['trace_sha256']=h('swapped trace')
        self.assert_bad(lambda:g.mechanism_costs(m,s),'drifting')

    def test_bool_or_negative_resource_measurement_rejected(self):
        m,s=synthetic_mechanism();m['results'][0]['p99_tick_nanos']=True
        self.assert_bad(lambda:g.mechanism_costs(m,s),'non-integer')
        m,s=synthetic_mechanism();m['results'][0]['process_peak_rss_bytes']=-1
        self.assert_bad(lambda:g.mechanism_costs(m,s),'out-of-range')

    def test_resource_front_only_not_utility_pareto(self):
        m,s=synthetic_mechanism();r=g.mechanism_costs(m,s)
        self.assertEqual([a for a,v in g.resource_dominators(r,cells=4096).items() if not v],['v1'])
        self.assertFalse(g.strict_json(b'{"production_qualification":false}')['production_qualification'])

    def test_duplicate_json_keys_and_nan_refused(self):
        self.assert_bad(lambda:g.strict_json(b'{"x":1,"x":2}'),'duplicated')
        self.assert_bad(lambda:g.strict_json(b'{"x":NaN}'),'nonfinite')

    def test_pinned_zip_does_not_accept_relabelled_or_corrupt_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);z=root/'archive.zip'
            with zipfile.ZipFile(z,'w') as f:f.writestr('twenty-physical-q24-native-shadow.json','{}')
            self.assert_bad(lambda:g.pinned_zip(z,'trained'),'SHA256 mismatch')
            self.assert_bad(lambda:g.pinned_zip(z,'unregistered'),'unregistered')
            link=root/'link.zip';link.symlink_to(z)
            self.assert_bad(lambda:g.pinned_zip(link,'trained'),'symlink')

    def test_cli_never_overwrites_existing_result(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'review.json';p.write_text('existing')
            proc=subprocess.run([sys.executable,str(Path(g.__file__)),
                '--trained-zip',str(p),'--mechanism-zip',str(p),'--output',str(p)],
                text=True,capture_output=True)
            self.assertNotEqual(proc.returncode,0)
            self.assertEqual(p.read_text(),'existing')

    def test_authentic_hosted_archives_when_explicitly_supplied(self):
        a=os.environ.get('HEPTA_TRAINED_Q24_ZIP')
        b=os.environ.get('HEPTA_MECHANISM_Q24_ZIP')
        if a is None and b is None:
            self.assert_bad(lambda:g.pinned_zip(Path('/definitely/missing.zip'),'trained'),
                            'missing/symlink')
            return
        self.assertTrue(a and b, 'both original ZIP paths required')
        report=g.audit(Path(a),Path(b))
        self.assertEqual(report['physical_native_shadow_census']['distinct_weight_digests'],5)
        self.assertEqual(report['resource_only_4096_undominated'],['v1'])
        self.assertFalse(report['candidate_task_quality_and_future_utility_verified'])
        self.assertFalse(report['complete_lifecycle_quality_cost_pareto_admissible'])
        self.assertFalse(report['production_model_promotion_permitted'])


if __name__ == '__main__':
    unittest.main()
