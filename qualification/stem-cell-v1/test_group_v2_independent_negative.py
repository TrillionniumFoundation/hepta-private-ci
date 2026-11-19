"""Original three-seed pinned Granite Group metrics: independent numeric audit.

The original source is a committed real pretrained-Encoder research summary,
NOT the original offline raw evidence ZIP. Original raw model proof and future
efficacy remain separate unfulfilled evidence gates.
"""
import copy
from pathlib import Path
import unittest
import group_v2_independent_negative as g

ORIGINAL = Path(__file__).with_name('GROUP_REASONING_V2_3SEED_20261015.json')


class OriginalGroupAggregateAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.actual = g.read_original(ORIGINAL)
        cls.replayed = g.review(cls.actual)

    def test_original_8_arms_3_real_pretrained_training_seeds(self):
        x = self.replayed
        self.assertEqual(len(x['run_seeds']),3)
        self.assertEqual(x['task_observations_per_arm'],288)
        self.assertTrue(x['actual_three_seed_training_summary_rechecked'])
        self.assertTrue(x['split_candidates_all_rejected'])
        self.assertFalse(x['model_or_NDU_promotion_permitted'])

    def test_original_online_versus_static_cpu_and_quality_not_winner(self):
        x=self.replayed
        self.assertEqual(x['split_test_correct_delta_vs_static'],0)
        self.assertEqual(x['ndu_test_correct_delta_vs_static'],-5)
        self.assertAlmostEqual(x['split_online_cpu_ratio_vs_static'],6.762576209,places=8)
        self.assertAlmostEqual(x['ndu_online_cpu_ratio_vs_static'],2.952170064,places=8)
        self.assertFalse(x['learning_or_split_winner_certified'])

    def test_three_physical_encoder_forward_counts_reconciled(self):
        x=self.replayed['original_encoder']
        self.assertEqual(x['physical_forwards'],2267)
        self.assertEqual(x['logical_requests'],2496)
        self.assertEqual(x['logical_minus_physical_forwards'],229)
        self.assertFalse(x['complete_flops_known'])
        self.assertFalse(x['cache_bytes_are_peak_rss'])

    def test_original_full_three_seed_train_parameter_inventory(self):
        x=self.replayed['original_training']
        self.assertEqual(x['core']['parameters'],19112)
        self.assertEqual(x['split']['parameters'],22474)
        self.assertEqual(x['static']['parameters'],3152)
        self.assertEqual(x['wide']['parameters'],19265)
        self.assertEqual({role:v['steps'] for role,v in x.items()},
                         {role:360 for role in g.ROLES})

    def test_qualified_original_json_blob_tamper_denied(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'changed.json'
            p.write_bytes(ORIGINAL.read_bytes()+b' ')
            with self.assertRaises(g.Denied):g.read_original(p)

    def test_original_declared_aggregate_forgery_denied(self):
        x=copy.deepcopy(self.actual);x['aggregate_test']['ndu']['correct']+=1
        with self.assertRaises(g.Denied):g.review(x)
        x=copy.deepcopy(self.actual);x['aggregate_test']['split']['cpu_ns']-=1
        with self.assertRaises(g.Denied):g.review(x)

    def test_source_family_and_native_computation_forgery_denied(self):
        for edit in [('native_reference_match',False),('split_decision','promote'),
                     ('encoder_complete_formula_flops',999)]:
            x=copy.deepcopy(self.actual);x['runs']['47'][edit[0]]=edit[1]
            with self.subTest(field=edit[0]),self.assertRaises(g.Denied):g.review(x)

    def test_missing_old_task_seed_and_added_arm_denied(self):
        x=copy.deepcopy(self.actual);x['runs'].pop('53')
        with self.assertRaises(g.Denied):g.review(x)
        x=copy.deepcopy(self.actual);x['runs']['41']['test']['not_original']=x['runs']['41']['test']['static']
        with self.assertRaises(g.Denied):g.review(x)

    def test_false_efficacy_and_equal_compute_claim_denied(self):
        for field,value in [('learned_reasoning_emergence_established',True),
                            ('natural_future_efficacy',True),
                            ('equal_compute',True),
                            ('all_split_candidates_rejected',False)]:
            x=copy.deepcopy(self.actual);x[field]=value
            with self.subTest(field=field),self.assertRaises(g.Denied):g.review(x)

    def test_original_training_steps_and_source_pins_immutable(self):
        x=copy.deepcopy(self.actual);x['runs']['41']['training']['split']['completed_steps']=40
        with self.assertRaises(g.Denied):g.review(x)
        x=copy.deepcopy(self.actual);x['runs']['47']['source_sha256']['group_loop.py']='f'*64
        with self.assertRaises(g.Denied):g.review(x)

    def test_missing_encoder_operator_floats_do_not_silently_certify_flops(self):
        x=copy.deepcopy(self.actual);x['runs']['53']['encoder_unknown_operators']={}
        with self.assertRaises(g.Denied):g.review(x)
        self.assertTrue(self.replayed['inference_online_cpu_excludes_encoder_training_critic'])
        self.assertFalse(self.replayed['equal_full_lifecycle_compute'])
        self.assertFalse(self.replayed['unobserved_model_10t_100t_equivalence'])


if __name__=='__main__': unittest.main()
