"""Read-only synthetic adversarial panel reviewer tests."""
import copy
import unittest
from e5_sparse_sgd_review import evaluate,Invalid,SCALES,SEEDS,MODES
H='a'*64

def fixture():
    records={}
    for n in SCALES:
        a=max(8,n//10)
        records[str(n)]={}
        for seed in SEEDS:
            both={}
            for mode in MODES:
                report={'schema':'hepta.e5.sparse-packed-sgd-cpu.v1','mode':mode,
                 'authority':'DENY_ALL','production_promotion_permitted':False,
                 'pretrained_encoder_executed':False,'production_worker_executed':False,
                 'synthetic_labels_and_features':True,'independent_ndu_verified':False,
                 'p99_end_to_end_latency_verified':False,'measured_energy_joules':None,
                 'requested_logical_cells':n,'active_cell_count':a,
                 'inactive_cell_count':n-a,'seed':seed,
                 'optimizer':'torch.optim.SGD','optimizer_steps_per_active_cell':3,
                 'learning_rate':.01,'physical_feature_buffer_count':1,
                 'observed_resident_head_parameters':n*9744,
                 'measured_initialization_ms':1.,'measured_sgd_wall_ms':10. if mode=='packed' else 20.,
                 'measured_end_to_end_process_wall_ms':50.,'measured_process_cpu_ms':12.,
                 'measured_peak_rss_bytes':n*9744*4+1000000 if mode=='packed' else n*9744*4+2000000,
                 'measured_current_rss_bytes':1000000,
                 'dormant_weights_unchanged':True,
                 'dormant_bank_sha256_before':H,'dormant_bank_sha256_after':H,
                 'initial_active_weights_sha256':H,'final_active_weights_sha256':'b'*64,
                 'active_cell_index_sha256':H,'prediction_logits_sha256':'b'*64,
                 'training_loss_by_step_sum':[a*1.,a*.8,a*.7],
                 'last_step_training_loss_per_cell':.7}
                both[mode]=report
            records[str(n)][str(seed)]=both
    return records

class Tests(unittest.TestCase):
    def fail(self,fn):
        d=fixture();fn(d)
        with self.assertRaises((ValueError,TypeError,KeyError)):
            evaluate(d)
    def test_complete_never_production(self):
        r=evaluate(fixture())
        self.assertFalse(r['production_promotion_permitted'])
        self.assertEqual(len(r['scales']),4)
    def test_missing_scale(self):self.fail(lambda d:d.pop('4096'))
    def test_missing_repeat(self):self.fail(lambda d:d['1024'].pop('20261016'))
    def test_missing_mode(self):self.fail(lambda d:d['64']['20261014'].pop('packed'))
    def test_original_weight_mismatch(self):self.fail(lambda d:d['256']['20261015']['packed'].update(initial_active_weights_sha256='f'*64))
    def test_active_id_mismatch(self):self.fail(lambda d:d['4096']['20261014']['modules'].update(active_cell_index_sha256='f'*64))
    def test_dormant_drift(self):self.fail(lambda d:d['1024']['20261015']['modules'].update(dormant_bank_sha256_after='f'*64))
    def test_missing_real_update(self):self.fail(lambda d:d['64']['20261014']['packed'].update(final_active_weights_sha256=H))
    def test_missing_cpu(self):self.fail(lambda d:d['256']['20261016']['packed'].pop('measured_process_cpu_ms'))
    def test_fake_pretrained(self):self.fail(lambda d:d['4096']['20261016']['packed'].update(pretrained_encoder_executed=True))
    def test_loss_drift(self):self.fail(lambda d:d['1024']['20261014']['modules'].update(training_loss_by_step_sum=[1.,2.,3.]))
    def test_bad_label_budget(self):self.fail(lambda d:d['4096']['20261016']['packed'].update(optimizer_steps_per_active_cell=5))
    def test_wrong_cell_count(self):self.fail(lambda d:d['1024']['20261015']['modules'].update(observed_resident_head_parameters=10))
    def test_nan_mean_loss(self):self.fail(lambda d:d['1024']['20261014']['packed'].update(last_step_training_loss_per_cell=float('nan')))
    def test_underreported_resident_rss(self):self.fail(lambda d:d['4096']['20261015']['modules'].update(measured_peak_rss_bytes=1000000))
    def test_p99_forgery(self):self.fail(lambda d:d['256']['20261014']['packed'].update(p99_end_to_end_latency_verified=True))

if __name__=='__main__':unittest.main()
