"""Real unknown-kernel failure retains both sources of work uncertainty."""
import unittest

import torch

from execution_meter import WorkLedger
from final_campaign import _cost_record
from paired_execution import PHASES
from test_execution_meter import policy
from work_record import validate_work_record


class UnknownWorkFailureTests(unittest.TestCase):
    def test_unknown_and_failed_kernel_is_valid_but_never_complete(self):
        ledger = WorkLedger(policy(), dict.fromkeys(PHASES, 10**9))
        value = torch.tensor([1], dtype=torch.long)
        with self.assertRaises(RuntimeError):
            with ledger.scope('train', 'bank'):
                value.sin_()  # Unknown formula; actual result cannot fit Long.
        record = ledger.report()
        self.assertEqual(record['operators'], {'aten.sin_.default': 1})
        self.assertEqual(record['scopes'][0]['unknown_operators'], 2)
        self.assertEqual(validate_work_record(record)['train'], 0)
        self.assertEqual(_cost_record({'work_observation': record})['phases']['train'],
                         {'known_formula_work': 0, 'complete_count': None})
        record['phase_flops']['train'] = 0
        with self.assertRaisesRegex(ValueError, 'cannot claim complete'):
            validate_work_record(record)


if __name__ == '__main__':
    unittest.main()
