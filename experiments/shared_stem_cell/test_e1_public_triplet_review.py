"""Synthetic, nonauthorizing three-model publication reviewer fault cases."""
import copy,unittest
import e1_public_triplet_real_cpu as trainer
import e1_public_triplet_review as reviewer
from test_e1_public_triplet_real_cpu import panel
def fixture():
 import torch
 torch.set_num_threads(1)
 p=panel();reports={}
 for model,(_,revision,width) in trainer.MODELS.items():
  vectors={c['case_id']:[((int(c['case_id'][:4],16)%99)-50)/100]*width for c in p['cases']}
  fitted=trainer.fit_heads(p,model,vectors)
  reports[model]={'schema':'hepta.e1-english-public-pretrained-head.v1','model':model,
   'model_revision':revision,'feature_width':width,'public_panel_sha256':trainer.sha(trainer.canonical(p)),
   'authority':'DENY_ALL','production_promotion_permitted':False,
   'english_only':True,'public_dataset_is_chronological_future':False,
   'actual_pretrained_local_weight_execution_claimed':True,
   'model_origin_independently_authenticated':False,
   'tokens_per_case':{c['case_id']:20 for c in p['cases']},
   'features_q24_identity':{c['case_id']:'a'*64 for c in p['cases']},
   'fitting':fitted,
   'physical_transformer_forward_count_attested':False,
   'physical_observations':{'load_ms':1.0,'encode_ms_by_case':{c['case_id']:.01 for c in p['cases']},
      'local_model_api_requests':224,'physical_transformer_forward_count_attested':False,
      'mmbert_pretrained_complete_tied_table_verified':True if model=='mmbert_small' else None,
      'mmbert_local_complete_table_sha256':'b'*64 if model=='mmbert_small' else None,
      'mmbert_all_serialized_weights_byte_verified':True if model=='mmbert_small' else None,
      'mmbert_whole_pretrained_checkpoint_sha256':'c'*64 if model=='mmbert_small' else None,
      'mmbert_verified_source_tensor_count':133 if model=='mmbert_small' else None},
   'wall_ms':fitted['train_time_ms']+10.,'cpu_process_ms':fitted['train_time_ms']+1.,
   'process_lifetime_peak_rss_bytes':12345678}
 return p,reports
class Checks(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.original=fixture()
 def data(self):return copy.deepcopy(self.original)
 def deny(self,fn):
  p,arms=self.data();fn(p,arms)
  with self.assertRaises((ValueError,TypeError,KeyError)):reviewer.evaluate(p,arms)
 def test_descriptive_only(self):
  p,arms=self.data();r=reviewer.evaluate(p,arms)
  self.assertEqual(len(r['scores']),3);self.assertEqual(len(r['pairwise_test']),3)
  self.assertFalse(r['production_promotion_permitted']);self.assertFalse(r['stem_winner_selected'])
 def test_missing_model(self):self.deny(lambda p,a:a.pop('granite_97m_r2'))
 def test_panel_drift(self):self.deny(lambda p,a:a['granite_97m_r2'].update(public_panel_sha256='f'*64))
 def test_revision_drift(self):self.deny(lambda p,a:a['mmbert_small'].update(model_revision='f'*40))
 def test_parameter_ceiling(self):self.deny(lambda p,a:a['mmbert_small']['fitting'].update(head_parameter_count=9999))
 def test_training_budget(self):self.deny(lambda p,a:a['mmbert_small']['fitting'].update(steps=41))
 def test_token_missing(self):self.deny(lambda p,a:a['mmbert_small']['tokens_per_case'].pop(next(iter(a['mmbert_small']['tokens_per_case']))))
 def test_token_truncation(self):self.deny(lambda p,a:a['mmbert_small']['tokens_per_case'].__setitem__(next(iter(a['mmbert_small']['tokens_per_case'])),513))
 def test_missing_prediction(self):self.deny(lambda p,a:a['granite_97m_r2']['fitting']['controls']['learned_head']['predictions'].pop())
 def test_swapped_input(self):self.deny(lambda p,a:a['granite_97m_r2']['fitting']['controls']['learned_head']['predictions'][0].update(joint_input_digest='f'*64))
 def test_nan_probability(self):self.deny(lambda p,a:a['granite_97m_r2']['fitting']['controls']['learned_head']['predictions'][0].update(positive_probability=float('nan')))
 def test_missing_energy_or_compute_budget_not_recast_as_success(self):
  p,arms=self.data();value=reviewer.evaluate(p,arms)
  self.assertIsNone(value['resource_observations']['granite_97m_r2']['energy_joules'])
  self.assertFalse(value['same_host_total_lifecycle_budget_and_energy_verified'])
 def test_missing_encoder_latency(self):self.deny(lambda p,a:a['granite_97m_r2']['physical_observations']['encode_ms_by_case'].pop(next(iter(a['granite_97m_r2']['physical_observations']['encode_ms_by_case']))))
 def test_missing_rss(self):self.deny(lambda p,a:a['mmbert_small'].pop('process_lifetime_peak_rss_bytes'))
 def test_fabricated_physical_forward_attestation(self):self.deny(lambda p,a:a['mmbert_small'].update(physical_transformer_forward_count_attested=True))
 def test_total_wall_undercount(self):self.deny(lambda p,a:a['embeddinggemma_2_text'].update(wall_ms=0.001))
 def test_missing_complete_mmbert_model_weight_evidence(self):
  self.deny(lambda p,a:a['mmbert_small']['physical_observations'].update(mmbert_all_serialized_weights_byte_verified=False))
 def test_too_few_verified_mmbert_tensors(self):
  self.deny(lambda p,a:a['mmbert_small']['physical_observations'].update(mmbert_verified_source_tensor_count=1))
 def test_missing_pretrained_mmbert_tie_evidence(self):
  self.deny(lambda p,a:a['mmbert_small']['physical_observations'].update(mmbert_pretrained_complete_tied_table_verified=False))
 def test_fake_tie_evidence_on_granite(self):
  self.deny(lambda p,a:a['granite_97m_r2']['physical_observations'].update(mmbert_pretrained_complete_tied_table_verified=True))
 def test_false_future(self):self.deny(lambda p,a:a['granite_97m_r2'].update(public_dataset_is_chronological_future=True))
if __name__=='__main__':unittest.main()
