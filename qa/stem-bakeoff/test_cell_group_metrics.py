import unittest

import numpy as np

from cell_group_metrics import group_weighted_metrics, independent_group_weights, weighted_auc


class GroupMetricTests(unittest.TestCase):
    def test_large_candidate_group_does_not_dominate_scores_or_class_recalls(self):
        y = np.array([0, 0, 0, 0, 0, 1])
        p = np.array([[.2, .8]]*4+[[.8, .2], [.2, .8]])
        rows = [dict(group_id=g) for g in ['a']*4+['b', 'c']]
        score = group_weighted_metrics(p, y, rows)
        self.assertEqual(score['weighted_class_support'], [2, 1])
        self.assertEqual(score['per_class_recall'], [.5, 1])
        self.assertEqual(score['balanced_accuracy'], .75)
        self.assertAlmostEqual(score['forced_accuracy'], 2/3)
        self.assertAlmostEqual(score['nll'], (-np.log(.2)-2*np.log(.8))/3)
        self.assertAlmostEqual(score['brier_multiclass_sum'], (1.28+.08+.08)/3)

    def test_candidate_replication_preserves_group_metrics(self):
        p = np.array([[.8, .2], [.6, .4], [.4, .6], [.1, .9]])
        y = np.array([0, 1, 0, 1])
        groups = ['a', 'a', 'b', 'c']
        first = group_weighted_metrics(p, y, [dict(group_id=g) for g in groups])
        second = group_weighted_metrics(np.repeat(p, 5, axis=0), np.repeat(y, 5),
                                        [dict(group_id=str(g)) for g in np.repeat(groups, 5)])
        for key in ['nll', 'brier_multiclass_sum', 'balanced_accuracy', 'positive_recall',
                    'coverage', 'overall_success', 'ece10_equal_width', 'auroc']:
            self.assertAlmostEqual(first[key], second[key], places=14)

    def test_weighted_tie_auc_matches_pair_enumeration(self):
        scores = np.array([.2, .4, .4, .9, .9])
        labels, weights = np.array([0, 0, 1, 0, 1]), np.array([.5, .5, 1., .2, .8])
        total = sum(weights[i]*weights[j]*(float(scores[i] > scores[j])+.5*float(scores[i] == scores[j]))
                    for i in range(5) for j in range(5) if labels[i] == 1 and labels[j] == 0)
        expected = total/(weights[labels == 1].sum()*weights[labels == 0].sum())
        self.assertAlmostEqual(weighted_auc(scores, labels, weights), expected)

    def test_abstention_missing_class_and_group_bootstrap_denominators(self):
        p, y = np.array([[.2, .8], [.8, .2], [.2, .8]]), np.array([0, 0, 1])
        rows = [dict(group_id=g) for g in ['a', 'b', 'c']]
        none = group_weighted_metrics(p, y, rows, eligible=np.zeros(3, dtype=bool))
        self.assertEqual(none['coverage'], 0)
        self.assertEqual(none['overall_success'], 0)
        self.assertIsNone(none['selective_risk'])
        boot = group_weighted_metrics(p, y, rows, group_multiplicities={'a': 2, 'b': 0, 'c': 1})
        self.assertAlmostEqual(boot['forced_accuracy'], 1/3)
        self.assertEqual(boot['weighted_class_support'], [2, 1])
        one = group_weighted_metrics(p, y, rows, group_multiplicities={'a': 2, 'b': 1, 'c': 0})
        self.assertIsNone(one['balanced_accuracy'])
        self.assertIsNone(one['auroc'])
        with self.assertRaises(ValueError):
            independent_group_weights(rows, {'a': 0, 'b': 0, 'c': 0})


if __name__ == '__main__':
    unittest.main()
