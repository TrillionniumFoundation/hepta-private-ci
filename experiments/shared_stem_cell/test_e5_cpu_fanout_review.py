"""Review tests use synthetic minimal observation fields, not model validation."""
import copy,unittest
import e5_cpu_fanout_review as a

def fixture():
    out={}
    for n in a.SCALES:
        active=max(8,n//10); rows={}
        for arm in a.CASES:
            if arm=='packed_inference':
                rows[arm]={'schema':'hepta.e5.packed-physical-cpu-head-v1','logical_cells':n,'active_cells':active,
                  'seed':20261014,'complete_head_parameters':n*9744,'measured_peak_rss_bytes':1000000,
                  'authority':'DENY_ALL','production_promotion_permitted':False,'pretrained_encoder_executed':False,
                  'production_worker_verified':False,'p99_independently_qualified':False,'batch_repeats':20,
                  'batch_forward_samples':20,'physical_head_weight_tensors':6,'physical_input_feature_buffers':1,
                  'per_cell_equivalent_loop_ms_mean':.01,'power_or_gpu_evidence':None}
            else:
                steps=1 if arm.endswith('sgd') else 0;reps=2 if steps else 20
                numbuffers=active if arm=='cloned_sgd' else 1
                rows[arm]={'schema':'hepta.e5-local-cpu-head-fanout.v1','logical_cells':n,'active_cells':active,
                  'seed':20261014,'physical_cell_head_parameters':n*9744,'observed_process_lifetime_peak_rss_bytes':2000000,
                  'authority':'DENY_ALL','production_promotion_permitted':False,
                  'actual_pretrained_encoder_forward':False,'production_worker_or_ndu_verified':False,
                  'real_pytorch_cpu_head_forward':True,'synthetic_input_and_labels':True,'per_head_parameters':9744,
                  'synthetic_feature_producer_count':1,'train_steps_per_active_cell':steps,'serving_repeats':reps,
                  'raw_sample_count':active*reps,'heads_with_changed_weights':active*steps,
                  'physical_feature_buffer_count':numbuffers,'resident_feature_tensor_payload_bytes':numbuffers*384*4,
                  'measured_serving_loop_wall_ms':active*reps*.03,'measured_training_loop_wall_ms':steps*.01,
                  'synthetic_feature_q24_sha256':'a'*64,'sampled_f32_prediction_sha256':'b'*64,
                  'hardware_energy_joules':None}
        out[str(n)]=rows
    return out

class Tests(unittest.TestCase):
    def deny(self,fn):
        f=fixture();fn(f)
        with self.assertRaises((a.Invalid,ValueError,TypeError,KeyError)):a.examine(f)
    def test_complete_panel_is_never_production(self):
        r=a.examine(fixture());self.assertEqual(len(r['scales']),4)
        self.assertFalse(r['production_promotion_permitted'])
    def test_no_missing_4096(self):self.deny(lambda x:x.pop('4096'))
    def test_no_forged_power(self):self.deny(lambda x:x['64']['packed_inference'].update(power_or_gpu_evidence=1))
    def test_no_unpaired_activation(self):self.deny(lambda x:x['4096']['shared_inference'].update(active_cells=8))
    def test_no_fake_sgd_steps(self):self.deny(lambda x:x['64']['shared_sgd'].update(heads_with_changed_weights=0))
    def test_no_fake_feature_buffer_copy(self):self.deny(lambda x:x['1024']['cloned_sgd'].update(physical_feature_buffer_count=1))
    def test_no_fake_prediction_digest(self):self.deny(lambda x:x['64']['cloned_sgd'].update(sampled_f32_prediction_sha256='f'*64))
    def test_no_forged_pretrained_encoder(self):self.deny(lambda x:x['256']['shared_sgd'].update(actual_pretrained_encoder_forward=True))
    def test_no_fake_p99_claim(self):self.deny(lambda x:x['4096']['packed_inference'].update(p99_independently_qualified=True))
    def test_no_tampered_cell_parameter_count(self):self.deny(lambda x:x['1024']['packed_inference'].update(complete_head_parameters=123))

if __name__=='__main__':unittest.main()
