"""Mechanism fixtures: no real learned model or newly untouched future cohort."""
import copy
import math
import unittest
from exploratory_temperature_probe import probe, scale_probability, ReviewError
from test_paired_independent_audit import trial


class ExploratoryCalibration(unittest.TestCase):
    def test_source_probabilities_and_scope_remain_immutable(self):
        objects = trial()
        original = copy.deepcopy(objects)
        out = probe(*objects)
        self.assertEqual(objects, original)
        self.assertEqual(out['production_promotion'], 'DENY_ALL')
        self.assertFalse(out['confirmatory_future_window_tested'])
        self.assertTrue(out['test_distribution_already_reviewed_by_researcher'])
        self.assertFalse(out['model_weights_or_selected_head_mutated'])
        self.assertIn(out['selected_logit_multiplier'], out['candidate_scale_grid'])
        self.assertEqual(out['raw_test']['cases'], 64)
        self.assertEqual(out['raw_calibration']['cases'], 32)

    def test_test_labels_do_not_change_calibration_selection(self):
        objects = trial()
        previous = probe(*objects)['selected_logit_multiplier']
        # Changing test truth also changes the dataset digest. Rebuild the
        # synthetic comparison around a new panel, keeping calibration intact.
        import agnews_paired_shadow
        for row in objects[0]['cases']:
            if row['split'] == 'test':
                row['label'] = 1-row['label']
                row['label_name'] = row['joint_input']['options'][row['label']]
        new_digest,_=agnews_paired_shadow.check_panel(objects[0])
        objects[1]['panel_digest']=new_digest
        objects[1]['counts_by_split_label']={f'{s}/{y}':sum(x['split']==s and x['label']==y for x in objects[0]['cases']) for s in ('train','calibration','test') for y in (0,1)}
        for r in [*objects[2],objects[3]]: r['panel_digest']=new_digest
        objects[4]=agnews_paired_shadow.compare(objects[0],[*objects[2],objects[3]])
        self.assertEqual(probe(*objects)['selected_logit_multiplier'],previous)

    def test_nonfinite_degenerate_and_unreviewed_scale_fail_closed(self):
        for p,alpha in ((0.0,1),(1.0,1),(float('nan'),1),(0.5,3)):
            with self.subTest(p=p,alpha=alpha),self.assertRaises(ReviewError):
                scale_probability(p,alpha)

    def test_monotone_transform_keeps_binary_rank(self):
        for alpha in (1,64,512,1024):
            seq=[scale_probability(p,alpha) for p in (.1,.49,.5,.51,.9)]
            self.assertEqual(seq,sorted(seq))
            self.assertTrue(all(0<p<1 for p in seq))


if __name__=='__main__':
    unittest.main()
