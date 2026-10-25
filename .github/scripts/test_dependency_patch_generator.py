"""Offline synthetic positive/adversarial checks; no resolver or downloads."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import dependency_patch_generator as g


def encode(packages):
    text = 'version = 4\n'
    for package in packages:
        text += '\n[[package]]\n'
        for key, value in package.items():
            text += key + ' = ' + json.dumps(value) + '\n'
    return text.encode()


class Gates(unittest.TestCase):
    def setUp(self):
        self.packages = [dict(name=x['name'], version=x['old'], source=g.REGISTRY,
                              checksum='old', dependencies=[]) for x in g.TARGETS]
        self.new = copy.deepcopy(self.packages)
        for package, target in zip(self.new, g.TARGETS):
            package.update(version=target['new'], checksum=target['checksum'])
        self.old_bazel = {'lockFileVersion': 26, 'moduleExtensions': {}, 'registryFileHashes': {},
                          'facts': {g.CRATE_FACTS: {x['name']+'_'+x['old']: '{}' for x in g.TARGETS}}}
        self.new_bazel = copy.deepcopy(self.old_bazel)
        self.new_bazel['facts'][g.CRATE_FACTS] = {
            x['name']+'_'+x['new']: json.dumps(x['fact']) for x in g.TARGETS}

    def test_exact_targets_pass(self):
        self.assertEqual(len(g.cargo_delta(encode(self.packages), encode(self.new), g.TARGETS)), 4)

    def test_incremental_only_first_passes(self):
        partial = copy.deepcopy(self.packages)
        partial[0] = self.new[0]
        g.cargo_delta(encode(self.packages), encode(partial), g.TARGETS[:1])

    def test_later_target_changed_early_fails(self):
        with self.assertRaisesRegex(ValueError, 'unexpected_package'):
            g.cargo_delta(encode(self.packages), encode(self.new), g.TARGETS[:1])

    def test_checksum_change_fails(self):
        self.new[0]['checksum'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'checksum'):
            g.cargo_delta(encode(self.packages), encode(self.new), g.TARGETS)

    def test_source_switch_fails(self):
        self.new[0]['source'] = 'registry+https://evil.invalid'
        with self.assertRaises(ValueError):
            g.cargo_delta(encode(self.packages), encode(self.new), g.TARGETS)

    def test_add_remove_package_fails(self):
        self.new.append(dict(name='other', version='1.0.0'))
        with self.assertRaisesRegex(ValueError, 'unexpected_package'):
            g.cargo_delta(encode(self.packages), encode(self.new), g.TARGETS)

    def test_unrelated_record_drift_fails(self):
        self.packages.append(dict(name='other', version='1.0.0', dependencies=[]))
        self.new.append(dict(name='other', version='1.0.0', dependencies=['ctutils']))
        with self.assertRaisesRegex(ValueError, 'nontarget'):
            g.cargo_delta(encode(self.packages), encode(self.new), g.TARGETS)

    def test_unexpected_target_edges_fail(self):
        self.new[0]['dependencies'] = ['ctutils']
        with self.assertRaisesRegex(ValueError, 'target_dependency_edges'):
            g.cargo_delta(encode(self.packages), encode(self.new), g.TARGETS)

    def test_duplicate_package_fails(self):
        self.new.append(self.new[0])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            g.cargo_delta(encode(self.packages), encode(self.new), g.TARGETS)

    def test_bazel_exact_four_facts_pass(self):
        g.bazel_delta(json.dumps(self.old_bazel), json.dumps(self.new_bazel))

    def test_bazel_unrelated_extension_fails(self):
        self.new_bazel['moduleExtensions']['other'] = {}
        with self.assertRaisesRegex(ValueError, 'unexpected_bazel'):
            g.bazel_delta(json.dumps(self.old_bazel), json.dumps(self.new_bazel))

    def test_bazel_target_fact_forgery_fails(self):
        key = g.TARGETS[0]['name']+'_'+g.TARGETS[0]['new']
        self.new_bazel['facts'][g.CRATE_FACTS][key] = '{}'
        with self.assertRaisesRegex(ValueError, 'registry_exact'):
            g.bazel_delta(json.dumps(self.old_bazel), json.dumps(self.new_bazel))

    def test_bazel_removed_platform_fact_fails(self):
        self.old_bazel['facts']['platform'] = {'ten': 'triples'}
        with self.assertRaisesRegex(ValueError, 'unexpected_bazel'):
            g.bazel_delta(json.dumps(self.old_bazel), json.dumps(self.new_bazel))

    def test_no_assert_security_checks(self):
        self.assertNotIn('assert ', Path(g.__file__).read_text())

    def test_configuration_refuses_implicit_optins(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / 'MODULE.bazel').write_text('platform_triples=['+','.join('"triple"' for _ in range(10))+']\n' +
                                              'platform_triples=['+','.join('"triple"' for _ in range(10))+']\n')
            (path / '.bazelrc').write_text('common --repo_env=ASPECT_TOOLS_TELEMETRY=-all\n')
            g.configuration_gate(path)
            for setting in ['common --remote_cache=grpcs://host',
                            'common --repo_env=BAZEL_MSVC_RUNTIME_VISUAL_STUDIO_EULA=1',
                            'common --config=buildbuddy-generic']:
                (path / '.bazelrc').write_text(setting)
                with self.assertRaises(ValueError):
                    g.configuration_gate(path)

# Real Linux process cases run in a dedicated supervisor process so unrelated
# unittest children never become eligible for owned teardown.
import os
import subprocess
import signal
import sys
import time
from unittest.mock import patch
import dependency_patch_support as support

DRIVER = '''import sys,json,os
sys.path.insert(0,sys.argv[1]);import dependency_patch_support as s
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

class ActualPublicationFailure(unittest.TestCase):
    def test_failed_command_never_writes_either_stream_or_generated_locks(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);repo=root/'source';repo.mkdir();(repo/'codex-rs').mkdir()
            (repo/'codex-rs/Cargo.lock').write_text('version = 4\n')
            (repo/'MODULE.bazel.lock').write_text('{}')
            tool=root/'tool';tool.write_bytes(b'fake-test-tool')
            out=root/'out';control=root/'control';control.mkdir()
            streams=[support.Stream(),support.Stream()]
            streams[0].feed(b'safe stdout must remain private')
            streams[1].feed(b'token=verysecretvalue')
            result={'argv':['fixed-test-command'],'exit':1,'stop':None,
                    'cleanup':{'confirmed':True},'streams':[s.finish() for s in streams]}
            def git(repo,env,*args):
                return ((g.BASE+'\n').encode() if args==('rev-parse','HEAD') else
                        (g.BASE_TREE+'\n').encode() if args==('rev-parse','HEAD^{tree}') else b'')
            with patch.object(g,'BLOBS',{}), patch.object(g,'configuration_gate'), \
                 patch.object(g,'control_gate',return_value={'tree':'bound'}), \
                 patch.object(support,'identity'), patch.object(support,'input_gate',return_value=True), \
                 patch.object(support,'git',side_effect=git), \
                 patch.object(support,'capture',return_value=(result,streams)), \
                 patch.object(g.shutil,'which',return_value=str(tool)), \
                 patch.object(g.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()):
                self.assertEqual(g.main(repo,out,control),1)
            names={p.name for p in (out/'public').iterdir()}
            self.assertEqual(names,{'before-Cargo.lock','before-MODULE.bazel.lock','report.json'})
            report=json.loads((out/'public/report.json').read_text())
            self.assertFalse(report['publication_gate_passed'])
            self.assertNotIn('verysecretvalue',json.dumps(report))
            self.assertNotIn('safe stdout',json.dumps(report))


class ContentClosure(unittest.TestCase):
    setUp = Gates.setUp
    def test_nonfinite_outer_and_embedded_json_rejected(self):
        for number in ('1e999', '-1e999', 'NaN', 'Infinity', '-Infinity'):
            with self.subTest(number=number, location='outer'):
                value=json.dumps(self.new_bazel)[:-1]+',"opaque":'+number+'}'
                with self.assertRaisesRegex(ValueError, 'nonfinite_json_number'):
                    g.bazel_delta(json.dumps(self.old_bazel), value)
            with self.subTest(number=number, location='embedded'):
                value=copy.deepcopy(self.new_bazel)
                target=g.TARGETS[0];key=target['name']+'_'+target['new']
                value['facts'][g.CRATE_FACTS][key]='{"opaque":'+number+'}'
                with self.assertRaisesRegex(ValueError, 'nonfinite_json_number'):
                    g.bazel_delta(json.dumps(self.old_bazel), json.dumps(value))

    def test_full_metadata_command_invariants(self):
        commands=g.metadata_commands()
        self.assertEqual(len(commands),2)
        for command in commands:
            self.assertEqual(command[:3], ['cargo','+1.95.0','metadata'])
            self.assertIn('--locked',command)
            self.assertIn('--all-features',command)
            self.assertIn('--format-version=1',command)
            self.assertNotIn('--no-deps',command)
            self.assertFalse(any(x.startswith('--filter-platform') for x in command))
        self.assertNotIn('--offline',commands[0])
        self.assertIn('--offline',commands[1])
        self.assertEqual(commands[0], [x for x in commands[1] if x!='--offline'])

    def test_preventive_targets_are_not_in_observed_batch(self):
        self.assertEqual([x['name'] for x in g.TARGETS],
                         ['rustls-webpki','rustls','webpki-roots','webpki-root-certs'])

    def test_numeric_type_coercion_rejected(self):
        with self.assertRaisesRegex(ValueError, 'cargo_nonpackage_drift'):
            g.cargo_delta(encode(self.packages), encode(self.new).replace(b'version = 4', b'version = 4.0', 1), g.TARGETS)

    def test_new_comment_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unexpected_cargo_comment'):
            g.cargo_lexical_gate(encode(self.packages), encode(self.new)+b'# token=secret\n')

    def test_inline_comment_rejected(self):
        with self.assertRaises(ValueError):
            g.cargo_lexical_gate(encode(self.packages), encode(self.new)+b'version = 4 # secret\n')

    def test_arbitrary_target_field_rejected(self):
        self.new[0]['opaque'] = 'secret'
        with self.assertRaisesRegex(ValueError, 'unexpected_target_record_fields'):
            g.cargo_delta(encode(self.packages), encode(self.new), g.TARGETS)

    def test_duplicate_json_field_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_json_key'):
            g.bazel_delta(json.dumps(self.old_bazel), '{"secret":"hidden","secret":null}')

    def test_duplicate_embedded_fact_rejected(self):
        target=g.TARGETS[0]
        key=target['name']+'_'+target['new']
        fact=self.new_bazel['facts'][g.CRATE_FACTS][key]
        field=next(iter(target['fact']))
        self.new_bazel['facts'][g.CRATE_FACTS][key]='{'+json.dumps(field)+':"secret",'+fact[1:]
        with self.assertRaisesRegex(ValueError, 'duplicate_json_key'):
            g.bazel_delta(json.dumps(self.old_bazel), json.dumps(self.new_bazel))

    def test_known_url_and_comments_closed(self):
        extra=dict(name='public-git',version='1.0.0',
                   source='git+https://github.com/helix-editor/nucleo.git?rev=4253de9faabb4e5c6d81d946a5e35a90f87347ee')
        old=encode(self.packages+[extra]);new=encode(self.new+[extra])
        before={g.LOCKS[0]:old,g.LOCKS[1]:json.dumps(self.old_bazel).encode()}
        after={g.LOCKS[0]:new,g.LOCKS[1]:json.dumps(self.new_bazel).encode()}
        g.known_lock_content(before,after)

class ActualPublicationSuccess(unittest.TestCase):
    def test_raw_secret_and_public_metadata_url_never_exported(self):
        fixture=Gates();fixture.setUp()
        for raw in (b'token=verysecretvalue',
                    b'git+https://github.com/helix-editor/nucleo.git?rev=4253de9faabb4e5c6d81d946a5e35a90f87347ee'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as root:
                root=Path(root);repo=root/'source';repo.mkdir();(repo/'codex-rs').mkdir()
                (repo/g.LOCKS[0]).write_bytes(encode(fixture.packages))
                (repo/g.LOCKS[1]).write_text(json.dumps(fixture.old_bazel))
                tool=root/'tool';tool.write_bytes(b'fake-test-tool')
                out=root/'out';control=root/'control';control.mkdir()
                packages=copy.deepcopy(fixture.packages)
                def git(repo,env,*args):
                    if args==('rev-parse','HEAD'):return g.BASE.encode()
                    if args==('rev-parse','HEAD^{tree}'):return g.BASE_TREE.encode()
                    return b''
                def capture(argv,env,seconds,disk):
                    stdout=b''
                    if argv[:3]==['cargo','+1.95.0','-V']:stdout=b'cargo 1.95.0 test'
                    elif argv[:3]==['rustc','+1.95.0','-Vv']:stdout=b'rustc 1.95.0 test'
                    elif argv[0]=='rustup':stdout=str(tool).encode()
                    elif argv[-2:]==['version','--gnu_format']:stdout=b'bazel 9.0.0'
                    elif argv[:3]==['cargo','+1.95.0','update']:
                        i=next(i for i,t in enumerate(g.TARGETS) if t['name']+'@'+t['old']==argv[4])
                        packages[i]=fixture.new[i];(repo/g.LOCKS[0]).write_bytes(encode(packages))
                    elif '--lockfile_mode=update' in argv:
                        (repo/g.LOCKS[1]).write_text(json.dumps(fixture.new_bazel))
                    elif 'metadata' in argv:stdout=raw
                    streams=[support.Stream(),support.Stream()]
                    streams[0].feed(stdout);streams[1].feed(raw)
                    return {'argv':argv,'exit':0,'stop':None,'cleanup':{'confirmed':True},
                            'streams':[s.finish() for s in streams]},streams
                with patch.object(g,'BLOBS',{}), patch.object(g,'configuration_gate'), \
                     patch.object(g,'control_gate',return_value={'tree':'bound'}), \
                     patch.object(g,'registry_recheck',return_value=[]), \
                     patch.object(support,'identity'),patch.object(support,'input_gate',return_value=True), \
                     patch.object(support,'git',side_effect=git),patch.object(support,'capture',side_effect=capture), \
                     patch.object(g.shutil,'which',return_value=str(tool)), \
                     patch.object(g.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()):
                    self.assertEqual(g.main(repo,out,control),0)
                names={p.name for p in (out/'public').iterdir()}
                self.assertEqual(names,{'before-Cargo.lock','before-MODULE.bazel.lock','report.json',
                                       'after-Cargo.lock','after-MODULE.bazel.lock','locks.diff'})
                for file in (out/'public').iterdir():
                    self.assertNotIn(raw,file.read_bytes())
                report=json.loads((out/'public/report.json').read_text())
                self.assertTrue(report['publication_gate_passed'])
                self.assertTrue(report['known_lock_content_confirmed'])
                self.assertEqual([c['argv'] for c in report['commands'] if 'version' in c['argv']],
                    [['bazel','--batch','--nosystem_rc','--nohome_rc',
                      '--output_user_root='+str(out/'bazel-root'),
                      '--output_base='+str(out/'bazel-output'),
                      '--noexperimental_remote_repo_contents_cache','version','--gnu_format']])
                self.assertEqual([c['argv'] for c in report['commands'] if 'metadata' in c['argv']],
                                 g.metadata_commands())
                for command in report['commands']:
                    self.assertEqual(command['exit'],0)
                    for stream in command['streams']:
                        self.assertEqual(len(stream['sha256']),64)
                        self.assertIsInstance(stream['bytes'],int)


class KeylessBootstrap(unittest.TestCase):
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
            with patch.dict(os.environ,{'GITHUB_PATH':str(github_path)}),                  patch.object(g,'BAZEL_ASSET_BYTES',len(body)),patch.object(g,'BAZEL_ASSET_SHA256',g.digest(body)),                  patch.object(g,'control_gate',return_value={'bound':True}),patch.object(support,'identity'),                  patch.object(support,'capture',side_effect=capture),                  patch.object(g.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()):
                self.assertEqual(g.bootstrap_bazel(repo,out,control),0)
            self.assertEqual(github_path.read_text(),str(out/'job-tools')+'\n')
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
            with patch.dict(os.environ,{'GITHUB_PATH':str(github_path)}),                  patch.object(g,'control_gate',return_value={'bound':True}),patch.object(support,'identity'),                  patch.object(support,'capture',return_value=(result,streams)) as capture,                  patch.object(g.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()):
                self.assertEqual(g.bootstrap_bazel(repo,out,control),1)
            self.assertEqual(capture.call_count,1);self.assertEqual(github_path.read_bytes(),b'')
            receipt=json.loads((out/'public/bootstrap.json').read_text())
            self.assertEqual(receipt['hold'],'public_asset_http_denied_or_failed')


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


if __name__ == '__main__':
    unittest.main()
