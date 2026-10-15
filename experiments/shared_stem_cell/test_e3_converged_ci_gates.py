"""Converged original-source provenance and same-branch queue semantics.

These checks only validate contract-source mechanics. A passing fixture does
not mean a pretrained model, five-arm result, or runtime permission passed.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
PHYSICAL = ROOT / ".github/workflows/hepta-e3-five-arm-original-physical.yml"
CONTRACT = ROOT / ".github/workflows/hepta-e3-five-arm-historical-contract.yml"
CHILD = "research/e3-five-arm-merged-admission-decongestion-20261015"
BYTE_CHILD = "research/e3-byte-bound-model-ledger-20261015"
RACE_CHILD = "research/e3-race-resnapshot-20261015"

def sections(text):
    starts=list(re.finditer(r"(?m)^  ([a-z][a-z0-9-]*):\n",text))
    return {m.group(1):text[m.end():(starts[i+1].start() if i+1<len(starts) else len(text))]
            for i,m in enumerate(starts)}

class Converged(unittest.TestCase):
    def test_both_checklists_have_one_complete_branch_only_trigger(self):
        for file in (PHYSICAL,CONTRACT):
            with self.subTest(file=file):
                raw=file.read_text()
                self.assertIn(f'branches: ["{CHILD}", "{BYTE_CHILD}", "{RACE_CHILD}"]',raw)
                self.assertIn('cancel-in-progress: true',raw)
                self.assertIn('test_e3_runner_budget.py',raw)
                self.assertIn('test_e3_model_entry_ledger.py',raw)
                self.assertIn('test_e3_converged_ci_gates.py',raw)

    def test_physical_jobs_push_only_and_prepost_receipts(self):
        raw=PHYSICAL.read_text()
        jobs=sections(raw.split("\njobs:\n",1)[1])
        for name in ('physical-ocr-granite','physical-native-gemma2','independent-five-arm-review'):
            self.assertTrue(jobs[name].startswith("    if: github.event_name == 'push'\n"),name)
        for job,mod in (('physical-ocr-granite','ocr'),('physical-native-gemma2','native')):
            section=jobs[job]
            self.assertIn(f'e3-{mod}-pre-view.json',section)
            self.assertIn(f'e3-{mod}-post-view.json',section)
            self.assertIn('e3_model_entry_ledger.py',section)
            self.assertIn('--predictor-source-only',section)
            self.assertIn('rm -rf -- "$RUNNER_TEMP/e3-source-cache"',section)

    def test_model_target_digest_never_global_or_in_producer_job(self):
        raw=PHYSICAL.read_text()
        h,j=raw.split("\njobs:\n",1)
        self.assertNotIn('HELD_SHA:',h)
        jobs=sections(j)
        for name in ('schema-and-security-contract','physical-ocr-granite','physical-native-gemma2'):
            self.assertNotIn('HELD_SHA:',jobs[name])
        self.assertIn('HELD_SHA:',jobs['independent-five-arm-review'])
        self.assertEqual(raw.count('--predictor-source-only'),2)

    def test_original_source_receipts_are_checked_before_sealing(self):
        raw=PHYSICAL.read_text()
        jobs=sections(raw.split("\njobs:\n",1)[1])
        reviewer=jobs['independent-five-arm-review']
        self.assertIn('independently verify both physical model jobs'.lower(),
                      reviewer.lower())
        self.assertIn('test_label_count',reviewer)
        self.assertIn('tree_fingerprint',reviewer)
        self.assertIn('tree_fingerprint_profile',reviewer)
        self.assertIn('hepta.e3-path-byte-sha256.v2',reviewer)
        self.assertIn('tree_fingerprint_file_count',reviewer)
        self.assertIn('original_source_receipt_sha256',reviewer)
        self.assertIn('sha256sum',reviewer)

if __name__ == '__main__':
    unittest.main()
