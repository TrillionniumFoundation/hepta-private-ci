import tempfile
import unittest

import numpy as np

from coverage_retrieval import CoverageRetrieval
from fit_input_coverage import balanced_order, labels_for
from prepare_input_coverage import TASKS
from score_input_coverage import paired_contrast


class CoverageControlTests(unittest.TestCase):
    def test_fitter_cannot_request_evaluation_labels(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, 'only train and calibration'):
                labels_for(root, {}, [], 'evaluation')

    def test_nested_budgets_have_equal_class_source_counts(self):
        labels = np.array([0] * 200 + [1] * 100)
        order = balanced_order(labels, 7)
        self.assertEqual(len(set(order.tolist())), 128)
        self.assertEqual(np.bincount(labels[order[:32]]).tolist(), [16, 16])
        self.assertEqual(np.bincount(labels[order]).tolist(), [64, 64])
        np.testing.assert_array_equal(order, balanced_order(labels, 7))
        with self.assertRaisesRegex(ValueError, '128-source'):
            balanced_order(np.array([0] * 63 + [1] * 80), 7)

    def test_full_source_bm25_retains_tail_beyond_previous_text_cap(self):
        texts = ['common ' * 6000 + ' distinct_tail', 'common plain']
        control = CoverageRetrieval(np.eye(2), np.array([0, 1]), texts)
        similarities, _ = control.similarities('bm25_topk', np.array([[1., 0.]]), ['distinct_tail'])
        self.assertGreater(similarities[0, 0], 0)
        self.assertEqual(similarities[0, 1], 0)
        probability = control.predict(similarities, {'k': 1, 'temperature': 1.})
        self.assertEqual(int(probability.argmax(axis=1)[0]), 0)
        np.testing.assert_allclose(probability.sum(axis=1), 1)

    def test_identical_predictions_have_exactly_zero_paired_interval(self):
        records, predictions = [], []
        labels = {task: np.array([0, 1] * 16) for task in TASKS}
        for task in TASKS:
            for seed in (7, 17, 29):
                for policy in ('prefix', 'head_tail'):
                    records.append({'task': task, 'seed': seed, 'budget': 128,
                                    'policy': policy, 'arm': 'linear'})
                    predictions.append(np.tile([[.8, .2], [.2, .8]], (16, 1)))
        result = paired_contrast(records, np.array(predictions), labels,
                                  left=('head_tail', 'linear'), right=('prefix', 'linear'))
        self.assertEqual(result['difference'], 0)
        self.assertEqual(result['ci95'], [0, 0])
        self.assertFalse(result['positive_interval'])
        self.assertEqual(result['paired_source_group_draws'], 2000)


if __name__ == '__main__':
    unittest.main()
