"""Complete original historical model ZIP replay and independent adversarial audit.

This suite REQUIRES two original successfully completed real-model artifacts;
run only after retrieving their exact pinned bytes. No model downloads/forwards.
"""
import copy, json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import archive_cascade_materials as owner
import archive_cascade_policy as fitter
import archive_cascade_review as auditor

class OriginalPhysicalArchiveCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hist=os.environ['HEPTA_HIST_SOURCE_ZIP']
        cls.phys=os.environ['HEPTA_REAL_PHYS_ZIP']
        cls.cal,cls.blind,cls.labels=owner.prepare(cls.hist,cls.phys)
        cls.obs=fitter.fit(cls.cal,cls.blind)
    def review(self,**updates):
        docs=dict(calibration=copy.deepcopy(self.cal),blind=copy.deepcopy(self.blind),
                  owner=copy.deepcopy(self.labels),observation=copy.deepcopy(self.obs))
        docs.update(updates)
        return auditor.audit(docs['calibration'],docs['blind'],docs['owner'],docs['observation'],
            original_zip=self.hist,physical_zip=self.phys)
    @staticmethod
    def reseal_obs(x):x['observation_id']=fitter.digest({k:v for k,v in x.items() if k!='observation_id'})
    @staticmethod
    def reseal_mat(x):x['material_id']=fitter.digest({k:v for k,v in x.items() if k!='material_id'})
    def test_real_granite_predictions_and_archived_source_replay(self):
        src,models=owner.assemble_archive(self.hist,self.phys)
        self.assertEqual(len(src),128)
        self.assertEqual(len(models['granite97']),128)
        self.assertEqual(len(models['mmbert_small']),128)
    def test_true_zip_sha256(self):
        self.assertEqual(owner.raw_sha(Path(self.hist).read_bytes()),owner.ORIGINAL_ZIP_SHA)
        self.assertEqual(owner.raw_sha(Path(self.phys).read_bytes()),owner.PHYSICAL_ZIP_SHA)
    def test_real_independent_holdout_baselines(self):
        r=self.review()['report']
        self.assertEqual(r['granite_only']['correct'],61)
        self.assertEqual(r['mmbert_only']['correct'],36)
        self.assertEqual(r['granite_only']['extra_second_stem_calls'],0)
        self.assertEqual(r['mmbert_only']['number_of_stem_forwards_estimated'],64)
    def test_model_selection_did_not_see_holdout(self):
        for p in self.obs['rules'].values():self.assertEqual(p['calibration_calls'],0)
        self.assertFalse(self.obs['selected_after_evaluation_labels'])
        self.assertNotIn('label',self.blind['rows'][0])
    def test_always_dual_has_cost_without_gain(self):
        r=self.review()['report'];self.assertEqual(r['dual_most_confident']['correct'],r['granite_only']['correct'])
        self.assertEqual(r['dual_most_confident']['number_of_stem_forwards_estimated'],128)
        self.assertGreater(r['dual_most_confident']['total_replayed_encoder_ns'],r['granite_only']['total_replayed_encoder_ns'])
    def test_fixed_margin_deteriorations_kept(self):
        r=self.review()['report'];self.assertEqual(r['fixed_margin_020']['correct'],59)
        self.assertEqual(r['fixed_margin_040']['correct'],54)
        self.assertEqual(r['fixed_margin_020']['extra_second_stem_calls'],6)
        self.assertEqual(r['fixed_margin_040']['extra_second_stem_calls'],15)
    def test_matching_random_controls(self):
        r=self.review()['report']
        for k in ('020','040'):
            self.assertEqual(r[f'fixed_margin_{k}']['extra_second_stem_calls'],r[f'random_equal_fixed_margin_{k}']['extra_second_stem_calls'])
    def test_no_new_model_execution_claim(self):
        score=self.review();self.assertFalse(score['real_pretrained_model_forward_newly_executed'])
        self.assertFalse(score['physical_joint_fallback_request_timed'])
        self.assertFalse(score['production_authorized'])
    def test_rehashed_fake_probability_rejected(self):
        obs=copy.deepcopy(self.obs)
        obs['observations']['granite_only'][0]['probability']+=.1
        self.reseal_obs(obs)
        with self.assertRaises(auditor.Invalid):self.review(observation=obs)
    def test_rehashed_original_case_id_swap_rejected(self):
        obs=copy.deepcopy(self.obs)
        obs['observations']['fallback_0'][0]['case_id']='forged'
        self.reseal_obs(obs)
        with self.assertRaises(auditor.Invalid):self.review(observation=obs)
    def test_rehashed_hide_second_encoder_cost_rejected(self):
        obs=copy.deepcopy(self.obs)
        obs['observations']['fixed_margin_020'][0]['observed_ledger_encoder_sum_ns']=1
        self.reseal_obs(obs)
        with self.assertRaises(auditor.Invalid):self.review(observation=obs)
    def test_rehashed_policy_budget_drift_rejected(self):
        obs=copy.deepcopy(self.obs)
        obs['rules']['fallback_100']['confidence_margin']=.5
        self.reseal_obs(obs)
        with self.assertRaises(auditor.Invalid):self.review(observation=obs)
    def test_rehashed_source_feature_probability_rejected(self):
        blind=copy.deepcopy(self.blind)
        blind['rows'][0]['granite_probability']+=.001
        self.reseal_mat(blind)
        with self.assertRaises(auditor.Invalid):self.review(blind=blind)
    def test_rehashed_owner_label_flip_rejected(self):
        label=copy.deepcopy(self.labels)
        key=next(iter(label['labels']));label['labels'][key]=1-label['labels'][key]
        label['owner_id']=fitter.digest({k:v for k,v in label.items() if k!='owner_id'})
        with self.assertRaises(auditor.Invalid):self.review(owner=label)
    def test_rehashed_historical_calibration_label_flip_rejected(self):
        cal=copy.deepcopy(self.cal);cal['rows'][0]['label']^=1
        self.reseal_mat(cal)
        with self.assertRaises(auditor.Invalid):self.review(calibration=cal)
    def test_missing_one_budget_arm_rejected(self):
        obs=copy.deepcopy(self.obs);obs['observations'].pop('fallback_25')
        self.reseal_obs(obs)
        with self.assertRaises(auditor.Invalid):self.review(observation=obs)
    def test_false_authority_in_observation_rejected(self):
        obs=copy.deepcopy(self.obs);obs['production_authorized']=True
        self.reseal_obs(obs)
        with self.assertRaises(auditor.Invalid):self.review(observation=obs)
    def test_false_temporal_independence_rejected(self):
        obs=copy.deepcopy(self.obs);obs['future_time_independent']=True
        self.reseal_obs(obs)
        with self.assertRaises(auditor.Invalid):self.review(observation=obs)
    def test_zero_cost_secondary_model_rejected(self):
        blind=copy.deepcopy(self.blind);blind['rows'][0]['mmbert_encoder_ns']=0
        self.reseal_mat(blind)
        with self.assertRaises(auditor.Invalid):self.review(blind=blind)
    def test_archive_one_byte_edit_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            altered=Path(tmp)/'physical.zip';raw=bytearray(Path(self.phys).read_bytes());raw[-45]^=1;altered.write_bytes(raw)
            with self.assertRaises(auditor.Invalid):auditor.original_archive(self.hist,altered)
    def test_no_source_file_reembedding_through_audit(self):
        import inspect
        self.assertNotIn('import torch',inspect.getsource(auditor))
        self.assertNotIn('AutoModel',inspect.getsource(auditor))

if __name__=='__main__':unittest.main()
