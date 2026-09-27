"""Synthetic evidence tests only: fixture counts are not Rust test results."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import attest_candidate as attest
from test_receipt_validation import receipt

class CandidateAttestationTests(unittest.TestCase):
    def fixture(self, root, role, passed=True):
        root.mkdir()
        value=receipt()
        value.update(schema='hepta.secrets-native-feedback.v1',candidateRole=role,tree='b'*40,identityClean=True,passed=passed)
        for row in value['checks']:
            log=root/(row['check']+'.log')
            log.write_text('test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n')
            row['logSha256']=hashlib.sha256(log.read_bytes()).hexdigest()
        path=root/'receipt.json';path.write_text(json.dumps(value));return path

    def test_complete_logs_are_checked_and_counted(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.fixture(Path(d)/'source','source-head')
            self.assertEqual(attest.load_receipt(p,'source-head')['verifiedExecutedTests'],{'tests':3,'authbus-schema':3})
    def test_failed_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.fixture(Path(d)/'source','source-head',False)
            with self.assertRaisesRegex(ValueError,'did not pass'):attest.load_receipt(p,'source-head')
    def test_tampered_or_missing_log_rejected(self):
        for missing in (True,False):
            with tempfile.TemporaryDirectory() as d:
                p=self.fixture(Path(d)/'source','source-head');log=p.parent/'tests.log'
                if missing:log.unlink()
                else:log.write_text('replaced log')
                with self.assertRaises(ValueError):attest.load_receipt(p,'source-head')
    def test_zero_execution_rejected_even_with_valid_digest(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.fixture(Path(d)/'source','source-head');log=p.parent/'tests.log';log.write_text('test result: ok. 0 passed; 0 failed;\n')
            v=json.loads(p.read_text())
            for row in v['checks']:
                if row['check']=='tests':row['logSha256']=hashlib.sha256(log.read_bytes()).hexdigest()
            p.write_text(json.dumps(v))
            with self.assertRaisesRegex(ValueError,'zero executed'):attest.load_receipt(p,'source-head')
    def test_joint_attestation_preserves_nonclaims(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=self.fixture(root/'source','source-head');merge=self.fixture(root/'merge','synthetic-merge')
            provider=root/'provider.json';provider.write_text(json.dumps({'serverSha256':'e'*64,'dynamicLeaseExecutionProved':False}))
            out=root/'joint.json'
            argv=['attest_candidate.py','--source-receipt',str(source),'--merge-receipt',str(merge),'--source-lock-sha256','1'*64,'--source-manifest-sha256','2'*64,'--merge-lock-sha256','3'*64,'--merge-manifest-sha256','4'*64,'--provider-evidence',str(provider),'--output',str(out)]
            with patch('sys.argv',argv), patch.object(attest,'tool',side_effect=['rustc synthetic','cargo synthetic']):self.assertEqual(attest.main(),0)
            value=json.loads(out.read_text());self.assertEqual(value['providerBinarySha256'],'e'*64);self.assertFalse(value['releaseAuthority'])
    def test_empty_receipt_cannot_produce_joint_attestation(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.fixture(Path(d)/'source','source-head');v=json.loads(p.read_text());v['checks']=[];p.write_text(json.dumps(v))
            with self.assertRaises(ValueError):attest.load_receipt(p,'source-head')

if __name__=='__main__':unittest.main()
