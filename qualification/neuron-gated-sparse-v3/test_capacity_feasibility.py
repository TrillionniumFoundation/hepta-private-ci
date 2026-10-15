"""Closed-world research geometry tests; not a physical model efficacy test."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import capacity_feasibility as m


class FixedGeometryTruth(unittest.TestCase):
    def test_train_fixture_32d_realized_tensor_counts(self):
        report = m.audit(width=32)
        expected = {
            2048: {'v2': 65, 'v3': 161, 'ssm': 129, 'min_gru': 1921},
            8192: {'v2': 65, 'v3': 161, 'ssm': 129, 'min_gru': 4225},
            16384: {'v2': 65, 'v3': 161, 'ssm': 129, 'min_gru': 4225},
            65536: {'v2': 65, 'v3': 161, 'ssm': 129, 'min_gru': 4225},
            262144: {'v2': 65, 'v3': 161, 'ssm': 129, 'min_gru': 4225},
        }
        for row in report['rows']:
            self.assertEqual(row['total'], expected[row['nominal_ceiling']][row['arm']])
        self.assertEqual(len(report['rows']), 20)
        self.assertEqual(report['distinct_geometry_count_not_weight_sha_count'], 5)
        self.assertEqual(report['distinct_capacities_by_arm'],
                         {'v2': 1, 'v3': 1, 'ssm': 1, 'min_gru': 2})
        self.assertTrue(report['fixed_width_cross_arm_exact_match_mathematically_impossible'])
        self.assertFalse(report['five_tier_equal_realized_parameter_design_valid'])
        self.assertFalse(report['per_cap_cross_arm_equal_realized_parameters'])
        self.assertFalse(report['each_arm_five_distinct_parameter_tiers'])
        self.assertFalse(report['ndu_eligible'])
        self.assertEqual(report['authority'], 'DENY_ALL')

    def test_v2_v3_ssm_inherently_different_for_every_supported_width(self):
        for width in range(5, 257):
            a = [m.component_count(arm, width)['total'] for arm in ('v2','v3','ssm')]
            self.assertEqual(a, [2 * width + 1, 5 * width + 1, 4 * width + 1])
            self.assertEqual(len(set(a)), 3)

    def test_min_gru_capacity_bounded_and_saturation(self):
        self.assertEqual(m.rank_for_budget(32, 2048), 14)
        self.assertEqual(m.rank_for_budget(32, 8192), 32)
        self.assertEqual(m.rank_for_budget(32, 262144), 32)
        self.assertEqual(m.component_count('min_gru', 32, rank=32)['total'], 4225)
        self.assertRaises(m.Invalid, m.rank_for_budget, 256, 2048)

    def test_no_invalid_widths_and_budget_labels(self):
        for width in (-1, 0, 4, 257, 10**500, True, 32.5, '32'):
            self.assertRaises(m.Invalid, m.audit, width=width)
        for caps in [(2048, 2048), (8192, 2048), (2048, -1), [2048, 8192],
                     (True,), (), (262145,), (2048.0,)]:
            self.assertRaises(m.Invalid, m.audit, width=32, caps=caps)

    def test_unregistered_arm_and_invalid_rank_rejected(self):
        self.assertRaises(m.Invalid, m.component_count, 'other', 32)
        for rank in (0, -1, 33, True, '3'):
            self.assertRaises(m.Invalid, m.component_count, 'min_gru', 32, rank=rank)

    def test_same_profile_other_width_still_blocks(self):
        for w in (5, 16, 64, 128, 256):
            caps = tuple(cap for cap in m.CAPS if cap >= 4 * w + 1)
            if w == 256:
                caps = m.CAPS[1:]
            try:
                result = m.audit(width=w, caps=caps)
            except m.Invalid:
                continue
            self.assertFalse(result['five_tier_equal_realized_parameter_design_valid'])
            self.assertFalse(result['per_cap_cross_arm_equal_realized_parameters'])

    def test_generated_report_does_not_grant_authority(self):
        result = m.audit(width=32)
        self.assertIs(result['production_promotion_permitted'], False)
        self.assertIs(result['signed_a0_selected_cell_verified'], False)
        self.assertIs(result['actual_weight_loading_verified'], False)
        self.assertIs(result['train_optimizer_work_or_cost_verified'], False)

    def test_git_blob_matches_raw_bytes_not_plain_sha1(self):
        data = b'pin-test-original-source\n'
        import hashlib
        want = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        self.assertEqual(m.git_blob_sha(data), want)
        self.assertNotEqual(want, hashlib.sha1(data).hexdigest())
        self.assertRaises(m.Invalid, m.git_blob_sha, 'not bytes')

    def test_trainer_source_rejects_symlink_wrong_blob_and_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / 'trainer.py'; p.write_bytes(b'physical\n')
            symlink = root / 'link.py'; symlink.symlink_to(p)
            pinned = m.git_blob_sha(p.read_bytes())
            self.assertRaises(m.Invalid, m.verify_trainer, symlink, pinned_sha=pinned)
            self.assertRaises(m.Invalid, m.verify_trainer, p, pinned_sha='0'*40)
            ok = m.verify_trainer(p, pinned_sha=pinned)
            self.assertTrue(ok['source_bytes_locally_bound'])
            p.write_bytes(b'changed\n')
            self.assertRaises(m.Invalid, m.verify_trainer, p, pinned_sha=pinned)

    def test_cli_research_only_and_create_once(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'review.json'
            cmd = [sys.executable, str(Path(m.__file__)), '--width','32','--output',str(out)]
            first = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            doc = json.loads(out.read_text())
            self.assertEqual(doc['authority'],'DENY_ALL')
            self.assertFalse(doc['five_tier_equal_realized_parameter_design_valid'])
            self.assertFalse(doc['source_git_blob_verified_locally'])
            second = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(second.returncode,0)
            self.assertIn('BLOCKED_FIXED_WIDTH_CAPACITY_PLAN', second.stderr)


if __name__ == '__main__':
    unittest.main()
