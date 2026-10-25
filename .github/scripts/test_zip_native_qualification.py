import json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest import mock
import zip_native_qualification as q
import zip_native_owned as support
class PolicyTests(unittest.TestCase):
    def tearDown(self):q.DEADLINE=None;q.FINALIZING=False;support.OWNERSHIP_UNCERTAIN=False
    def test_commands_locked_targeted_full_metadata_offline(self):
        commands=q.command_plan(Path('/source'),Path('/temp'))
        cargo=[x for x in commands if x[0]=='cargo' and x[2]=='metadata' or x[0]=='cargo' and x[2:4] in [['nextest','list'],['nextest','run']]]
        self.assertEqual(len(cargo),6)
        for x in cargo:
            self.assertIn('--locked',x);self.assertIn('--all-features',x)
            self.assertNotIn('--filter-platform',x);self.assertNotIn('--no-deps',x)
            self.assertNotIn('update',x)
        self.assertEqual(sum('--offline' in x for x in cargo),3)
        for x in cargo:
            if 'nextest' in x:
                self.assertIn('codex-core-plugins',x);self.assertIn('test(startup_sync::tests::)',x);self.assertIn('--lib',x)
            if 'run' in x:
                self.assertEqual(x[x.index('--retries')+1],'0')
                self.assertEqual(x[x.index('--no-tests')+1],'fail')

    def test_deadline_exhaustion_no_launch_and_reserve(self):
        q.DEADLINE=100
        with mock.patch.object(q.time,'monotonic',return_value=95),mock.patch.object(support,'capture',side_effect=AssertionError('no launch')):
            with self.assertRaises(q.Hold):q.capture(['never'],{},10,[],Path('/tmp'))
        q.FINALIZING=True
        with mock.patch.object(q.time,'monotonic',return_value=95),mock.patch.object(support,'capture',return_value=({'exit':0,'stop':None,'cleanup':{'confirmed':True}},[])) as call:
            q.capture(['cleanup'],{},10,[],Path('/tmp'));self.assertEqual(call.call_count,1)
    def test_denial_no_retry(self):
        q.DEADLINE=time.monotonic()+100
        with mock.patch.object(support,'capture',side_effect=PermissionError('secret')) as call:
            with self.assertRaises(PermissionError):q.capture(['fixed'],{},10,[],Path('/tmp'))
            self.assertEqual(call.call_count,1)
    def test_v8_graph_rejection_and_ambiguity(self):
        safe=b'[[package]]\nname="codex-core-plugins"\nversion="0.0.0"\ndependencies=["leaf"]\n[[package]]\nname="leaf"\nversion="1.0.0"\n'
        self.assertEqual(q.no_v8(safe),2)
        with self.assertRaises(q.Hold):q.no_v8(safe.replace(b'leaf',b'v8'))
        with self.assertRaises(q.Hold):q.no_v8(safe+b'[[package]]\nname="leaf"\nversion="2.0.0"\n')
    def test_output_boundary_source_contract(self):
        s=Path(q.__file__).read_text()
        self.assertNotIn('write_bytes(stream',s);self.assertNotIn('taskkill',s)
        self.assertIn("report['locks_before']==report['locks_after']",s)
        self.assertIn("return 0 if report['qualified'] else 125",s)
        self.assertIn("require(sys.platform=='linux')",s)
        workflow=Path(q.__file__).parent.parent/'workflows/zip-owner-native.yml'
        text=workflow.read_text();self.assertNotIn('workflow_dispatch:',text);self.assertNotIn('windows-',text)
        self.assertLess(text.index('ZIP_STARTED_MONOTONIC_NS'),text.index('uses: actions/checkout'))

DRIVER = '''import sys,json,os
sys.path.insert(0,sys.argv[1]);import zip_native_owned as s
r,streams=s.capture(json.loads(sys.argv[2]),dict(os.environ),float(sys.argv[3]))
r['retained']=[x.retained().decode(errors='replace') for x in streams]
print(json.dumps(r))
'''


