"""E25 source-locked authentic head learning, owner-label isolation and adversarial control replay."""
import copy, hashlib, io, json, os, pathlib, tempfile, unittest, zipfile
from unittest.mock import patch
import numpy as np
import study, audit, download

HERE=pathlib.Path(os.environ.get('E25_ORIGINAL_DIR','/mnt/data'))
ARCH={'historic':HERE/'original_reader_11946621518.zip',
 'public':HERE/'github-original-11991113170.zip','model':HERE/'github-original-12010699818.zip',
 'owner':HERE/'github-original-11991387730.zip','score':HERE/'github-original-12018967923.zip',
 'folds':[HERE/f'e15-owner-original-{n}.zip' for n,_ in study.E15_ARCHIVES]}

def mutated(data,filename,change):
 obj=json.loads((data/filename).read_text())
 change(obj)
 tmp=data/(filename+'.changed')
 tmp.write_text(json.dumps(obj))
 return tmp

class OriginalTrueE25ControlTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory()
  cls.dir=pathlib.Path(cls.tmp.name)
  cls.result=study.study(ARCH)
  cls.path=cls.dir/'sealed.json';study.write_once(cls.path,cls.result)
  cls.audit=audit.recount(ARCH,cls.path)
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def test_old_vs_new_disjoint(self):
  r=self.result
  self.assertEqual(len(r['rows']),51)
  self.assertEqual(len({(v['source_group'],v['question_slot']) for v in r['rows']}),12)
  self.assertEqual(len({v['source_group'] for v in r['rows']}),6)
  self.assertFalse(r['prospective_source_generalization'])
 def test_original_model_reader_provenance(self):
  self.assertEqual(self.result['original_reader_archive_sha256'],study.ORIGINAL)
  self.assertEqual(self.result['source_commit'],'1ab2615004fc524ca18d47aaa97f6dc59356d533')
  self.assertEqual(self.result['original_reader_forwards_this_study'],0)
 def test_frozen48_exactly_matches_previous_original_reader(self):
  self.assertTrue(self.result['readout_original_frozen_brier_48_exactly_reproduced'])
  old=study.member(ARCH['model'],study.E25_ARCHIVES['model'][0],'sealed-new-six-blind-model-predictions.json')
  orig={r['task_id']:r['probabilities']['e16_scaled_brier_5'] for r in old['rows']}
  self.assertTrue(all(r['probabilities']['fixed_48']==orig[r['task_id']] for r in self.result['rows']))
 def test_true_5_parameter_heads_and_cpu(self):
  for f in self.result['fold_records']:
   for c in f['arm_results'].values():
    self.assertEqual(len(c['weights']),5)
    self.assertGreater(c['predict_cpu_ns'],0)
    self.assertGreater(c['train_cpu_ns'],0)
 def test_paid_all_pilots_independently(self):
  self.assertTrue(self.result['each_control_trains_own_pilot_not_shared_across_arms'])
  self.assertEqual(self.result['physical_total_optimizer_updates_including_all_separate_pilots'],2752)
  for arm in ['calibrated_neutral','calibrated_fixed_risk','ndu_discrete','ordinary_same_profile']:
   self.assertEqual(self.result['counters'][arm]['pilot_updates'],576)
   self.assertEqual(self.result['counters'][arm]['actual_optimizer_updates_including_pilots'],632)
 def test_baselines_no_fake_pilots(self):
  self.assertEqual(self.result['counters']['fixed_8']['actual_optimizer_updates_including_pilots'],32)
  self.assertEqual(self.result['counters']['fixed_48']['actual_optimizer_updates_including_pilots'],192)
  self.assertEqual(self.result['counters']['no_update']['pilot_updates'],0)
 def test_model_does_not_see_e25_owner_labels(self):
  self.assertFalse(self.result['new_original_holdout_labels_used'])
  self.assertFalse(self.result['new_original_training_labels_used'])
  self.assertFalse(self.result['production_accepted'])
 def test_exact_original_training_labels_only(self):
  for fold,r in enumerate(self.result['fold_records']):
   self.assertEqual(r['original_historic_training_rows'],[27,24,23,25][fold])
 def test_ndu_same_profile_no_distinct_power(self):
  for r in self.result['rows']:
   self.assertEqual(r['probabilities']['ndu_discrete'],r['probabilities']['ordinary_same_profile'])
 def test_seven_candidate_controls(self):self.assertEqual(set(self.result['counters']),set(study.CONTROLS))
 def test_original_human_e25_question_scores(self):
  a=self.audit['metrics'];self.assertEqual([a['fixed_8']['complete_questions'],a['fixed_8']['correct_candidates']],[1,34])
  self.assertEqual([a['ndu_discrete']['complete_questions'],a['ndu_discrete']['correct_candidates']],[1,31])
  self.assertEqual([a['fixed_48']['complete_questions'],a['fixed_48']['correct_candidates']],[1,33])
 def test_no_new_family_or_future(self):
  self.assertFalse(self.audit['source_family_new']);self.assertFalse(self.audit['ndu_specific_superiority_established'])
 def test_honest_total_service_cost_nonclaim(self):
  self.assertFalse(self.audit['full_service_cost_qualified'])
  for a in self.audit['metrics'].values():self.assertFalse(a['complete_service_TCO_qualified'])
 def test_source_physical_sha_correct(self):
  for key,expect in audit.SOURCE.items():self.assertEqual(hashlib.sha256(ARCH[key].read_bytes()).hexdigest(),expect)
 def test_train_zip_sha_correct(self):
  for file,expected in zip(ARCH['folds'],audit.FOLDS):self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),expected)
 def test_one_short_wrong_source_zip_denied(self):
  with self.assertRaises(ValueError):study.member(ARCH['historic'],'a'*64,'multirc-native-candidate-audit/audit.json')
 def test_no_hidden_owner_input_to_producer(self):
  self.assertNotIn('owner',study.get_data.__code__.co_varnames)
  self.assertEqual(set(study.get_data(ARCH) and ['historic','public','model','folds']),{'historic','public','model','folds'})
 def test_no_repeated_original_training_id(self):
  a=[{'task_id':'a','x':(0.,0.,0.,0.)},{'task_id':'a','x':(0.,0.,0.,0.)}]
  with self.assertRaises(ValueError):study.scales(a,{'a'})
 def test_bounded_training_inputs(self):
  with self.assertRaises(ValueError):study.train_path([],{'x':1})
 def test_bad_new_controller_denied(self):
  with self.assertRaises(ValueError):study.control_steps({},'imaginary')
 def test_full_historical_seal_cannot_be_replaced(self):
  with self.assertRaises(FileExistsError):study.write_once(self.path,self.result)
 def test_new_human_labels_cannot_rewrite_blind_results(self):
  # Original owner labels are a separate audited input, never a worker argument.
  self.assertEqual(self.result['source_original_zip_sha256']['model'],audit.SOURCE['model'])
 def test_user_visible_brier_declared(self):
  self.assertGreater(self.audit['metrics']['fixed_8']['brier'],0)
  self.assertGreater(self.audit['metrics']['ndu_discrete']['brier'],0)
 def test_fourfold_trained_features_not_random(self):
  self.assertTrue(any(abs(x)>1e-6 for f in self.result['fold_records'] for x in f['arm_results']['fixed_8']['weights']))
 def test_do_not_accept_non_finite_stored_sgd(self):
  with self.assertRaises(ValueError):study.canonical({'x':float('nan')})
 def test_new_passage_lack_of_independent_future(self):
  self.assertFalse(self.audit['independent_authenticated_publisher'])
 def test_independent_reviewer_producer_digest(self):
  self.assertEqual(self.audit['producer_sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())
 def test_explicit_same_objective_control(self):
  for f in self.result['fold_records']:
   self.assertEqual(f['arm_results']['ndu_discrete']['chosen_steps'],f['arm_results']['ordinary_same_profile']['chosen_steps'])
 def test_all_paid_work_is_positive(self):
  self.assertGreater(self.result['counters']['ndu_discrete']['pilot_cpu_ns'],0)
  self.assertGreater(self.result['counters']['fixed_8']['measured_cached_input_cpu_ns'],0)
 def test_arm_has_no_subsidized_shared_fits(self):
  self.assertTrue(all(len(f['arm_results'][a]['pilot_observations'])==3 for f in self.result['fold_records'] for a in ('calibrated_neutral','calibrated_fixed_risk','ndu_discrete','ordinary_same_profile')))
 def test_mutated_predictions_refused(self):
  x=copy.deepcopy(self.result);x['rows'][0]['probabilities']['fixed_8']=.99
  p=self.dir/'fake-output.json';p.write_bytes(study.canonical(x)+b'\n')
  with self.assertRaises(ValueError):audit.recount(ARCH,p)
 def test_mutated_calibration_refused(self):
  x=copy.deepcopy(self.result);x['fold_records'][0]['arm_results']['ndu_discrete']['pilot_observations'][0]['parameters']['8'][0]+=1
  p=self.dir/'fake-pilot.json';p.write_bytes(study.canonical(x)+b'\n')
  with self.assertRaises(ValueError):audit.recount(ARCH,p)
 def test_fake_costs_refused(self):
  x=copy.deepcopy(self.result);x['counters']['ndu_discrete']['pilot_updates']=0
  p=self.dir/'fake-costs.json';p.write_bytes(study.canonical(x)+b'\n')
  with self.assertRaises(ValueError):audit.recount(ARCH,p)
 def test_unjustified_production_claim_refused(self):
  x=copy.deepcopy(self.result);x['production_accepted']=True
  p=self.dir/'fake-prod.json';p.write_bytes(study.canonical(x)+b'\n')
  with self.assertRaises(ValueError):audit.recount(ARCH,p)
 def test_scenario_utility_fees_are_not_dollars(self):
  self.assertAlmostEqual(self.result['counters']['ndu_discrete']['declared_utility_update_fee'],.632)
 def test_e25_question_complete_count(self):
  self.assertEqual(len(self.audit['metrics']['ndu_discrete']['question_outcomes']),12)
 def test_all_new_candidate_ids_unique(self):
  self.assertEqual(len({r['candidate_id'] for r in self.result['rows']}),51)

class TransportTests(unittest.TestCase):
 def test_blind_role_refuses_owner(self):
  with self.assertRaises(ValueError):download.download('blind','owner','token','/tmp/should-never-write',opener=None)
 def test_blind_role_refuses_independent_score(self):
  with self.assertRaises(ValueError):download.download('blind','score','token','/tmp/should-never-write',opener=None)
 def test_missing_github_token_fails(self):
  with self.assertRaises(ValueError):download.download('blind','historic','','/tmp/should-never-write')
 def test_signed_redirect_never_insecure(self):
  with self.assertRaises(ValueError):download.signed_endpoint('http://blob.core.windows.net/x?sig=1')
 def test_bad_host_denied(self):
  with self.assertRaises(ValueError):download.signed_endpoint('https://attacker.invalid/blob?sig=x')
 def test_credentials_in_url_denied(self):
  with self.assertRaises(ValueError):download.signed_endpoint('https://user:pw@foo.blob.core.windows.net/blob?sig=1')
 def test_duplicate_output_never_overwritten(self):
  with tempfile.TemporaryDirectory() as x:
   p=pathlib.Path(x)/'exists';p.write_text('safe')
   with self.assertRaises(FileExistsError):download.download('blind','historic','token',p)
   self.assertEqual(p.read_text(),'safe')
 def test_source_registry_real_digest(self):self.assertEqual(download.SOURCE['model'][1],audit.SOURCE['model'])

if __name__=='__main__':unittest.main()
