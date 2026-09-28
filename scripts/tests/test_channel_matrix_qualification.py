"""Synthetic receipt validation only; these tests are NOT native execution."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import channel_matrix_qualification as q
from channel_matrix_evidence import COMMANDS, file_digest


class ScenarioLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.registry = ROOT / q.REGISTRY
        self.row = q.load_registry(self.registry)
        sources = {t['source'] for s in self.row['scenarios'] for t in s['tests']}
        source = {'schema':'hepta.channel-matrix-source-snapshot.v1','testedSha':'a'*40,
                  'testedTree':'b'*40,'sourceSha':'a'*40,'baseSha':'c'*40,'lane':'source-head',
                  'files':[{'path':q.REGISTRY,'sha256':file_digest(self.registry)}]+[{'path':s} for s in sources]}
        self.write('source.json',source); self.write('source-after.json',source)

    def write(self,name,row): (self.path/name).write_text(json.dumps(row))

    def receipt(self,xml,**changes):
        log=self.path/'focused-tests.log';log.write_text('test fixture, not native execution')
        report=self.path/'focused-tests.junit.xml';report.write_text(xml)
        row={'schema':'hepta.channel-matrix-command.v1','label':'focused-tests',
             'arguments':COMMANDS['focused-tests'],'workingDirectory':'codex-rs','testedSha':'a'*40,
             'sourceSnapshotSha256':file_digest(self.path/'source.json'),'completed':True,'exitCode':0,
             'launchError':None,'sourceUnchanged':True,
             'log':{'path':log.name,'bytes':log.stat().st_size,'sha256':file_digest(log),'withinBudget':True},
             'junit':{'path':report.name,'bytes':report.stat().st_size,'sha256':file_digest(report)}}
        row.update(changes);self.write('focused-tests.command.json',row)

    def report(self,child=''):
        t=self.row['scenarios'][23]['tests'][0]
        return f'<testsuites><testsuite name="{t["binary"]}"><testcase name="{t["test"]}">{child}</testcase></testsuite></testsuites>'

    def test_exact_case_does_not_qualify_other_cases_or_external_target(self):
        self.receipt(self.report());row=q.ledger(self.path,self.registry)
        self.assertEqual(row['scenarios'][23]['native_fixture_result'],'passed')
        self.assertEqual(row['scenarios'][24]['native_fixture_result'],'not_executed')
        self.assertEqual(row['scenarios'][11]['external_qualification'],'not_proved')
        self.assertFalse(row['authority_granted']);self.assertFalse(row['release'])

    def test_skip_flaky_and_failure_never_become_pass(self):
        for tag,state in [('skipped','skipped'),('failure','failed'),('flakyFailure','flaky')]:
            self.receipt(self.report(f'<{tag}/>'))
            self.assertEqual(q.ledger(self.path,self.registry)['scenarios'][23]['native_fixture_result'],state)

    def test_missing_report_not_inferred_from_green_command(self):
        self.receipt(self.report(),junit=None)
        self.assertEqual(q.ledger(self.path,self.registry)['scenarios'][23]['native_fixture_result'],'not_executed')

    def test_tampered_report_rejected(self):
        self.receipt(self.report());(self.path/'focused-tests.junit.xml').write_text(self.report('<skipped/>'))
        with self.assertRaises(ValueError):q.ledger(self.path,self.registry)

    def test_wrong_sha_boolean_exit_and_alternate_command_rejected(self):
        for change in ({'testedSha':'d'*40},{'exitCode':False},{'arguments':['echo','passed']}):
            self.receipt(self.report(),**change)
            with self.subTest(change=change),self.assertRaises(ValueError):q.ledger(self.path,self.registry)

    def test_duplicate_tests_zero_tests_and_dtd_are_rejected(self):
        for xml in ('<testsuites/>','<!DOCTYPE x><testsuites/>', '<testsuites><testsuite name="x"><testcase name="y"/><testcase name="y"/></testsuite></testsuites>'):
            with self.subTest(xml=xml),self.assertRaises(ValueError):q.parse_junit(xml.encode())

    def test_stale_registry_cannot_be_swapped_after_execution(self):
        self.receipt(self.report());p=self.path/'changed.json';row=dict(self.row);row['note']='different';self.write(p.name,row)
        with self.assertRaises(ValueError):q.ledger(self.path,p)

    def test_registry_tests_exist_in_native_source(self):
        for scenario in self.row['scenarios']:
            for t in scenario['tests']:
                self.assertIn('fn '+t['test'].split('::')[-1]+'(', (ROOT/t['source']).read_text())
