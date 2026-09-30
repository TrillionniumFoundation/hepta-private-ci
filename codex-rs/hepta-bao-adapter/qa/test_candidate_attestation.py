"""Synthetic evidence tests only: fixture counts are not Rust test results."""
import hashlib
import json
import os
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
        value.update(candidateRole=role,tree='b'*40,identityClean=True,passed=passed,
                     workflowRunId='fixture-run',workflowAttempt='1',workflowSha='c'*40)
        for row in value['checks']:
            log=root/(row['check']+'.log')
            log.write_text('test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n')
            row['logSha256']=hashlib.sha256(log.read_bytes()).hexdigest()
        path=root/'receipt.json';path.write_text(json.dumps(value));return path

    def test_complete_logs_are_checked_and_counted(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.fixture(Path(d)/'source','source-head')
            self.assertEqual(attest.load_receipt(p,'source-head')['verifiedExecutedTests'],{'tests':3,'authbus-schema':3,'authbus-operation':3})
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
            argv=['attest_candidate.py','--source-receipt',str(source),'--merge-receipt',str(merge),'--expected-source-sha','a'*40,'--expected-base-sha','d'*40,'--expected-merge-sha','a'*40,'--source-lock-sha256','1'*64,'--source-manifest-sha256','2'*64,'--merge-lock-sha256','3'*64,'--merge-manifest-sha256','4'*64,'--provider-evidence',str(provider),'--output',str(out)]
            with patch('sys.argv',argv), patch.object(attest,'tool',return_value='cargo synthetic'), patch.object(attest,'verify_source_bindings',return_value='d'*40):self.assertEqual(attest.main(),0)
            value=json.loads(out.read_text());self.assertEqual(value['providerBinarySha256'],'e'*64);self.assertFalse(value['releaseAuthority'])
    def test_empty_receipt_cannot_produce_joint_attestation(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.fixture(Path(d)/'source','source-head');v=json.loads(p.read_text());v['checks']=[];p.write_text(json.dumps(v))
            with self.assertRaises(ValueError):attest.load_receipt(p,'source-head')

    def test_cross_run_attempt_or_workflow_is_rejected_before_git(self):
        for field in ('workflowRunId', 'workflowAttempt', 'workflowSha'):
            source={'workflowRunId':'123','workflowAttempt':'1','workflowSha':'a'*40}
            merge=dict(source);merge[field]='other'
            with patch.object(attest,'git') as git:
                with self.assertRaisesRegex(ValueError,'execution identity'):
                    attest.verify_source_bindings(source,merge,{})
                git.assert_not_called()

    def test_tree_hash_and_merge_parent_are_verified_against_git_objects(self):
        source={'head':'a'*40,'tree':'b'*40,'workflowRunId':'123','workflowAttempt':'1','workflowSha':'c'*40,'rustToolchain':'rustc synthetic'}
        merge=dict(source,head='d'*40,tree='e'*40)
        hashes={name:hashlib.sha256(name.encode()).hexdigest() for name in ('source_lock','source_manifest','merge_lock','merge_manifest')}
        outputs=[('b'*40).encode(),b'source_lock',b'source_manifest',('e'*40).encode(),b'merge_lock',b'merge_manifest',('f'*40+' '+'a'*40).encode()]
        environment={'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_WORKFLOW_SHA':'c'*40}
        with patch.object(attest,'git',side_effect=outputs), patch.dict(os.environ,environment):
            self.assertEqual(attest.verify_source_bindings(source,merge,hashes),'f'*40)
        for index,replacement in ((0,b'wrong-tree'),(1,b'tampered-lock'),(6,('f'*40+' '+'0'*40).encode())):
            tampered=list(outputs);tampered[index]=replacement
            with patch.object(attest,'git',side_effect=tampered), patch.dict(os.environ,environment):
                with self.assertRaises(ValueError):attest.verify_source_bindings(source,merge,hashes)

    def test_old_run_pair_and_wrong_expected_base_cannot_be_reused(self):
        source={'head':'a'*40,'tree':'b'*40,'workflowRunId':'123','workflowAttempt':'1','workflowSha':'c'*40,'rustToolchain':'rustc synthetic'}
        merge=dict(source,head='d'*40,tree='e'*40)
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'other-run'}):
            with self.assertRaisesRegex(ValueError,'current execution'):
                attest.verify_source_bindings(source,merge,{})
        outputs=[b'b'*40,b'source_lock',b'source_manifest',b'e'*40,b'merge_lock',b'merge_manifest',('f'*40+' '+'a'*40).encode()]
        hashes={name:hashlib.sha256(name.encode()).hexdigest() for name in ('source_lock','source_manifest','merge_lock','merge_manifest')}
        expected={'source':'a'*40,'merge':'d'*40,'base':'0'*40}
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_WORKFLOW_SHA':'c'*40}), patch.object(attest,'git',side_effect=outputs):
            with self.assertRaisesRegex(ValueError,'expected base'):
                attest.verify_source_bindings(source,merge,hashes,expected)

    def test_source_and_merge_toolchain_mismatch_is_rejected(self):
        source={'workflowRunId':'123','workflowAttempt':'1','workflowSha':'c'*40,'rustToolchain':'rustc old'}
        merge=dict(source,rustToolchain='rustc different')
        with self.assertRaisesRegex(ValueError,'toolchains'):
            attest.verify_source_bindings(source,merge,{})

if __name__=='__main__':unittest.main()
