import json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest import mock
import zip_native_qualification as q
import zip_native_owned as support
class PolicyTests(unittest.TestCase):
    def tearDown(self):q.DEADLINE=None;q.FINALIZING=False;q.FINAL_READ_REPOS=frozenset();q.GIT_ADMIN_BASELINES={};q.CARGO_CONFIG_BASELINE=None;q.CARGO_CONFIG_PATHS=[];support.OWNERSHIP_UNCERTAIN=False
    def test_admin_preflight_spends_absolute_work_and_final_deadline(self):
        for final in [False,True]:
            for exhausted in [False,True]:
                with self.subTest(final=final,exhausted=exhausted):
                    q.DEADLINE=100;q.FINALIZING=final
                    q.FINAL_READ_REPOS=frozenset({'/source'});q.GIT_ADMIN_BASELINES={'/source':{}}
                    clock=[250 if final else 80]
                    def admin(repo):
                        clock[0]=(270 if final else 90) if exhausted else (269 if final else 89)
                        return {}
                    with mock.patch.object(q.time,'monotonic',side_effect=lambda:clock[0]),mock.patch.object(q,'git_admin_snapshot',side_effect=admin),mock.patch.object(support,'capture',return_value=({'exit':0,'stop':None,'cleanup':{'confirmed':True}},[])) as launch:
                        if exhausted:
                            with self.assertRaises(q.Hold):q.capture(['git','-C','/source','status','--porcelain','--untracked-files=all'],{},20,[],Path('/tmp'))
                            launch.assert_not_called()
                        else:
                            q.capture(['git','-C','/source','status','--porcelain','--untracked-files=all'],{},20,[],Path('/tmp'))
                            self.assertEqual(launch.call_args.args[2],1)

    def test_pinned_checkout_gc_and_exact_tracking_config(self):
        base=b'[core]\n repositoryformatversion = 0\n bare = false\n'
        gc=b'[gc]\n auto = 0\n'
        branch=('[branch "'+q.BRANCH+'"]\n remote = origin\n merge = refs/heads/'+q.BRANCH+'\n').encode()
        for suffix in [b'',gc,branch,gc+branch]:
            self.assertEqual(q.strict_git_config(base+suffix),q.sha(base+suffix))

    def test_checkout_config_allowance_does_not_expand_other_keys_or_values(self):
        base=b'[core]\n repositoryformatversion = 0\n bare = false\n'
        good=('[branch "'+q.BRANCH+'"]\n remote = origin\n merge = refs/heads/'+q.BRANCH+'\n').encode()
        bad=[b'[gc]\n auto = 1\n',b'[gc]\n auto = -1\n',b'[gc]\n auto = 0\n autopacklimit = 0\n',
             good.replace(b'remote = origin',b'remote = elsewhere'),
             good.replace(('merge = refs/heads/'+q.BRANCH).encode(),b'merge = refs/heads/main'),
             good.replace(q.BRANCH.encode(),b'other-branch'),
             good.replace(b' remote = origin\n',b''),
             good.replace((' merge = refs/heads/'+q.BRANCH+'\n').encode(),b''),
             good+b' rebase = true\n',b'[include]\n path = /tmp/forbidden\n',
             base,b'[core]\n fsmonitor = forbidden\n']
        for suffix in bad:
            with self.subTest(suffix=suffix),self.assertRaises(q.Hold):q.strict_git_config(base+suffix)

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
                self.assertEqual(x[x.index('--cargo-profile')+1],'dev-small')
                self.assertIn('codex-core-plugins',x);self.assertIn('test(startup_sync::tests::)',x);self.assertIn('--lib',x)
            if 'run' in x:
                self.assertEqual(x[x.index('--retries')+1],'0')
                self.assertEqual(x[x.index('--no-tests')+1],'fail')

    def test_deadline_exhaustion_no_launch_and_reserve(self):
        q.DEADLINE=100
        with mock.patch.object(q.time,'monotonic',return_value=95),mock.patch.object(support,'capture',side_effect=AssertionError('no launch')):
            with self.assertRaises(q.Hold):q.capture(['never'],{},10,[],Path('/tmp'))
        q.FINALIZING=True
        with mock.patch.object(q.time,'monotonic',return_value=95),mock.patch.object(q,'git_admin_snapshot',return_value={}),mock.patch.object(support,'capture',return_value=({'exit':0,'stop':None,'cleanup':{'confirmed':True}},[])) as call:
            q.FINAL_READ_REPOS=frozenset({'/source'});q.GIT_ADMIN_BASELINES={'/source':{}};q.capture(['git','-C','/source','ls-files','-z'],{},10,[],Path('/tmp'));self.assertEqual(call.call_count,1)
    def test_final_reads_bypass_only_build_disk_gate(self):
        q.DEADLINE=time.monotonic()-30;q.FINALIZING=True;q.FINAL_READ_REPOS=frozenset({'/source','/control'});q.GIT_ADMIN_BASELINES={'/source':{},'/control':{}}
        records=[];environment={'GIT_OPTIONAL_LOCKS':'1'}
        def capture(argv,env,seconds,disk):
            self.assertIsNone(disk);self.assertEqual(env['GIT_OPTIONAL_LOCKS'],'0');self.assertGreater(seconds,0)
            self.assertEqual(argv[1:1+len(q.GIT_SAFE_FLAGS)],q.GIT_SAFE_FLAGS)
            self.assertEqual(env['GIT_NO_LAZY_FETCH'],'1');self.assertEqual(env['GIT_NO_REPLACE_OBJECTS'],'1')
            return {'exit':0,'stop':None,'cleanup':{'confirmed':True}},[]
        with mock.patch.object(q,'git_admin_snapshot',return_value={}),mock.patch.object(support,'capture',side_effect=capture) as call:
            for repo in ['/source','/control']:
                for args in q.FINAL_GIT_READS:q.capture(['git','-C',repo,*args],environment,20,records,Path('/disk'))
            self.assertEqual(call.call_count,8)
        self.assertEqual(environment['GIT_OPTIONAL_LOCKS'],'1');self.assertTrue(all(r['final_readonly'] for r in records))
    def test_final_nonread_commands_unknown_paths_cleanup_and_expired_reserve_rejected(self):
        q.DEADLINE=time.monotonic();q.FINALIZING=True;q.FINAL_READ_REPOS=frozenset({'/source'})
        with mock.patch.object(support,'capture',side_effect=AssertionError('must not launch')):
            for argv in [['cargo','test'],['cargo','metadata'],['git','-C','/source','gc'],['git','-C','/source','status','--short'],['git','-C','/outside','ls-files','-z']]:
                with self.assertRaises(q.Hold):q.capture(argv,{},20,[],Path('/disk'))
            support.OWNERSHIP_UNCERTAIN=True
            with self.assertRaises(q.Hold):q.capture(['git','-C','/source','ls-files','-z'],{},20,[],Path('/disk'))
            support.OWNERSHIP_UNCERTAIN=False;q.DEADLINE=time.monotonic()-200
            with self.assertRaises(q.Hold):q.capture(['git','-C','/source','ls-files','-z'],{},20,[],Path('/disk'))
    def test_final_denied_read_not_retried(self):
        q.DEADLINE=time.monotonic();q.FINALIZING=True;q.FINAL_READ_REPOS=frozenset({'/source'})
        q.GIT_ADMIN_BASELINES={'/source':{}}
        with mock.patch.object(q,'git_admin_snapshot',return_value={}),mock.patch.object(support,'capture',side_effect=PermissionError('private')) as call:
            with self.assertRaises(PermissionError):q.capture(['git','-C','/source','ls-files','-z'],{},20,[],Path('/disk'))
            self.assertEqual(call.call_count,1)
    def test_disk_observations_exact_thresholds_and_separate_causes(self):
        g=1024**3
        floor=support._disk_sample(10*g,3*g);self.assertTrue(floor['floor_breached']);self.assertFalse(floor['growth_breached'])
        growth=support._disk_sample(30*g,21*g);self.assertFalse(growth['floor_breached']);self.assertTrue(growth['growth_breached'])
        both=support._disk_sample(30*g,3*g);self.assertTrue(both['floor_breached']);self.assertTrue(both['growth_breached'])
        equal=support._disk_sample(12*g,4*g);self.assertFalse(equal['floor_breached']);self.assertFalse(equal['growth_breached'])
        later=support._disk_sample(10*g,5*g,floor);self.assertEqual(later['samples'],2);self.assertEqual(later['minimum_free_bytes'],3*g);self.assertEqual(later['maximum_growth_bytes'],7*g)
        self.assertTrue(all(type(v) in (int,bool) for v in later.values()))
        source=Path(support.__file__).read_text();self.assertIn("result['disk_observation'] = _disk_sample",source)
    def test_devsmall_does_not_modify_command_scope_or_source_profile(self):
        commands=q.command_plan(Path('/source'),Path('/temp'))
        selected=[a for a in commands if a[:3]==['cargo','+1.95.0','nextest'] and a[3] in ['list','run']]
        self.assertEqual(len(selected),4)
        for a in selected:
            self.assertEqual(a.count('--cargo-profile'),1);self.assertEqual(a[a.index('--cargo-profile')+1],'dev-small')
            self.assertIn('--all-features',a);self.assertIn('--locked',a);self.assertNotIn('--release',a)
        self.assertEqual(sum('--offline' in a for a in selected),2)
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

