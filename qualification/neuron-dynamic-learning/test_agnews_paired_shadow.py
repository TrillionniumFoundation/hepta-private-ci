"""Mechanism-only tests; no pretrained weights or longitudinal outcomes."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from agnews_paired_shadow import CapabilityError, check_panel, compare, run_laya, _bound_report, _row
from public_agnews_panel import select_rows


def panel():
    tr = [{"text": f"Training report on event {i} topic {i%2}", "label": i%2}
          for i in range(160)]
    ho = [{"text": f"Held-out report on event {i} topic {i%2}", "label": i%2}
          for i in range(160)]
    return select_rows(tr, ho)


def reports(source):
    digest, splits = check_panel(source)
    rows = []
    for kind in ('calibration', 'test'):
        for case in splits[kind]:
            rows.append(_row(case, 0.75 if case['label'] else 0.25, 130))
    return [_bound_report(digest, arm, copy.deepcopy(rows)) for arm in
            ('laya421_frozen', 'gemma2_frozen_head', 'gemma2_trained_head')]


class FakeLaya:
    def system_one(self, state, questions):
        assert state['text'] and questions['category']['type'] == 'choice'
        return {'answers': {'category': {'probabilities': {
            'world': 0.25, 'sports': 0.75}}}}


class PairedCapability(unittest.TestCase):
    def test_complete_panel_and_untouched_authority(self):
        p = panel()
        q = compare(p, reports(p))
        self.assertEqual(q['windows']['test']['laya421_frozen']['cases'], 64)
        self.assertAlmostEqual(q['windows']['test']['gemma2_trained_head']['brier'], 0.0625)
        self.assertFalse(q['matched_full_lifecycle_cost'])
        self.assertFalse(q['three_future_windows_present'])
        self.assertEqual(q['production_promotion'], 'DENY_ALL')

    def test_panel_tamper_disallowed(self):
        for field, value in [('label', 8), ('group_id', 'unrelated'),
                             ('case_id', 'duplicate'), ('source_digest', '0' * 64)]:
            p = panel()
            p['cases'][1][field] = value
            with self.subTest(field=field), self.assertRaises(CapabilityError):
                check_panel(p)

    def test_missing_case_or_mixed_digest_or_false_attestation(self):
        for reason in ('missing', 'source', 'authority', 'future'):
            p = panel()
            rr = reports(p)
            if reason == 'missing':
                rr[0]['rows'].pop()
            elif reason == 'source':
                rr[1]['rows'][0]['joint_input_digest'] = '0' * 64
            elif reason == 'authority':
                rr[2]['production_promotion'] = 'ALLOW'
            else:
                rr[2]['cross_sectional_not_future'] = False
            with self.subTest(reason=reason), self.assertRaises(CapabilityError):
                compare(p, rr)

    def test_invalid_duplicate_nonfinite_or_bad_timing(self):
        for reason in ('duplicate', 'nan', 'zero_time'):
            p = panel()
            rr = reports(p)
            if reason == 'duplicate':
                rr[0]['rows'][1] = copy.deepcopy(rr[0]['rows'][0])
            elif reason == 'nan':
                rr[0]['rows'][0]['prob_sports'] = float('nan')
            else:
                rr[0]['rows'][0]['measured_serving_micros'] = 0
            with self.subTest(reason=reason), self.assertRaises(CapabilityError):
                compare(p, rr)

    def test_laya_frozen_real_api_shape_fixture_is_not_claim_of_weights(self):
        p = panel()
        r = run_laya(p, FakeLaya(), revision='a' * 40)
        self.assertEqual(len(r['rows']), 96)
        self.assertEqual(r['rows'][0]['split'], 'calibration')
        self.assertFalse(r['model_execution_independently_attested'])
        self.assertEqual(r['production_promotion'], 'DENY_ALL')

if __name__ == '__main__':
    unittest.main()
