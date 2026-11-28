"""Publication controls use real, small Git objects; no model execution or network."""
from contextlib import ExitStack, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import publish_mosi as relay


class PublicationResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mosi-publication-control-')
        self.addCleanup(self.temp.cleanup)
        self.task=Path(self.temp.name);self.root=self.task/'publication';self.root.mkdir()
        self.repo=self.task/'remote.git';self.repo.mkdir()
        self.command(['init','--bare'])
        self.kinds=('mosi_recovery_raw','mosi_fresh_raw');self.maps={};self.manifests={}
        self.ready=[self.task/'candidate_replay/reconstruction_result.json',self.task/'fresh/terminal_manifest.json']
        for path in self.ready:path.parent.mkdir();path.write_text('{}\n')
        for kind in self.kinds:
            base=self.task/kind;base.mkdir();files={}
            for name in ('source.py','selected/weights.pt'):
                path=base/name;path.parent.mkdir(exist_ok=True);path.write_bytes(('control fixture: '+kind+' '+name).encode())
                files[name]=path
            self.maps[kind]=files
            report={name:{'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}
                    for name,path in sorted(files.items())}
            self.manifests[kind]=(json.dumps(report,indent=2,allow_nan=False)+'\n').encode()
        self.commit=self.archive()
        self.api=mock.Mock(side_effect=self.git_api)
        self.push=mock.Mock(return_value=self.commit)
        self.map_calls=[mock.Mock(return_value=self.maps[kind]) for kind in self.kinds]
        self.output=io.StringIO();self.git_calls=[]

    def command(self,args,data=None):
        result=subprocess.run(['git',*args],input=data,capture_output=True,cwd=self.repo,timeout=10)
        if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace'))
        return result.stdout.decode().strip()

    def archive(self,omit=None,corrupt=None):
        self.command(['read-tree','--empty']);entries=[]
        for kind in self.kinds:
            files={name:path.read_bytes() for name,path in self.maps[kind].items()}
            files['verified_objects.json']=self.manifests[kind]
            files['independent/append.json']=b'{"unrelated_appended_scope":true}\n'
            for name,data in files.items():
                path=relay.PREFIX+kind+'/'+name
                if path==omit:continue
                if path==corrupt:data=b'different bytes, valid Git blob'
                oid=self.command(['hash-object','-w','--stdin'],data)
                entries.append(f'100644 blob {oid}\t{path}\0'.encode())
        self.command(['update-index','-z','--index-info'],b''.join(entries))
        tree=self.command(['write-tree'])
        commit=self.command(['-c','user.name=Publication Test','-c','user.email=test@example.invalid',
                             'commit-tree',tree],b'Synthetic publication control\n')
        self.command(['update-ref','refs/heads/'+relay.BRANCH,commit])
        return commit

    def git_api(self,method,endpoint,body=None):
        self.assertEqual(method,'GET');self.assertIsNone(body)
        self.assertTrue(endpoint.startswith(relay.API+'/'))
        part=endpoint.removeprefix(relay.API+'/')
        if part.startswith('commits/'):
            commit=part.removeprefix('commits/')
            return {'sha':self.command(['rev-parse',commit+'^{commit}']),
                    'tree':{'sha':self.command(['rev-parse',commit+'^{tree}'])}}
        tree=part.removeprefix('trees/').split('?')[0]
        args=['ls-tree','-rz' if '?recursive=1' in part else '-z',tree]
        entries=[]
        for record in self.command(args).split('\0'):
            if not record:continue
            metadata,path=record.split('\t',1);mode,kind,oid=metadata.split(' ')
            entries.append({'path':path,'type':kind,'mode':mode,'sha':oid})
        return {'sha':tree,'truncated':False,'tree':entries}

    def receipt(self,kind,commit=None):
        data=self.manifests[kind]
        return {'kind':kind,'commit':commit or self.commit,'branch':relay.BRANCH,
                'repo_prefix':relay.PREFIX+kind+'/','file_count':len(self.maps[kind])+1,
                'route':'GitHub Git Data API','manifest_sha256':hashlib.sha256(data).hexdigest(),
                'manifest_blob':self.command(['hash-object','--stdin'],data),'utc_unix':1795860000.0}

    def receipts(self):
        for kind in self.kinds:self.marker(kind).write_text(json.dumps(self.receipt(kind))+'\n')

    def marker(self,kind):return self.root/(kind+'-receipt.json')

    def run_relay(self):
        helper=Path(__file__).resolve().parent.parent/'crema/publish_results.py'
        original_spec=importlib.util.spec_from_file_location
        original_git=relay.git
        def spec_for(name,path):
            spec=original_spec(name,path)
            if name=='results_helper':
                execute=spec.loader.exec_module
                def load(module):
                    execute(module);module.gh=self.api;module.push=self.push
                spec.loader.exec_module=load
            return spec
        def recorded_git(cwd,args,*pos,**kwargs):
            self.git_calls.append(args[:])
            self.assertNotIn(args[0],('push','update-ref'))
            return original_git(cwd,args,*pos,**kwargs)
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys,'path',sys.path[:]))
            stack.enter_context(mock.patch.dict(sys.modules));sys.modules.pop('archive',None)
            for target,value in [('SHARED',str(helper)),('REPO',str(self.repo)),('git',recorded_git),
                                 ('recovery_map',self.map_calls[0]),('fresh_map',self.map_calls[1])]:
                stack.enter_context(mock.patch.object(relay,target,value))
            stack.enter_context(mock.patch.object(importlib.util,'spec_from_file_location',spec_for))
            stack.enter_context(mock.patch.object(relay,'native',side_effect=AssertionError('no publication fallback in controls')))
            stack.enter_context(mock.patch.object(relay.time,'sleep',side_effect=AssertionError('no waiting in controls')))
            stack.enter_context(redirect_stdout(self.output))
            relay.run(self.task)

    def test_original_bad_json_and_wrong_scope_never_skip(self):
        for raw in ('not JSON\n',json.dumps({**self.receipt(self.kinds[0]),'kind':'wrong','branch':'wrong'})):
            with self.subTest(raw=raw[:30]):
                for kind in self.kinds:self.marker(kind).write_text(raw)
                with self.assertRaises(relay.PublicationIncomplete):self.run_relay()
                self.assertEqual([self.marker(k).read_text() for k in self.kinds],[raw,raw])
        self.assertEqual([m.call_count for m in self.map_calls],[0,0]);self.api.assert_not_called();self.push.assert_not_called()

    def test_receipt_schema_and_scalar_mutations_rejected(self):
        kind=self.kinds[0];valid=self.receipt(kind)
        mutations={'kind':['wrong'],'branch':['wrong'],'repo_prefix':['../wrong/'],'commit':['0'*40,'HEAD','ABCDEF'*7],
                   'manifest_blob':['0'*40],'manifest_sha256':['bad'],'route':['completed'],'file_count':[True,0,3.0],
                   'utc_unix':[True,float('nan'),float('inf'),'now']}
        for key,values in mutations.items():
            for value in values:
                with self.subTest(key=key,value=value):
                    self.marker(kind).write_text(json.dumps({**valid,key:value}))
                    with self.assertRaises(relay.PublicationIncomplete):self.run_relay()
        for raw in ('[]',json.dumps(valid)[:-1]+',"commit":"'+self.commit+'"}'):
            self.marker(kind).write_text(raw)
            with self.assertRaises(relay.PublicationIncomplete):self.run_relay()
        self.api.assert_not_called();self.push.assert_not_called()

    def test_valid_receipts_read_current_sources_and_exact_git_objects(self):
        self.receipts();before=[self.marker(k).read_bytes() for k in self.kinds]
        self.run_relay()
        self.assertEqual([m.call_count for m in self.map_calls],[1,1]);self.push.assert_not_called()
        self.assertEqual([self.marker(k).read_bytes() for k in self.kinds],before)
        self.assertEqual(self.output.getvalue().count('resumed verified publication'),2)
        for kind in self.kinds:self.assertEqual(relay.publication_snapshot(self.maps[kind])[0],self.manifests[kind])

    def test_valid_recovery_resume_continues_fresh_publication(self):
        kind=self.kinds[0];self.marker(kind).write_text(json.dumps(self.receipt(kind)))
        before=self.marker(kind).read_bytes();self.run_relay()
        self.assertEqual(self.marker(kind).read_bytes(),before)
        self.assertEqual([m.call_count for m in self.map_calls],[1,1])
        self.assertEqual([call.args[0] for call in self.push.call_args_list],[self.kinds[1]])
        self.assertEqual(relay.receipt_from(self.marker(self.kinds[1]),self.kinds[1])['commit'],self.commit)

    def test_missing_local_terminal_cannot_claim_complete(self):
        self.receipts();self.ready[0].unlink()
        with self.assertRaisesRegex(relay.PublicationIncomplete,'missing local terminal'):self.run_relay()
        self.assertEqual([m.call_count for m in self.map_calls],[0,0]);self.api.assert_not_called();self.push.assert_not_called()

    def test_original_validator_assertion_retains_receipts_and_stops(self):
        self.receipts();before=[self.marker(k).read_bytes() for k in self.kinds]
        for failing in (0,1):
            for validation in self.map_calls:validation.reset_mock();validation.side_effect=None
            self.map_calls[failing].side_effect=AssertionError('original saved prediction seal mismatch')
            with self.subTest(scope=self.kinds[failing]),self.assertRaisesRegex(relay.PublicationIncomplete,'prediction seal mismatch') as error:
                self.run_relay()
            self.assertIsInstance(error.exception.__cause__,AssertionError)
            self.assertEqual([m.call_count for m in self.map_calls],[1,failing])
            self.assertEqual([self.marker(k).read_bytes() for k in self.kinds],before)
        self.push.assert_not_called()

    def test_optimized_interpreters_refuse_before_helper_or_any_io(self):
        program='''
from pathlib import Path
import publish_mosi as relay
def forbidden(*args, **kwargs):
    raise RuntimeError("unexpected helper loading, I/O, waiting or publication")
relay.digest = forbidden
relay.importlib.util.spec_from_file_location = forbidden
relay.subprocess.run = forbidden
relay.time.sleep = forbidden
relay.SHARED = "/missing/helper/must-not-be-opened.py"
try:
    relay.run(Path("must-not-be-created"))
except relay.PublicationIncomplete as error:
    if "requires Python assertions" not in str(error):
        raise SystemExit(str(error))
else:
    raise SystemExit("optimized execution was not rejected")
'''
        module_dir=Path(__file__).resolve().parent
        program='import sys; sys.path.insert(0, '+repr(str(module_dir))+')\n'+program
        before=sorted(str(p.relative_to(self.task)) for p in self.task.rglob('*'))
        for option in ('-O','-OO'):
            with self.subTest(option=option):
                result=subprocess.run([sys.executable,option,'-B','-c',program],cwd=self.task,capture_output=True,timeout=10)
                self.assertEqual((result.returncode,result.stdout,result.stderr),(0,b'',b''))
        self.assertEqual(sorted(str(p.relative_to(self.task)) for p in self.task.rglob('*')),before)

    def test_source_change_or_manifest_count_mismatch_stops_before_remote_read(self):
        self.receipts();kind=self.kinds[0];path=self.maps[kind]['source.py'];before=path.read_bytes()
        for change in ('source','count','hash','blob'):
            with self.subTest(change=change):
                doc=self.receipt(kind)
                if change=='source':path.write_bytes(b'changed source')
                if change=='count':doc['file_count']+=1
                if change=='hash':doc['manifest_sha256']='1'*64
                if change=='blob':doc['manifest_blob']='1'*40
                self.marker(kind).write_text(json.dumps(doc))
                with self.assertRaisesRegex(relay.PublicationIncomplete,'current verified inputs'):self.run_relay()
                path.write_bytes(before)
        self.api.assert_not_called();self.push.assert_not_called()

    def test_missing_local_original_stays_incomplete(self):
        self.receipts();self.maps[self.kinds[0]]['selected/weights.pt'].unlink()
        with self.assertRaisesRegex(relay.PublicationIncomplete,'current input verification failed'):self.run_relay()
        self.api.assert_not_called();self.push.assert_not_called()

    def test_manifest_without_original_or_wrong_blob_is_not_complete(self):
        self.receipts();kind=self.kinds[0];target=relay.PREFIX+kind+'/selected/weights.pt'
        for mutation in ('omit','corrupt'):
            with self.subTest(mutation=mutation):
                commit=self.archive(**{mutation:target});raw=json.dumps(self.receipt(kind,commit))
                self.marker(kind).write_text(raw)
                with self.assertRaisesRegex(relay.PublicationIncomplete,'remote object mismatch'):self.run_relay()
                self.assertEqual(self.marker(kind).read_text(),raw)
        self.push.assert_not_called()

    def test_nonexistent_fixed_commit_is_incomplete_after_both_transports(self):
        self.receipts();kind=self.kinds[0];self.marker(kind).write_text(json.dumps(self.receipt(kind,'1'*40)))
        with self.assertRaisesRegex(relay.PublicationIncomplete,'cannot read fixed remote commit'):self.run_relay()
        self.assertTrue(any(args[:2]==['fetch','--depth=1'] for args in self.git_calls));self.push.assert_not_called()

    def test_api_transport_failure_reads_real_native_git_objects_without_push(self):
        self.receipts();self.api.side_effect=RuntimeError('API unavailable in local control')
        self.run_relay()
        self.assertEqual(self.output.getvalue().count('native immutable commit tree'),2)
        self.assertEqual([args[-1] for args in self.git_calls if args[0]=='fetch'],[self.commit,self.commit])
        self.push.assert_not_called()

    def test_bad_api_identity_or_truncated_tree_never_falls_back_to_skip(self):
        self.receipts()
        for mutation in ('commit','tree'):
            def bad(method,endpoint,body=None):
                doc=self.git_api(method,endpoint,body)
                if mutation=='commit' and '/commits/' in endpoint:doc['sha']='1'*40
                if mutation=='tree' and '/trees/' in endpoint:doc['truncated']=True
                return doc
            self.api.side_effect=bad
            with self.subTest(mutation=mutation),self.assertRaises(relay.PublicationIncomplete):self.run_relay()
        self.assertEqual(self.git_calls,[]);self.push.assert_not_called()

    def test_unsafe_local_object_paths_cannot_publish(self):
        self.receipts();kind=self.kinds[0]
        for name in ('../source.py','/source.py','selected//weights.pt','selected\\weights.pt','verified_objects.json'):
            self.map_calls[0].return_value={name:self.maps[kind]['source.py']}
            with self.subTest(name=name),self.assertRaisesRegex(relay.PublicationIncomplete,'unsafe object path'):self.run_relay()
        self.api.assert_not_called();self.push.assert_not_called()

    def test_new_publication_requires_original_objects_before_writing_receipt(self):
        kind=self.kinds[0];target=relay.PREFIX+kind+'/selected/weights.pt'
        self.push.side_effect=lambda *args:self.archive(omit=target)
        with self.assertRaisesRegex(relay.PublicationIncomplete,'remote object mismatch'):self.run_relay()
        self.assertFalse(self.marker(kind).exists());self.assertEqual(self.map_calls[1].call_count,0)


if __name__=='__main__':unittest.main()
