import copy
import unittest
from fair_ablation import ARMS,check_matched
from multimodal_gate import check_pairs
from native_gate import check_hardware


def fake_rows():
    # Synthetic metadata to exercise rejection and matching logic ONLY.
    rows=[]
    for seed in (11,23,37,41,59):
        for arm in ARMS:
            rows.append({'seed':seed,'arm':arm,
                         'train_set_sha256':'1'*64,'holdout_set_sha256':'2'*64,
                         'information_sha256':'3'*64,'encoder_sha256':'4'*64,
                         'parameter_count':1024,'local_slope_norm':1.,
                         'train_tokens':4096,'train_flops':1e8,
                         'hyperparameter_search_trials':20,
                         'quality':.5,'inference_flops':1e5,
                         'training_joules':1000.,'peak_rss_bytes':1e8})
    return rows


class PreRegistration(unittest.TestCase):
    def test_factorial_arms_and_all_seeds_present(self):
        r=check_matched(fake_rows(),(11,23,37,41,59))
        self.assertTrue(r['metadata_comparable'])
        self.assertFalse(r['production_evidence_accepted'])
        self.assertEqual(set(r['exploratory_paired_deltas']),set(ARMS)-{'control'})

    def test_mismatched_information_rejected(self):
        x=fake_rows()
        x[5]['information_sha256']='5'*64
        self.assertFalse(check_matched(x,(11,23,37,41,59))['metadata_comparable'])

    def test_wrong_slope_wrong_budget_rejected(self):
        x=fake_rows()
        x[5]['local_slope_norm']=1.15
        x[5]['train_tokens']=2048
        msg=' '.join(check_matched(x,(11,23,37,41,59))['issues'])
        self.assertIn('local_slope_norm',msg)
        self.assertIn('train_tokens',msg)

    def test_missing_arm_rejected(self):
        x=fake_rows()
        x.pop()
        self.assertFalse(check_matched(x,(11,23,37,41,59))['metadata_comparable'])


class MultiModal(unittest.TestCase):
    def test_entity_and_scene_holdout_leak_rejected(self):
        sample=lambda sid,sp:{'sample_id':sid,'entity_id':'same-person',
                             'scene_id':'same-scene','split':sp,
                             't_start_sec':0.,'t_end_sec':2.,
                             'asset_sha256':{'text':'1'*64,'image':'2'*64,
                                             'audio':'3'*64,'video':'4'*64},
                             'provenance':'synthetic TEST ONLY'}
        result=check_pairs([sample('s1','train'),sample('s2','holdout')])
        self.assertFalse(result['metadata_valid'])
        self.assertTrue(any('entity leaks' in issue for issue in result['failures']))

    def test_missing_audio_rejected(self):
        row={'sample_id':'s1','entity_id':'e1','scene_id':'scene1','split':'holdout',
             't_start_sec':0.,'t_end_sec':1.,'provenance':'synthetic TEST ONLY',
             'asset_sha256':{'text':'1'*64,'image':'2'*64,'video':'4'*64}}
        self.assertFalse(check_pairs([row])['metadata_valid'])


class PhysicalMeasurements(unittest.TestCase):
    def test_missing_all_scales_fail_closed(self):
        result=check_hardware([])
        self.assertFalse(result['metadata_complete'])
        self.assertEqual(len(result['issues']),4)
        self.assertFalse(result['production_evidence_accepted'])

    def test_stub_kernel_rejected(self):
        result=check_hardware([{'cells':64, 'real_kernel':'dummy'}])
        self.assertFalse(result['metadata_complete'])

if __name__=='__main__':unittest.main()
