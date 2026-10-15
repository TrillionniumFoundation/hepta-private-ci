"""Negative-control tests of independent full 8000-step sample replay."""
from dataclasses import dataclass
from copy import deepcopy
from collections import Counter
import unittest

from cross_fact_granite_receipt_oracle import (
    _hash, derive_schedule, ordered_four_row_groups, verify_observed_training,
)


@dataclass(frozen=True)
class Case:
    case_id: str
    paragraph_id: str
    answer_id: str


def cases():
    return [Case(f'group-{g}/world-{w}/answer-{a}',
                 f'group-{g}/world-{w}', str(a))
            for g in range(8) for w in (0, 1) for a in (0, 1)]


def receipts(seed, completed=8):
    cohort=cases()
    schedule=derive_schedule(cohort,seed,steps=16,batch_size=8)
    updates=[]
    counter=Counter()
    for step, indices in enumerate(schedule[:completed],1):
        ids=[cohort[i].case_id for i in indices]
        counter.update(ids)
        updates.append(dict(step=step, indices=indices, case_ids=ids,
                            sample_sha256=_hash(ids), exposures=8, depth=3,
                            pair_weight=.5, finite_gradients=True,
                            inference_feature_arguments=6, cpu_ns=5, wall_ns=6))
    return cohort,dict(schedule_sha256=_hash(schedule), updates=updates,
                       cpu_ns=completed*5+10, wall_ns=completed*6+10,
                       completed_steps=completed, actual_training_exposures=completed*8,
                       case_exposures=dict(counter))


class OracleTests(unittest.TestCase):
    def test_registered_four_row_group_and_update_identity(self):
        source, receipt=receipts(47)
        groups=ordered_four_row_groups(source)
        self.assertEqual(len(groups),8)
        self.assertEqual(groups[0],(0,1,2,3))
        result=verify_observed_training(source,47,receipt,steps=16,batch_size=8)
        self.assertEqual(result['completed_steps'],8)
        self.assertEqual(sum(result['source_exposures'].values()),64)
        self.assertFalse(result['independently_attested_execution'])

    def test_forged_schedule_digest_or_sample_order_rejected(self):
        source,receipt=receipts(41)
        drift=deepcopy(receipt)
        drift['schedule_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'schedule SHA'):
            verify_observed_training(source,41,drift,steps=16,batch_size=8)
        drift=deepcopy(receipt)
        drift['updates'][3]['indices'].reverse()
        with self.assertRaisesRegex(ValueError,'source membership'):
            verify_observed_training(source,41,drift,steps=16,batch_size=8)

    def test_claimed_updates_without_complete_receipts_rejected(self):
        source,receipt=receipts(53)
        receipt['updates'].pop()
        with self.assertRaisesRegex(ValueError,'physical optimizer update receipts'):
            verify_observed_training(source,53,receipt,steps=16,batch_size=8)

    def test_zero_cost_nan_or_hidden_exposure_rejected(self):
        source,receipt=receipts(47)
        tampered=deepcopy(receipt)
        tampered['updates'][0]['cpu_ns']=0
        with self.assertRaisesRegex(ValueError,'training cost'):
            verify_observed_training(source,47,tampered,steps=16,batch_size=8)
        tampered=deepcopy(receipt)
        tampered['case_exposures'].pop(next(iter(tampered['case_exposures'])))
        with self.assertRaisesRegex(ValueError,'source exposures'):
            verify_observed_training(source,47,tampered,steps=16,batch_size=8)

    def test_underreported_full_lifecycle_cost_denied(self):
        source,receipt=receipts(47)
        receipt['cpu_ns']=1
        with self.assertRaisesRegex(ValueError,'lifecycle cost'):
            verify_observed_training(source,47,receipt,steps=16,batch_size=8)

    def test_duplicate_group_member_rejected(self):
        source=cases()
        source[1]=source[0]
        with self.assertRaisesRegex(ValueError,'unique TRAIN case'):
            ordered_four_row_groups(source)


if __name__=='__main__':
    unittest.main()
