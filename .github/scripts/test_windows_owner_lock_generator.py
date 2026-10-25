"""Offline gates and owned synthetic Linux processes; no Cargo/Bazel resolver."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import windows_owner_lock_generator as g
import windows_owner_lock_support as support


def encode(packages):
    text = 'version = 4\n'
    for package in packages:
        text += '\n[[package]]\n'
        for key, value in package.items():
            text += key + ' = ' + json.dumps(value) + '\n'
    return text.encode()


class Gates(unittest.TestCase):
    def setUp(self):
        self.old = [dict(name=n,version='0.0.0',dependencies=['serde']) for n in g.EDGE_ADDITIONS]
        self.old += [dict(name='serde',version='1.0.0',source=g.REGISTRY,checksum='serde'),
            dict(name='pretty_assertions',version='1.4.1',source=g.REGISTRY,checksum='pretty'),
            dict(name='winapi-util',version='0.1.11',source=g.REGISTRY,checksum='winapi'),
            dict(name='windows-sys',version='0.52.0',source=g.REGISTRY,checksum='windows52'),
            dict(name='windows-sys',version='0.61.2',source=g.REGISTRY,checksum='windows61')]
        self.new=copy.deepcopy(self.old)
        for package in self.new:
            if package['name'] in g.EDGE_ADDITIONS:package['dependencies']=sorted(package['dependencies']+g.EDGE_ADDITIONS[package['name']])
        self.bazel = {'lockFileVersion': 26, 'moduleExtensions': {}, 'registryFileHashes': {},
                      'facts': {g.CRATE_FACTS: {'rustix_1.1.4':'{"features":{"fs":[]}}'}}}

    def test_exact_edge_passes(self):
        result=g.cargo_delta(encode(self.old),encode(self.new))
        self.assertTrue(result['versions_checksums_sources_unchanged'])

    def test_missing_duplicate_wrong_or_extra_edge_rejected(self):
        for deps in (['serde'], ['codex-utils-path','codex-utils-path','serde'], ['windows-sys','serde'], ['codex-utils-path','other','serde']):
            changed=copy.deepcopy(self.new);changed[0]['dependencies']=deps
            with self.assertRaises(ValueError):g.cargo_delta(encode(self.old),encode(changed))

    def test_versions_checksums_sources_fields_unchanged(self):
        for field,value in [('version','1.1.5'),('checksum','wrong'),('source','registry+https://other.invalid'),('extra','secret')]:
            changed=copy.deepcopy(self.new);changed[2][field]=value
            with self.assertRaises(ValueError):g.cargo_delta(encode(self.old),encode(changed))

    def test_other_crate_edge_rejected(self):
        self.new[4]['dependencies']=['winapi-util']
        with self.assertRaises(ValueError):g.cargo_delta(encode(self.old),encode(self.new))

    def test_duplicate_packages_rejected(self):
        self.new.append(self.new[1])
        with self.assertRaisesRegex(ValueError,'duplicate'):g.cargo_delta(encode(self.old),encode(self.new))

    def test_new_or_removed_packages_rejected(self):
        for packages in (self.new[:-1],self.new+[dict(name='extra',version='1')]):
            with self.assertRaises(ValueError):g.cargo_delta(encode(self.old),encode(packages))

    def test_numeric_type_coercion_rejected(self):
        with self.assertRaises(ValueError):g.cargo_delta(encode(self.old),encode(self.new).replace(b'version = 4',b'version = 4.0',1))

    def test_comments_and_lexical_channels_rejected(self):
        for suffix in (b'# secret\n',b'opaque = "value" # hidden\n',b"opaque = 'hidden'\n"):
            with self.assertRaises(ValueError):g.cargo_lexical_gate(encode(self.old),encode(self.new)+suffix)

    def test_exact_bazel_passes(self):g.bazel_delta(json.dumps(self.bazel),json.dumps(self.bazel,indent=2))

    def test_any_bazel_extension_or_fact_drift_rejected(self):
        for field in ('moduleExtensions','registryFileHashes','facts'):
            changed=copy.deepcopy(self.bazel);changed[field]['unreviewed']='value'
            with self.assertRaises(ValueError):g.bazel_delta(json.dumps(self.bazel),json.dumps(changed))

    def test_duplicate_outer_and_embedded_json_rejected(self):
        with self.assertRaises(ValueError):g.bazel_delta(json.dumps(self.bazel),'{"x":1,"x":2}')
        changed=copy.deepcopy(self.bazel);changed['facts'][g.CRATE_FACTS]['rustix_1.1.4']='{"x":1,"x":2}'
        with self.assertRaises(ValueError):g.bazel_delta(json.dumps(changed),json.dumps(changed))

    def test_nonfinite_or_boolean_numeric_bazel_rejected(self):
        for value in (True,float('nan')):
            changed=copy.deepcopy(self.bazel);changed['lockFileVersion']=value
            with self.assertRaises(ValueError):g.bazel_delta(json.dumps(self.bazel),json.dumps(changed))

    def test_exact_stage2_stage3_payload(self):
        items=g.overlay_items();self.assertEqual(len(items),22)
        self.assertFalse(any('network-proxy' in x['path'] for x in items))
        self.assertEqual(sum(x['path'].endswith('Cargo.toml') for x in items),4)
        with patch.object(g,'OVERLAY_BLOB','0'*40),self.assertRaises(ValueError):g.overlay_items()

    def test_windows_sys_wrong_version_and_edge_ambiguity_rejected(self):
        changed=copy.deepcopy(self.new)
        changed[3]['dependencies']=[x.replace('windows-sys 0.52.0','windows-sys 0.61.2') for x in changed[3]['dependencies']]
        with self.assertRaises(ValueError):g.cargo_delta(encode(self.old),encode(changed))
        old=copy.deepcopy(self.old);new=copy.deepcopy(self.new)
        extra=dict(name='pretty_assertions',version='1.5.0',source=g.REGISTRY,checksum='other')
        old.append(extra);new.append(extra)
        with self.assertRaises(ValueError):g.cargo_delta(encode(old),encode(new))

    def test_nonfinite_exponent_outer_and_embedded_rejected(self):
        for value in ['1e999','-1e999']:
            with self.assertRaises(ValueError):g.strict_json('{"x":'+value+'}')
            changed=copy.deepcopy(self.bazel);changed['facts'][g.CRATE_FACTS]['bad']='{"x":'+value+'}'
            with self.assertRaises(ValueError):g.bazel_delta(json.dumps(changed),json.dumps(changed))

    def test_no_assert_security_checks(self):self.assertNotIn('assert ',Path(g.__file__).read_text())

    def test_budget_exact_and_expired_tampered_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'budget.json';record=dict(start=100.25,deadline=2800.25,seconds=2700,head='a'*40,platform='linux')
            path.write_text(json.dumps(record))
            with patch.dict(os.environ,LOCK_GENERATION_BUDGET=str(path),LOCK_GENERATION_BUDGET_SHA256=g.digest(path.read_bytes()),GITHUB_SHA='a'*40),patch.object(g.time,'monotonic',return_value=200):
                self.assertEqual(g.budget_remaining(Path(d)),2600.25)
                for key,value in [('deadline',2801.25),('seconds',2701),('head','b'*40),('start',True),('platform','darwin')]:
                    bad=dict(record);bad[key]=value;path.write_text(json.dumps(bad))
                    with self.assertRaises(ValueError):g.budget_remaining(Path(d))
                path.write_text(json.dumps(record))
                with patch.object(g.time,'monotonic',return_value=2800.25),self.assertRaises(ValueError):g.budget_remaining(Path(d))


    def test_configuration_refuses_implicit_optins(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)
            (path/'MODULE.bazel').write_text(('platform_triples=['+','.join('"triple"' for _ in range(10))+']\n')*2)
            (path/'.bazelrc').write_text('common --repo_env=ASPECT_TOOLS_TELEMETRY=-all\n')
            g.configuration_gate(path)
            for setting in ('common --remote_cache=grpcs://host','common --repo_env=BAZEL_MSVC_RUNTIME_VISUAL_STUDIO_EULA=1','common --config=buildbuddy-generic'):
                (path/'.bazelrc').write_text(setting)
                with self.assertRaises(ValueError):g.configuration_gate(path)

    def test_full_checkout_map_rejects_extra_mode_blob_stage_and_wrong_parent(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source';control=root/'control';source.mkdir();control.mkdir()
            for name in g.CONTROL_FILES:
                p=control/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'known')
            source_rows=b'100644 '+b'a'*40+b' 0\tordinary\0'
            added=b''.join(b'100644 '+g.blob(b'known').encode()+b' 0\t'+x.encode()+b'\0' for x in g.CONTROL_FILES)
            for fault in [None,'extra','mode','blob','stage','parent']:
                rows=source_rows+added
                if fault=='extra':rows+=b'100644 '+b'b'*40+b' 0\textra\0'
                if fault=='mode':rows=rows.replace(b'100644',b'100755',1)
                if fault=='blob':rows=rows.replace(b'a'*40,b'b'*40,1)
                if fault=='stage':rows=rows.replace(b' 0\t',b' 1\t',1)
                def git(repo,env,*args):
                    if args==('rev-parse','HEAD^'):return (('b'*40) if fault=='parent' else g.BASE).encode()
                    return source_rows if repo==source else rows
                with patch.object(support,'git',side_effect=git):
                    if fault:
                        with self.assertRaises(ValueError):g.checkout_gate(source,control,{})
                    else:self.assertEqual(g.checkout_gate(source,control,{})['control_entries'],7)

    def test_control_trigger_and_sha_mismatch_fail_before_git(self):
        with patch.dict(os.environ,GITHUB_SHA='a'*40,GITHUB_WORKFLOW_SHA='b'*40),patch.object(support,'identity',side_effect=AssertionError('no git')):
            with self.assertRaises(ValueError):g.control_gate(Path('.'),{})
        with patch.dict(os.environ,GITHUB_SHA='a'*40,GITHUB_WORKFLOW_SHA='a'*40,GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_REF='refs/heads/'+g.BRANCH),patch.object(support,'identity',side_effect=AssertionError('no git')):
            with self.assertRaises(ValueError):g.control_gate(Path('.'),{})

class LateAdmission(unittest.TestCase):
    def test_preflight_post_provenance_and_report_budget(self):
        for phase in ['provenance','report']:
            for finish in [2799.95,2800.25]:
                with self.subTest(phase=phase,finish=finish),tempfile.TemporaryDirectory() as td:
                    root=Path(td);repo=root/'repo';repo.mkdir();(repo/'codex-rs').mkdir()
                    for name in g.LOCKS:(repo/name).write_bytes(b'known original')
                    out=root/'out';out.mkdir();control=root/'control';control.mkdir();clock=[2799.9];calls=[0]
                    path=root/'budget';path.write_text(json.dumps(dict(start=100.0,deadline=2800.0,seconds=2700,head='a'*40,platform='linux')))
                    original=Path.write_text
                    def write(p,data,*args,**kwargs):
                        value=original(p,data,*args,**kwargs)
                        if phase=='report' and p==out/'public/report.json':clock[0]=finish
                        return value
                    def gate(*args):
                        calls[0]+=1
                        if phase=='provenance' and calls[0]==2:clock[0]=finish
                        return {'bound':True}
                    with patch.dict(os.environ,LOCK_GENERATION_BUDGET=str(path),LOCK_GENERATION_BUDGET_SHA256=g.digest(path.read_bytes()),GITHUB_SHA='a'*40),patch.object(g.time,'monotonic',side_effect=lambda:clock[0]),patch.object(g,'control_gate',side_effect=gate),patch.object(g,'budget_identity'),patch.object(g,'budget_git',return_value=g.BASE_TREE.encode()),patch.object(g,'checkout_gate'),patch.object(g,'BLOBS',{}),patch.object(support,'input_gate',return_value=True),patch.object(g,'configuration_gate'),patch.object(g,'overlay_gate'),patch.object(g.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()),patch.object(Path,'write_text',write):
                        result=g.preflight(repo,out,control)
                    report=json.loads((out/'public/report.json').read_text())
                    self.assertEqual(result,0 if finish<2800 else 1);self.assertEqual(report.get('preflight_passed',False),finish<2800)
    def test_bootstrap_post_cleanup_and_receipt_budget_no_path_mutation(self):
        for phase in ['cleanup','report']:
            for finish in [2799.95,2800.25]:
                with self.subTest(phase=phase,finish=finish),tempfile.TemporaryDirectory() as td:
                    root=Path(td);repo=root/'repo';repo.mkdir();(repo/'.bazelversion').write_bytes(b'9.0.0\n');control=root/'control';control.mkdir();out=root/'out';out.mkdir()
                    path=root/'budget';path.write_text(json.dumps(dict(start=100.0,deadline=2800.0,seconds=2700,head='a'*40,platform='linux')))
                    github_path=root/'path';github_path.write_text('unchanged\n');clock=[2799.9];body=b'synthetic';original=Path.write_text
                    def write(p,data,*args,**kwargs):
                        value=original(p,data,*args,**kwargs)
                        if phase=='report' and p==out/'public/bootstrap.json':clock[0]=finish
                        return value
                    def capture(argv,env,seconds,disk):
                        streams=[support.Stream(),support.Stream()]
                        if '--download-bazel-asset' in argv:Path(argv[-1]).write_bytes(body)
                        else:
                            streams[0].feed(b'bazel 9.0.0')
                            if phase=='cleanup':clock[0]=finish
                        return {'argv':argv,'exit':0,'stop':None,'cleanup':{'confirmed':True}},streams
                    with patch.dict(os.environ,LOCK_GENERATION_BUDGET=str(path),LOCK_GENERATION_BUDGET_SHA256=g.digest(path.read_bytes()),GITHUB_SHA='a'*40,GITHUB_PATH=str(github_path)),patch.object(g.time,'monotonic',side_effect=lambda:clock[0]),patch.object(g,'control_gate',return_value={'bound':True}),patch.object(g,'budget_identity'),patch.object(g,'BAZEL_ASSET_BYTES',len(body)),patch.object(g,'BAZEL_ASSET_SHA256',g.digest(body)),patch.object(support,'capture',side_effect=capture),patch.object(g.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()),patch.object(Path,'write_text',write):
                        result=g.bootstrap_bazel(repo,out,control)
                    report=json.loads((out/'public/bootstrap.json').read_text())
                    self.assertEqual(result,0 if finish<2800 else 1);self.assertEqual(report['bootstrap_passed'],finish<2800)
                    self.assertEqual(github_path.read_text(),'unchanged\n')
    def test_workflow_admits_fixed_derived_path_only_after_success_exit(self):
        text=(Path(g.__file__).parents[1]/'workflows/windows-owner-lock-generation.yml').read_text()
        generate=text.split('      - name: Generate both locks',1)[1].split('      - name: Upload',1)[0]
        self.assertIn('id: generate',generate);self.assertIn('set -euo pipefail',generate)
        self.assertLess(generate.index('python3 control/'),generate.index('qualified_locks=%s'))
        self.assertIn('${{ steps.generate.outputs.qualified_locks }}',text)
        self.assertNotIn('path: ${{ runner.temp }}/windows-owner-lock-generation/\n',text)

# Real Linux process cases run in a dedicated supervisor process so unrelated
# unittest children never become eligible for owned teardown.
import os
import subprocess
import sys
import time
from unittest.mock import patch
import windows_owner_lock_support as support

DRIVER = '''import sys,json,os
sys.path.insert(0,sys.argv[1]);import windows_owner_lock_support as s
r,streams=s.capture(json.loads(sys.argv[2]),dict(os.environ),float(sys.argv[3]))
r['retained']=[x.retained().decode(errors='replace') for x in streams]
print(json.dumps(r))
'''
DESCENDANT = '''import os,time,sys
from pathlib import Path
root=Path(sys.argv[1]);(root/'pid').write_text(str(os.getpid()))
for fd in (0,1,2):
 try:os.close(fd)
 except OSError:pass
while True:
 with (root/'heartbeat').open('ab') as f:f.write(b'x')
 time.sleep(.01)
'''
LEADER = '''import subprocess,sys,time
from pathlib import Path
p=Path(sys.argv[1]);subprocess.Popen([sys.executable,'-c',sys.argv[2],str(p)])
while not (p/'pid').exists():time.sleep(.005)
print('leader',flush=True)
if sys.argv[3]=='wait':time.sleep(60)
'''


class OwnedSupervisor(unittest.TestCase):
    def isolated(self, argv, seconds):
        p = subprocess.run([sys.executable, '-c', DRIVER, str(Path(support.__file__).parent),
                            json.dumps(argv), str(seconds)], capture_output=True, text=True,
                           timeout=10, check=True)
        return json.loads(p.stdout)

    def exercise(self, mode, seconds):
        with tempfile.TemporaryDirectory() as root:
            sentinel = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(3)'])
            try:
                result = self.isolated([sys.executable, '-c', LEADER, root, DESCENDANT, mode], seconds)
                self.assertTrue(result['cleanup']['confirmed'], result)
                self.assertIsNone(sentinel.poll())
                pid = int((Path(root)/'pid').read_text())
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
                before = (Path(root)/'heartbeat').read_bytes()
                time.sleep(.05)
                self.assertEqual(before, (Path(root)/'heartbeat').read_bytes())
                self.assertIn(pid, [r['pid'] for r in result['cleanup']['reaped_descendants']])
                return result
            finally:
                sentinel.terminate()
                sentinel.wait(timeout=5)

    def test_normal_leader_exit_still_reaps_descendant(self):
        result = self.exercise('exit', 3)
        self.assertEqual(result['exit'], 0)
        self.assertIsNone(result['stop'])

    def test_timeout_reaps_owned_descendant(self):
        result = self.exercise('wait', .3)
        self.assertEqual(result['stop'], 'timeout')
        self.assertNotEqual(result['exit'], 0)

    def test_permission_denial_one_signal_no_retry(self):
        class Proc:
            pid = 987654321
            def wait(self, timeout):
                raise AssertionError('Must not wait after denied signal')
        with patch.object(support.os, 'killpg', side_effect=PermissionError('secret-denial')) as signal:
            receipt = support._cleanup_owned(Proc())
        self.assertFalse(receipt['confirmed'])
        self.assertEqual(signal.call_count, 1)
        self.assertEqual(receipt['error'], 'signal_permission_denied')
        self.assertNotIn('secret', json.dumps(receipt))

    def test_unavailable_subreaper_never_launches(self):
        with patch.object(support, '_subreaper', side_effect=RuntimeError('secret')):
            with patch.object(support.subprocess, 'Popen', side_effect=AssertionError('No launch')):
                result, _ = support.capture(['never'], {}, 1)
        self.assertFalse(result['cleanup']['confirmed'])
        self.assertNotIn('secret', json.dumps(result))

    def test_existing_child_never_signalled_or_launched(self):
        sentinel = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(3)'])
        try:
            with patch.object(support.subprocess, 'Popen', side_effect=AssertionError('No launch')):
                result, _ = support.capture(['never'], {}, 1)
            self.assertFalse(result['cleanup']['confirmed'])
            self.assertIsNone(sentinel.poll())
        finally:
            sentinel.terminate()
            sentinel.wait(timeout=5)



class PublicationGates(unittest.TestCase):
    def valid(self):
        return dict(qualified=True, source_after_confirmed=True, known_lock_content_confirmed=True, control_before={'tree':'x'},
                    control_after={'tree':'x'}, commands=[{'cleanup':{'confirmed':True},'stop':None,'exit':0,
                        'streams':[{'suspected_sensitive':False},{'suspected_sensitive':False}]}])

    def test_only_complete_final_gates_allow_publication(self):
        self.assertTrue(g.publication_allowed(self.valid()))

    def test_stream_suspicion_does_not_change_known_content_gate(self):
        for index in (0,1):
            report=self.valid();report['commands'][0]['streams'][index]['suspected_sensitive']=True
            self.assertTrue(g.publication_allowed(report))

    def test_timeout_cleanup_or_source_failure_withholds_all(self):
        for key in ('timeout','cleanup','source','control','content','exit'):
            report=self.valid()
            if key=='content':report['known_lock_content_confirmed']=False
            if key=='exit':report['commands'][0]['exit']=1
            if key=='timeout':report['commands'][0]['stop']='timeout'
            if key=='cleanup':report['commands'][0]['cleanup']['confirmed']=False
            if key=='source':report['source_after_confirmed']=False
            if key=='control':report['control_after']={'tree':'changed'}
            self.assertFalse(g.publication_allowed(report))

    def test_arbitrary_exception_text_never_published(self):
        self.assertEqual(g.error_code(ValueError('token=highlysensitive')), 'unexpected_exception')
        self.assertEqual(g.error_code(g.GateError('control_changed')), 'control_changed')


class MainPublication(unittest.TestCase):
    def exercise(self, failure=None, expiry=None, finish=2800.25):
        fixture=Gates();fixture.setUp()
        raw=b'token=verysecretvalue https://github.com/public/repo?rev=abc'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=root/'source';repo.mkdir();(repo/'codex-rs').mkdir(parents=True)
            (repo/g.LOCKS[0]).write_bytes(encode(fixture.old));(repo/g.LOCKS[1]).write_text(json.dumps(fixture.bazel))
            originals={}
            source_fixture=Path(__file__).resolve().parents[4]/'windows-owner-source-candidate-v3-7896-20261025T1525Z/original'
            if not source_fixture.exists():source_fixture=Path(os.environ['GITHUB_WORKSPACE'])/'source'
            for item in g.overlay_items():
                if item['before_blob']:
                    data=(source_fixture/item['path']).read_bytes();self.assertEqual(g.blob(data),item['before_blob'])
                    target=repo/item['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);originals[item['path']]=data
            first=next(iter(originals))
            out=root/'out';(out/'job-tools').mkdir(parents=True)
            tool=out/'job-tools/bazel';tool.write_bytes(b'fake tool');control=root/'control';control.mkdir()
            (out/'public').mkdir()
            budget_path=out/'budget.json';budget_path.write_text(json.dumps(dict(start=100.0,deadline=2800.0,seconds=2700,head='a'*40,platform='linux')))
            budget_hash=g.digest(budget_path.read_bytes());clock={'now':2799.9};real_budget=g.budget_remaining
            receipt=dict(source_commit=g.BASE,source_tree=g.BASE_TREE,control_before={'tree':'bound'},
                         control_after={'tree':'bound'},budget_sha256=budget_hash,bootstrap_passed=True,
                         actual={'bytes':9,'sha256':g.digest(b'fake tool'),'version':'bazel 9.0.0'},
                         commands=[{'exit':0,'stop':None,'cleanup':{'confirmed':True}}]*2,
                         ignored_secret='never export')
            (out/'public/bootstrap.json').write_text(json.dumps(receipt))
            def git(repo,env,*args):
                if args==('rev-parse','HEAD'):return g.BASE.encode()
                if args==('rev-parse','HEAD^{tree}'):return g.BASE_TREE.encode()
                if args==('ls-files','--others','--exclude-standard'):
                    return ('\n'.join(x['path'] for x in g.overlay_items() if x['before_blob'] is None and (repo/x['path']).exists())).encode()
                if args==('diff','HEAD','--name-only') and failure=='untracked-mutation':return b'foreign.txt\n'
                return b''
            def capture(argv,env,seconds,disk):
                stdout=b'';exit=0;stop=None;cleanup=True
                if argv[:3]==['cargo','+1.95.0','-V']:stdout=b'cargo 1.95.0 test'
                elif argv[:3]==['rustc','+1.95.0','-Vv']:stdout=b'rustc 1.95.0 test'
                elif argv[0]=='rustup':stdout=str(tool).encode()
                elif argv[-2:]==['version','--gnu_format']:stdout=b'bazel 9.0.0'
                elif 'metadata' in argv:
                    if expiry=='command' and '--locked' in argv:clock['now']=finish
                    stdout=raw
                    if '--locked' not in argv:(repo/g.LOCKS[0]).write_bytes(encode(fixture.new))
                    if failure=='exit':exit=1
                    if failure=='cleanup':cleanup=False
                    if failure=='timeout':stop='timeout'
                    if failure=='manifest':(repo/first).write_bytes(b'changed')
                    if failure=='receipt':(out/'public/bootstrap.json').write_text('never export')
                    if failure=='cargo':(repo/g.LOCKS[0]).write_bytes(encode(fixture.new)+b'# secret\n')
                if '--lockfile_mode=update' in argv and failure=='bazel-drift':
                    changed=copy.deepcopy(fixture.bazel);changed['moduleExtensions']['new-secret-key']={'private':'secret-value'}
                    (repo/g.LOCKS[1]).write_text(json.dumps(changed))
                if '--lockfile_mode=update' in argv and failure=='bazel':
                    (repo/g.LOCKS[1]).write_text('{"secret":"never export"}')
                streams=[support.Stream(),support.Stream()];streams[0].feed(stdout);streams[1].feed(raw)
                return {'argv':argv,'exit':exit,'stop':stop,'cleanup':{'confirmed':cleanup},'streams':[s.finish() for s in streams]},streams
            original_write_bytes=Path.write_bytes;original_write_text=Path.write_text;real_known=g.known_lock_content;controls=[0]
            def write_bytes(path,data):
                value=original_write_bytes(path,data)
                if expiry=='privatewrite' and path.parent.name=='qualified':clock['now']=finish
                return value
            def write_text(path,data,*args,**kwargs):
                value=original_write_text(path,data,*args,**kwargs)
                if expiry=='reportwrite' and path==out/'public/report.json':clock['now']=finish
                return value
            def control_gate(*args,**kwargs):
                controls[0]+=1
                if expiry=='provenance' and controls[0]==2:clock['now']=finish
                return {'tree':'bound'}
            def known(*args):
                value=real_known(*args)
                if expiry=='validation':clock['now']=finish
                return value
            with patch.dict(os.environ,{'LOCK_GENERATION_BUDGET_SHA256':budget_hash,'LOCK_GENERATION_BUDGET':str(budget_path),'GITHUB_SHA':'a'*40}),patch.object(g,'BAZEL_ASSET_BYTES',9),patch.object(g,'BAZEL_ASSET_SHA256',g.digest(b'fake tool')),patch.object(g,'BLOBS',{**{k:g.blob(v) for k,v in originals.items()},g.LOCKS[1]:g.blob(json.dumps(fixture.bazel).encode())}),patch.object(g,'configuration_gate'),patch.object(g,'checkout_gate'), \
                 patch.object(g,'budget_remaining',side_effect=lambda out:real_budget(out) if expiry else 2000),patch.object(g.time,'monotonic',side_effect=lambda:clock['now']),patch.object(g,'control_gate',side_effect=control_gate),patch.object(g,'known_lock_content',side_effect=known),patch.object(Path,'write_bytes',write_bytes),patch.object(Path,'write_text',write_text), \
                 patch.object(g,'budget_identity'),patch.object(support,'input_gate',return_value=True), \
                 patch.object(support,'git',side_effect=git),patch.object(support,'capture',side_effect=capture), \
                 patch.object(g.shutil,'which',return_value=str(tool)), \
                 patch.object(g.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()):
                result=g.main(repo,out,control)
            expired=expiry is not None and finish>=2800
            self.assertEqual(result,1 if failure or expired else 0)
            expected={'before-Cargo.lock','before-MODULE.bazel.lock','report.json','bootstrap.json'}
            if not failure and not expired:self.assertEqual({f.name for f in (out/'qualified').iterdir()},{'after-Cargo.lock','after-MODULE.bazel.lock','locks.diff'})
            self.assertEqual({f.name for f in (out/'public').iterdir()},expected)
            for file in (out/'public').iterdir():
                self.assertNotIn(raw,file.read_bytes())
                self.assertNotIn(b'never export',file.read_bytes())
            return json.loads((out/'public/report.json').read_text())

    def test_absolute_deadline_includes_cleanup_provenance_content_and_publication(self):
        for stage in ['command','provenance','validation','privatewrite','reportwrite']:
            for finish in [2799.95,2800.0,2800.25]:
                with self.subTest(stage=stage,finish=finish):
                    report=self.exercise(expiry=stage,finish=finish)
                    self.assertEqual(report['qualified'],finish<2800)
                    self.assertEqual(report['publication_gate_passed'],finish<2800)
                    if finish>=2800:self.assertEqual(report['withheld'],'all_raw_diff_generated_locks')

    def test_success_never_exports_raw_secret_or_metadata(self):
        report=self.exercise()
        self.assertTrue(report['publication_gate_passed'])
        metadata=[c['argv'] for c in report['commands'] if 'metadata' in c['argv']]
        self.assertEqual(len(metadata),2)
        self.assertTrue(all('--all-features' in x and '--filter-platform' not in x and '--no-deps' not in x for x in metadata))
        self.assertNotIn('--locked',metadata[0]);self.assertIn('--locked',metadata[1]);self.assertIn('--offline',metadata[1])
        self.assertFalse(any('update' in c['argv'] and c['argv'][0]=='cargo' for c in report['commands']))
        versions=[c['argv'] for c in report['commands'] if 'version' in c['argv']]
        self.assertEqual(len(versions),1)
        argv=versions[0]
        self.assertEqual(argv[:4],['bazel','--batch','--nosystem_rc','--nohome_rc'])
        self.assertTrue(argv[4].startswith('--output_user_root='))
        self.assertTrue(argv[5].startswith('--output_base='))
        self.assertEqual(argv[6:],['--noexperimental_remote_repo_contents_cache','version','--gnu_format'])

    def test_main_receipt_drift_withholds_and_replaces_unknown_bytes(self):
        report=self.exercise('receipt')
        self.assertEqual(report['bootstrap_final_hold'],'bootstrap_final_receipt_drift')
        self.assertFalse(report['publication_gate_passed'])

    def test_main_bazel_hold_localizes_without_releasing_locks(self):
        report=self.exercise('bazel-drift')
        self.assertEqual(report['bazel_hold_summary']['status'],'localized')
        self.assertFalse(report['publication_gate_passed'])
        self.assertNotIn('new-secret-key',json.dumps(report))
        self.assertNotIn('secret-value',json.dumps(report))

    def test_each_failure_withholds_derived_artifacts(self):
        for reason in ('exit','cleanup','timeout','manifest','cargo','bazel','bazel-drift','untracked-mutation'):
            with self.subTest(reason=reason):self.assertFalse(self.exercise(reason)['publication_gate_passed'])



import windows_owner_lock_diagnostics as d


class HoldDiagnostic(unittest.TestCase):
    def baseline(self):
        return {'moduleExtensions': {'known-extension': {'general': {'usagesDigest': 'old', 'inputs': [1]}}},
                'facts': {d.CRATE_FACTS: {'known-crate': '{"features":{"fs":[]}}'}}}

    def summary(self, before, after):
        left=json.dumps(before).encode()
        right=after if isinstance(after,bytes) else json.dumps(after).encode()
        return d.summarize(left,right,g.blob(left))

    def test_known_type_hash_localization_without_values(self):
        old=self.baseline();new=copy.deepcopy(old)
        new['moduleExtensions']['known-extension']['general']['usagesDigest']='token=hiddennewvalue'
        new['moduleExtensions']['known-extension']['general']['inputs'][0]=True
        result=self.summary(old,new)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['changes']),2)
        self.assertNotIn('hiddennewvalue',json.dumps(result))
        self.assertEqual(result['changes'][0]['path'][-1],{'known_key':'usagesDigest'})
        self.assertEqual(result['changes'][1]['before']['type'],'integer')
        self.assertEqual(result['changes'][1]['after']['type'],'boolean')
        self.assertEqual(result['changes'][0]['after'],d.descriptor('token=hiddennewvalue'))

    def test_unknown_keys_nested_values_urls_never_printed(self):
        old=self.baseline();new=copy.deepcopy(old)
        new['moduleExtensions']['token=unknown-key-secret']={'nested-secret': ['https://evil.invalid/token?secret=123',{'more-secret':'value-secret'}]}
        result=self.summary(old,new);raw=json.dumps(result)
        for secret in ('unknown-key-secret','nested-secret','evil.invalid','more-secret','value-secret'):
            self.assertNotIn(secret,raw)
        self.assertEqual(len(result['changes']),1)
        last=result['changes'][0]['path'][-1]
        self.assertIn('unknown_key_sha256',last)
        self.assertEqual(result['changes'][0]['after']['type'],'object')

    def test_key_known_elsewhere_is_hashed_at_new_parent(self):
        old=self.baseline();new=copy.deepcopy(old);new['facts']['usagesDigest']='private'
        result=self.summary(old,new)
        self.assertEqual(result['changes'][0]['path'][0],{'known_key':'facts'})
        self.assertIn('unknown_key_sha256',result['changes'][0]['path'][1])
        self.assertNotIn('private',json.dumps(result))

    def test_removed_known_field_and_array_indices(self):
        old=self.baseline();new=copy.deepcopy(old)
        del new['moduleExtensions']['known-extension']['general']['usagesDigest']
        new['moduleExtensions']['known-extension']['general']['inputs'].append('hidden')
        result=self.summary(old,new)
        self.assertEqual(result['changes'][0]['change'],'removed')
        self.assertEqual(result['changes'][1]['path'][-1],{'index':1})
        self.assertNotIn('hidden',json.dumps(result))

    def test_outer_nested_and_embedded_duplicates_never_echo_parser_text(self):
        old=self.baseline()
        for raw in (b'{"secret-key":1,"secret-key":2}', b'{"facts":{},"x":{"secret-key":1,"secret-key":2}}', b'not-json-secret'):
            result=self.summary(old,raw)
            self.assertEqual(result['status'],'parse_rejected')
            self.assertEqual(result['changes'],[])
            self.assertNotIn('secret-key',json.dumps(result))
            self.assertNotIn('not-json-secret',json.dumps(result))
        changed=copy.deepcopy(old);changed['facts'][d.CRATE_FACTS]['known-crate']='{"secret-key":1,"secret-key":2}'
        result=self.summary(old,changed)
        self.assertEqual(result['status'],'parse_rejected');self.assertNotIn('secret-key',json.dumps(result))

    def test_nonfinite_and_deep_json_fixed_rejection(self):
        old=self.baseline()
        for value in ('NaN','Infinity','1e999'):
            raw=json.dumps(old).encode()[:-1]+b',"secret":'+value.encode()+b'}'
            result=self.summary(old,raw)
            self.assertEqual(result['status'],'parse_rejected')
            self.assertEqual(result['changes'],[])
        raw=json.dumps(old).encode()[:-1]+b',"secret":'+b'['*5000+b'0'+b']'*5000+b'}'
        result=self.summary(old,raw)
        self.assertEqual(result['status'],'parse_rejected')
        self.assertEqual(result['changes'],[])
        changed=copy.deepcopy(old);changed['facts'][d.CRATE_FACTS]['known-crate']='['*5000+'0'+']'*5000
        self.assertEqual(self.summary(old,changed)['status'],'parse_rejected')

    def test_embedded_known_path_localizes_without_literal_values(self):
        old=self.baseline();changed=copy.deepcopy(old)
        changed['facts'][d.CRATE_FACTS]['known-crate']='{"features":{"fs":["secret-feature"]}}'
        result=self.summary(old,changed)
        self.assertTrue(any({'embedded_json':True} in item['path'] for item in result['changes']))
        self.assertNotIn('secret-feature',json.dumps(result))

    def test_limits_are_explicit_and_deterministic(self):
        old=self.baseline();old['many']={str(i):i for i in range(140)}
        changed=copy.deepcopy(old);changed['many']={str(i):i+1 for i in range(140)}
        result=self.summary(old,changed)
        self.assertFalse(result['complete']);self.assertLessEqual(len(result['changes']),128)
        self.assertLessEqual(d.output_size(result),32*1024)
        self.assertEqual(result,self.summary(old,changed))
        with patch.object(d,'MAX_NODES',5):
            result=self.summary(old,changed)
            self.assertFalse(result['complete']);self.assertLessEqual(result['visited_nodes'],5)
        with patch.object(d,'MAX_DEPTH',2):
            result=self.summary(old,changed)
            self.assertFalse(result['complete']);self.assertIn('depth_limit',result['limits_reached'])

    def test_output_and_long_baseline_path_bounded(self):
        old=self.baseline();key='known'*5000;old[key]=1;changed=copy.deepcopy(old);changed[key]=2
        result=self.summary(old,changed)
        self.assertFalse(result['complete']);self.assertLessEqual(d.output_size(result),32*1024)
        self.assertIn('path_or_record_bytes',result['limits_reached'])


    def test_recursion_exception_is_never_echoed(self):
        old=self.baseline()
        with patch.object(d,'strict_json',side_effect=RecursionError('token=private-exception')):
            result=self.summary(old,old)
        self.assertEqual(result['status'],'parse_rejected')
        self.assertEqual(result['changes'],[])
        self.assertNotIn('private-exception',json.dumps(result))

    def test_unicode_unknown_keys_and_string_brackets_are_safe(self):
        old=self.baseline();new=copy.deepcopy(old)
        new['未知秘密'] = '"' + '['*100 + '\\"' + ']'*100
        result=self.summary(old,new)
        self.assertEqual(result['status'],'localized')
        self.assertNotIn('未知秘密',json.dumps(result,ensure_ascii=False))
        self.assertEqual(result['changes'][0]['path'][-1]['key_utf8_bytes'],len('未知秘密'.encode()))
        self.assertNotIn('['*100,json.dumps(result))

    def test_unpinned_or_oversized_input_never_localizes(self):
        original=json.dumps(self.baseline()).encode()
        self.assertEqual(d.summarize(original,original,'0'*40)['reason'],'baseline_identity_mismatch')
        result=d.summarize(original,b'x'*(d.MAX_INPUT_BYTES+1),g.blob(original))
        self.assertEqual(result['reason'],'input_size_limit');self.assertEqual(result['changes'],[])

    def test_final_gates_and_snapshot_mutation_forbid_localization(self):
        old=json.dumps(self.baseline()).encode();new=old.replace(b'"old"',b'"secret"')
        with tempfile.TemporaryDirectory() as directory:
            repo=Path(directory);(repo/g.LOCKS[1]).write_bytes(new)
            (repo/'codex-rs').mkdir();(repo/g.LOCKS[0]).write_bytes(b'unchanged')
            valid=PublicationGates().valid();valid['qualified']=False
            for field in ('cleanup','source','control','stop','exit'):
                report=copy.deepcopy(valid)
                if field=='cleanup':report['commands'][0]['cleanup']['confirmed']=False
                if field=='source':report['source_after_confirmed']=False
                if field=='control':report['control_after']={'tree':'changed'}
                if field=='stop':report['commands'][0]['stop']='timeout'
                if field=='exit':report['commands'][0]['exit']=1
                g.retain_hold_diagnostic(report,repo,{g.LOCKS[0]:b'unchanged',g.LOCKS[1]:old},{g.LOCKS[0]:b'unchanged',g.LOCKS[1]:new},lambda:None)
                self.assertNotIn('bazel_hold_summary',report)
            with patch.object(g,'BLOBS',{g.LOCKS[1]:g.blob(old)}):
                report=copy.deepcopy(valid)
                g.retain_hold_diagnostic(report,repo,{g.LOCKS[0]:b'unchanged',g.LOCKS[1]:old},{g.LOCKS[0]:b'unchanged',g.LOCKS[1]:new},lambda:None)
                self.assertEqual(report['bazel_hold_summary']['status'],'localized')
                self.assertFalse(g.publication_allowed(report))
                report=copy.deepcopy(valid)
                def mutate():(repo/g.LOCKS[1]).write_bytes(b'new secret mutation')
                g.retain_hold_diagnostic(report,repo,{g.LOCKS[0]:b'unchanged',g.LOCKS[1]:old},{g.LOCKS[0]:b'unchanged',g.LOCKS[1]:new},mutate)
                self.assertEqual(report['bazel_hold_summary']['status'],'unavailable')
                self.assertNotIn('secret mutation',json.dumps(report))

    def test_control_recheck_failure_discards_partial_summary(self):
        old=json.dumps(self.baseline()).encode();new=old.replace(b'"old"',b'"secret"')
        with tempfile.TemporaryDirectory() as directory,patch.object(g,'BLOBS',{g.LOCKS[1]:g.blob(old)}):
            repo=Path(directory);(repo/g.LOCKS[1]).write_bytes(new)
            (repo/'codex-rs').mkdir();(repo/g.LOCKS[0]).write_bytes(b'unchanged')
            report=PublicationGates().valid();report['qualified']=False
            def fail():raise ValueError('token=exception-secret')
            g.retain_hold_diagnostic(report,repo,{g.LOCKS[0]:b'unchanged',g.LOCKS[1]:old},{g.LOCKS[0]:b'unchanged',g.LOCKS[1]:new},fail)
            self.assertEqual(report['bazel_hold_summary']['status'],'unavailable')
            self.assertNotIn('exception-secret',json.dumps(report))

class OfficialBootstrap(unittest.TestCase):
    def test_official_version_shortcut_requires_argc_two(self):
        # Bazel9 blaze.cc blob c0a717e933ea63948acebd1be488cb098e01bf73:
        # if (argc == 2 && strcmp(argv[1], "--version") == 0).
        # This is a source-contract regression, not local Bazel execution.
        def official_shortcut(argv):
            return len(argv)==2 and argv[1]=='--version'
        self.assertTrue(official_shortcut(['bazel','--version']))
        self.assertFalse(official_shortcut(['bazel','--batch','--version']))
        self.assertFalse(official_shortcut(['bazel','--batch','version','--gnu_format']))

    def test_asset_redirect_allowlist_and_single_hop(self):
        import urllib.request
        good='https://release-assets.githubusercontent.com/github-production-release-asset/20773773/asset?signature=private'
        for bad in ('http://release-assets.githubusercontent.com/github-production-release-asset/20773773/x',
                    'https://evil.invalid/asset', 'https://user@release-assets.githubusercontent.com/github-production-release-asset/20773773/x',
                    'https://release-assets.githubusercontent.com:443/github-production-release-asset/20773773/x',
                    'https://release-assets.githubusercontent.com/github-production-release-asset/99/x'):
            with self.assertRaises(g.GateError):
                g.OfficialAssetRedirect().redirect_request(urllib.request.Request(g.BAZEL_ASSET_URL),None,302,'',{},bad)
        handler=g.OfficialAssetRedirect()
        result=handler.redirect_request(urllib.request.Request(g.BAZEL_ASSET_URL),None,302,'',{},good)
        self.assertEqual(result.full_url,good)
        self.assertNotIn('Authorization',result.headers)
        with self.assertRaises(g.GateError):
            handler.redirect_request(result,None,302,'',{},good)

    def test_download_content_size_hash_deadline_gates(self):
        import io
        body=b'official-test-binary'
        class Response:
            status=200
            headers={'Content-Length':str(len(body))}
            def __init__(self,data):self.buffer=io.BytesIO(data)
            def read1(self,n):return self.buffer.read(n)
        with tempfile.TemporaryDirectory() as root, patch.object(g,'BAZEL_ASSET_BYTES',len(body)),              patch.object(g,'BAZEL_ASSET_SHA256',g.digest(body)):
            g.copy_official_asset(Response(body),Path(root)/'valid',lambda:0)
            for name,data in [('long',body+b'x'),('short',body[:-1]),('hash',b'x'*len(body))]:
                with self.assertRaises(g.GateError):
                    g.copy_official_asset(Response(data),Path(root)/name,lambda:0)
            with self.assertRaisesRegex(g.GateError,'asset_download_deadline'):
                g.copy_official_asset(Response(body),Path(root)/'deadline',iter([0,151]).__next__)
            with self.assertRaises(FileExistsError):
                g.copy_official_asset(Response(body),Path(root)/'valid',lambda:0)

    def test_http_denial_never_retries_or_exports_error(self):
        import urllib.error
        error=urllib.error.HTTPError(g.BAZEL_ASSET_URL,403,'private-secret-message',{},None)
        with patch.object(g.urllib.request,'build_opener') as build:
            build.return_value.open.side_effect=error
            self.assertEqual(g.download_official_asset(Path('never-written')),23)
            self.assertEqual(build.return_value.open.call_count,1)

    def test_bootstrap_success_private_receipt_and_github_path(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);repo=root/'source';repo.mkdir();(repo/'.bazelversion').write_bytes(b'9.0.0\n')
            control=root/'control';control.mkdir();out=root/'out';out.mkdir();github_path=root/'path';github_path.touch()
            body=b'test-binary';calls=[]
            def capture(argv,env,seconds,disk):
                self.assertEqual(set(env),{'PATH','HOME','LANG','GIT_CONFIG_NOSYSTEM','GIT_CONFIG_GLOBAL',
                                          'GIT_TERMINAL_PROMPT','PYTHONDONTWRITEBYTECODE'})
                calls.append(argv)
                stdout=b''
                if '--download-bazel-asset' in argv:Path(argv[-1]).write_bytes(body)
                else:stdout=b'bazel 9.0.0\n'
                streams=[support.Stream(),support.Stream()]
                streams[0].feed(stdout);streams[1].feed(b'token=neverpublishsecret')
                return {'argv':argv,'exit':0,'stop':None,'cleanup':{'confirmed':True},
                        'streams':[s.finish() for s in streams]},streams
            with patch.dict(os.environ,{'GITHUB_PATH':str(github_path)}),                  patch.object(g,'BAZEL_ASSET_BYTES',len(body)),patch.object(g,'BAZEL_ASSET_SHA256',g.digest(body)),                  patch.object(g,'budget_remaining',return_value=2000),patch.object(g,'control_gate',return_value={'bound':True}),patch.object(g,'budget_identity'),                  patch.object(support,'capture',side_effect=capture),                  patch.object(g.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()):
                self.assertEqual(g.bootstrap_bazel(repo,out,control),0)
            self.assertEqual(github_path.read_text(),'')  # Shell handoff occurs only after exit0.
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[1], [str(out/'job-tools/bazel'), '--batch', '--nosystem_rc', '--nohome_rc',
                '--output_user_root='+str(out/'bazel-root'), '--output_base='+str(out/'bazel-output'),
                '--noexperimental_remote_repo_contents_cache', 'version', '--gnu_format'])
            self.assertEqual({p.name for p in (out/'public').iterdir()},{'bootstrap.json'})
            receipt=(out/'public/bootstrap.json').read_text()
            self.assertNotIn('neverpublishsecret',receipt)
            self.assertTrue(json.loads(receipt)['bootstrap_passed'])

    def test_bootstrap_denied_download_never_versions_or_sets_path(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);repo=root/'source';repo.mkdir();(repo/'.bazelversion').write_bytes(b'9.0.0\n')
            control=root/'control';control.mkdir();out=root/'out';out.mkdir();github_path=root/'path';github_path.touch()
            streams=[support.Stream(),support.Stream()]
            result={'argv':['fixed'],'exit':23,'stop':None,'cleanup':{'confirmed':True},
                    'streams':[s.finish() for s in streams]}
            with patch.dict(os.environ,{'GITHUB_PATH':str(github_path)}),                  patch.object(g,'budget_remaining',return_value=2000),patch.object(g,'control_gate',return_value={'bound':True}),patch.object(g,'budget_identity'),                  patch.object(support,'capture',return_value=(result,streams)) as capture,                  patch.object(g.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()):
                self.assertEqual(g.bootstrap_bazel(repo,out,control),1)
            self.assertEqual(capture.call_count,1);self.assertEqual(github_path.read_bytes(),b'')
            receipt=json.loads((out/'public/bootstrap.json').read_text())
            self.assertEqual(receipt['hold'],'public_asset_http_denied_or_failed')



    def test_bootstrap_shared_budget_bounds_both_commands(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);repo=root/'source';repo.mkdir();(repo/'.bazelversion').write_bytes(b'9.0.0\n')
            control=root/'control';control.mkdir();out=root/'out';out.mkdir();path=root/'path';path.touch()
            body=b'synthetic';caps=[]
            def capture(argv,env,seconds,disk):
                caps.append(seconds)
                if '--download-bazel-asset' in argv:Path(argv[-1]).write_bytes(body)
                streams=[support.Stream(),support.Stream()]
                if 'version' in argv:streams[0].feed(b'bazel 9.0.0')
                return {'argv':argv,'exit':0,'stop':None,'cleanup':{'confirmed':True}},streams
            with patch.dict(os.environ,{'GITHUB_PATH':str(path)}), \
                 patch.object(g,'budget_remaining',side_effect=[40,30,20,10,8,6,5]) as budget, \
                 patch.object(g,'control_gate',return_value={'bound':True}),patch.object(g,'budget_identity'), \
                 patch.object(g,'BAZEL_ASSET_BYTES',len(body)),patch.object(g,'BAZEL_ASSET_SHA256',g.digest(body)), \
                 patch.object(support,'capture',side_effect=capture), \
                 patch.object(g.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()):
                self.assertEqual(g.bootstrap_bazel(repo,out,control),0)
            self.assertEqual(caps,[30,10]);self.assertEqual(budget.call_count,7)

    def test_bootstrap_expired_budget_never_downloads_or_sets_path(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);repo=root/'source';repo.mkdir();control=root/'control';control.mkdir()
            out=root/'out';out.mkdir();path=root/'path';path.touch()
            with patch.dict(os.environ,{'GITHUB_PATH':str(path)}), \
                 patch.object(g,'budget_remaining',side_effect=g.GateError('shared_budget_expired')), \
                 patch.object(support,'capture') as capture:
                self.assertEqual(g.bootstrap_bazel(repo,out,control),1)
            capture.assert_not_called();self.assertEqual(path.read_bytes(),b'')
            self.assertFalse((out/'job-tools').exists())
            self.assertEqual(json.loads((out/'public/bootstrap.json').read_text())['hold'],'shared_budget_expired')

    def test_bootstrap_summary_rejects_binding_and_binary_swaps(self):
        with tempfile.TemporaryDirectory() as root:
            binary=Path(root)/'bazel';binary.write_bytes(b'x');control={'bound':True}
            receipt=dict(source_commit=g.BASE,source_tree=g.BASE_TREE,control_before=control,
                         control_after=control,budget_sha256='a'*64,bootstrap_passed=True,
                         actual={'bytes':1,'sha256':g.digest(b'x'),'version':'bazel 9.0.0'},
                         commands=[{'exit':0,'stop':None,'cleanup':{'confirmed':True}}]*2,
                         secret='DO-NOT-EXPORT')
            with patch.dict(os.environ,{'LOCK_GENERATION_BUDGET_SHA256':'a'*64}), \
                 patch.object(g,'BAZEL_ASSET_BYTES',1),patch.object(g,'BAZEL_ASSET_SHA256',g.digest(b'x')):
                self.assertNotIn('DO-NOT-EXPORT',json.dumps(g.bootstrap_summary(receipt,control,binary)))
                for field,value in [('source_commit','f'*40),('source_tree','f'*40),
                                    ('control_after',{'secret':'private'}),('budget_sha256','b'*64),
                                    ('bootstrap_passed',False),('actual',{}),('commands',[])]:
                    bad=copy.deepcopy(receipt);bad[field]=value
                    with self.assertRaises(g.GateError):g.bootstrap_summary(bad,control,binary)
                binary.write_bytes(b'y')
                with self.assertRaises(g.GateError):g.bootstrap_summary(receipt,control,binary)
                binary.unlink();target=Path(root)/'other';target.write_bytes(b'x');binary.symlink_to(target)
                with self.assertRaises(g.GateError):g.bootstrap_summary(receipt,control,binary)

import signal

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
            with patch.object(support.os,'waitid',return_value=self.event()),                  patch.object(support.os,'waitpid',return_value=value) as reap,                  patch.object(support.os,'kill',side_effect=AssertionError('No signal')):
                receipt={}
                self.assertFalse(support._observe_and_reap_adopted(receipt,time.monotonic()+1))
                self.assertEqual(receipt['error'],'adopted_reap_identity_unconfirmed')
                reap.assert_called_once_with(43210,os.WNOHANG)

    def test_wait_and_reap_denial_once_no_retry(self):
        for which in ('waitid','waitpid'):
            with patch.object(support.os,'waitid',return_value=self.event()) as wait,                  patch.object(support.os,'waitpid',return_value=(43210,0)) as reap:
                denied=wait if which=='waitid' else reap
                denied.side_effect=PermissionError('secret-denial')
                receipt={}
                self.assertFalse(support._observe_and_reap_adopted(receipt,time.monotonic()+1))
                self.assertEqual(denied.call_count,1)
                self.assertNotIn('secret',json.dumps(receipt))
                if which=='waitid':reap.assert_not_called()

    def test_assumptions_fail_before_launch(self):
        for target,value in [('active_count',2),('current_thread',object())]:
            with patch.object(support.threading,target,return_value=value),                  patch.object(support.subprocess,'Popen',side_effect=AssertionError('No launch')):
                result,_=support.capture(['never'],{},1)
                self.assertFalse(result['cleanup']['confirmed'])
        with patch.object(support.signal,'getsignal',return_value=signal.SIG_IGN),              patch.object(support.subprocess,'Popen',side_effect=AssertionError('No launch')):
            result,_=support.capture(['never'],{},1)
            self.assertFalse(result['cleanup']['confirmed'])

    def test_unsupported_terminal_uid_holds_without_reap(self):
        event=self.event();event.si_uid=os.getuid()+1
        with patch.object(support.os,'waitid',return_value=event),              patch.object(support.os,'waitpid',side_effect=AssertionError('No reap')):
            receipt={}
            self.assertFalse(support._observe_and_reap_adopted(receipt,time.monotonic()+1))
            self.assertEqual(receipt['error'],'adopted_terminal_identity_unsupported')


if __name__ == '__main__':unittest.main()
