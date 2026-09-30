"""Synthetic receipt tests; these never count as Rust execution evidence."""
import copy
import unittest
from receipt_validation import NATIVE_SCHEMA, REQUIRED_COMMANDS, validate_native_checks

def receipt():
    return {'schema':NATIVE_SCHEMA,'head':'a'*40,'expectedSha':'a'*40,
            'trackedAndUntrackedBefore':'','trackedAndUntrackedAfter':'',
            'diffCheckBefore':0,'diffCheckAfter':0,'buildSurface':'single_complete',
            'rustToolchain':'rustc synthetic\nhost: synthetic-target',
            'providerDynamicE2E':False,'productionExecutionProved':False,'storageProfileQualified':False,
            'productComposed':False,'independentAcceptance':False,'releaseAuthority':False,
            'checks':[{'check':key,'command':list(command),'exitCode':0,'durationSeconds':1.0,'logSha256':'b'*64} for key,command in REQUIRED_COMMANDS.items()]}

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
        for key,value in [('schema','hepta.secrets-native-feedback.v1'),('expectedSha','c'*40),('trackedAndUntrackedBefore','?? src/lib.rs'),('trackedAndUntrackedAfter',None),('diffCheckBefore',True),('diffCheckAfter',1),('productComposed',True),('productionExecutionProved',True),('releaseAuthority',True)]:
            r=receipt();r[key]=value
            with self.assertRaises(ValueError):validate_native_checks(r,'source-head')
    def test_failed_additional_gate_also_rejects(self):
        r=receipt(); extra=copy.deepcopy(r['checks'][0]);extra.update(check='additional',exitCode=1);r['checks'].append(extra)
        with self.assertRaises(ValueError):validate_native_checks(r,'source-head')
    def test_every_current_gate_is_required(self):
        for index in range(len(receipt()['checks'])):
            r=receipt();r['checks'].pop(index)
            with self.assertRaisesRegex(ValueError,'incomplete'):validate_native_checks(r,'source-head')
    def test_no_run_or_excluding_required_package_is_rejected(self):
        for suffix in (['--no-run'],['--exclude','codex-hepta-bao-adapter']):
            r=receipt();next(row for row in r['checks'] if row['check']=='tests')['command']+=suffix
            with self.assertRaises(ValueError):validate_native_checks(r,'source-head')

if __name__=='__main__':unittest.main()