class AdoptedChildEvidence(unittest.TestCase):
    def detached(self, exit_status, lifetime, cleanup_timeout=5):
        driver = DRIVER.replace("r,streams=s.capture", 
            "original=s._cleanup_owned\ns._cleanup_owned=lambda p:original(p,"+str(cleanup_timeout)+")\nr,streams=s.capture")
        child = ('import os,time,sys;from pathlib import Path;os.setsid();'
                 'Path(sys.argv[1]).write_text(str(os.getpid()));'
                 'os.close(1);os.close(2);time.sleep('+str(lifetime)+');sys.exit('+str(exit_status)+')')
        leader = ('import subprocess,sys,time;from pathlib import Path;'
                  'subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]]);'
                  '\nwhile not Path(sys.argv[2]).exists():time.sleep(.005)')
        with tempfile.TemporaryDirectory() as root:
            pidfile=Path(root)/'pid'
            sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(4)'])
            try:
                result=subprocess.run([sys.executable,'-c',driver,str(Path(support.__file__).parent),
                    json.dumps([sys.executable,'-c',leader,child,str(pidfile)]),'3'],
                    capture_output=True,text=True,timeout=8,check=True)
                self.assertIsNone(sentinel.poll())
                return json.loads(result.stdout),int(pidfile.read_text())
            finally:
                sentinel.terminate();sentinel.wait(timeout=5)

    def test_real_detached_zero_exit_is_observed_exactly_reaped_without_signal(self):
        result,pid=self.detached(0,.15)
        self.assertTrue(result['cleanup']['confirmed'],result)
        self.assertEqual(result['exit'],0)
        self.assertEqual(result['cleanup']['signal_attempts'],['SIGKILL'])
        self.assertEqual(result['cleanup']['adopted_terminal_events'],
                         [{'pid':pid,'uid':os.getuid(),'status':{'kind':'exited','value':0}}])
        self.assertTrue(result['ownership']['initial_children_absent'])
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)

    def test_real_detached_nonzero_reaped_but_holds(self):
        result,pid=self.detached(17,.15)
        self.assertFalse(result['cleanup']['confirmed'])
        self.assertEqual(result['cleanup']['error'],'adopted_helper_unsuccessful')
        self.assertEqual(result['cleanup']['adopted_terminal_events'][0]['status']['value'],17)
        self.assertIsNone(result['exit'])
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)

    def test_real_detached_live_timeout_not_signalled(self):
        result,pid=self.detached(0,1,.15)
        self.assertFalse(result['cleanup']['confirmed'])
        self.assertEqual(result['cleanup']['error'],'adopted_children_deadline')
        self.assertEqual(result['cleanup']['adopted_terminal_events'],[])
        self.assertEqual(result['cleanup']['signal_attempts'],['SIGKILL'])
        os.kill(pid,0)  # Still live after supervisor stopped: never signalled.
        time.sleep(1.05)  # It exits naturally; no cleanup signal to outside group.

    def event(self,status=0):
        from types import SimpleNamespace
        return SimpleNamespace(si_pid=43210,si_uid=os.getuid(),si_code=os.CLD_EXITED,si_status=status)

    def test_exact_reaping_pid_and_status_mismatch_hold(self):
        for value in [(43211,0),(43210,1<<8),(0,0)]:
            with mock.patch.object(support.os,'waitid',return_value=self.event()),                  mock.patch.object(support.os,'waitpid',return_value=value) as reap,                  mock.patch.object(support.os,'kill',side_effect=AssertionError('No signal')):
                receipt={}
                self.assertFalse(support._observe_and_reap_adopted(receipt,time.monotonic()+1))
                self.assertEqual(receipt['error'],'adopted_reap_identity_unconfirmed')
                reap.assert_called_once_with(43210,os.WNOHANG)

    def test_wait_and_reap_denial_once_no_retry(self):
        for which in ('waitid','waitpid'):
            with mock.patch.object(support.os,'waitid',return_value=self.event()) as wait,                  mock.patch.object(support.os,'waitpid',return_value=(43210,0)) as reap:
                denied=wait if which=='waitid' else reap
                denied.side_effect=PermissionError('secret-denial')
                receipt={}
                self.assertFalse(support._observe_and_reap_adopted(receipt,time.monotonic()+1))
                self.assertEqual(denied.call_count,1)
                self.assertNotIn('secret',json.dumps(receipt))
                if which=='waitid':reap.assert_not_called()

    def test_assumptions_fail_before_launch(self):
        for target,value in [('active_count',2),('current_thread',object())]:
            with mock.patch.object(support.threading,target,return_value=value),                  mock.patch.object(support.subprocess,'Popen',side_effect=AssertionError('No launch')):
                result,_=support.capture(['never'],{},1)
                self.assertFalse(result['cleanup']['confirmed'])
        with mock.patch.object(support.signal,'getsignal',return_value=signal.SIG_IGN),              mock.patch.object(support.subprocess,'Popen',side_effect=AssertionError('No launch')):
            result,_=support.capture(['never'],{},1)
            self.assertFalse(result['cleanup']['confirmed'])

    def test_unsupported_terminal_uid_holds_without_reap(self):
        event=self.event();event.si_uid=os.getuid()+1
        with mock.patch.object(support.os,'waitid',return_value=event),              mock.patch.object(support.os,'waitpid',side_effect=AssertionError('No reap')):
            receipt={}
            self.assertFalse(support._observe_and_reap_adopted(receipt,time.monotonic()+1))
            self.assertEqual(receipt['error'],'adopted_terminal_identity_unsupported')



