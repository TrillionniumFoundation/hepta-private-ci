import copy
import unittest
from head_only_physical import run
from head_panel_audit import audit_panel,_per


def valid():
    x=[run(n,trials=3,seed=19) for n in (64,256,1024,4096)]
    return x

class HeadPanelAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v=valid()
    def test_all_scales_shadow_only(self):
        r=audit_panel(self.v)
        self.assertTrue(r['structurally_consistent'])
        self.assertFalse(r['complete_neuron_p1_qualified'])
        self.assertFalse(r['pretrained_stem_executed'])
        self.assertFalse(r['independent_host_attested'])
    def test_missing_size_reject(self):
        with self.assertRaises(ValueError): audit_panel(self.v[:-1])
    def test_duplicate_size_reject(self):
        with self.assertRaises(ValueError): audit_panel(self.v[:-1]+self.v[:1])
    def test_fabricated_latency_reject(self):
        v=copy.deepcopy(self.v);v[0]['batch_wall_p50_ns']+=1
        with self.assertRaises(ValueError): audit_panel(v)
    def test_fabricated_future_p99_reject(self):
        v=copy.deepcopy(self.v);v[1]['batch_wall_p99_ns']=123
        with self.assertRaises(ValueError): audit_panel(v)
    def test_over_claimed_real_encoder_reject(self):
        v=copy.deepcopy(self.v);v[2]['pretrained_stem_executed']=True
        with self.assertRaises(ValueError): audit_panel(v)
    def test_mixed_source_reject(self):
        v=copy.deepcopy(self.v);v[0]['execution_source_sha256']='a'*64
        with self.assertRaises(ValueError): audit_panel(v)
    def test_changed_input_reject(self):
        v=copy.deepcopy(self.v);v[1]['synthetic_shared_feature_sha256']='b'*64
        with self.assertRaises(ValueError): audit_panel(v)
    def test_weights_count_reject(self):
        v=copy.deepcopy(self.v);v[3]['physical_fp32_head_weight_bytes']-=4
        with self.assertRaises(ValueError): audit_panel(v)
    def test_missing_duration_reject(self):
        v=copy.deepcopy(self.v);v[0]['batch_wall_raw_ns'].pop()
        with self.assertRaises(ValueError): audit_panel(v)
    def test_q99_nearest_rank(self):
        self.assertEqual(_per(list(range(1,101)),.99),99)

if __name__=='__main__':unittest.main()
