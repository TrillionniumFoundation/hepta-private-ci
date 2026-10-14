"""Synthetic receipt contracts, not evidence that real pretrained weights ran."""
import unittest
from public_stem_pair_gate_v9 import check_pair
from public_stem_material_v8 import CATALOG, RECEIPT, PROBE_TEXTS, probe_input_digest, AdmissionError


def fixtures():
    out = {}
    for i, name in enumerate(sorted(CATALOG)):
        p = CATALOG[name]
        out[name] = dict(schema=RECEIPT,candidate=name,repo_id=p['repo_id'],
            pooling=p['pooling'],normalization=p['normalization'],feature_width=p['width'],
            probe_input_sha256=probe_input_digest(PROBE_TEXTS),probe_count=len(PROBE_TEXTS),
            forward_calls=2,wall_ns=100,cpu_ns=99,revision=str(i+1)*40,
            snapshot_digest=str(i+1)*64,plan_sha256=str(i+3)*64,
            feature_sha256=str(i+5)*64,production_accepted=False,
            pretrained_source_independently_attested=False,
            matched_pair_completed=False,heldout_efficacy_evaluated=False,authority='DENY_ALL')
    return out

class PairTests(unittest.TestCase):
    def test_valid_synthetic_receipts_still_no_go(self):
        r=check_pair(fixtures())
        self.assertTrue(r['paired_physical_preflight_complete'])
        self.assertFalse(r['matched_training_completed'])
        self.assertFalse(r['production_accepted'])

    def test_missing_or_mismatched_inputs_rejected(self):
        for field,value in [('probe_input_sha256','f'*64),('probe_count',1),('pooling','bad'),
                            ('forward_calls',0),('authority','ALLOW'),('production_accepted',True),
                            ('heldout_efficacy_evaluated',True),('snapshot_digest','0'*64)]:
            pair=fixtures()
            name=sorted(pair)[0]
            pair[name][field]=value
            with self.subTest(field=field),self.assertRaises(AdmissionError):
                check_pair(pair)
        pair=fixtures()
        pair.pop(sorted(pair)[0])
        with self.assertRaises(AdmissionError):check_pair(pair)

if __name__ == '__main__':unittest.main()
