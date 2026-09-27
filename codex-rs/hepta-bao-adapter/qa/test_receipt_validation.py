"""Synthetic receipt tests; these never count as Rust execution evidence."""
import copy
import unittest
from receipt_validation import validate_native_checks

def receipt():
    commands = {
        'format': ['cargo','fmt','-p','codex-hepta-bao-adapter','--','--check'],
        'tests': ['cargo','test','--locked','-p','codex-hepta-bao-adapter','--all-targets'],
        'clippy': ['cargo','clippy','--locked','-p','codex-hepta-bao-adapter','--all-targets','--','-D','warnings'],
        'authbus-schema': ['cargo','test','--locked','-p','codex-hepta-authbus','authority_schema'],
    }
    return {'head':'a'*40,'expectedSha':'a'*40,'trackedChangesBefore':'','trackedChangesAfter':'',
            'providerDynamicE2E':False,'productionExecutionProved':False,'independentAcceptance':False,'releaseAuthority':False,
            'checks':[{'check':key,'command':command,'exitCode':0,'durationSeconds':1.0,'logSha256':'b'*64} for key,command in commands.items()]}

class ReceiptValidationTests(unittest.TestCase):
    def test_complete_receipt(self):
        validate_native_checks(receipt(), 'source-head')
    def test_empty_or_missing_checks_cannot_be_overridden_by_passed(self):
        for value in ([],None):
            r=receipt();r.update(checks=value,passed=True)
            with self.assertRaises(ValueError):validate_native_checks(r,'source-head')
    def test_duplicate_or_incomplete_checks(self):
        for checks in (receipt()['checks'][:-1],receipt()['checks']+[receipt()['checks'][0]]):
            r=receipt();r['checks']=checks
            with self.assertRaises(ValueError):validate_native_checks(r,'source-head')
    def test_nonexecution_failure_invalid_log_or_scope(self):
        for key,value in [('exitCode',1),('exitCode',True),('exitCode',None),('logSha256',''),('durationSeconds',float('nan')),('command',['echo','passed'])]:
            r=receipt();r['checks'][1][key]=value
            with self.assertRaises(ValueError):validate_native_checks(r,'source-head')
    def test_identity_drift_dirty_source_and_authority_escalation(self):
        for key,value in [('expectedSha','c'*40),('trackedChangesBefore',' M src/lib.rs'),('trackedChangesAfter',None),('productionExecutionProved',True),('releaseAuthority',True)]:
            r=receipt();r[key]=value
            with self.assertRaises(ValueError):validate_native_checks(r,'source-head')
    def test_failed_additional_gate_also_rejects(self):
        r=receipt(); extra=copy.deepcopy(r['checks'][0]);extra.update(check='additional',exitCode=1);r['checks'].append(extra)
        with self.assertRaises(ValueError):validate_native_checks(r,'source-head')

if __name__=='__main__':unittest.main()