def list_fixture(names):
    return {'rust-suites':{'codex-core-plugins':{'binary-id':'codex-core-plugins','status':'listed',
        'testcases':{name:{'ignored':False,'filter-match':{'status':'matches'}} for name in names}}}}

def junit_fixture(names):
    import xml.etree.ElementTree as ET
    root=ET.Element('testsuites',{'name':'zip-owner','tests':str(len(names)),'failures':'0','errors':'0'})
    suite=ET.SubElement(root,'testsuite',{'name':'codex-core-plugins','tests':str(len(names)),'failures':'0','errors':'0','disabled':'0'})
    for name in names:ET.SubElement(suite,'testcase',{'name':name,'classname':'codex-core-plugins','timestamp':'2026-10-25T00:00:00Z','time':'0.1'})
    return ET.tostring(root)

class NativeEvidenceTests(unittest.TestCase):
    def setUp(self):self.expected=['startup_sync::tests::a','startup_sync::tests::b']
    def test_list_exact_nonignored(self):
        value=q.validate_list(json.dumps(list_fixture(self.expected)).encode(),self.expected)
        self.assertEqual(value['count'],2)
    def test_list_zero_missing_extra_ignored_wrong_suite(self):
        for kind in ['zero','missing','extra','ignored','suite','unlisted','filter']:
            value=list_fixture(self.expected);suite=value['rust-suites']['codex-core-plugins'];cases=suite['testcases']
            if kind=='zero':cases.clear()
            if kind=='missing':cases.pop(self.expected[0])
            if kind=='extra':cases['unexpected']={'ignored':False,'filter-match':{'status':'matches'}}
            if kind=='ignored':cases[self.expected[0]]['ignored']=True
            if kind=='suite':suite['binary-id']='wrong'
            if kind=='unlisted':suite['status']='not-listed'
            if kind=='filter':cases[self.expected[0]]['filter-match']['status']='mismatch'
            with self.subTest(kind=kind),self.assertRaises(q.Hold):q.validate_list(json.dumps(value).encode(),self.expected)
    def test_duplicate_json_nonfinite_and_overlong_rejected(self):
        for data in [b'{"rust-suites":{},"rust-suites":{}}',b'{"x":1e999}',b'{"x":-1e999}',b'{"x":NaN}',b' '*1048577]:
            with self.assertRaises(q.Hold):q.validate_list(data,self.expected)
    def test_junit_exact(self):
        self.assertEqual(q.validate_junit(junit_fixture(self.expected),self.expected)['count'],2)
    def test_junit_zero_missing_duplicate_extra_skip_failure_error_retry(self):
        import xml.etree.ElementTree as ET
        for kind in ['zero','missing','duplicate','extra','skip','failure','error','retry','status','count','class','nonfinite','doctype']:
            root=ET.fromstring(junit_fixture(self.expected));suite=root[0]
            if kind=='zero':suite.clear()
            if kind=='missing':suite.remove(suite[0])
            if kind=='duplicate':suite[1].set('name',self.expected[0])
            if kind=='extra':suite[1].set('name','unexpected')
            if kind in ['skip','failure','error','retry']:ET.SubElement(suite[0],{'skip':'skipped','retry':'rerunFailure'}.get(kind,kind)).text='private failure prose'
            if kind=='status':suite[0].set('status','skipped')
            if kind=='count':root.set('tests','0')
            if kind=='class':suite[0].set('classname','wrong')
            if kind=='nonfinite':suite[0].set('time','inf')
            data=ET.tostring(root)
            if kind=='doctype':data=b'<!DOCTYPE root [<!ENTITY a "b">]>'+data
            with self.subTest(kind=kind),self.assertRaises(q.Hold):q.validate_junit(data,self.expected)
    def test_selected_central_guard_source_binding_and_prewrite_order(self):
        here=Path(q.__file__).parent
        source=(here.parents[1]/'codex-rs/core-plugins/src/startup_sync.rs').read_text()
        extract=source[source.index('fn extract_zipball_to_dir('):source.index('fn ordinary_zip_permissions(')]
        self.assertLess(extract.index('validate_selected_zip_central_directory('),extract.index('for index in 0..archive.len()'))
        self.assertIn('bytes,',extract);self.assertIn('archive.central_directory_start()',extract);self.assertIn('archive.len()',extract)
        guard=source[source.index('fn validate_selected_zip_central_directory('):source.index('fn extract_zipball_to_dir(')]
        for invariant in ['usize::try_from(directory_start)','visible_count > (bytes.len() - position) / 46','position.checked_add(46)','bytes.get(position..fixed_end)','[28, 30, 32]','end.checked_add(length)','end > bytes.len() || end <= position','bytes[position..].starts_with']:
            self.assertIn(invariant,guard)
        self.assertNotIn('.windows(',guard);self.assertNotIn('unsafe',guard)
    def test_exact_linux_source_inventory_and_base_config_preserved(self):
        here=Path(q.__file__).parent;policy=json.loads((here/'zip_native_policy.json').read_text())
        source=here.parents[1]/'codex-rs/core-plugins/src/startup_sync_tests.rs'
        self.assertEqual(q.source_inventory(source.read_text()),policy['tests']);self.assertEqual(len(policy['tests']),36)
        config=(here/'zip_native_nextest.toml').read_bytes();base=config[:-len(q.PROFILE_APPENDIX.encode())]
        self.assertTrue(config.endswith(q.PROFILE_APPENDIX.encode()));self.assertEqual(q.blob(base),q.NEXTTEST_BASE_BLOB)
        parsed=q.tomllib.loads(config.decode());self.assertEqual(parsed['profile']['default']['retries'],1);self.assertEqual(parsed['profile']['zip-owner']['retries'],0)
        self.assertNotIn('store-success-output = true',config.decode())

