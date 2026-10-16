"""Mechanism and adversarial checks; NOT an original-publisher source run."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from v21_banking77_cross_family_audit import (
    BANKING_ZIP_SHA, INTENTS, Invalid, evaluate, original_audit,
    paired, parse_csv, reconstruct, require, sha, text_key,
)


class SourceOnlyTests(unittest.TestCase):
    def test_sha_original_identity(self):
        self.assertEqual(sha(b'abc'), hashlib.sha256(b'abc').hexdigest())
        self.assertEqual(len(BANKING_ZIP_SHA), 64)

    def test_casefold_whitespace_nfkc(self):
        self.assertEqual(text_key('  How  is\tCARD? '), 'how is card?')
        self.assertEqual(text_key('ＦＯＯ'), 'foo')

    def test_parse_csv_and_duplicates(self):
        rows, duplicates = parse_csv(b'text,category\r\n"abc, yes",card_arrival\r\nabc,exchange_rate\r\n')
        self.assertEqual(len(rows), 2)
        self.assertEqual(duplicates, 0)

    def test_duplicate_conflicting_label_fails(self):
        with self.assertRaises(Invalid):
            parse_csv(b'text,category\nfoo,a\n FOO  ,b\n')

    def test_duplicate_same_label_keeps_deterministic_text(self):
        rows, duplicate_count = parse_csv(b'text,category\nfoo,a\nFOO,a\n')
        self.assertEqual(duplicate_count, 1)
        self.assertEqual(rows['foo']['text'], 'FOO')

    def test_empty_or_unbounded_csv_rejected(self):
        with self.assertRaises(Invalid):
            parse_csv(b'')
        with self.assertRaises(Invalid):
            parse_csv(b'a' * 2_000_001)

    def test_invalid_csv_schema(self):
        with self.assertRaises(Invalid):
            parse_csv(b'category,text\na,foo\n')

    def test_original_source_always_required(self):
        with self.assertRaises(Invalid):
            reconstruct(b'text,category\nfoo,a\n', b'text,category\nfoo,a\n')

    def test_identity_denies_missing_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'nope.zip'
            with self.assertRaises(Invalid):
                original_audit(missing, missing, missing)

    def test_perfect_brier_and_nll(self):
        logits = [[12., -8., -8., -8.]] * 32
        result = evaluate(logits, [0] * 32)
        self.assertEqual(result['count'], 32)
        self.assertEqual(result['correct'], 32)
        self.assertLess(result['brier'], 1e-13)

    def test_uniform_multiclass_brier(self):
        out = evaluate([[0., 0., 0., 0.]] * 32, [i//8 for i in range(32)])
        self.assertEqual(out['correct'], 8)
        self.assertAlmostEqual(out['brier'], 0.75)

    def test_bad_prediction_denied(self):
        with self.assertRaises(Invalid):
            evaluate([[float('nan'), 0, 0, 0]] * 32, [0] * 32)
        with self.assertRaises(Invalid):
            evaluate([[0,0,0,0]] * 31, [0] * 32)
        with self.assertRaises(Invalid):
            evaluate([[0,0,0,0]] * 32, [4] * 32)

    def test_pairwise_damage(self):
        y = [0] * 32
        old, new = [0] * 32, [0] * 32
        old[0] = 1
        new[1] = 1
        result = paired(old, new, y)
        self.assertEqual(result, {'rescues':1, 'harms':1, 'ties':30})

    def test_original_archive_correct_but_not_automatic_source(self):
        # The ZIP on its own contains original prediction IDs and aggregates,
        # but cannot prove independently reconstructed publisher truth.
        self.assertEqual(len(INTENTS), 4)
        self.assertFalse(hasattr(self, 'issuer_signature'))


if __name__ == '__main__':
    unittest.main()
