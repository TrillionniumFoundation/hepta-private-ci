"""Differential NumPy oracle: independent of the producer PyTorch Head.forward."""
import copy
import unittest
import torch

import e2_numpy_oracle as oracle
import e2_token_query_ablation as producer
from test_e2_token_query_ablation import fixture


def panel(width):
    cases,features=fixture(width)
    source={}
    result=producer.study(cases,features,width=width,replay_head_states=source)
    heads={f'{kind}.{status}.{name}':tensor for kind,s in source.items()
           for status,items in s.items() for name,tensor in items.items()}
    return cases,features,heads,result


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.small=panel(384)
        cls.wide=panel(768)

    def test_384d_six_real_checkpoints_576_predictions(self):
        answer=oracle.review(*self.small,384)
        self.assertEqual(answer['verified_head_states'],6)
        self.assertEqual(answer['verified_original_probabilities'],576)
        self.assertLess(answer['max_probability_absolute_error'],oracle.MAX_DEVIATION)
        self.assertTrue(answer['independent_numpy_forward_not_producer_torch_head'])
        self.assertEqual(answer['authority'],'DENY_ALL')

    def test_768d_six_checkpoints(self):
        answer=oracle.review(*self.wide,768)
        self.assertEqual(answer['verified_original_probabilities'],576)
        self.assertFalse(answer['production_promotion_permitted'])

    def test_swapped_head_order_or_weights_rejected(self):
        rows,features,heads,report=self.small
        altered=heads.copy()
        altered['token_query.learned.query']=heads['token_query.learned.query']+.1
        with self.assertRaisesRegex(oracle.Invalid,'does not match reported'):
            oracle.review(rows,features,altered,report,384)

    def test_changed_prediction_rejected(self):
        rows,features,heads,report=self.small
        changed=copy.deepcopy(report)
        changed['arms']['pooled_gated']['predictions'][0]['positive_probability']+=.05
        with self.assertRaisesRegex(oracle.Invalid,'does not match'):
            oracle.review(rows,features,heads,changed,384)

    def test_missing_query_tensor_rejected(self):
        rows,features,heads,report=self.small
        changed=heads.copy()
        changed.pop('token_query.frozen.query')
        with self.assertRaisesRegex(oracle.Invalid,'missing original serialized'):
            oracle.review(rows,features,changed,report,384)

    def test_changed_calibration_rejected(self):
        rows,features,heads,report=self.small
        altered=copy.deepcopy(report)
        altered['arms']['token_query']['calibration_temperature']=99
        with self.assertRaisesRegex(oracle.Invalid,'unregistered E2 calibration'):
            oracle.review(rows,features,heads,altered,384)

    def test_wrong_dataset_population_rejected(self):
        rows,features,heads,report=self.small
        with self.assertRaisesRegex(oracle.Invalid,'cohort'):
            oracle.review(rows[:-1],features,heads,report,384)

    def test_numpy_oracle_does_not_invoke_torch_head_forward(self):
        from unittest.mock import patch
        with patch.object(producer.Head,'forward',side_effect=RuntimeError('producer Head forbidden')):
            result=oracle.review(*self.small,384)
        self.assertEqual(result['verified_original_probabilities'],576)

if __name__=='__main__':unittest.main()
