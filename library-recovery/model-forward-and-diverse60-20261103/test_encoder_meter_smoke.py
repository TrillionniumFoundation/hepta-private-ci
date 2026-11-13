"""Bounded offline module-level smoke checks for the archived meter source."""
import sys
from pathlib import Path
import unittest

import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).parent / 'source'))
from encoder_meter import EncoderModuleForwardMeter


class PassThrough(nn.Module):
    def forward(self, input_ids):
        return input_ids + 1


class IntentionalFailure(nn.Module):
    def forward(self, input_ids):
        raise RuntimeError('intentional failure')


class MeterSmoke(unittest.TestCase):
    def test_two_successful_model_call_receipts_and_unhook(self):
        model = PassThrough()
        with EncoderModuleForwardMeter(model) as meter:
            for n in (3, 4):
                output = model(input_ids=torch.ones((2, n), dtype=torch.int64))
                self.assertEqual(output.shape, (2, n))
        receipt = meter.receipt()
        self.assertEqual(receipt['module_forward_attempts'], 2)
        self.assertEqual(receipt['module_forward_completions'], 2)
        self.assertEqual(receipt['rows_attempted'], 4)
        self.assertEqual(receipt['padded_token_slots_attempted'], 14)
        self.assertEqual(receipt['production_admission'], 'BLOCKED')
        self.assertEqual(len(model._forward_hooks), 0)
        self.assertEqual(len(model._forward_pre_hooks), 0)

    def test_failed_forward_is_not_counted_as_completion(self):
        model = IntentionalFailure()
        with EncoderModuleForwardMeter(model) as meter:
            with self.assertRaisesRegex(RuntimeError, 'intentional failure'):
                model(input_ids=torch.ones((2, 3), dtype=torch.int64))
        receipt = meter.receipt()
        self.assertEqual(receipt['module_forward_attempts'], 1)
        self.assertEqual(receipt['module_forward_completions'], 0)
        self.assertEqual(receipt['module_forward_failures_or_incomplete'], 1)
        self.assertFalse(receipt['independent_signature_verified'])
        self.assertEqual(len(model._forward_hooks), 0)
        self.assertEqual(len(model._forward_pre_hooks), 0)

    def test_bad_tensor_rejected_without_complete(self):
        model = PassThrough()
        with EncoderModuleForwardMeter(model) as meter:
            with self.assertRaisesRegex(ValueError, 'rank-2 input_ids'):
                model(input_ids=torch.ones((4,), dtype=torch.int64))
        self.assertEqual(meter.receipt()['module_forward_completions'], 0)
        self.assertEqual(len(model._forward_pre_hooks), 0)


if __name__ == '__main__':
    unittest.main()
