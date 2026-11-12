"""Synthetic local orchestration tests only; no Cargo, Rust, H or native evidence.

The fake controller is a small real Python child used to test parent sequencing,
budget acceptance and immutable record handling. It is deliberately not a test
of Rust or original CI process cleanup. Collector checks import the unchanged,
exact a4a collector and use explicitly synthetic XML/record fixtures.
"""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


GATE = module(ROOT / 'v2-candidate/list_run_gate.py', 'native11_v2_sequence')
COLLECT = module(ROOT / 'exact-source-tools/scripts/hepta_ci_junit.py', 'exact_a4a_collector')
SOURCE = '1' * 40
TREE = '2' * 40
IDENTITY = {'source': SOURCE, 'tree': TREE, 'status': ''}

FAKE_CONTROLLER = r'''
"""Synthetic local test fixture. This never executes a native command."""
import argparse, datetime, hashlib, json, os, sys, time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--timeout-seconds',type=float);p.add_argument('--minimum-tests',type=int);p.add_argument('--output',type=Path);p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
command=a.command[1:] if a.command[:1]==['--'] else a.command
started=datetime.datetime.now(datetime.timezone.utc).isoformat()
is_list='--list-only' in command
kind='list' if is_list else 'test'
code=int(os.environ.get('FAKE_'+kind.upper()+'_EXIT','0'))
directory=Path(os.environ['FAKE_RECORDS'])/'list-admission'
binary=Path(os.environ['FAKE_BINARY'])
identity={'source':os.environ['SOURCE_SHA'],'tree':'2'*40,'status':''}
if is_list and code==0:
 binary.write_bytes(b'explicit-synthetic-binary-not-native')
 inputs={'source':os.environ['SOURCE_SHA'],'binaries':[{'path':str(binary),'bytes':binary.stat().st_size,'sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}]}
 (directory/'listed-binary-inputs.json').write_text(json.dumps(inputs))
 (directory/'list-only-result.json').write_text(json.dumps({'status':'actual-list-exact','exit_code':0,'source_before':identity,'source_after':identity}))
if not is_list and os.environ.get('FAKE_MUTATE_BINARY')=='1': binary.write_bytes(b'synthetic-mutation')
time.sleep(float(os.environ.get('FAKE_CHILD_DELAY','0')))
before={'commit':os.environ['SOURCE_SHA'],'tree':'2'*40,'dirty':False}
record={'schema_version':1,'source_sha':os.environ['SOURCE_SHA'],'tested_sha':os.environ['TESTED_SHA'],'lane':'source-head','command':command,'working_directory':str(Path.cwd()),'before':before,'after':before,'status':'passed' if code==0 else 'failed','exit_code':code,'command_exit_code':code,'returncode':code,'timed_out':False,'output_limit_exceeded':False,'minimum_tests':a.minimum_tests,'observed_passed_tests':0 if is_list else 11,'observed_failed_tests':int(code!=0),'started_at':started,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'synthetic_fixture':True,'timeout_received':a.timeout_seconds,'actual_fake_child_pid':os.getpid()}
with a.output.open('x') as f:json.dump(record,f,indent=2);f.write('\n')
print('synthetic controller '+kind+' complete',flush=True)
raise SystemExit(code)
'''


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native11-v2-synthetic-')
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        (self.repo / 'scripts').mkdir(parents=True)
        (self.repo / 'scripts/hepta_ci_exec.py').write_text(FAKE_CONTROLLER)
        self.records = self.base / 'records'
        self.records.mkdir()
        self.directory = self.records / 'list-admission'
        self.binary = self.base / 'synthetic-binary'
        self.environment = patch.dict(os.environ, {
            'SOURCE_SHA': SOURCE, 'TESTED_SHA': SOURCE, 'HEPTA_CI_LANE': 'source-head',
            'FAKE_RECORDS': str(self.records), 'FAKE_BINARY': str(self.binary),
            'FAKE_LIST_EXIT': '0', 'FAKE_TEST_EXIT': '0', 'FAKE_MUTATE_BINARY': '0',
            'FAKE_CHILD_DELAY': '0'})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def sequence(self, clocks, identities=None):
        with patch.object(GATE.time, 'monotonic', side_effect=clocks), \
             patch.object(GATE, 'source_identity', side_effect=identities or [IDENTITY] * 8), \
             contextlib.redirect_stdout(io.StringIO()):
            status = GATE.sequence(self.repo, self.records, SOURCE)
        return status, json.loads((self.directory / 'result.json').read_text())


