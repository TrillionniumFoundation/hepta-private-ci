import copy
from fractions import Fraction as F
import unittest
from four_gate_common import digest
from fbsde_design import (independent_cases, label_cases, balanced_target_posterior,
                         source_census, stratified_metrics)
from fbsde_encoder_cases import decode_probability


class DesignTests(unittest.TestCase):
    def rows(self):
        return [{'id':f'u{i}', 'intent':i%4} for i in range(24)]

    def test_generator_does_not_accept_label_channels(self):
        with self.assertRaisesRegex(ValueError, 'ID-only'):
            independent_cases(self.rows(), 'test', 12, 17)

    def test_public_questions_invariant_under_label_permutation(self):
        rows = self.rows(); ids = [{'id':r['id']} for r in rows]
        before = independent_cases(ids, 'test', 80, 19)
        labels = label_cases(before, rows)
        changed = [{**r, 'intent':(r['intent']+1)%4} for r in rows]
        after = independent_cases([{'id':r['id']} for r in changed], 'test', 80, 19)
        self.assertEqual(before, after)
        self.assertNotEqual(labels, label_cases(after, changed))

    def test_ordering_is_not_a_covert_label_channel(self):
        ids = [{'id':r['id']} for r in self.rows()]
        self.assertEqual(independent_cases(ids, 'test', 12, 2),
                         independent_cases(list(reversed(ids)), 'test', 12, 2))

    def test_legacy_bayes_correction_matches_joint_probability(self):
        for q in [F(0), F(1,10), F(1,4), F(1,2), F(9,10), F(1)]:
            expected = q*F(1,2)/(q*F(1,2)+(1-q)*F(1,6))
            self.assertAlmostEqual(balanced_target_posterior(float(q)), float(expected))
        self.assertEqual(balanced_target_posterior(.25), .5)

    def test_nonfinite_belief_rejected(self):
        for q in [float('nan'), float('inf'), -.01, 1.01, True]:
            with self.assertRaises(ValueError): balanced_target_posterior(q)

    def test_shared_source_merges_transitively(self):
        rows = [{'case_id':'a','utterance_ids':['1','2']},
                {'case_id':'b','utterance_ids':['3','4']},
                {'case_id':'c','utterance_ids':['2','3']}]
        report = source_census(rows, {str(i):digest(i) for i in range(1,5)})
        self.assertEqual(report['source_connected_components'], 1)
        self.assertEqual(report['component_case_counts'], [3])
        self.assertFalse(report['iid_case_confidence_intervals_permitted'])

    def test_aliases_do_not_invent_new_sources(self):
        rows = [{'case_id':'a','utterance_ids':['1']},{'case_id':'b','utterance_ids':['2']}]
        report = source_census(rows, {'1':digest('x'),'2':digest('x')})
        self.assertEqual(report['unique_source_texts'], 1)
        self.assertEqual(report['maximum_cases_per_source'], 2)

    def test_stratum_single_class_does_not_get_fake_balanced_accuracy(self):
        rows = independent_cases([{'id':r['id']} for r in self.rows()], 'test', 4, 7)
        truths = {r['case_id']:False for r in rows}
        predictions = [{'case_id':r['case_id'],'probability':.1,'text':decode_probability(.1)} for r in rows]
        report = stratified_metrics(predictions, truths, rows)
        self.assertTrue(all(m['balanced_accuracy'] is None for m in report.values()))
        self.assertTrue(all(m['decoded_exact_accuracy']==1 for m in report.values()))

    def test_bounds_and_duplicate_ids(self):
        ids = [{'id':r['id']} for r in self.rows()]
        for split,count,seed in [('x',1,2),('test',0,2),('test',1,-1)]:
            with self.assertRaises(ValueError): independent_cases(ids,split,count,seed)
        with self.assertRaises(ValueError): independent_cases(ids+[ids[0]],'test',1,2)

if __name__ == '__main__': unittest.main()