class HarnessTests(unittest.TestCase):
    def exercise(self,fault=None):
        import shutil
        from types import SimpleNamespace
        candidate=Path(q.__file__).parents[2]
        workspace=candidate.parents[1]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);control=root/'control';source=root/'source'
            policy=json.loads((candidate/'.github/scripts/zip_native_policy.json').read_text())
            for name in q.CONTROL+[x['path'] for x in policy['source_files']]:
                path=control/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((candidate/name).read_bytes())
            for item in policy['source_files']:
                proof=workspace/'remaining-security-source-c01cc-20261025T0622Z/proof'/('remaining-local-'+item['path'].replace('/','__')+'.json')
                # In CI these proof files do not exist: use git-bound source files
                # supplied by the exact baseline checkout instead (test fixtures only).
                if proof.exists():data=json.loads(proof.read_text())['content'].encode()
                else:
                    fixture=Path(os.environ['GITHUB_WORKSPACE'])/'source'/item['path']
                    data=fixture.read_bytes()
                path=source/item['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            for name in policy['locks']:
                local=workspace/'tls-production-locks-e4ee-20261025T0453Z/candidate'/name
                if not local.exists():local=Path(os.environ['GITHUB_WORKSPACE'])/'source'/name
                path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(local.read_bytes())
            profile=(control/'.github/scripts/zip_native_nextest.toml').read_bytes()
            config=source/'codex-rs/.config/nextest.toml';config.parent.mkdir(parents=True,exist_ok=True);config.write_bytes(profile[:-len(q.PROFILE_APPENDIX.encode())])
            (source/'.git').mkdir();(source/'.git/config').write_text('')
            original={x['path']:q.sha((source/x['path']).read_bytes()) for x in policy['source_files']}
            original.update({name:q.sha((source/name).read_bytes()) for name in policy['locks']})
            original['codex-rs/.config/nextest.toml']=q.sha(config.read_bytes())
            expected=dict(original);expected.update({x['path']:x['sha256'] for x in policy['source_files']})
            event='d'*40;calls=[];snapshots=[]
            def snapshot(*args):
                snapshots.append(1)
                if len(snapshots)==1:return dict(original)
                value=dict(expected)
                if len(snapshots)==3 and fault=='source':value['unexpected']='changed'
                return value
            def git(repo,env,records,disk,*args):
                if args[0]=='status':
                    if repo==source and snapshots:return ''.join(' M '+x['path']+'\n' for x in policy['source_files']).encode()
                    return b''
                if args[0]=='diff':return ('\n'.join(q.CONTROL+[x['path'] for x in policy['source_files']])+'\n').encode()
                target=args[1]
                if target=='HEAD':return (event if repo==control else q.BASE).encode()
                if target=='HEAD^':return q.BASE.encode()
                if target=='HEAD^{tree}':return ('a'*40 if repo==control else q.BASE_TREE).encode()
                if target.startswith('HEAD:'):return q.blob((repo/target[5:]).read_bytes()).encode()
                raise AssertionError(args)
            def capture(argv,env,maximum,records,disk):
                calls.append(argv)
                self.assertEqual(Path.cwd(),source/'codex-rs')
                record={'argv':argv,'exit':0,'stop':None,'cleanup':{'confirmed':True},'streams':[]};records.append(record)
                raw=b'token=private_never_export_this\n'
                if argv[0]=='rustc':raw=b'rustc 1.95.0 (fixture)\n'
                if argv[0]=='cargo' and argv[2]=='--version':raw=b'cargo 1.95.0 (fixture)\n'
                if argv[0]=='cargo' and argv[2:]==['nextest','--version']:raw=b'cargo-nextest 0.9.103 (fixture)\n'
                if 'nextest' in argv and 'list' in argv:raw=json.dumps(list_fixture([] if fault=='zero-tests' else policy['tests'])).encode()
                if 'nextest' in argv and 'run' in argv:
                    report=root/'run/target/nextest/zip-owner/junit.xml';report.parent.mkdir(parents=True,exist_ok=True);report.write_bytes(junit_fixture(policy['tests']))
                    if fault=='missing-junit':report.unlink()
                    if fault=='retry-junit':report.write_bytes(report.read_bytes().replace(b'</testcase>',b'<rerunFailure>private failure prose</rerunFailure></testcase>',1).replace(b' />',b'><rerunFailure>private failure prose</rerunFailure></testcase>',1))
                    if fault=='command':record['exit']=1;raise q.Hold()
                    if fault=='lock':(source/'codex-rs/Cargo.lock').write_text('changed')
                    if fault=='control':(control/'.github/scripts/zip_native_policy.json').write_text('changed')
                    if fault=='cleanup':support.OWNERSHIP_UNCERTAIN=True
                return [SimpleNamespace(count=len(raw),retained=lambda:raw)]
            env={'GITHUB_EVENT_NAME':'push','GITHUB_REF':'refs/heads/'+q.BRANCH,
                 'GITHUB_SHA':event,'GITHUB_WORKFLOW_SHA':event,
                 'GITHUB_WORKFLOW_REF':'TrillionniumFoundation/hepta-private-ci/'+q.WORKFLOW+'@refs/heads/'+q.BRANCH,
                 'ZIP_STARTED_MONOTONIC_NS':str(time.monotonic_ns())}
            support.OWNERSHIP_UNCERTAIN=False
            with mock.patch.dict(os.environ,env),mock.patch.object(q,'git',side_effect=git),mock.patch.object(q,'snapshot',side_effect=snapshot),mock.patch.object(q,'capture',side_effect=capture),mock.patch.object(q.shutil,'disk_usage',return_value=SimpleNamespace(free=30*1024**3)):
                code=q.main(control,source,root/'run')
            output=(root/'run/public/receipt.json').read_text()
            self.assertNotIn('private_never_export_this',output)
            self.assertEqual([x.name for x in (root/'run/public').iterdir()],['receipt.json'])
            support.OWNERSHIP_UNCERTAIN=False;q.DEADLINE=None;q.FINALIZING=False
            return code,json.loads(output),calls
    def test_mock_complete_success_and_raw_never_published(self):
        code,report,calls=self.exercise();self.assertEqual(code,0);self.assertTrue(report['qualified'])
        self.assertEqual(len(calls),11);self.assertEqual(report['locks_before'],report['locks_after'])
        self.assertEqual([p['junit']['count'] for p in report['test_phases']],[36,36])
        self.assertEqual(report['config_before'],report['config_after'])
    def test_mock_command_source_control_lock_cleanup_hold(self):
        for fault in ['command','source','control','lock','cleanup','zero-tests','missing-junit','retry-junit']:
            with self.subTest(fault=fault):
                code,report,_=self.exercise(fault);self.assertEqual(code,125);self.assertFalse(report['qualified'])

if __name__=='__main__':unittest.main()

