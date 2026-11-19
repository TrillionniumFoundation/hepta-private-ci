from pathlib import Path
import json
import unittest
import base64
import gzip
from .audit_live_mqar_receipts import (EXPECTED,sha,canonical,
    verify_bundle_bytes,verify_file_bytes,load_and_verify,UnresolvedReceiptAudit)

EVIDENCE=Path(__file__).parent/'P2_LIVE_MQAR_PAIR_RECEIPTS_20261031.json.gz.b64'

class LivePairTests(unittest.TestCase):
    def test_two_real_receipts_replay(self):
        r=load_and_verify(EVIDENCE)
        self.assertEqual(r['paired_real_training_count'],2)
        self.assertLess(r['training_cpu_relative_gap'],.05)
        self.assertFalse(r['full_12_seal'])
        self.assertLess(r['ood_signed_pp'],0)
    def test_tampered_compressed_or_truncated_refused(self):
        payload=gzip.decompress(base64.b64decode(EVIDENCE.read_text()))
        with self.assertRaises(UnresolvedReceiptAudit):verify_bundle_bytes(payload+b' ')
        obj=json.loads(payload);obj['trial_files'].pop(next(iter(obj['trial_files'])))
        with self.assertRaises(UnresolvedReceiptAudit):verify_bundle_bytes(canonical(obj))
    def test_corrupt_authorship_or_model_hash_refused(self):
        obj=json.loads(gzip.decompress(base64.b64decode(EVIDENCE.read_text())))
        for name,entry in obj['trial_files'].items():
            arm=name.split('.')[2]
            envelope=json.loads(entry);envelope['record']['initial_model_sha256']='0'*64
            with self.assertRaises(UnresolvedReceiptAudit):verify_file_bytes(canonical(envelope),arm)
    def test_losslessly_preserved_original_receipt_bytes(self):
        obj=json.loads(gzip.decompress(base64.b64decode(EVIDENCE.read_text())))
        for arm,hashval in EXPECTED.items():
            encoded=obj['trial_files'][f'mqar4.2.{arm}.json'].encode('ascii')
            self.assertEqual(sha(encoded),hashval)
            self.assertEqual(verify_file_bytes(encoded,arm)['arm'],arm)

if __name__=='__main__':unittest.main()
