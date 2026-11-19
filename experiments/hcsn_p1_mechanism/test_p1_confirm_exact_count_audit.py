from copy import deepcopy
from pathlib import Path
import json
import unittest
from .p1_confirm_exact_count_audit import verify,IncompleteEvidence,p_exact,load_evidence

DATA=load_evidence(Path(__file__).parent/'P1_CONFIRM_COMPACT_12SEEDS_20261031.json.gz.b64')

class CountAuditTests(unittest.TestCase):
    def test_complete_frozen_twenty_seven_statistics(self):
        z=verify(DATA)
        self.assertEqual(z['rows'],16)
        self.assertEqual(z['paired_comparisons'],14)
        self.assertFalse(z['all_scientific_blockers_closed'])
    def test_five_seed_two_sided_signflip_cannot_pass_family(self):
        # 2/2^5=1/16 cannot beat 0.05/14. Twelve seeds permit smaller p.
        self.assertGreater(1/16,.05/14)
        self.assertLess(1/2048,.05/14)
        self.assertEqual(p_exact([1]*12),1/2048)
    def test_missing_trials_and_bad_sample_counts_refused(self):
        for key in ('rows','complete_records','full_sha256'):
            doc=deepcopy(DATA)
            doc.pop(key)
            with self.assertRaises(IncompleteEvidence):verify(doc)
        bad=deepcopy(DATA)
        bad['rows'][0]['ood_correct'][0]+=1
        with self.assertRaises(IncompleteEvidence):verify(bad)
    def test_broken_signflip_and_wrong_holm_refused(self):
        for target in ('exact_p','holm_adjusted'):
            bad=deepcopy(DATA)
            row=next(x for x in bad['rows'] if target in x)
            row[target]='0'
            with self.assertRaises(IncompleteEvidence):verify(bad)

if __name__=='__main__':unittest.main()
