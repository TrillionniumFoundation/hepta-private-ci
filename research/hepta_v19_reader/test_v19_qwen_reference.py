"""Research-only source/mechanism/adversarial fixtures; NO pretrained Qwen inference."""
import copy
from hashlib import sha1,sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import source_first as v17
import v19_qwen_reference as q
import v19_qwen_material as mat
import v19_reference_review as reviewer


def old_qa(i):
    return {'question':f'Which location held the cedar document number {i}?',
            'answer':'Loma' if i%3 else None,
            'evidence':['u-1','u-2'], 'category': 'single-hop'}


def fake_corpus():
    chosen=[]
    for root in v17.ROOTS:
        names=[f'{root}/q{i}' for i in range(50)]
        chosen+=sorted(names,key=lambda cid:(v17.sha_text(cid),cid))[:3]
    single=set(sorted(chosen)[:24])
    roots=[]
    for root in v17.ROOTS:
        lines=[dict(dia_id='u-'+str(i),speaker='Agent',text=(
            'Cedar document '+str(i)+' was discussed in a small museum at Loma.'))
               for i in range(100)]
        qas=[]
        for i in range(50):
            row=old_qa(i)
            row['question']=root+': '+row['question']
            row['evidence']=['u-1'] if f'{root}/q{i}' in single else ['u-1','u-2']
            qas.append(row)
        roots.append({'sample_id':root,'conversation':{'session_1':lines},'qa':qas})
    return roots


class SourceFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.dir=Path(cls.tmp.name)
        cls.original=cls.dir/'original.json';cls.original.write_bytes(v17.canon(fake_corpus()))
        cls.hash=v17.sha_file(cls.original)
        with patch.object(v17,'CORPUS_SHA',cls.hash):
            v17.prepare(cls.original,cls.dir/'owned')
            d=cls.dir/'owned';cls.d=d
            v17.plan(d/'public.json',d/'owner.json',d/'plan.json')
            v17.annotations(d/'public.json',d/'owner.json',d/'hidden.json',d/'plan.json',d/'annotation.json')
            v17.requests(d/'public.json',d/'owner.json',d/'plan.json',d/'annotation.json',d/'requests.json')
            cls.paths=tuple(str(d/x) for x in ('public.json','owner.json','plan.json','annotation.json','requests.json'))
            with patch.object(q.v17,'CORPUS_SHA',cls.hash):
                q.build(cls.paths,d/'qwen.json')
            cls.proposal=v17.read(d/'qwen.json')
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_original_source_first_roster_and_byte_binding(self):
        with patch.object(q.v17,'CORPUS_SHA',self.hash):
            p=q.validate(self.paths,self.d/'qwen.json')
        self.assertEqual(p['cases'],sorted(p['cases']))
        self.assertEqual(len(p['cases']),30)
        self.assertEqual(len(p['entries']),120)
        self.assertEqual(set(p['arms']),set(v17.ARMS))
        self.assertFalse(p['source_time_prospective'])
        self.assertFalse(p['independent_human_sufficiency'])
        self.assertTrue(p['publisher_answer_labels_not_exposed'])
        self.assertEqual(p['decision'],'HOLD_NO_GO')

    def test_original_review_rebuild_no_producer_import(self):
        args=[reviewer.secure_read(self.original)]+[reviewer.secure_read(self.d/x) for x in
            ('public.json','owner.json','hidden.json','plan.json','annotation.json','requests.json','qwen.json')]
        with patch.object(reviewer,'SOURCE_SHA',self.hash):
            self.assertEqual(len(reviewer.sourceaudit(*args)),30)

    def test_input_source_utterance_byte_exact(self):
        p=self.proposal
        for entry in p['entries'].values():
            s=entry['messages']
            self.assertEqual(s[0]['content'],q.SYSTEM)
            self.assertNotIn('category',s[1]['content'])
            self.assertIn('Question: ',s[1]['content'])
            self.assertEqual(entry['message_sha256'],v17.digest(s))
            self.assertEqual(entry['source_ids'],list(entry['source_ids']))

    def test_no_source_label_fields_in_reference_plan(self):
        self.assertNotIn('"support_ids"',v17.canon(self.proposal).decode())
        self.assertNotIn('"category"',v17.canon(self.proposal).decode())
        self.assertNotIn('"answer"',v17.canon(self.proposal).decode())

    def test_resealed_model_prompt_tamper_denied(self):
        x=copy.deepcopy(self.proposal);rid=next(iter(x['entries']))
        x['entries'][rid]['messages'][1]['content']+=' INJECTED'
        x['entries'][rid]['message_sha256']=v17.digest(x['entries'][rid]['messages'])
        x['entry_sha256']=v17.digest(x['entries']);x['plan_sha256']=v17.digest({k:v for k,v in x.items() if k!='plan_sha256'})
        with tempfile.TemporaryDirectory() as d:
            fp=Path(d)/'changed.json';fp.write_bytes(v17.canon(x))
            with patch.object(q.v17,'CORPUS_SHA',self.hash),self.assertRaises(ValueError):
                q.validate(self.paths,fp)
            vals=[reviewer.secure_read(self.original)]+[reviewer.secure_read(self.d/n) for n in
                ('public.json','owner.json','hidden.json','plan.json','annotation.json','requests.json')]+[x]
            with patch.object(reviewer,'SOURCE_SHA',self.hash),self.assertRaises(ValueError):
                reviewer.sourceaudit(*vals)

    def test_witness_lesion_bound_to_original(self):
        old=v17.read(self.d/'requests.json')
        for cid in self.proposal['cases']:
            ref=old['requests'][cid+'|annotated']['source_ids']
            self.assertEqual(old['requests'][cid+'|lesion']['source_ids'],ref[1:])
            self.assertEqual(self.proposal['entries'][cid+'|annotated']['source_ids'],ref)
            self.assertEqual(self.proposal['entries'][cid+'|lesion']['source_ids'],ref[1:])

    def test_unchanged_input_source_label_lesion_not_physical_win(self):
        self.assertEqual(self.proposal['authority'],'DENY_ALL')
        self.assertFalse(self.proposal['production_authorized'])
        for cid in self.proposal['cases']:
            none=self.proposal['entries'][cid+'|none']
            self.assertEqual(none['source_ids'],[])

    def test_forged_source_owner_denied(self):
        owner=v17.read(self.d/'owner.json');owner['authority']='ALLOW_ALL'
        with tempfile.TemporaryDirectory() as tmp:
            bad=Path(tmp)/'owner.json';bad.write_bytes(v17.canon(owner))
            paths=list(self.paths);paths[1]=str(bad)
            with patch.object(q.v17,'CORPUS_SHA',self.hash),self.assertRaises(ValueError):
                q.derive(*paths)

    def test_reference_plan_output_create_only(self):
        with patch.object(q.v17,'CORPUS_SHA',self.hash),self.assertRaises(FileExistsError):
            q.build(self.paths,self.d/'qwen.json')

    def test_reviewer_rejects_publisher_gold_rewrite(self):
        vals=[reviewer.secure_read(self.original)]+[reviewer.secure_read(self.d/n) for n in
            ('public.json','owner.json','hidden.json','plan.json','annotation.json','requests.json','qwen.json')]
        vals[3]=copy.deepcopy(vals[3]);root=next(iter(vals[3]));cid=next(iter(vals[3][root]))
        vals[3][root][cid]['answer']='tampered'
        with patch.object(reviewer,'SOURCE_SHA',self.hash),self.assertRaises(ValueError):
            reviewer.sourceaudit(*vals)

    def test_reviewer_rejects_synthetic_source_shortcut(self):
        vals=[reviewer.secure_read(self.original)]+[reviewer.secure_read(self.d/n) for n in
            ('public.json','owner.json','hidden.json','plan.json','annotation.json','requests.json','qwen.json')]
        vals[0]=copy.deepcopy(vals[0]);vals[0][0]['qa'][1]['question']='modified publisher original'
        with patch.object(reviewer,'SOURCE_SHA',self.hash),self.assertRaises(ValueError):
            reviewer.sourceaudit(*vals)

    def test_invalid_titleless_citation_does_not_entail(self):
        info={'test':{'original':{'answer':'Loma'}}}
        p={'entries':{'test|annotated':{'case_id':'test','arm':'annotated','source_ids':['w1']}}}
        physical={'requests_by_id':{'test|annotated':'tokens'},
                  'physical_outputs':{'tokens':{
                      'answer':'Loma [E9]','logical_ids':['test|annotated'],
                      'output_tokens':2,'input_tokens':8,'cpu_ms':5}}}
        scores=reviewer.score_after_seal(info,p,physical)['annotated']
        self.assertEqual(scores['literal_hits'],1)
        self.assertEqual(scores['strict_equals'],0)
        self.assertEqual(scores['foreign_citation_cases'],1)
        self.assertEqual(scores['valid_syntactic_citations'],0)

    def test_unlabeled_does_not_count_as_wrong(self):
        info={'test':{'original':{'answer':None}}}
        p={'entries':{'test|none':{'case_id':'test','arm':'none','source_ids':[]}}}
        phys={'requests_by_id':{'test|none':'t'},'physical_outputs':{'t':{
            'answer':'unknown','logical_ids':['test|none'],'input_tokens':5,
            'output_tokens':1,'cpu_ms':7}}}
        score=reviewer.score_after_seal(info,p,phys)['none']
        self.assertEqual(score['missing_answer'],1)
        self.assertEqual(score['labeled'],0)
        self.assertEqual(score['strict_equals'],0)

    def test_duplicate_physical_cost_charged_once(self):
        info={'a':{'original':{'answer':'X'}}}
        p={'entries':{'a|none':{'case_id':'a','arm':'none','source_ids':[]},
                      'a|lesion':{'case_id':'a','arm':'lesion','source_ids':[]}}}
        phys={'requests_by_id':{'a|none':'same','a|lesion':'same'},'physical_outputs':{
            'same':{'answer':'X','input_tokens':2,'output_tokens':1,
                    'logical_ids':['a|lesion','a|none'],'cpu_ms':123}}}
        total=reviewer.score_after_seal(info,p,phys)
        self.assertEqual(sum(x['model_cpu_ms'] for x in total.values()),123)

    def test_no_torch_import_through_qwen_source_only(self):
        script=('import v19_qwen_reference,v19_qwen_material,v19_reference_review,sys; '
                "assert not any(x in sys.modules for x in ('torch','transformers','safetensors','huggingface_hub'))")
        env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'hepta_v17_reader')+os.pathsep+str(Path(__file__).resolve().parent)}
        result=subprocess.run([sys.executable,'-S','-c',script],env=env,capture_output=True,text=True,timeout=20,check=False)
        self.assertEqual(result.returncode,0,result.stderr)