class FixedEndMechanism(Fixture):
    def test_real_fake_children_create_independent_unchanged_list_and_just_records(self):
        status, result = self.sequence([100, 101, 108, 109, 115, 116])
        self.assertEqual(status, 0)
        self.assertFalse(result['budget_expired'])
        listing = json.loads((self.records / 'list-execution.json').read_text())
        testing = json.loads((self.records / 'diagnostic-eleven.json').read_text())
        self.assertIn('--list-only', listing['command'])
        self.assertEqual(testing['command'], GATE.ORIGINAL_TEST_COMMAND)
        self.assertEqual(testing['command'][:3], ['just', 'test', '--locked'])
        self.assertNotEqual(listing['actual_fake_child_pid'], testing['actual_fake_child_pid'])
        self.assertEqual(listing['timeout_received'], 7199)
        self.assertEqual(testing['timeout_received'], 7191)
        self.assertTrue(result['native_test_child_started'])
        for label, filename in [('list', 'list-execution.json'), ('test', 'diagnostic-eleven.json')]:
            data = (self.records / filename).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), result[label+'_controller']['original_execution']['sha256'])
            self.assertEqual(result[label+'_controller']['returncode'], 0)
            self.assertFalse(result[label+'_controller']['parent_signal_or_kill'])

    def test_list_at_end_is_not_started(self):
        status, result = self.sequence([100, 7300, 7300])
        self.assertEqual(status, 1)
        self.assertTrue(result['budget_expired'])
        self.assertFalse((self.records / 'list-execution.json').exists())
        self.assertFalse((self.directory / 'test-controller-launch.json').exists())

    def test_zero_exit_list_completed_at_end_is_failure_and_no_test(self):
        status, result = self.sequence([100, 101, 7300, 7300])
        self.assertEqual(status, 1)
        self.assertEqual(result['status'], 'original-budget-expired')
        self.assertEqual(result['list_execution']['status'], 'passed')
        self.assertFalse((self.directory / 'test-controller-launch.json').exists())

    def test_expiry_between_phases_never_starts_just(self):
        status, result = self.sequence([100, 101, 7299, 7300, 7301])
        self.assertEqual(status, 1)
        self.assertFalse(result['native_test_child_started'])
        self.assertFalse((self.records / 'diagnostic-eleven.json').exists())
        self.assertTrue((self.directory / 'test-not-started.json').is_file())

    def test_zero_exit_just_at_end_does_not_upgrade_overall_result(self):
        status, result = self.sequence([100, 101, 102, 103, 7300, 7301])
        self.assertEqual(status, 1)
        self.assertEqual(result['test_execution']['status'], 'passed')
        self.assertEqual(result['test_execution']['exit_code'], 0)
        self.assertTrue(result['budget_expired'])
        self.assertEqual(result['status'], 'original-budget-expired')

    def test_final_identity_accounting_at_end_also_fails_closed(self):
        status, result = self.sequence([100, 101, 102, 103, 104, 7300])
        self.assertEqual(status, 1)
        self.assertEqual(result['test_execution']['status'], 'passed')
        self.assertTrue(result['budget_expired'])

    def test_original_failed_list_is_preserved_without_just(self):
        os.environ['FAKE_LIST_EXIT'] = '7'
        status, result = self.sequence([100, 101, 102, 103])
        self.assertEqual(status, 1)
        self.assertEqual(result['list_execution']['returncode'], 7)
        self.assertEqual(result['list_controller']['returncode'], 7)
        self.assertFalse((self.directory / 'test-controller-launch.json').exists())

    def test_original_failed_just_is_preserved(self):
        os.environ['FAKE_TEST_EXIT'] = '9'
        status, result = self.sequence([100, 101, 102, 103, 104, 105])
        self.assertEqual(status, 1)
        self.assertEqual(result['test_execution']['returncode'], 9)
        self.assertTrue(result['native_test_child_started'])

    def test_source_change_between_phases_stops_before_just(self):
        changed = {**IDENTITY, 'status': ' M actual-source.rs'}
        status, result = self.sequence([100, 101, 102, 103], [IDENTITY, changed, changed])
        self.assertEqual(status, 1)
        self.assertTrue(result['source_changed'])
        self.assertFalse((self.directory / 'test-controller-launch.json').exists())

    def test_listed_binary_change_during_just_fails_closed(self):
        os.environ['FAKE_MUTATE_BINARY'] = '1'
        status, result = self.sequence([100, 101, 102, 103, 104, 105])
        self.assertEqual(status, 1)
        self.assertEqual(result['test_execution']['returncode'], 0)
        self.assertIn('binary changed', result['error'])

    def test_actual_natural_wait_has_no_parent_signal_or_kill(self):
        os.environ['FAKE_CHILD_DELAY'] = '0.05'
        with patch.object(GATE, 'source_identity', return_value=IDENTITY), \
             contextlib.redirect_stdout(io.StringIO()):
            status = GATE.sequence(self.repo, self.records, SOURCE)
        result = json.loads((self.directory / 'result.json').read_text())
        self.assertEqual(status, 0)
        self.assertGreaterEqual(result['elapsed_seconds'], 0.1)
        self.assertFalse(result['parent_signal_or_kill'])


