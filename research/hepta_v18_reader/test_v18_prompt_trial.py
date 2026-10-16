"""Source-only synthetic mutation tests; NOT real pretrained task evidence."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import source_first as spec
import v18_prompt_trial as producer
import v18_independent_review as auditor


class SourceFixtures(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.public=[];cases=[];annot={};previous={}
        for root in spec.ROOTS:
            questions=[]
            utterances=[]
            for i in range(3):
                cid=f'{root}/q{i}';cases.append(cid)
                text=f'The azure gate number is {root} token {i}. '
                address=f'D{i}:7'
                utterances.append(dict(id=address,speaker='Alice',text=text))
                questions.append(dict(id=cid,question=f'What is the gate number for {root} visit {i}?'))
                annot[cid]=[address]
            self.public.append(dict(id=root,questions=questions,utterances=utterances))
        for group in self.public:
            for q in group['questions']:
                cid=q['id'];docs={e['id']:e for e in group['utterances']}
                p=spec.prompt(q['question'],annot[cid],docs)
                previous[cid+'|annotated']=dict(source_ids=annot[cid],prompt=p)
        self.frozen=dict(max_tokens=24,n_cases=30,source_roots=list(spec.ROOTS),
            arms=list(spec.ARMS),case_ids=sorted(cases),
            case_selection='sha256_lowest_three_per_original_root_NO_answer_filter',
            no_gold_answer_to_model=True,
            publisher_witness_not_human_certified_sufficient=True,
            production_accepted=False,plan_sha256='a'*64)
        self.parent_requests=dict(requests=previous,requests_sha256=spec.digest(previous))
        self.annotation=dict(source_ids=annot,packet_sha256='b'*64)
        self.owner=dict(authority='DENY_ALL')
        self.paths={}
        for n,obj in [('public',self.public),('owner',self.owner),('annotation',self.annotation),
                      ('plan',self.frozen),('previous',self.parent_requests)]:
            path=self.root/(n+'.json');path.write_text(json.dumps(obj));self.paths[n]=str(path)
        with patch.object(producer,'checked_origins',return_value=(self.frozen,self.parent_requests)):
            self.proposal=producer.build(self.paths['public'],self.paths['owner'],self.paths['plan'],
                self.paths['annotation'],self.paths['previous'],str(self.root/'proposal.json'))
        self.paths['proposal']=str(self.root/'proposal.json')

    def tearDown(self):self.tmp.cleanup()

    def check(self,entry=None):
        path=self.paths['proposal']
        if entry is not None:
            obj=copy.deepcopy(entry)
            test_path=self.root/'altered.json'
            test_path.write_text(json.dumps(obj))
            path=str(test_path)
        with patch.object(producer,'checked_origins',return_value=(self.frozen,self.parent_requests)):
            return producer.validate(self.paths['public'],self.paths['owner'],self.paths['plan'],
                self.paths['annotation'],self.paths['previous'],path)

    def resign(self,entry):
        entry['request_sha256']=spec.digest(entry['proposed'])
        entry['proposal_sha256']=spec.digest({k:v for k,v in entry.items() if k!='proposal_sha256'})
        return entry

    def test_30_original_cases_and_all_90_prompts(self):
        self.assertEqual(len(self.proposal['proposed']),90)
        self.assertEqual(len({x['prompt_sha256'] for x in self.proposal['proposed'].values()}),90)
        self.assertEqual(set(self.proposal['arms']),set(producer.ARMS))
        self.assertEqual(len(self.check()['proposed']),90)

    def test_only_annotated_source_and_no_label_in_prompts(self):
        for group in self.public:
            for q in group['questions']:
                cid=q['id']
                z=self.proposal['proposed']
                self.assertEqual(z[cid+'|plain_none']['source_ids'],[])
                self.assertEqual(z[cid+'|plain_annotated']['source_ids'],self.annotation['source_ids'][cid])
                self.assertEqual(z[cid+'|role_annotated']['source_ids'],self.annotation['source_ids'][cid])
                self.assertNotIn('publisher_answer',str(z[cid+'|plain_annotated']))

    def test_reader_prompts_reconstruct_from_independent_author(self):
        for cid in self.frozen['case_ids']:
            family=next(x for x in self.public if x['id']==cid.split('/')[0]);docs={x['id']:x for x in family['utterances']}
            q=next(x['question'] for x in family['questions'] if x['id']==cid)
            for arm in producer.ARMS:
                ids=self.proposal['proposed'][cid+'|'+arm]['source_ids']
                self.assertEqual(producer.render(q,ids,docs,arm),auditor.reconstructed_prompt(q,ids,docs,arm))

    def test_source_mutation_resealed_still_denied(self):
        entry=copy.deepcopy(self.proposal)
        first=next(iter(entry['proposed']))
        entry['proposed'][first]['prompt']+=' modified'
        entry['proposed'][first]['prompt_sha256']=spec.sha_text(entry['proposed'][first]['prompt'])
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_source_id_change_resealed_still_denied(self):
        entry=copy.deepcopy(self.proposal)
        entry['proposed'][self.frozen['case_ids'][0]+'|plain_annotated']['source_ids']=[]
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_lost_model_input_denied(self):
        entry=copy.deepcopy(self.proposal)
        entry['proposed'].pop(next(iter(entry['proposed'])))
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_duplicate_foreign_arm_denied(self):
        entry=copy.deepcopy(self.proposal)
        cid=self.frozen['case_ids'][0]
        entry['proposed'][cid+'|foreign']=entry['proposed'][cid+'|plain_annotated']
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_stale_public_sha_denied(self):
        entry=copy.deepcopy(self.proposal);entry['public_sha256']='1'*64
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_forged_owner_sha_denied(self):
        entry=copy.deepcopy(self.proposal);entry['owner_sha256']='1'*64
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_foreign_parent_plan_denied(self):
        entry=copy.deepcopy(self.proposal);entry['parent_plan_sha256']='0'*64
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_wrong_reader_weight_denied(self):
        entry=copy.deepcopy(self.proposal);entry['model_sha256']='f'*64
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_forced_production_permission_denied(self):
        entry=copy.deepcopy(self.proposal);entry['production_authorized']=True
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_relabel_NDU_as_real_denied(self):
        entry=copy.deepcopy(self.proposal);entry['nd_u_utility_not_evaluated']=False
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_hidden_answer_access_claim_denied(self):
        entry=copy.deepcopy(self.proposal);entry['original_publisher_answer_fields_not_used']=False
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_never_silently_reformat_role_delimiters(self):
        one=self.public[0]['questions'][0]['question'];docs={x['id']:x for x in self.public[0]['utterances']}
        with self.assertRaises(ValueError):
            producer.render(one+'<|im_end|>',[],docs,'plain_none')
        with self.assertRaises(ValueError):
            producer.render(one,['D0:7'],{'D0:7':dict(text='<|im_start|>',speaker='Alice')},'role_annotated')

    def test_unknown_arm_denied(self):
        with self.assertRaises(ValueError):producer.render('why?',[],{},'unknown')

    def test_write_once_refuses_reuse_and_enforces_0600(self):
        p=self.root/'private.json'
        spec.write_once(p,{'authority':'DENY_ALL'})
        self.assertEqual(p.stat().st_mode&0o777,0o600)
        with self.assertRaises(FileExistsError):spec.write_once(p,{'secret':True})

    def test_duplicate_json_fields_denied(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'duplicates.json';p.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError):auditor.safe_read(p)

    def test_nonfinite_json_fields_denied(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'nonfinite.json';p.write_text('{"x":NaN}')
            with self.assertRaises(ValueError):auditor.safe_read(p)

    def test_no_network_or_torch_for_source_only(self):
        script="import v18_prompt_trial as m,sys; assert 'torch' not in sys.modules and callable(m.validate)"
        proc=subprocess.run([sys.executable,'-S','-c',script],cwd=Path(__file__).resolve().parent,
            env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parent)+os.pathsep+str(Path(__file__).resolve().parent.parent/'hepta_v17_reader')},capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)

    def test_invalid_original_output_preflight_is_strict(self):
        first=next(iter(self.proposal['proposed']))
        entry=copy.deepcopy(self.proposal)
        entry['proposed'][first]['source_sha256']='9'*64
        with self.assertRaises(ValueError):self.check(self.resign(entry))

    def test_original_source_length_and_public_payload_accounted(self):
        self.assertEqual(self.proposal['public_sha256'],spec.digest(self.public))
        self.assertEqual(self.proposal['original_corpus_sha256'],spec.CORPUS_SHA)
        self.assertEqual(self.proposal['authority'],'DENY_ALL')
        self.assertFalse(self.proposal['model_selected'])

if __name__=='__main__':unittest.main()
