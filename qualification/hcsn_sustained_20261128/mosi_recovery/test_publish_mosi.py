"""Original math on explicit synthetic fixtures, real Git objects, and frozen publication controls; no models or network."""
from contextlib import ExitStack, redirect_stdout
import hashlib
import base64
import importlib.util
import io
import os
import shutil
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
import numpy as np
from unittest import mock

import publish_mosi as relay


# These fixtures execute the original saved-prediction verifier. They do not run a
# model or claim synthetic predictions are scientific experiment results.
def fixture_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,indent=1,allow_nan=False)+'\n')


def build_math_fixture(root):
    here=Path(__file__).resolve().parent
    (root/'source').mkdir(parents=True)
    for source,destination,expected in [
        (here/'fresh_study.py',root/'fresh_study.py',relay.FRESH_DRIVER_SHA),
        (here.parent.parent/'hcsn_mosi_three_stream_20261127/verify.py',root/'source/verify.py',relay.FRESH_VERIFIER_SHA),
    ]:
        payload=source.read_bytes()
        if hashlib.sha256(payload).hexdigest()!=expected:raise AssertionError('original validator fixture source identity')
        destination.write_bytes(payload)
    protocol=(here/'PROSPECTIVE_REPLICATION.md').read_bytes()
    (root/'PROSPECTIVE_REPLICATION.md').write_bytes(protocol)
    fixture_json(root/'input_recovery.json',{'fixture_only':True,'note':'synthetic publisher control'})
    fixture_json(root/'source_transfer.json',{'fixture_only':True})
    count=686;videos=np.arange(count,dtype=np.int64)%31
    y=np.linspace(-2,2,count,dtype=np.float32)
    weights=b'synthetic publisher fixture: opaque weight identity, no inference\n'
    old=root/'candidate_replay';(old/'fits').mkdir(parents=True)
    (old/'fits/weights.pt').write_bytes(weights)
    fixture_json(root/'source/SEAL.json',{'fixture_only':True,'weights':{'weights.pt':relay.digest(old/'fits/weights.pt')}})
    fixture_json(old/'candidate_hash_seal.json',{'fixture_only':True})
    np.savez_compressed(old/'weights.pt.cold.npz',y=y,video=videos,intact=y+np.float32(.1))
    delta=np.abs((y+np.float32(.1))-y)
    mae=float(np.asarray([delta[videos==v].mean() for v in np.unique(videos)]).mean())
    fixture_json(old/'reconstruction_result.json',{
        'fixture_only':True,'eligible_objects':1,
        'original_seal_sha256':relay.digest(root/'source/SEAL.json'),
        'hash_comparison_seal_sha256':relay.digest(old/'candidate_hash_seal.json'),
        'authenticated_cold_results':{'weights.pt':{
            'score_sha256':relay.digest(old/'weights.pt.cold.npz'),'intact':{'video_mae':mae}}}})
    fixture_json(root/'reconstructed/data.json',{
        'fixture_only':True,'feature_prep_total_wall_s':1.25,
        'splits':{key:{'videos':list(range(n))} for key,n in [('train',52),('valid',10),('test',31)]}})
    fresh=root/'fresh';(fresh/'models').mkdir(parents=True);(fresh/'cold').mkdir()
    (fresh/'models/control.pt').write_bytes(weights)
    fixture_json(fresh/'av_train_inputs/manifest.json',{'fixture_only':True})
    driver=relay.module_bytes('_fixture_pinned_driver',(root/'fresh_study.py').read_bytes(),root/'fresh_study.py')
    designs=driver.DESIGNS;fits={}
    for width,arm in designs:
        for seed in (413,677,941):
            key=f'{width}-{arm}-{seed}'
            selected={str(r):{'file':'control.pt','sha256':relay.digest(fresh/'models/control.pt'),
                               'cpu':1.0,'wall':.1,'dev_video_mae':.1,'steps':1} for r in (15,60,180)}
            fit={'fixture_only':True,'parameter_count':1,'selected':selected,
                 'common_process':{'wall':.01},'fit_wall':.5,'serialization_wall':.005,
                 'history':[{'cpu':1.0,'wall':.1},{'cpu':16.0,'wall':.2},
                            {'cpu':61.0,'wall':.3},{'cpu':181.0,'wall':.4}]}
            path=fresh/'models'/(key+'.json');fixture_json(path,fit);fits[path.name]=relay.digest(path)
    seal={'fixture_only':True,'fits':fits,'weights':{'control.pt':relay.digest(fresh/'models/control.pt')},
          'data_manifest_sha256':relay.digest(root/'reconstructed/data.json'),
          'fresh_driver_sha256':relay.digest(root/'fresh_study.py'),
          'fresh_protocol_sha256':relay.digest(root/'PROSPECTIVE_REPLICATION.md'),
          'AV_input_provenance_sha256':relay.digest(fresh/'av_train_inputs/manifest.json'),
          'code':{'verify.py':relay.digest(root/'source/verify.py')}}
    fixture_json(fresh/'FRESH_SEAL.json',seal)
    donor=np.stack([(np.arange(count)+shift)%count for shift in (1,2,3)])
    for width,arm in designs:
        for seed in (413,677,941):
            key=f'{width}-{arm}-{seed}'
            prediction=y+np.float32(.1+(seed%7)*.001)
            arrays={'y':y,'video':videos,'clip':np.arange(count,dtype=np.int64),'donors':donor}
            for r in (15,60,180):arrays['r'+str(r)]=prediction.copy()
            for channel in ('text','audio','vision','av'):
                arrays['drop_'+channel]=prediction+np.float32(.01)
                for index in range(3):arrays[f'swap_{channel}_{index}']=prediction+np.float32(.02)
            path=fresh/'cold'/(key+'.npz');np.savez_compressed(path,**arrays)
            fixture_json(path.with_suffix('.json'),{
                'fixture_only':True,'pred_sha256':relay.digest(path),
                'seal_sha256':relay.digest(fresh/'FRESH_SEAL.json'),'source_and_start_wall':.01,
                'rungs':{str(r):{'model_load_and_inference_wall':.01} for r in (15,60,180)}})
    verifier=relay.module_bytes('_fixture_pinned_original_verify',(root/'source/verify.py').read_bytes(),root/'source/verify.py')
    verifier.DESIGNS=designs;verifier.SHARED=('fp_h','fp_r','random_h','bp_h','transformer','fp_h_av')
    saved=sys.argv[:]
    try:
        sys.argv=[str(root/'source/verify.py'),str(fresh/'models'),str(fresh/'cold'),
                  str(root/'reconstructed/data.json'),str(fresh/'FRESH_SEAL.json'),str(fresh/'result')]
        with redirect_stdout(io.StringIO()):verifier.main()
    finally:sys.argv=saved
    files=sorted(p for section in ('models','cold','result') for p in (fresh/section).iterdir() if p.is_file())
    fixture_json(fresh/'terminal_manifest.json',{
        'fixture_only':True,'actual_groups':36,'score_archives':36,
        'seal_sha256':relay.digest(fresh/'FRESH_SEAL.json'),
        'summary_sha256':relay.digest(fresh/'result/SUMMARY.json'),
        'files':{str(path.relative_to(fresh)):relay.digest(path) for path in files}})
    with redirect_stdout(io.StringIO()):
        maps={'mosi_recovery_raw':relay.recovery_map(root),'mosi_fresh_raw':relay.fresh_map(root)}
    return {kind:{name:str(path.relative_to(root)) for name,path in paths.items()} for kind,paths in maps.items()}


class PublicationResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_temp=tempfile.TemporaryDirectory(prefix='mosi-original-validator-fixture-')
        cls.addClassCleanup(cls.fixture_temp.cleanup)
        cls.fixture_root=Path(cls.fixture_temp.name)
        cls.relative_maps=build_math_fixture(cls.fixture_root)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mosi-publication-control-')
        self.addCleanup(self.temp.cleanup)
        self.task=Path(self.temp.name);shutil.copytree(self.fixture_root,self.task,dirs_exist_ok=True)
        self.root=self.task/'publication';self.root.mkdir()
        self.repo=self.task/'remote.git';self.repo.mkdir();self.command(['init','--bare'])
        self.kinds=('mosi_recovery_raw','mosi_fresh_raw')
        self.maps={kind:{name:self.task/relative for name,relative in files.items()}
                   for kind,files in self.relative_maps.items()}
        self.manifests={kind:relay.publication_snapshot({name:path.read_bytes() for name,path in files.items()})[0]
                        for kind,files in self.maps.items()}
        self.ready=[self.task/'candidate_replay/reconstruction_result.json',self.task/'fresh/terminal_manifest.json']
        self.commit=self.archive();self.api=mock.Mock(side_effect=self.git_api)
        self.push=mock.Mock(return_value=self.commit)
        self.actual_mappers=(relay.recovery_map,relay.fresh_map)
        self.verifier_loads=mock.Mock();self.replay_outputs=[];self.verifier_hashes=[]
        self.map_calls=[mock.Mock(side_effect=self.actual_mappers[0]),mock.Mock(side_effect=self.tracked_fresh_map)]
        self.fresh_data=self.task/'reconstructed/data.json'
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
        original_publisher=relay.publisher_module;original_git=relay.git
        def load_publisher():
            module=original_publisher()
            module.gh=self.api;module.push=self.push
            return module
        def recorded_git(cwd,args,*pos,**kwargs):
            self.git_calls.append(args[:])
            self.assertNotIn(args[0],('push','update-ref'))
            return original_git(cwd,args,*pos,**kwargs)
        with ExitStack() as stack:
            for target,value in [('SHARED',str(helper)),('REPO',str(self.repo)),('git',recorded_git),
                                 ('recovery_map',self.map_calls[0]),('fresh_map',self.map_calls[1])]:
                stack.enter_context(mock.patch.object(relay,target,value))
            stack.enter_context(mock.patch.object(relay,'publisher_module',side_effect=load_publisher))
            stack.enter_context(mock.patch.object(relay,'native',side_effect=AssertionError('no publication fallback in these controls')))
            stack.enter_context(mock.patch.object(relay,'time',SimpleNamespace(
                time=relay.time.time,sleep=mock.Mock(side_effect=AssertionError('no waiting in controls')))))
            stack.enter_context(redirect_stdout(self.output))
            relay.run(self.task)

    def tracked_fresh_map(self,task):
        original_loader=relay.module_bytes;original_temp=relay.tempfile
        def observe_module(name,payload,path,*args,**kwargs):
            module=original_loader(name,payload,path,*args,**kwargs)
            if name=='_mosi_verified_fresh_verifier':
                identity=hashlib.sha256(payload).hexdigest()
                self.assertEqual(identity,relay.FRESH_VERIFIER_SHA)
                self.verifier_hashes.append(identity);self.verifier_loads()
            return module
        def observe_temp(*args,**kwargs):
            temporary=original_temp.TemporaryDirectory(*args,**kwargs)
            self.replay_outputs.append(Path(temporary.name))
            return temporary
        # Observe source loading and real temp paths only. The original module and
        # its main() function are returned untouched and actually execute.
        with mock.patch.object(relay,'module_bytes',side_effect=observe_module),mock.patch.object(
                relay,'tempfile',SimpleNamespace(TemporaryDirectory=observe_temp)):
            return self.actual_mappers[1](task)
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
        for kind in self.kinds:self.assertEqual(relay.publication_snapshot({name:path.read_bytes() for name,path in self.maps[kind].items()})[0],self.manifests[kind])

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
            for index,validation in enumerate(self.map_calls):
                validation.reset_mock()
                validation.side_effect=self.actual_mappers[0] if index==0 else self.tracked_fresh_map
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
relay.publisher_module = forbidden
relay.regular_bytes = forbidden
relay.module_bytes = forbidden
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
        self.receipts();kind=self.kinds[0];path=self.maps[kind]['input_recovery.json'];before=path.read_bytes()
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
        with self.assertRaisesRegex(relay.PublicationIncomplete,'input verification failed'):self.run_relay()
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
        self.receipts()
        for name in ('../source.py','/source.py','selected//weights.pt','selected\\weights.pt','verified_objects.json'):
            def invalid(private):
                actual=self.actual_mappers[0](private)
                return {name:actual['input_recovery.json']}
            self.map_calls[0].side_effect=invalid
            with self.subTest(name=name),self.assertRaisesRegex(relay.PublicationIncomplete,'unsafe object path|reserved manifest name'):
                self.run_relay()
        self.api.assert_not_called();self.push.assert_not_called()
    def test_new_publication_requires_original_objects_before_writing_receipt(self):
        kind=self.kinds[0];target=relay.PREFIX+kind+'/selected/weights.pt'
        self.push.side_effect=lambda *args:self.archive(omit=target)
        with self.assertRaisesRegex(relay.PublicationIncomplete,'remote object mismatch'):self.run_relay()
        self.assertFalse(self.marker(kind).exists());self.assertEqual(self.map_calls[1].call_count,0)


    def fresh_map_fixture(self):
        """Already-built synthetic inputs; the unchanged original verifier really runs."""
        return self.tracked_fresh_map
    def test_fresh_map_keeps_same_sealed_data_for_replay_and_publication(self):
        actual=self.fresh_map_fixture()
        before={name:path.read_bytes() for name,path in self.maps[self.kinds[1]].items()}
        files=actual(self.task)
        self.assertEqual(files,self.maps[self.kinds[1]])
        self.assertEqual(files['data.json'],self.fresh_data)
        self.verifier_loads.assert_called_once()
        self.assertTrue(self.replay_outputs and all(not p.exists() for p in self.replay_outputs))
        self.assertEqual({name:path.read_bytes() for name,path in files.items()},before)

    def test_fresh_new_publication_covers_data_in_manifest_and_fixed_tree(self):
        self.fresh_map_fixture();kind=self.kinds[1]
        self.marker(self.kinds[0]).write_text(json.dumps(self.receipt(self.kinds[0]))+'\n')
        source=self.fresh_data.read_bytes();self.run_relay()
        self.assertEqual([call.args[0] for call in self.push.call_args_list],[kind])
        supplied=self.push.call_args.args[1]
        published={str(item.relative_to(self.root/kind)):item.read_bytes() for item in supplied}
        self.assertEqual(published['data.json'],source)
        self.assertFalse((self.root/kind).exists())
        self.assertEqual(self.fresh_data.read_bytes(),source)
        receipt=relay.receipt_from(self.marker(kind),kind)
        self.assertEqual(receipt['file_count'],len(self.maps[kind])+1)
        data,objects=relay.publication_snapshot({name:path.read_bytes() for name,path in self.maps[kind].items()})
        self.assertIn('data.json',json.loads(data))
        actual=relay.api_objects(type('API',(),{'gh':staticmethod(self.git_api)})(),receipt['commit'],receipt['repo_prefix'])
        self.assertEqual(actual['data.json']['sha'],objects['data.json'])
        self.verifier_loads.assert_called_once()
    def test_fresh_missing_or_wrong_local_data_stops_before_replay(self):
        self.fresh_map_fixture();self.receipts();original=self.fresh_data.read_bytes()
        before=[self.marker(k).read_bytes() for k in self.kinds]
        for mutation in ('missing','wrong'):
            with self.subTest(mutation=mutation):
                if mutation=='missing':self.fresh_data.unlink()
                else:self.fresh_data.write_bytes(b'changed data manifest, not a scientific original')
                self.verifier_loads.reset_mock()
                with self.assertRaisesRegex(relay.PublicationIncomplete,'input verification failed'):
                    self.run_relay()
                self.verifier_loads.assert_not_called();self.push.assert_not_called()
                self.assertEqual([self.marker(k).read_bytes() for k in self.kinds],before)
                if mutation=='missing':self.assertFalse(self.fresh_data.exists())
                else:self.assertEqual(self.fresh_data.read_bytes(),b'changed data manifest, not a scientific original')
                self.fresh_data.write_bytes(original)

    def test_fresh_remote_missing_or_wrong_data_refuses_api_and_native_readback(self):
        self.fresh_map_fixture();kind=self.kinds[1];target=relay.PREFIX+kind+'/data.json'
        for route in ('api','native'):
            for mutation in ('omit','corrupt'):
                with self.subTest(route=route,mutation=mutation):
                    commit=self.archive(**{mutation:target});self.receipts()
                    raw=(json.dumps(self.receipt(kind,commit))+'\n').encode();self.marker(kind).write_bytes(raw)
                    self.api.side_effect=self.git_api if route=='api' else RuntimeError('fixture API unavailable')
                    with self.assertRaisesRegex(relay.PublicationIncomplete,'remote object mismatch data.json'):
                        self.run_relay()
                    self.assertEqual(self.marker(kind).read_bytes(),raw);self.push.assert_not_called()
                    if route=='native':self.assertTrue(any(a[0]=='fetch' and a[-1]==commit for a in self.git_calls))

    def test_fresh_legacy_manifest_receipt_cannot_skip_new_required_data(self):
        self.fresh_map_fixture();kind=self.kinds[1]
        current_files=self.maps[kind];current_manifest=self.manifests[kind]
        self.maps[kind]={k:v for k,v in current_files.items() if k!='data.json'}
        report={name:{'sha256':relay.digest(path),'size':path.stat().st_size}
                for name,path in sorted(self.maps[kind].items())}
        self.manifests[kind]=(json.dumps(report,indent=2)+'\n').encode()
        old_commit=self.archive();old_receipt=(json.dumps(self.receipt(kind,old_commit))+'\n').encode()
        self.maps[kind]=current_files;self.manifests[kind]=current_manifest
        self.receipts();self.marker(kind).write_bytes(old_receipt)
        with self.assertRaisesRegex(relay.PublicationIncomplete,'receipt does not bind current verified inputs'):
            self.run_relay()
        self.assertEqual(self.marker(kind).read_bytes(),old_receipt);self.push.assert_not_called()
        self.verifier_loads.assert_called_once()

    def test_fresh_terminal_cannot_replace_any_required_original(self):
        actual=self.fresh_map_fixture();base=self.task/'fresh';path=base/'terminal_manifest.json'
        original=path.read_bytes();source=self.fresh_data.read_bytes()
        required=('data.json','FRESH_SEAL.json','terminal_manifest.json','AV_input_provenance.json',
                  'PROSPECTIVE_REPLICATION.md','fresh_study.py','input_recovery.json')
        for name in required:
            with self.subTest(name=name):
                terminal=json.loads(original);terminal['files'][name]='1'*64
                path.write_text(json.dumps(terminal)+'\n')
                with self.assertRaisesRegex(ValueError,'fresh object overlaps required input '+re.escape(name)):
                    actual(self.task)
                self.assertEqual(self.fresh_data.read_bytes(),source)
        path.write_bytes(original)


    def empty_remote_tip(self):
        self.command(['read-tree','--empty']);tree=self.command(['write-tree'])
        current=self.command(['rev-parse','refs/heads/'+relay.BRANCH])
        tip=self.command(['-c','user.name=Publication Test','-c','user.email=test@example.invalid',
                          'commit-tree',tree,'-p',current],b'Empty local fixture destination\n')
        self.command(['update-ref','refs/heads/'+relay.BRANCH,tip])
        return tip

    def writable_git_api(self,method,endpoint,body=None):
        """Local bare Git implements the original helper's real Git Data API protocol."""
        self.assertTrue(endpoint.startswith(relay.API+'/'))
        part=endpoint.removeprefix(relay.API+'/')
        if method=='GET' and part=='ref/heads/'+relay.BRANCH:
            return {'object':{'sha':self.command(['rev-parse','refs/heads/'+relay.BRANCH])}}
        if method=='GET':return self.git_api(method,endpoint,body)
        if method=='POST' and part=='blobs':
            self.assertEqual(body['encoding'],'base64')
            payload=base64.b64decode(body['content'],validate=True)
            return {'sha':self.command(['hash-object','-w','--stdin'],payload)}
        if method=='POST' and part=='trees':
            self.command(['read-tree',body['base_tree']]);entries=[]
            for row in body['tree']:
                self.assertEqual((row['mode'],row['type']),('100644','blob'))
                entries.append(f"100644 blob {row['sha']}\t{row['path']}\0".encode())
            self.command(['update-index','-z','--index-info'],b''.join(entries))
            return {'sha':self.command(['write-tree'])}
        if method=='POST' and part=='commits':
            args=['-c','user.name=Publication Test','-c','user.email=test@example.invalid','commit-tree',body['tree']]
            for parent in body['parents']:args+=['-p',parent]
            return {'sha':self.command(args,(body['message']+'\n').encode())}
        if method=='PATCH' and part=='refs/heads/'+relay.BRANCH:
            self.assertIs(body['force'],False)
            old=self.command(['rev-parse','refs/heads/'+relay.BRANCH])
            self.command(['merge-base','--is-ancestor',old,body['sha']])
            self.command(['update-ref','refs/heads/'+relay.BRANCH,body['sha'],old])
            return {'object':{'sha':body['sha']}}
        raise AssertionError('unexpected local API request '+method+' '+part)

    def publish_frozen_locally(self,frozen,kind,route='api'):
        helper=Path(__file__).resolve().parent.parent/'crema/publish_results.py'
        with mock.patch.object(relay,'SHARED',str(helper)),mock.patch.object(relay,'REPO',str(self.repo)):
            pub=relay.publisher_module();pub.gh=self.writable_git_api
            files=frozen.files(self.root,kind)
            self.assertTrue(all(type(item.read_bytes()) is bytes for item in files))
            self.assertFalse((self.root/kind).exists())
            if route=='api':
                commit=pub.push(kind,files,self.root);route_name='GitHub Git Data API'
            else:
                with mock.patch.object(relay,'git',wraps=relay.git) as commands:
                    commit=relay.native(self.root,kind,files)
                hashes=[call for call in commands.call_args_list if call.args[1][:2]==['hash-object','-w']]
                self.assertEqual(len(hashes),len(files))
                self.assertTrue(all(call.args[1]==['hash-object','-w','--stdin'] and
                                    type(call.args[2]) is bytes for call in hashes))
                pub.gh=mock.Mock(side_effect=RuntimeError('local API transport unavailable'))
                route_name='native Git fast-forward'
            receipt={'kind':kind,'commit':commit,'branch':relay.BRANCH,
                     'repo_prefix':relay.PREFIX+kind+'/','file_count':len(files),
                     'route':route_name,'manifest_sha256':hashlib.sha256(frozen.manifest).hexdigest(),
                     'manifest_blob':frozen.objects['verified_objects.json'],'utc_unix':1795870000.0}
            selected=relay.verify_publication(pub,self.root,kind,receipt,frozen.manifest,frozen.objects)
            self.assertIn('native' if route=='native' else 'GitHub',selected)
            return receipt

    def scope_target(self,kind,task):
        return task/('candidate_replay/fits/weights.pt' if kind==self.kinds[0] else 'reconstructed/data.json')

    def original_mapper(self,kind):
        return self.actual_mappers[0] if kind==self.kinds[0] else self.tracked_fresh_map

    def test_private_original_validation_produces_identical_manifest_and_no_live_paths(self):
        for kind in self.kinds:
            seen=[]
            def validate(private):
                self.assertNotEqual(private,self.task)
                self.assertEqual(private.stat().st_mode&0o777,0o700)
                for name in relay.capture_inputs(self.task,kind):
                    src=self.task/name;copied=private/name
                    self.assertNotEqual((src.stat().st_dev,src.stat().st_ino),
                                        (copied.stat().st_dev,copied.stat().st_ino))
                    self.assertEqual(copied.stat().st_nlink,1)
                    self.assertEqual(copied.stat().st_mode&0o222,0)
                seen.append(private)
                return self.original_mapper(kind)(private)
            with self.subTest(kind=kind):
                frozen=relay.freeze_publication(self.task,self.root,kind,validate)
                self.assertEqual(frozen.manifest,self.manifests[kind])
                self.assertTrue(seen and all(not path.exists() for path in seen))
                self.assertEqual(dict(frozen.payloads),{name:path.read_bytes() for name,path in self.maps[kind].items()})

    def test_mutation_after_capture_cannot_replace_bytes_given_to_original_api(self):
        original_capture=relay.capture_inputs
        for kind in self.kinds:
            target=self.scope_target(kind,self.task);original=target.read_bytes()
            changed=original.replace(b'1.25',b'9.25') if kind==self.kinds[1] else b'X'*len(original)
            self.assertNotEqual(changed,original)
            def capture(task,scope):
                captured=original_capture(task,scope)
                target.write_bytes(changed)
                return captured
            with self.subTest(kind=kind),mock.patch.object(relay,'capture_inputs',side_effect=capture):
                frozen=relay.freeze_publication(self.task,self.root,kind,self.original_mapper(kind))
            self.empty_remote_tip()
            receipt=self.publish_frozen_locally(frozen,kind,'api')
            published_name='selected/weights.pt' if kind==self.kinds[0] else 'data.json'
            oid=frozen.objects[published_name]
            result=subprocess.run(['git','cat-file','blob',oid],cwd=self.repo,capture_output=True,check=True)
            self.assertEqual(result.stdout,original)
            self.assertNotEqual(result.stdout,target.read_bytes())
            self.assertEqual(receipt['manifest_blob'],frozen.objects['verified_objects.json'])
            target.write_bytes(original)

    def test_mutation_after_validation_cannot_change_snapshot_or_native_stdin(self):
        for kind in self.kinds:
            target=self.scope_target(kind,self.task);original=target.read_bytes()
            def validate(private):
                selected=self.original_mapper(kind)(private)
                target.write_bytes(b'Z'*len(original))
                return selected
            with self.subTest(kind=kind):
                frozen=relay.freeze_publication(self.task,self.root,kind,validate)
                self.empty_remote_tip()
                self.publish_frozen_locally(frozen,kind,'native')
                published_name='selected/weights.pt' if kind==self.kinds[0] else 'data.json'
                self.assertEqual(dict(frozen.payloads)[published_name],original)
                self.assertNotEqual(target.read_bytes(),original)
            target.write_bytes(original)

    def test_private_replacement_before_original_validator_refuses_and_preserves_receipts(self):
        self.receipts();before=[self.marker(k).read_bytes() for k in self.kinds]
        for index,kind in enumerate(self.kinds):
            for n,call in enumerate(self.map_calls):
                call.side_effect=self.actual_mappers[0] if n==0 else self.tracked_fresh_map
            def replace(private):
                target=self.scope_target(kind,private);content=target.read_bytes()
                target.unlink();target.write_bytes(b'B'*len(content))
                return self.original_mapper(kind)(private)
            self.map_calls[index].side_effect=replace
            with self.subTest(kind=kind),self.assertRaises(relay.PublicationIncomplete):
                self.run_relay()
            self.assertEqual([self.marker(k).read_bytes() for k in self.kinds],before)
        self.push.assert_not_called()

    def test_private_replacement_after_original_validator_refuses_even_same_bytes(self):
        for kind in self.kinds:
            for same in (False,True):
                def replace(private):
                    selected=self.original_mapper(kind)(private)
                    target=self.scope_target(kind,private);content=target.read_bytes()
                    replacement=target.with_name(target.name+'.replacement')
                    replacement.write_bytes(content if same else b'B'*len(content))
                    replacement.chmod(0o400);replacement.replace(target)
                    return selected
                with self.subTest(kind=kind,same_bytes=same),self.assertRaisesRegex(
                        relay.PublicationIncomplete,'private input identity changed'):
                    relay.freeze_publication(self.task,self.root,kind,replace)
        self.push.assert_not_called()

    def test_private_symlink_and_hardlink_substitution_refuse(self):
        for kind in self.kinds:
            for symlink in (True,False):
                def replace(private):
                    selected=self.original_mapper(kind)(private)
                    target=self.scope_target(kind,private);source=self.scope_target(kind,self.task)
                    target.unlink()
                    if symlink:target.symlink_to(source)
                    else:os.link(source,target)
                    return selected
                with self.subTest(kind=kind,symlink=symlink),self.assertRaises(relay.PublicationIncomplete):
                    relay.freeze_publication(self.task,self.root,kind,replace)

    def test_legal_source_hardlinks_are_independently_copied(self):
        for kind in self.kinds:
            source=self.scope_target(kind,self.task);alias=self.task/(kind+'-source-alias')
            os.link(source,alias)
            self.assertGreater(source.stat().st_nlink,1)
            try:
                with self.subTest(kind=kind):
                    frozen=relay.freeze_publication(self.task,self.root,kind,self.original_mapper(kind))
                    self.assertEqual(frozen.manifest,self.manifests[kind])
            finally:alias.unlink()

    def test_source_symlink_and_parent_directory_escape_refuse_before_mapper(self):
        target=self.scope_target(self.kinds[0],self.task);original=target.read_bytes()
        other=self.task/'outside-closure.bin';other.write_bytes(original)
        target.unlink();target.symlink_to(other)
        forbidden=mock.Mock(side_effect=AssertionError('validator must not run'))
        with self.assertRaises(relay.PublicationIncomplete):
            relay.freeze_publication(self.task,self.root,self.kinds[0],forbidden)
        forbidden.assert_not_called()
        target.unlink();target.write_bytes(original)
        directory=self.task/'candidate_replay/fits';moved=self.task/'outside-directory'
        directory.rename(moved);directory.symlink_to(moved,target_is_directory=True)
        with self.assertRaises(relay.PublicationIncomplete):
            relay.freeze_publication(self.task,self.root,self.kinds[0],forbidden)
        forbidden.assert_not_called()

    def test_fifo_rejected_in_bounded_real_subprocess(self):
        fifo=self.task/'no-writer.fifo';os.mkfifo(fifo)
        program='import sys; sys.path.insert(0,'+repr(str(Path(__file__).resolve().parent))+')\n'
        program+='from pathlib import Path\nimport publish_mosi as relay\n'
        program+='try:\n    relay.regular_bytes(Path('+repr(str(self.task))+'),"no-writer.fifo",1024)\n'
        program+='except relay.PublicationIncomplete:\n    print("refused nonregular input")\nelse:\n    raise SystemExit("FIFO accepted")\n'
        result=subprocess.run([sys.executable,'-B','-c',program],capture_output=True,timeout=3)
        self.assertEqual((result.returncode,result.stdout,result.stderr),(0,b'refused nonregular input\n',b''))

    def test_real_growth_during_descriptor_read_is_refused(self):
        path=self.task/'growing.bin';path.write_bytes(b'abcd')
        original_fdopen=relay.os.fdopen;changed=False
        class GrowingReader:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):return self.stream.__exit__(*args)
            def fileno(self):return self.stream.fileno()
            def read(self,size):
                nonlocal changed
                data=self.stream.read(size)
                if not changed:
                    changed=True
                    with path.open('ab') as output:output.write(b'ef')
                return data
        def open_recorded(descriptor,*args,**kwargs):
            return GrowingReader(original_fdopen(descriptor,*args,**kwargs))
        with mock.patch.object(relay.os,'fdopen',side_effect=open_recorded),self.assertRaises(relay.PublicationIncomplete):
            relay.regular_bytes(self.task,'growing.bin',5)
        self.assertTrue(changed);self.assertEqual(path.read_bytes(),b'abcdef')

    def test_byte_count_total_count_and_metadata_path_limits_fail_closed(self):
        forbidden=mock.Mock(side_effect=AssertionError('validator must not run'))
        for field,value in [('MAX_SCOPE_BYTES',32),('MAX_INPUT_FILES',1)]:
            with self.subTest(limit=field),mock.patch.object(relay,field,value),self.assertRaises(relay.PublicationIncomplete):
                relay.freeze_publication(self.task,self.root,self.kinds[0],forbidden)
        forbidden.assert_not_called()
        with self.assertRaises(relay.PublicationIncomplete):relay.regular_bytes(self.task,'input_recovery.json',1)
        path=self.task/'candidate_replay/reconstruction_result.json';original=path.read_bytes()
        for name in ('../outside','/absolute','nested//key','nested\\key'):
            record=json.loads(original);record['authenticated_cold_results']={name:{}}
            path.write_text(json.dumps(record))
            with self.subTest(name=name),self.assertRaises(relay.PublicationIncomplete):
                relay.freeze_publication(self.task,self.root,self.kinds[0],forbidden)
        path.write_bytes(b'{"authenticated_cold_results":{},"authenticated_cold_results":{}}')
        with self.assertRaisesRegex(relay.PublicationIncomplete,'duplicate metadata key'):
            relay.freeze_publication(self.task,self.root,self.kinds[0],forbidden)
        forbidden.assert_not_called()

    def test_mapper_cannot_publish_uncaptured_or_outside_paths(self):
        for outside in (False,True):
            def escape(private):
                selected=self.actual_mappers[0](private)
                extra=(self.task if outside else private)/'uncaptured.bin';extra.write_bytes(b'unvalidated extra')
                return {**selected,'extra.bin':extra}
            with self.subTest(outside=outside),self.assertRaises(relay.PublicationIncomplete):
                relay.freeze_publication(self.task,self.root,self.kinds[0],escape)

    def test_pinned_modules_ignore_task_cache_without_changing_global_bindings(self):
        poison={}
        for name in ('verify','fresh_study','archive'):
            module=ModuleType(name)
            module.main=mock.Mock(side_effect=AssertionError('cached module must not execute'))
            module.DESIGNS=[];module.BRANCH='wrong cached branch';poison[name]=module
        original_path=sys.path[:]
        with mock.patch.dict(sys.modules,poison):
            frozen=relay.freeze_publication(self.task,self.root,self.kinds[1],self.tracked_fresh_map)
            helper=Path(__file__).resolve().parent.parent/'crema/publish_results.py'
            with mock.patch.object(relay,'SHARED',str(helper)):
                pub=relay.publisher_module();self.assertEqual(pub.BRANCH,relay.BRANCH)
            self.assertEqual(frozen.manifest,self.manifests[self.kinds[1]])
            self.assertEqual(sys.path,original_path)
            for name,module in poison.items():
                self.assertIs(sys.modules[name],module);module.main.assert_not_called()

    def test_changed_validator_or_driver_is_not_executed(self):
        for name in ('fresh_study.py','source/verify.py'):
            target=self.task/name;original=target.read_bytes()
            target.write_bytes(original+b'\nraise RuntimeError("changed code must never execute")\n')
            try:
                with self.subTest(name=name),self.assertRaisesRegex(relay.PublicationIncomplete,'identity'):
                    relay.freeze_publication(self.task,self.root,self.kinds[1],self.tracked_fresh_map)
            finally:target.write_bytes(original)

    def test_snapshot_after_validation_uses_bytes_even_if_private_path_replaced(self):
        kind=self.kinds[1];seen=[];original_snapshot=relay.publication_snapshot
        original=self.fresh_data.read_bytes()
        def mapper(private):
            selected=self.tracked_fresh_map(private);seen.append(private)
            return selected
        def snapshot(payloads):
            self.assertTrue(all(type(data) is bytes for data in payloads.values()))
            private=seen[-1];path=private/'reconstructed/data.json'
            path.unlink();path.write_bytes(b'X'*len(original))
            self.fresh_data.write_bytes(b'Y'*len(original))
            return original_snapshot(payloads)
        with mock.patch.object(relay,'publication_snapshot',side_effect=snapshot):
            frozen=relay.freeze_publication(self.task,self.root,kind,mapper)
        self.assertTrue(all(not path.exists() for path in seen))
        self.assertEqual(dict(frozen.payloads)['data.json'],original)
        self.empty_remote_tip();self.publish_frozen_locally(frozen,kind,'api')

    def test_frozen_file_has_no_path_read_and_requires_its_bound_destination(self):
        file=relay.FrozenFile(self.root/'scope','a.bin',b'valid bytes')
        self.assertEqual(file.read_bytes(),b'valid bytes')
        self.assertEqual(file.relative_to(self.root/'scope'),Path('a.bin'))
        with self.assertRaises(relay.PublicationIncomplete):file.relative_to(self.root/'other')
        with self.assertRaises(relay.PublicationIncomplete):relay.FrozenFile(self.root,'a.bin',bytearray(b'wrong'))
        with self.assertRaises(relay.PublicationIncomplete):relay.FrozenFile(self.root,'../escape',b'wrong')
        with self.assertRaises(AttributeError):file.data=b'changed'



if __name__=='__main__':unittest.main()
