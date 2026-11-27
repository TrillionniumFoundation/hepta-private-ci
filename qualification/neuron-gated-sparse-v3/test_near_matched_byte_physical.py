"""Physical safetensors byte-budget training protocol; never real A0 or NDU."""
from __future__ import annotations

from argparse import Namespace
import copy
import os
from pathlib import Path
import tempfile
import unittest

from near_matched_byte_budget import BYTE_CAPS, ARMS, choose as byte_choose
from near_matched_physical_fixture import generate
from near_matched_physical_train import train
from near_matched_physical_native_oracle import physically_load


@unittest.skipUnless(
    os.environ.get('HEPTA_NEURON_PHYSICAL_TESTS') == '1',
    'real Torch+safetensors framework is confined to pinned physical jobs',
)
class ByteMatchedPhysicalTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.fixture = generate(cls.root / 'fixture')
        cls.models = cls.root / 'trained'
        cls.report = train(Namespace(
            train_data=cls.root / 'fixture' / 'train.json',
            train_sha256=cls.fixture['train_sha256'],
            output=cls.models, steps=2, seed=20261015,
            synthetic_canary=True, physical_byte_budget=True,
        ))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_all_eight_weight_files_are_physically_serialized_and_reloaded(self):
        self.assertEqual(self.report['schema'],
                         'hepta.neuron.byte-matched-physical-train.v1')
        self.assertEqual(self.report['predeclared_serialized_byte_caps'], list(BYTE_CAPS))
        self.assertEqual(self.report['physical_model_file_count'], 8)
        self.assertEqual(len(self.report['cells']), 8)
        self.assertEqual({(row['cap'], row['arm']) for row in self.report['cells']},
                         {(cap, arm) for cap in BYTE_CAPS for arm in ARMS})
        for row in self.report['cells']:
            expected = byte_choose(row['arm'], row['cap'])
            self.assertEqual(row['budget_kind'], 'SERIALIZED_SAFETENSORS_BYTES')
            self.assertEqual(row['physical_bytes'], expected['physical_safetensors_bytes'])
            self.assertEqual(row['complete_realized_parameters'],
                             expected['private_parameter_count'])
            self.assertLessEqual(row['physical_bytes'], row['cap'])
            self.assertLessEqual(
                (row['cap'] - row['physical_bytes'])*1_000_000,
                20_000*row['cap'],
            )
            loaded = physically_load(self.models, row)
            self.assertEqual(len(loaded), row['tensor_count'])
            self.assertEqual(row['optimizer_steps'], 2)

    def test_byte_matching_changes_parameter_counts_and_never_claims_flops(self):
        by_cap = {}
        for row in self.report['cells']:
            by_cap.setdefault(row['cap'], set()).add(row['complete_realized_parameters'])
        self.assertTrue(all(len(counts) > 1 for counts in by_cap.values()))
        self.assertFalse(self.report['same_resident_memory_or_training_flops_verified'])
        self.assertFalse(self.report['equal_training_FLOPs_verified'])
        self.assertFalse(self.report['original_selected_v1_a0_verified'])
        self.assertFalse(self.report['future_utility_verified'])
        self.assertFalse(self.report['ndu_eligible'])
        self.assertFalse(self.report['production_qualification'])

    def test_false_exact_byte_claim_rejected_by_independent_reopen(self):
        row = copy.deepcopy(self.report['cells'][0])
        row['physical_bytes'] += 1
        with self.assertRaises(ValueError):
            physically_load(self.models, row)

    def test_duplicate_or_false_budget_kind_cannot_relabel_weight(self):
        row = copy.deepcopy(self.report['cells'][0])
        row['budget_kind'] = 'PRIVATE_PARAMETER_COUNT'
        with self.assertRaises(ValueError):
            physically_load(self.models, row)
        row = copy.deepcopy(self.report['cells'][0])
        row['cap'] = 262144
        with self.assertRaises(ValueError):
            physically_load(self.models, row)

    def test_tampered_original_weight_hash_fail_closed(self):
        row = copy.deepcopy(self.report['cells'][0])
        row['weight_sha256'] = '0'*64
        with self.assertRaises(ValueError):
            physically_load(self.models, row)

    def test_new_study_output_is_create_only(self):
        with self.assertRaises(FileExistsError):
            train(Namespace(
                train_data=self.root / 'fixture' / 'train.json',
                train_sha256=self.fixture['train_sha256'],
                output=self.models, steps=1, seed=20261015,
                synthetic_canary=True, physical_byte_budget=True,
            ))


if __name__ == '__main__':
    unittest.main()