class CollectorAndActualPredicates(Fixture):
    def collector_fixture(self, command, output_name):
        from datetime import datetime, timezone
        now = time.time()
        before = {'commit': SOURCE, 'tree': TREE, 'dirty': False}
        record = {'schema_version': 1, 'source_sha': SOURCE, 'tested_sha': SOURCE,
                  'lane': 'source-head', 'before': before, 'after': before,
                  'command': command, 'started_at': datetime.fromtimestamp(now-10,timezone.utc).isoformat(),
                  'finished_at': datetime.fromtimestamp(now+10,timezone.utc).isoformat(),
                  'observed_passed_tests': 11, 'observed_failed_tests': 0,
                  'status': 'passed', 'exit_code': 0, 'command_exit_code': 0,
                  'synthetic_fixture_not_native_evidence': True}
        execution = self.records / (output_name + '.execution.json')
        execution.write_text(json.dumps(record))
        xml = self.records / (output_name + '.input.xml')
        xml.write_text('<testsuite>'+''.join('<testcase name="'+x+'"/>' for x in GATE.EXPECTED_NAMES)+'</testsuite>')
        with contextlib.redirect_stdout(io.StringIO()):
            status = COLLECT.collect(execution, xml, self.records/(output_name+'.xml'))
        return status, json.loads((self.records/(output_name+'.summary.json')).read_text())

    def test_real_original_collector_rejects_frozen_v1_wrapper_command(self):
        status, result = self.collector_fixture(['python3','list_run_gate.py','--'], 'v1-rejected')
        self.assertEqual(status, 1)
        self.assertEqual(result['status'], 'rejected')
        self.assertIn('clean source-head test', result['error'])

    def test_real_original_collector_accepts_true_just_command_shape(self):
        status, result = self.collector_fixture(GATE.ORIGINAL_TEST_COMMAND, 'v2-shape')
        self.assertEqual(status, 0)
        self.assertEqual(result['total_testcases'], 11)

    def test_parent_budget_failure_remains_failure_when_collector_shape_passes(self):
        status, result = self.sequence([100, 101, 102, 103, 7300, 7301])
        collector, _ = self.collector_fixture(GATE.ORIGINAL_TEST_COMMAND, 'expired-child')
        self.assertEqual(collector, 0)
        self.assertEqual(status, 1)
        self.assertTrue(result['budget_expired'])

    def test_real_prepare_acceptance_expression_rejects_expired_parent(self):
        source = (ROOT/'v2-candidate/prepare-driver.py').read_text()
        candidates = [n.value for n in ast.walk(ast.parse(source))
                      if isinstance(n,ast.Assign) and len(n.targets)==1
                      and isinstance(n.targets[0],ast.Subscript)
                      and isinstance(n.targets[0].value,ast.Name)
                      and n.targets[0].value.id=='list_admission'
                      and isinstance(n.targets[0].slice,ast.Constant) and n.targets[0].slice.value=='exact']
        self.assertEqual(len(candidates),1)
        code=compile(ast.Expression(candidates[0]),'<actual-v2-prepare-list-expression>','eval')
        record={'native_test_child_started':True,'exit_code':0,'status':'original-test-returned-zero',
                'budget_seconds':7200,'budget_expired':False,'parent_signal_or_kill':False,
                'finished_monotonic':100,'absolute_end_monotonic':200,
                'list_execution':{'returncode':0},'test_execution':{'returncode':0,'command':GATE.ORIGINAL_TEST_COMMAND},
                'source_before':IDENTITY,'source_after':IDENTITY}
        context={'listed':GATE.EXPECTED_NAMES,'CONFIG':{'required_names':GATE.EXPECTED_NAMES},
                 'list_coverage':{'exact_selected_names':True},'list_result':record}
        self.assertTrue(eval(code,{},context))
        record['budget_expired']=True;self.assertFalse(eval(code,{},context))
        record['budget_expired']=False;record['finished_monotonic']=200;self.assertFalse(eval(code,{},context))
        record['finished_monotonic']=100;record['test_execution']['command']=['python3','wrapper'];self.assertFalse(eval(code,{},context))

    def test_original_collector_source_blob_and_no_signal_or_record_rewrite_in_gate(self):
        path=ROOT/'exact-source-tools/scripts/hepta_ci_junit.py';b=path.read_bytes()
        self.assertEqual(hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),'683626df091bdfe160a8965fdc92bf40f5783cf8')
        source=(ROOT/'v2-candidate/list_run_gate.py').read_text();tree=ast.parse(source)
        calls=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        for forbidden in ['kill','killpg','send_signal','terminate','settrace']:
            self.assertNotIn(forbidden,calls)
        self.assertIn("record = json.loads(execution_path.read_text()",source)
        self.assertNotIn('execution_path.write',source)
        self.assertNotIn('execution_path.open(',source)

    def test_actual_list_parser_rejects_missing_extra_duplicate_and_ignored_cases(self):
        import copy
        suite={'status':'listed','package-name':'codex-hepta-agentd','kind':'lib',
               'binary-id':'one','binary-path':str(self.binary),
               'testcases':{name:{'ignored':False,'filter-match':{'status':'matches'}} for name in GATE.EXPECTED_NAMES}}
        valid={'test-count':11,'rust-suites':{'one':suite}}
        self.assertTrue(GATE.selected_cases(valid,GATE.EXPECTED_NAMES)['exact_selected_names'])
        variants=[]
        missing=copy.deepcopy(valid);missing['rust-suites']['one']['testcases'].pop(GATE.EXPECTED_NAMES[-1]);missing['test-count']=10;variants.append(missing)
        extra=copy.deepcopy(valid);extra['rust-suites']['one']['testcases']['unrequested-case']={'ignored':False,'filter-match':{'status':'matches'}};extra['test-count']=12;variants.append(extra)
        duplicate=copy.deepcopy(valid);duplicate['rust-suites']['two']=copy.deepcopy(suite);duplicate['rust-suites']['two']['binary-id']='two';duplicate['test-count']=22;variants.append(duplicate)
        ignored=copy.deepcopy(valid);ignored['rust-suites']['one']['testcases'][GATE.EXPECTED_NAMES[0]]['ignored']=True;variants.append(ignored)
        for variant in variants:
            with self.assertRaises(ValueError):GATE.selected_cases(variant,GATE.EXPECTED_NAMES)
        with self.assertRaises(ValueError):json.loads('{"same":1,"same":2}',object_pairs_hook=GATE.unique_object)

    def test_actual_prepare_junit_block_requires_eleven_unique_clean_cases(self):
        import xml.etree.ElementTree as ET
        tree=ast.parse((ROOT/'v2-candidate/prepare-driver.py').read_text())
        candidates=[n for n in ast.walk(tree) if isinstance(n,ast.If)
                    and isinstance(n.test,ast.Call) and isinstance(n.test.func,ast.Attribute)
                    and isinstance(n.test.func.value,ast.Name) and n.test.func.value.id=='report'
                    and n.test.func.attr=='is_file']
        self.assertEqual(len(candidates),1)
        code=compile(ast.Module(body=candidates,type_ignores=[]),'<actual-v2-junit-block>','exec')
        def evaluate(names, child=''):
            report=self.records/'synthetic-junit.xml'
            report.write_text('<testsuite>'+''.join('<testcase name="'+name+'">'+(child if i==0 else '')+'</testcase>' for i,name in enumerate(names))+'</testsuite>')
            scope={'report':report,'checks':[],'coverage':{},'ET':ET,
                   'CONFIG':{'required_names':GATE.EXPECTED_NAMES},
                   'sha':lambda p:hashlib.sha256(p.read_bytes()).hexdigest()}
            exec(code,scope)
            return scope['coverage']['exact_pass_coverage']
        self.assertTrue(evaluate(GATE.EXPECTED_NAMES))
        self.assertFalse(evaluate(GATE.EXPECTED_NAMES[:-1]+[GATE.EXPECTED_NAMES[0]]))
        self.assertFalse(evaluate(GATE.EXPECTED_NAMES+['unrequested-case']))
        for child in ['<failure/>','<error/>','<skipped/>','<flakyFailure/>','<rerunError/>']:
            self.assertFalse(evaluate(GATE.EXPECTED_NAMES,child))

    def test_actual_prepare_exception_always_restores_nonzero_exit(self):
        from types import SimpleNamespace
        tree=ast.parse((ROOT/'v2-candidate/prepare-driver.py').read_text())
        handlers=[n for n in ast.walk(tree) if isinstance(n,ast.ExceptHandler)
                  and 'native_result_file_observed' in ast.unparse(n)]
        self.assertEqual(len(handlers),1)
        code=compile(ast.Module(body=handlers[0].body,type_ignores=[]),'<actual-v2-exception-body>','exec')
        scope={'exit_code':0,'result':{},'error':RuntimeError('synthetic post-check interruption'),
               'NATIVE':self.records,'RECORDS':self.records,
               'traceback':SimpleNamespace(print_exc=lambda:None)}
        exec(code,scope)
        self.assertEqual(scope['exit_code'],1)
        self.assertEqual(scope['result']['status'],'failed')


if __name__ == '__main__':
    unittest.main(verbosity=2)
