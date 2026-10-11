"""Model-free internal pairing tests; signature integration runs separately."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from baseline_bridge_fixtures import fixture
from four_gate_baseline import pair_verified, verify_owner
from four_gate_common import digest
from four_gate_review import BASELINE_BUNDLE, review_all
from prequential_threeway_review import verify_cell_trace, verify_and_index


class TypedBaselineTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.cell, self.cohort, self.sealed, self.packet, self.verified = fixture()

    def run_pair(self):
        return pair_verified(self.plan, self.cell.rows, self.cell.trial, self.cell.journal,
                             self.cohort, self.sealed, self.packet, self.verified)

    def test_hard_baseline_has_no_invented_brier(self):
        r = self.run_pair()
        self.assertEqual(r['status'], 'diagnostic_complete')
        self.assertIsNone(r['windows']['future_1']['no_change']['brier'])
        self.assertIsNone(r['windows']['future_1']['no_change']['ece'])
        self.assertFalse(r['replaces_probability_learning_gate'])
        self.assertFalse(r['production_promotion_permitted'])
        self.assertTrue(r['cell_weights_changed'])

    def test_abstention_and_slow_path_not_called_wrong(self):
        for n, row in enumerate(self.verified['observations'].values()):
            row.update(disposition='abstained' if n % 2 else 'slow_path', selected_option=None)
        r = self.run_pair()['windows']['future_1']
        self.assertIsNone(r['no_change']['selective_accuracy'])
        self.assertEqual(r['no_change']['coverage'], 0)
        self.assertEqual(r['trained']['baseline_selected_pairs'], 0)
        self.assertEqual(r['trained']['better'], 0)

    def test_partial_abstention_keeps_both_denominators(self):
        cid = next(k for k in self.verified['observations'] if k.startswith('future-4'))
        self.verified['observations'][cid].update(disposition='abstained', selected_option=None)
        r = self.run_pair()['windows']['future_1']
        self.assertEqual(r['rows'], 32)
        self.assertEqual(r['no_change']['selected'], 31)
        self.assertEqual(r['trained']['baseline_selected_pairs'], 31)

    def test_exact_source_group_mismatch_rejected(self):
        self.cohort['payload']['rows'][-1]['source_group'] = 'new-group'
        with self.assertRaisesRegex(ValueError, 'group or window'):
            self.run_pair()

    def test_option_order_mismatch_rejected(self):
        self.sealed[-1]['option_order'] = list(reversed(self.sealed[-1]['option_order']))
        with self.assertRaisesRegex(ValueError, 'identical input'):
            self.run_pair()

    def test_side_information_mismatch_rejected(self):
        self.sealed[-1]['domain'] = 'gold-domain-not-given-to-cell'
        with self.assertRaisesRegex(ValueError, 'identical input'):
            self.run_pair()

    def test_sealed_label_mapping_cannot_change(self):
        self.sealed[-1]['gold'] = 'no'
        with self.assertRaisesRegex(ValueError, 'label/option'):
            self.run_pair()

    def test_scope_mismatch_rejected(self):
        self.cell.rows[-5]['native_scope_digest'] = digest('another-scope')
        # Refresh audit only; the independent owner descriptor must still match.
        from qualified_eval import audit_dataset
        self.cell.trial['dataset_audit'] = audit_dataset(self.cell.rows)
        with self.assertRaisesRegex(ValueError, 'scope mismatch'):
            self.run_pair()

    def test_stale_and_future_source_reread_rejected(self):
        original = self.cohort['payload']['source_current_revalidated_at_unix_micros']
        for change in (-10_000_000, 10_000_000):
            self.cohort['payload']['source_current_revalidated_at_unix_micros'] = original + change
            with self.assertRaisesRegex(ValueError, 'stale or future'):
                self.run_pair()

    def test_future_signature_rejected(self):
        self.packet['owner_signature']['signed_at_unix_micros'] += 10_000_000
        with self.assertRaisesRegex(ValueError, 'signature timestamp'):
            self.run_pair()

    def test_generation_mismatch_rejected(self):
        for row in self.verified['observations'].values():
            row['generation'] += 1
        with self.assertRaisesRegex(ValueError, 'generation drift'):
            self.run_pair()

    def test_no_cherry_pick_future_inventory(self):
        self.cohort['payload']['rows'].pop()
        with self.assertRaisesRegex(ValueError, 'future coverage'):
            self.run_pair()

    def test_forged_head_chain_still_rejected(self):
        self.cell.trial['temporal_receipts'][-1]['preupdate_head_digest'] = digest('forged')
        with self.assertRaises(ValueError):
            self.run_pair()

    def test_descriptor_pin_cannot_change(self):
        self.cohort['payload']['no_change']['policy_digest'] = digest('changed-policy')
        with self.assertRaisesRegex(ValueError, 'descriptor drift'):
            self.run_pair()

    def test_missing_trust_source_fails_closed(self):
        with self.assertRaises(FileNotFoundError):
            verify_owner({}, None, None, None)

    def test_same_entrypoint_reports_missing_not_success(self):
        bundle = {'schema': BASELINE_BUNDLE, 'plan_sha256': digest(self.plan),
                  'evidence': {k: None for k in ('compute','learning','reasoning','ndu')},
                  'production_baseline': None}
        with tempfile.TemporaryDirectory() as root:
            report = review_all(self.plan, bundle, root)
        self.assertEqual(report['typed_production_baseline']['status'], 'blocked_missing_baseline_dependency')
        self.assertFalse(report['current_acceptance_profile_passed'])
        self.assertFalse(report['typed_baseline_replaces_learning_gate'])

    def test_original_probability_contract_cannot_omit_nochange(self):
        with self.assertRaises(ValueError):
            verify_and_index(self.cell.rows, self.cell.trial, self.cell.journal, [])
        indexed, _, changed = verify_cell_trace(self.cell.rows, self.cell.trial, self.cell.journal)
        self.assertEqual(len(indexed), 64)
        self.assertTrue(changed)


if __name__ == '__main__':
    unittest.main()