class MaterialTests(unittest.TestCase):
    def mkfiles(self,root):
        root=Path(root);root.mkdir(exist_ok=True)
        fake={'config.json':b'config','tokenizer_config.json':b'configtok',
              'tokenizer.json':b'tokenizer','model.safetensors':b'fake-weights-fixture-only'}
        for name,data in fake.items(): (root/name).write_bytes(data)
        siblings=[]
        for name,data in fake.items():
            oid=sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            lfs={'sha256':sha256(data).hexdigest()} if name=='model.safetensors' else None
            siblings.append(SimpleNamespace(rfilename=name,size=len(data),blob_id=oid,lfs=lfs))
        return SimpleNamespace(sha=q.REVISION,siblings=siblings)

    def test_official_material_contract_static(self):
        with tempfile.TemporaryDirectory() as td:
            info=self.mkfiles(Path(td)/'cache')
            roster=mat.pub_manifest(info)
            self.assertEqual(len(roster),4)
            self.assertEqual(roster['model.safetensors']['publisher_lfs_sha256'],sha256(b'fake-weights-fixture-only').hexdigest())

    def test_missing_publisher_lfs_denied(self):
        with tempfile.TemporaryDirectory() as td:
            info=self.mkfiles(Path(td)/'cache');info.siblings[-1].lfs=None
            with self.assertRaises(ValueError):mat.pub_manifest(info)

    def test_changed_immutable_revision_denied(self):
        with tempfile.TemporaryDirectory() as td:
            info=self.mkfiles(Path(td)/'cache');info.sha='main'
            with self.assertRaises(ValueError):mat.pub_manifest(info)

    def test_mismatched_source_bytes_staging_denied(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cache=root/'cache';info=self.mkfiles(cache)
            info.siblings[-1].lfs={'sha256':'0'*64}
            with self.assertRaises(ValueError):
                mat.stage(lambda:info,lambda name:cache/name,cache,root/'model',root/'manifest.json')
            self.assertFalse((root/'model').exists())

    def test_real_byte_copy_and_git_blob_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cache=root/'cache';info=self.mkfiles(cache)
            good=mat.stage(lambda:info,lambda name:cache/name,cache,root/'model',root/'manifest.json')
            self.assertEqual(good['model_files'],4)
            spec=json.loads((root/'manifest.json').read_text())
            self.assertEqual(good['model_material_sha256'],mat.verify_snapshot(root/'model',spec))
            (root/'model'/'config.json').write_text('changed config!')
            with self.assertRaises(ValueError):mat.verify_snapshot(root/'model',spec)

    def test_unknown_extra_material_file_denied(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cache=root/'cache';info=self.mkfiles(cache)
            mat.stage(lambda:info,lambda name:cache/name,cache,root/'model',root/'manifest.json')
            (root/'model'/'secret.private').write_text('no')
            with self.assertRaises(ValueError):
                mat.verify_snapshot(root/'model',json.loads((root/'manifest.json').read_text()))

    def test_symlinked_snapshot_denied(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cache=root/'cache';info=self.mkfiles(cache)
            mat.stage(lambda:info,lambda name:cache/name,cache,root/'model',root/'manifest.json')
            (root/'model'/'config.json').unlink()
            (root/'model'/'config.json').symlink_to(cache/'config.json')
            with self.assertRaises(ValueError):
                mat.verify_snapshot(root/'model',json.loads((root/'manifest.json').read_text()))


if __name__=='__main__':unittest.main()

class FakePhysicalReviewer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SourceFixture.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):
        SourceFixture.tearDownClass.__func__(cls)
    """Forged fabricated packets for verifier abuse tests; never a model result."""

    def toy_pair(self,folder,change=None):
        class FakeTokenizer:
            def apply_chat_template(self,messages,**kwargs):
                h=sha256(v17.canon(messages)).digest()
                return [int.from_bytes(h[:8],'big'),int.from_bytes(h[8:16],'big')]
            def decode(self,items,skip_special_tokens=True):
                if items==[10]:return 'unknown'
                return 'not-a-real-reader-answer'
        tok=FakeTokenizer();inputs={};aliases={}
        for rid,entry in sorted(self.proposal['entries'].items()):
            key=v17.digest(tok.apply_chat_template(entry['messages']))
            inputs.setdefault(key,[]).append(rid)
            aliases[rid]=key
        self.assertEqual(len(inputs),96)
        physical_outputs={}
        starts=[]
        for key in sorted(inputs):
            physical_outputs[key]={'representative_id':inputs[key][0],
                'logical_ids':inputs[key],'generated_token_ids':[10],
                'answer':'unknown','answer_sha256':v17.sha_text('unknown'),
                'input_sha256':key,'input_tokens':2,'output_tokens':1,
                'observed_root_model_forwards':1,'cpu_ms':0,'wall_ms':0}
            starts.append({'token_ids_sha256':key,'model_spec_sha256':'fixture-material',
                 'plan_sha256':self.proposal['plan_sha256'],
                 'representative_id':inputs[key][0], 'logical_ids':inputs[key],
                 'input_tokens':2,'physical_model_generation_started':True,'authority':'DENY_ALL'})
        if change=='answer':
            key=next(iter(physical_outputs));physical_outputs[key]['answer']='fake'
            physical_outputs[key]['answer_sha256']=v17.sha_text('fake')
        if change=='alias':
            key=next(iter(physical_outputs));physical_outputs[key]['logical_ids'].append('foreign|none')
        result={'schema':q.SCHEMA+'.physical-private',
                'plan_sha256':self.proposal['plan_sha256'],'source_roots':list(v17.ROOTS),
                'model_repo':q.REPO,'model_revision':q.REVISION,
                'model_spec_sha256':'fixture-material',
                'model_weights_sha256':'fixture-weights',
                'requests_by_id':aliases,'requests_by_id_sha256':v17.digest(aliases),
                'physical_outputs':physical_outputs,'physical_outputs_sha256':v17.digest(physical_outputs),
                'original_archive_sha256':v17.ARCHIVE_SHA,
                'actual_unique_qwen_requests':96,'logical_arm_requests':120,
                'measured_root_forward_calls':96,'wall_ms':0,'cpu_ms':0,
                'original_pretrained_qwen3_executed':True,
                'physical_model_host_independently_signed':False,
                'task_semantic_correctness_independently_verified':False,
                'publisher_witness_sufficiency_human_certified':False,
                'model_token_budget_matched_to_135m':False,
                'current_135m_model_executed_by_this_runner':False,
                'ndu_fbsde_solves':0,'authority':'DENY_ALL',
                'production_authorized':False,'decision':'HOLD_NO_GO'}
        j=Path(folder)/'starts.jsonl';j.write_text(''.join(json.dumps(s)+'\n' for s in starts))
        j.chmod(0o600);result['journal_sha256']=sha256(j.read_bytes()).hexdigest()
        p=Path(folder)/'synthetic-private.json';p.write_bytes(v17.canon(result));p.chmod(0o600)
        material=Path(folder)/'spec.json';material.write_text(json.dumps({'files_sha256':{'model.safetensors':'fixture-weights'}}))
        fake=SimpleNamespace(AutoTokenizer=SimpleNamespace(from_pretrained=lambda *args,**kwargs:tok))
        return p,j,material,fake

    def verify_fixture_only(self,p,j,material,fake,out):
        with patch.object(reviewer,'SOURCE_SHA',self.hash),patch.object(mat,'verify_snapshot',return_value='fixture-material'),patch.dict(sys.modules,{'transformers':fake}):
            return reviewer.audit(self.original,self.d/'public.json',self.d/'owner.json',
                self.d/'hidden.json',self.d/'plan.json',self.d/'annotation.json',self.d/'requests.json',
                self.d/'qwen.json',p,j,self.dir,material,out)

    def test_fixture_positive_source_and_token_integrity_not_model_proof(self):
        with tempfile.TemporaryDirectory() as td:
            f,j,meta,fake=self.toy_pair(td)
            result=self.verify_fixture_only(f,j,meta,fake,Path(td)/'out.json')
            self.assertEqual(result['questions'],30)
            self.assertEqual(result['physical_requests'],96)
            report=json.loads((Path(td)/'out.json').read_text())
            self.assertFalse(report['independent_host_signature'])
            self.assertFalse(report['independent_semantic_review_verified'])
            self.assertFalse(report['production_authorized'])
            self.assertEqual(report['decision'],'HOLD_NO_GO')

    def test_reseal_original_answer_without_token_parity_is_denied(self):
        with tempfile.TemporaryDirectory() as td:
            f,j,meta,fake=self.toy_pair(td,change='answer')
            with self.assertRaises(ValueError):
                self.verify_fixture_only(f,j,meta,fake,Path(td)/'out.json')

    def test_reseal_extra_model_alias_without_real_source_is_denied(self):
        with tempfile.TemporaryDirectory() as td:
            f,j,meta,fake=self.toy_pair(td,change='alias')
            with self.assertRaises(ValueError):
                self.verify_fixture_only(f,j,meta,fake,Path(td)/'out.json')

class PhysicalForgeryTests(FakePhysicalReviewer):
    """Negative receipt mutations; these are still synthetic source-only fixtures."""
    def test_forged_semantic_authority_field_denied_even_when_resealed(self):
        with tempfile.TemporaryDirectory() as td:
            f,j,meta,fake=self.toy_pair(td)
            value=json.loads(f.read_text())
            value['independent_semantic_accuracy']=1.0
            f.write_bytes(v17.canon(value))
            with self.assertRaises(ValueError):
                self.verify_fixture_only(f,j,meta,fake,Path(td)/'out.json')

    def test_forged_positive_forward_census_denied_even_when_resealed(self):
        with tempfile.TemporaryDirectory() as td:
            f,j,meta,fake=self.toy_pair(td)
            value=json.loads(f.read_text());value['measured_root_forward_calls']=17
            f.write_bytes(v17.canon(value))
            with self.assertRaises(ValueError):
                self.verify_fixture_only(f,j,meta,fake,Path(td)/'out.json')

    def test_reconstructed_journal_wrong_event_denied(self):
        with tempfile.TemporaryDirectory() as td:
            f,j,meta,fake=self.toy_pair(td)
            events=[json.loads(line) for line in j.read_text().splitlines()]
            events[0]['logical_ids']=['forged|arm']
            j.write_text(''.join(json.dumps(e)+'\n' for e in events))
            v=json.loads(f.read_text());v['journal_sha256']=sha256(j.read_bytes()).hexdigest()
            f.write_bytes(v17.canon(v))
            with self.assertRaises(ValueError):
                self.verify_fixture_only(f,j,meta,fake,Path(td)/'out.json')