class GitAdminAndCargoIdentityTests(unittest.TestCase):
    def tearDown(self):
        q.DEADLINE=None;q.FINALIZING=False;q.GIT_ADMIN_BASELINES={};q.FINAL_READ_REPOS=frozenset()
        q.CARGO_CONFIG_BASELINE=None;q.CARGO_CONFIG_PATHS=[];support.OWNERSHIP_UNCERTAIN=False
    def fixture(self,root):
        repo=Path(root)/'repo'
        for directory in ['info','objects/info','objects/pack','refs']:(repo/'.git'/directory).mkdir(parents=True,exist_ok=True)
        (repo/'.git/config').write_text('[core]\nrepositoryformatversion = 0\nbare = false\n')
        (repo/'.git/HEAD').write_text('a'*40+'\n');(repo/'.git/index').write_bytes(b'index')
        return repo
    def test_strict_config_rejects_execution_include_protocol_promisor_and_unknown(self):
        safe=b'[core]\nrepositoryformatversion=0\nbare=false\n'
        q.strict_git_config(safe)
        for extra in [b'fsmonitor=/tmp/marker\n',b'hooksPath=/tmp/hooks\n',b'[filter "x"]\nprocess=marker\n',b'[include]\npath=/tmp/config\n',b'[remote "origin"]\npromisor=true\n',b'[submodule "x"]\nupdate=!marker\n',b'[core]\nunknown=true\n',b'[core]\nbare=false\n',b'[protocol "file"]\nallow=always\n']:
            with self.subTest(extra=extra),self.assertRaises(q.Hold):q.strict_git_config(safe+extra)
    def test_admin_paths_absence_identity_and_symlinks(self):
        for name in ['commondir','gitdir','config.worktree','objects/info/alternates','objects/info/http-alternates','objects/pack/x.promisor','refs/replace','info/grafts']:
            with tempfile.TemporaryDirectory() as td:
                repo=self.fixture(td);q.git_admin_snapshot(repo);path=repo/'.git'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('harmless')
                with self.subTest(name=name),self.assertRaises(q.Hold):q.git_admin_snapshot(repo)
        with tempfile.TemporaryDirectory() as td:
            repo=self.fixture(td);before=q.git_admin_snapshot(repo);(repo/'.git/HEAD').write_text('b'*40+'\n')
            self.assertNotEqual(q.git_admin_snapshot(repo),before)
            (repo/'.git/config').unlink();(repo/'.git/config').symlink_to(repo/'.git/HEAD')
            with self.assertRaises(q.Hold):q.git_admin_snapshot(repo)
    def test_cargo_missing_present_content_and_symlink_rechecked(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'config.toml';q.CARGO_CONFIG_PATHS=[path];q.CARGO_CONFIG_BASELINE=q.cargo_config_identity();q.recheck_cargo_config()
            path.write_text('[profile.dev-small]\noverflow-checks=false\n')
            with self.assertRaises(q.Hold):q.recheck_cargo_config()
            path.unlink();q.recheck_cargo_config();path.symlink_to(Path(td)/'missing')
            with self.assertRaises(q.Hold):q.recheck_cargo_config()
    def test_cargo_capture_rechecks_after_outer_gate_before_launch(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'config.toml';q.CARGO_CONFIG_PATHS=[path];q.CARGO_CONFIG_BASELINE=q.cargo_config_identity();q.DEADLINE=time.monotonic()+30
            q.recheck_cargo_config();path.write_text('[profile.dev-small]\ndebug-assertions=false\n')
            with mock.patch.object(support,'capture',side_effect=AssertionError('must not launch')) as call:
                with self.assertRaises(q.Hold):q.capture(['cargo','+1.95.0','metadata'],{},20,[],Path(td))
                call.assert_not_called()
    def test_real_safe_final_git_status_preserves_admin_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);repo=root/'repo';subprocess.run(['git','init','--quiet',str(repo)],check=True,capture_output=True)
            (repo/'ordinary').write_text('harmless');subprocess.run(['git','-C',str(repo),'add','ordinary'],check=True,capture_output=True)
            driver="import sys,time,os,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import zip_native_qualification as q;r=Path(sys.argv[2]);q.DEADLINE=time.monotonic();q.FINALIZING=True;q.FINAL_READ_REPOS=frozenset({str(r)});q.GIT_ADMIN_BASELINES={str(r):q.git_admin_snapshot(r)};before=q.GIT_ADMIN_BASELINES[str(r)];records=[];q.capture(['git','-C',str(r),'status','--porcelain','--untracked-files=all'],{'PATH':os.environ['PATH'],'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'},20,records,r);print(json.dumps({'unchanged':before==q.git_admin_snapshot(r),'cleanup':records[0]['cleanup']['confirmed'],'exit':records[0]['exit'],'final_readonly':records[0]['final_readonly']}))"
            completed=subprocess.run([sys.executable,'-c',driver,str(Path(q.__file__).parent),str(repo)],capture_output=True,text=True,timeout=10,check=True)
            self.assertEqual(json.loads(completed.stdout),{'unchanged':True,'cleanup':True,'exit':0,'final_readonly':True})

    def test_real_fsmonitor_marker_refused_before_final_git_launch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);repo=root/'repo';subprocess.run(['git','init','--quiet',str(repo)],check=True,capture_output=True)
            (repo/'ordinary').write_text('harmless');subprocess.run(['git','-C',str(repo),'add','ordinary'],check=True,capture_output=True)
            marker=root/'marker';script=root/'monitor.py';script.write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("harmless")\n')
            q.DEADLINE=time.monotonic()+10;q.FINALIZING=True;q.FINAL_READ_REPOS=frozenset({str(repo)})
            q.GIT_ADMIN_BASELINES={str(repo):q.git_admin_snapshot(repo)}
            with (repo/'.git/config').open('a') as f:f.write('\n[core]\nfsmonitor = '+sys.executable+' '+str(script)+'\n')
            with mock.patch.object(support,'capture',side_effect=AssertionError('must not launch')) as call:
                with self.assertRaises(q.Hold):q.capture(['git','-C',str(repo),'status','--porcelain','--untracked-files=all'],{},20,[],root)
                call.assert_not_called()
            self.assertFalse(marker.exists())

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

    def test_real_owned_disk_stop_retains_exact_sample_without_filling_disk(self):
        for initial,free,floor,growth in [(10,3,True,False),(30,21,False,True)]:
            driver = "import sys,json,os;from types import SimpleNamespace;sys.path.insert(0,sys.argv[1]);import zip_native_owned as s;g=1024**3;s.DISK_INITIAL_FREE=int(sys.argv[2])*g;s.shutil.disk_usage=lambda _:SimpleNamespace(free=int(sys.argv[3])*g);r,_=s.capture([sys.executable,'-c','import time;time.sleep(.2)'],dict(os.environ),2,'mock_disk');print(json.dumps(r))"
            output=subprocess.run([sys.executable,'-c',driver,str(Path(support.__file__).parent),str(initial),str(free)],capture_output=True,text=True,timeout=8,check=True)
            result=json.loads(output.stdout);sample=result['disk_observation']
            self.assertEqual(result['stop'],'disk_floor_or_total_budget');self.assertTrue(result['cleanup']['confirmed'])
            self.assertEqual(sample['initial_free_bytes'],initial*1024**3);self.assertEqual(sample['free_bytes'],free*1024**3)
            self.assertEqual(sample['floor_breached'],floor);self.assertEqual(sample['growth_breached'],growth)
            self.assertEqual(sample['samples'],1)

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
            proof=workspace/'rustsec-independent-20261025T0228Z/current-manifest-response.json'
            data=json.loads(proof.read_text())['content'].encode() if proof.exists() else (Path(os.environ['GITHUB_WORKSPACE'])/'source/codex-rs/Cargo.toml').read_bytes()
            (source/'codex-rs/Cargo.toml').write_bytes(data)
            configproof=candidate.parent/'cargo-config-source.json'
            configdata=json.loads(configproof.read_text())['content'].encode() if configproof.exists() else (Path(os.environ['GITHUB_WORKSPACE'])/'source/codex-rs/.cargo/config.toml').read_bytes()
            cargoconfig=source/'codex-rs/.cargo/config.toml';cargoconfig.parent.mkdir(parents=True,exist_ok=True);cargoconfig.write_bytes(configdata)
            if fault=='profile-config':
                (source/'.cargo').mkdir();(source/'.cargo/config.toml').write_text('[profile.dev-small]\noverflow-checks=false\n')
            profile=(control/'.github/scripts/zip_native_nextest.toml').read_bytes()
            config=source/'codex-rs/.config/nextest.toml';config.parent.mkdir(parents=True,exist_ok=True);config.write_bytes(profile[:-len(q.PROFILE_APPENDIX.encode())])
            for repo in [source,control]:
                for directory in ['.git/info','.git/objects/info','.git/objects/pack','.git/refs']:(repo/directory).mkdir(parents=True,exist_ok=True)
                (repo/'.git/config').write_text('[core]\nrepositoryformatversion = 0\nbare = false\n')
                (repo/'.git/HEAD').write_text('a'*40+'\n');(repo/'.git/index').write_bytes(b'fixture-index')
            original={x['path']:q.sha((source/x['path']).read_bytes()) for x in policy['source_files']}
            original.update({name:q.sha((source/name).read_bytes()) for name in policy['locks']})
            original['codex-rs/.config/nextest.toml']=q.sha(config.read_bytes())
            original['codex-rs/Cargo.toml']=q.sha((source/'codex-rs/Cargo.toml').read_bytes())
            original['codex-rs/.cargo/config.toml']=q.sha(cargoconfig.read_bytes())
            expected=dict(original);expected.update({x['path']:x['sha256'] for x in policy['source_files']})
            event='d'*40;calls=[];snapshots=[]
            def snapshot(*args):
                snapshots.append(1)
                if len(snapshots)==1:return dict(original)
                value=dict(expected)
                if len(snapshots)==3 and fault=='source':value['unexpected']='changed'
                return value
            def git(repo,env,records,disk,*args):
                if args[:2]==('ls-files','--stage'):
                    mode=b'160000' if fault=='gitlink' else b'100644'
                    name=b'.gitmodules' if fault=='gitmodules' else b'known-source'
                    return mode+b' '+b'a'*40+b' 0\t'+name+b'\0'
                if args[0]=='status':
                    if repo==source and snapshots:return ''.join(' M '+x['path']+'\n' for x in policy['source_files']).encode()
                    return b''
                if args[0]=='diff':return ('\n'.join(q.CONTROL+[x['path'] for x in policy['source_files']])+'\n').encode()
                target=args[1]
                if target=='HEAD':return (event if repo==control else q.BASE).encode()
                if target=='HEAD^':return q.CONTROL_PARENT.encode()
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
                if fault=='late-private-config' and argv[0]=='rustup':
                    (Path(env['CARGO_HOME'])/'config.toml').write_text('[profile.dev-small]\noverflow-checks=false\ndebug-assertions=false\n')
                if fault=='late-ancestor-config' and argv[0]=='rustup':
                    (source/'.cargo').mkdir(exist_ok=True);(source/'.cargo/config.toml').write_text('[profile.dev-small]\noverflow-checks=false\n')
                if fault=='final-private-config' and '--offline' in argv and 'run' in argv:
                    (Path(env['CARGO_HOME'])/'config.toml').write_text('[profile.dev-small]\noverflow-checks=false\n')
                if fault=='disk' and 'nextest' in argv and 'list' in argv:
                    record['exit']=-9;record['stop']='disk_floor_or_total_budget';raise q.Hold()
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
    def test_disk_hold_preserves_final_identity_but_never_qualifies(self):
        code,report,calls=self.exercise('disk')
        self.assertEqual(code,125);self.assertFalse(report['qualified']);self.assertTrue(report['hold'])
        self.assertFalse(report['native_execution_complete']);self.assertEqual(report['test_phases'],[])
        self.assertTrue(report['cleanup_confirmed']);self.assertTrue(report['owned_commands_cleanup_confirmed'])
        self.assertEqual(report['locks_before'],report['locks_after']);self.assertEqual(report['control_before'],report['control_after'])
        self.assertEqual(report['source_before_sha256'],report['source_after_sha256'])
        self.assertFalse(any(x[:4]==['cargo','+1.95.0','nextest','run'] for x in calls))
    def test_mock_complete_success_and_raw_never_published(self):
        code,report,calls=self.exercise();self.assertEqual(code,0);self.assertTrue(report['qualified'])
        self.assertEqual(len(calls),11);self.assertEqual(report['locks_before'],report['locks_after'])
        self.assertEqual([p['junit']['count'] for p in report['test_phases']],[36,36])
        self.assertEqual(report['config_before'],report['config_after'])
    def test_mock_command_source_control_lock_cleanup_hold(self):
        for fault in ['command','source','control','lock','cleanup','zero-tests','missing-junit','retry-junit','profile-config','late-private-config','late-ancestor-config','final-private-config','gitlink','gitmodules']:
            with self.subTest(fault=fault):
                code,report,_=self.exercise(fault);self.assertEqual(code,125);self.assertFalse(report['qualified'])

if __name__=='__main__':unittest.main()

