import copy
import unittest
from raw_trace_guard import check_raw_traces
from backbone_budget import check_backbone,COSTS

class NativeTraceGate(unittest.TestCase):
    def test_requires_real_cpu_gpu_64_to_4096(self):
        r=check_raw_traces([])
        self.assertFalse(r['structurally_comparable'])
        self.assertEqual(sum('missing true native trace' in x for x in r['issues']),8)

    def test_raw_p99_recompute_refuses_fabricated_summary(self):
        vals=[1.0]*999+[1000.0]
        record={'cells':64,'kernel':'rust_cpu','source_sha':'a'*40,
                'model_sha256':'b'*64,'input_sha256':'c'*64,
                'hardware_manifest_sha256':'d'*64,
                'latency_ms_samples':vals,'elapsed_seconds':2.,
                'completed_events':1000,'p95_ms':1.,'p99_ms':300.,
                'throughput_events_s':500., 'peak_rss_bytes':1048576,
                'cpu_util_percent':40.,'gpu_util_percent':0.,'gpu_peak_bytes':0,
                'energy':{'meter_type':'rapl','meter_scope':'whole_node',
                          'calibration_sha256':'e'*64,'gross_joules':12.,
                          'idle_joules':2.,'net_joules':10.},
                'fault_receipts':{'mid_batch_crash':'a'*64,
                                  'corrupt_checkpoint':'b'*64,
                                  'old_generation_replay':'c'*64}}
        r=check_raw_traces([record])
        self.assertFalse(r['structurally_comparable'])
        self.assertTrue(any('p99_ms disagrees' in x for x in r['issues']))
        record['p99_ms']=r['recomputed'][0]['recomputed_p99_ms']
        self.assertFalse(check_raw_traces([record])['production_evidence_accepted'])

class BackboneFairness(unittest.TestCase):
    def _rows(self):
        rows=[]
        for seed in (1,2,3):
            for model in ('hcsn','transformer','ssm'):
                rows.append({'task':'mqar','seed':seed,'model':model,
                             'train_sha256':'1'*64,'holdout_sha256':'2'*64,
                             'max_training_tokens':1000,'max_training_flops':1e8,
                             'actual_training_flops':8e7,'hparam_trial_budget':10,
                             'quality':.92 if model=='hcsn' else .90,
                             'p99_ms':10.,
                             'costs_joules':{k:100. if model=='hcsn' else 200.
                                              for k in COSTS}})
        return rows

    def test_missing_cost_component_denies(self):
        rows=self._rows();del rows[0]['costs_joules']['cleanup']
        r=check_backbone(rows,['mqar'],[1,2,3])
        self.assertFalse(r['metadata_matched'])
        self.assertTrue(any('unmeasured/negative cost cleanup' in x for x in r['issues']))

    def test_mismatch_and_budget_overrun_denied(self):
        rows=self._rows();rows[1]['holdout_sha256']='3'*64
        rows[2]['actual_training_flops']=1.1e8
        r=check_backbone(rows,['mqar'],[1,2,3])
        self.assertFalse(r['metadata_matched'])
        self.assertTrue(any('mismatched holdout_sha256' in x for x in r['issues']))
        self.assertTrue(any('exceeded FLOP budget' in x for x in r['issues']))

    def test_perfect_synthetic_metadata_still_not_production_evidence(self):
        r=check_backbone(self._rows(),['mqar'],[1,2,3])
        self.assertTrue(r['metadata_matched'])
        self.assertTrue(r['exploratory_paired_effects']['mqar:ssm']['all_seeds_better_quality'])
        self.assertFalse(r['production_evidence_accepted'])
        self.assertFalse(r['tuned_baseline_attestation'])

if __name__=='__main__':unittest.main()
