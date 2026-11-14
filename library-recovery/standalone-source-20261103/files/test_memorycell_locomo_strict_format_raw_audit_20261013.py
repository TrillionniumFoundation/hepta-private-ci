"""Original-answer comparison: tamper rejection and no-gold constraints."""
import os
from pathlib import Path
import tempfile
import unittest

from memorycell_locomo_strict_format_raw_audit_20261013 import (
    OLD_SHA,
    NEW_SHA,
    audit,
    metrics,
    read_json,
    sealed,
)


class PairedRawFormatTests(unittest.TestCase):
    def test_duplicate_and_nonfinite_json_refused(self):
        for bad in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.assertRaises(ValueError):
                read_json(bad)

    def test_format_score_does_not_interpret_labels_as_entailment(self):
        row = {
            'answer': 'I do not have enough evidence. [E1]',
            'receipt': {
                'delivered_evidence': [{'label': 'E1'}],
                'input_tokens': 1,
                'generated_tokens': 1,
                'seconds': 1.0,
                'answer_postprocessed': False,
            },
        }
        summary = metrics({'one': row})
        self.assertEqual(summary['exact_refusal'], 0)
        self.assertEqual(summary['refusal_mixed_with_other_text'], 1)
        self.assertEqual(summary['answers_with_delivered_citations'], 1)

    def test_wrong_pins_rejected(self):
        self.assertNotEqual(OLD_SHA, NEW_SHA)
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'not-original.zip'
            fake.write_bytes(b'unsupported substitute')
            with self.assertRaises(ValueError):
                sealed(fake, NEW_SHA)

    def test_changed_original_answer_rejected_by_outer_pin(self):
        source = os.getenv('HEPTA_LOCOMO_NEW_ZIP')
        if not source:
            self.skipTest('external raw model artifact absent')
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / 'changed.zip'
            copied.write_bytes(Path(source).read_bytes() + b'altered')
            with self.assertRaises(ValueError):
                sealed(copied, NEW_SHA)

    def test_original_real_paired_answersonly_audit(self):
        old = os.getenv('HEPTA_LOCOMO_OLD_ZIP')
        new = os.getenv('HEPTA_LOCOMO_NEW_ZIP')
        if not old or not new:
            self.skipTest('pinned real source ZIPs absent')
        report = audit(Path(old), Path(new))
        self.assertEqual(report['paired_original_question_count'], 16)
        self.assertEqual(report['answer_text_changed'], 14)
        self.assertEqual(report['historical_unmodified_answers']['exact_refusal'], 1)
        self.assertEqual(report['new_unmodified_answers']['exact_refusal'], 0)
        self.assertFalse(report['exact_refusal_improved'])
        self.assertFalse(report['mixed_refusal_reduced'])
        self.assertFalse(report['original_gold_answers_read'])
        self.assertFalse(report['production_accepted'])


if __name__ == '__main__':
    unittest.main()
