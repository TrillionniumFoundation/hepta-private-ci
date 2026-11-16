"""Real serializer bytes, not false same-parameter-budget claims."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from near_matched_byte_budget import (
    ARMS, BYTE_CAPS, Invalid, audit, choose, physical_shape,
)


@unittest.skipUnless(
    os.environ.get('HEPTA_NEURON_PHYSICAL_TESTS') == '1',
    'pinned Torch+safetensors physical tests only; cheap A0 remains framework-free',
)
class PhysicalByteBudgetTests(unittest.TestCase):
    def test_original_eight_real_physical_file_size_shapes(self):
        original = {
            ('v2', 58, None): 8724, ('v3', 53, None): 9516,
            ('ssm', 55, None): 9332, ('min_gru', 45, 2): 10948,
            ('v2', 234, None): 34084, ('v3', 215, None): 36748,
            ('ssm', 221, None): 35908, ('min_gru', 182, 2): 41660,
        }
        for (arm, width, rank), physical_bytes in original.items():
            with self.subTest(arm=arm, width=width, rank=rank):
                self.assertEqual(physical_shape(arm, width, rank)[
                    'physical_safetensors_bytes'], physical_bytes)

    def test_fully_materialized_eight_new_equal_byte_profiles(self):
        expected = {
            8192: {
                'v2': (54, None, 8148), 'v3': (45, None, 8172),
                'ssm': (47, None, 8052), 'min_gru': (38, 1, 8156),
            },
            32768: {
                'v2': (224, None, 32644), 'v3': (191, None, 32716),
                'ssm': (201, None, 32708), 'min_gru': (166, 1, 32756),
            },
        }
        for budget, arms in expected.items():
            for arm, (hidden, rank, size) in arms.items():
                with self.subTest(budget=budget, arm=arm):
                    result = choose(arm, budget)
                    self.assertEqual(
                        (result['hidden_width'], result['rank'],
                         result['physical_safetensors_bytes']),
                        (hidden, rank, size),
                    )
                    self.assertTrue(0 <= budget-size <= budget*0.02)
                    self.assertFalse(result['budget_unfilled_ppm'] > 20_000)

    def test_real_payload_and_safetensors_header_are_both_charged(self):
        for budget in BYTE_CAPS:
            for arm in ARMS:
                with self.subTest(budget=budget, arm=arm):
                    row = choose(arm, budget)
                    self.assertEqual(
                        row['actual_tensor_payload_bytes']
                        + row['safetensors_header_and_metadata_bytes'],
                        row['physical_safetensors_bytes'],
                    )
                    self.assertGreater(row['safetensors_header_and_metadata_bytes'], 8)
                    self.assertIn('adapter.weight', row['tensor_shapes_and_dtypes'])
                    self.assertIn('head.weight', row['tensor_shapes_and_dtypes'])
                    self.assertIn('structure.projection', row['tensor_shapes_and_dtypes'])
                    self.assertEqual(row['tensor_shapes_and_dtypes']['adapter.weight']['shape'][1], 32)

    def test_real_byte_match_does_not_fake_equal_parameter_or_runtime(self):
        report = audit()
        self.assertEqual(report['decision'], 'NO_MODEL_PROMOTION')
        self.assertEqual(report['authority'], 'DENY_ALL')
        self.assertFalse(report['equal_model_parameter_counts_verified'])
        self.assertFalse(report['equal_inference_resident_memory_verified'])
        self.assertFalse(report['equal_optimizer_or_training_flops_verified'])
        self.assertFalse(report['original_live_selected_v1_a0_verified'])
        self.assertFalse(report['native_full_forward_verified'])
        self.assertFalse(report['ndu_eligible'])
        for tier in report['tiers']:
            self.assertTrue(tier['within_2pct_serialized_byte_ceiling'])
            self.assertEqual(len(tier['candidate_shapes']), 4)
            self.assertGreater(len({
                row['private_parameter_count']
                for row in tier['candidate_shapes'].values()}), 1)

    def test_physical_template_is_not_a_weighted_model(self):
        for arm in ARMS:
            row = choose(arm, 8192)
            self.assertTrue(row['template_weights_are_untrained_zero_fixtures'])
            self.assertEqual(row['shared_feature_width'], 32)
            self.assertLessEqual(row['byte_budget']-row['physical_safetensors_bytes'], 163)

    def test_foreign_arm_or_budget_or_rank_rejected(self):
        for arm, budget, rank in [
            ('cf_c', 8192, 4), ('v2', 10000, 4), ('v3', 2048, 4),
            ('min_gru', True, 4), ('min_gru', 8192, 5),
            ('ssm', 32768, False), ('v2', 32768, 0),
        ]:
            with self.subTest(arm=arm, budget=budget, rank=rank):
                with self.assertRaises(Invalid):
                    choose(arm, budget, max_rank=rank)

    def test_out_of_range_shape_validation_still_deny(self):
        for arm, hidden, rank in [
            ('v2', 4, None), ('v3', 257, None),
            ('min_gru', 32, 0), ('min_gru', 32, 33),
            ('ssm', 32, 1), ('new-architecture', 32, None),
        ]:
            with self.subTest(arm=arm, hidden=hidden, rank=rank):
                with self.assertRaises(Invalid):
                    physical_shape(arm, hidden, rank)

    def test_deterministic_encoded_shape_digest_not_artifact_claim(self):
        first, second = audit(), audit()
        self.assertEqual(first, second)
        value = dict(first)
        expected = value.pop('planning_payload_sha256')
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        self.assertEqual(expected, hashlib.sha256(raw).hexdigest())
        self.assertFalse(first['genuine_learned_weights_measured'])
        self.assertFalse(first['production_qualification'])

    def test_cli_write_once_never_relabels_prior_results(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'byte-plan.json'
            args = [sys.executable,
                    str(Path(__file__).with_name('near_matched_byte_budget.py')),
                    '--output', str(path)]
            first = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(path.read_text())['predeclared_byte_caps'], [8192,32768])
            previous = path.read_bytes()
            next_run = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(next_run.returncode, 2)
            self.assertEqual(previous, path.read_bytes())


if __name__ == '__main__':
    unittest.main()
