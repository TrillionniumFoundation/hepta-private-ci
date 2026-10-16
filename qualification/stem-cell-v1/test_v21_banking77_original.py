"""Original PolyAI/prediction source audit; requires actual pinned file bytes."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from v21_banking77_cross_family_audit import Invalid, original_audit


class OriginalPublisherAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = {}
        for key, env in (
            ('archive', 'HEPTA_V21_BANKING_ARCHIVE'),
            ('train', 'HEPTA_V21_BANKING_TRAIN_CSV'),
            ('test', 'HEPTA_V21_BANKING_TEST_CSV'),
        ):
            original = os.getenv(env)
            if not original:
                raise RuntimeError(f'real publisher source required: {env}')
            cls.original[key] = Path(original)

    def check(self, *, archive=None, train=None, test=None):
        return original_audit(archive or self.original['archive'],
                              train or self.original['train'],
                              test or self.original['test'])

    def test_source_first_complete_original_result(self):
        result = self.check()
        self.assertEqual(result['decision'], 'SECOND_FAMILY_DESCRIPTIVE_NOT_CROSS_MODEL_TRANSFER')
        self.assertTrue(result['independent_public_publisher_label_roster_reconstructed'])
        self.assertEqual(result['original_selected_heldout_cases'], 32)
        self.assertEqual(result['modernbert_banking77_original_score_recount']['dense16']['after']['correct'],23)
        self.assertEqual(result['modernbert_banking77_original_score_recount']['sparse16_top2']['after']['correct'],17)
        self.assertEqual(result['dense_over_sparse_pairwise'],{'rescues':10,'harms':4,'ties':18})
        self.assertFalse(result['same_stem_or_budget_cross_family_comparison_verified'])
        self.assertFalse(result['production_authorized'])

    def test_wrong_train_data_denied(self):
        with tempfile.TemporaryDirectory() as t:
            forged = Path(t, 'train.csv')
            forged.write_bytes(self.original['train'].read_bytes() + b'\n')
            with self.assertRaises(Invalid):
                self.check(train=forged)

    def test_wrong_test_data_denied(self):
        with tempfile.TemporaryDirectory() as t:
            forged = Path(t, 'test.csv')
            forged.write_bytes(self.original['test'].read_bytes() + b'\n')
            with self.assertRaises(Invalid):
                self.check(test=forged)

    def test_bad_model_archive_denied(self):
        with tempfile.TemporaryDirectory() as t:
            forged = Path(t, 'original.zip')
            forged.write_bytes(self.original['archive'].read_bytes() + b'A')
            with self.assertRaises(Invalid):
                self.check(archive=forged)

    def test_missing_original_file_denied(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(Invalid):
                self.check(train=Path(t) / 'missing-original.csv')

    def test_original_source_is_one_exposed_family_not_prospective(self):
        result = self.check()
        self.assertEqual(result['source_family_count_in_pair'], 2)
        self.assertEqual(result['independent_future_calendar_windows'], 0)
        self.assertFalse(result['prospective_head_learning_gain'])
        self.assertFalse(result['model_selection_authorized'])

    def test_no_original_HF_parity_or_equal_lifecycle_claim(self):
        result = self.check()
        self.assertEqual(result['banking77_model'],'ModernBERT-base')
        self.assertEqual(result['comparator_agnews_model'],'mmBERT-small')
        self.assertTrue(result['different_model_and_task'])
        self.assertFalse(result['full_equal_lifecycle_cost_comparison'])
        self.assertFalse(result['independent_model_issuer_signature'])


if __name__ == '__main__':
    unittest.main()
