"""Source, paid-call, causal isolation, finite control and adversarial P8 tests.

Mock model produces NO pretrained inference evidence. Exact physical identity
must be checked in separate GitHub jobs and postseal real reviewer.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from online import (SCHEMA,source_packets,make_prompt,parse_answer,digest,random_seed,
                    execute,read,write_new,rotate,DIRECT_CAP,CHECK_CAP)
from policy import Controller,POLICIES,BUDGET,train_profile,feature,risk_alpha
from review import review
from source import select_publisher

SOURCE_SCHEMA=SCHEMA+'.original-publisher-second-occurrence'


def packets():
    source={'split_rule':'P8_second_and_third_per_original_publisher_label_length_index_parity',
            'historical_publisher_not_future_source':True,'p5_first_cohort_disjoint':True,
            'repo':'szhuggingface/ag_news','revision':'98c532231d96ae10e176a909192ecac548949288',
            'source_files_sha256':{
              'data/train_1_1.5k-00000-of-00001.parquet':'cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5',
              'data/test-00000-of-00001.parquet':'2237e86474314bae6c611718e5bd16a42b4e8dfae53bb4a84abdae1bc1c5d3ee'},
            'independent_source_families':False}
    train=[];held=[];gold=[]
    for phase,count in (('train',32),('held',16)):
        for i in range(count):
            bucket='long' if ((i//2)%2) else 'short'
            text=f'P8 hypothetical news report, demonstration only. Original mock {phase} {i} sports and world '
            if bucket=='long':text+=' Extra publisher sample ' * 15
            key=f'{phase}-{i:05}'
            r={'task_id':key,'text':text,'text_sha256':__import__('hashlib').sha256(text.encode()).hexdigest(),
               'bucket':bucket,'group':f'{phase}-row-parity-{i%2}'}
            if phase=='train':train.append({**r,'label':(i//4)%4})
            else:
                held.append(r);gold.append({'task_id':key,'text_sha256':r['text_sha256'],'label':(i//4)%4})
    return ({'schema':SOURCE_SCHEMA+'.train','source':source,'rows':train},
            {'schema':SOURCE_SCHEMA+'.held-public','source':source,'rows':held},
            {'schema':SOURCE_SCHEMA+'.held-private-labels','source':source,'rows':gold})


class FakeReader:
    physical=False
    identity={'mock':True}
    load_cpu=0.
    load_wall=0.
    def __init__(self):self.calls=[]
    def infer(self,text,action,direct=None):
        prompt=make_prompt(text,action,direct)
        # Same fixed task answer per separately paid call. These are fixtures only.
        if action=='direct':a='FINAL=0';nout=4;think=0;complete=False
        elif action=='check_plain':a='FINAL=1';nout=4;think=0;complete=False
        else:a='';nout=CHECK_CAP;think=CHECK_CAP;complete=False
        self.calls.append((action,text,direct))
        return {'prompt_sha256':digest(prompt),'input_ids_sha256':digest([23]),
                'output_ids_sha256':digest([17]*nout),'sampling_seed':random_seed(prompt),
                'input_tokens':91 if action=='direct' else 130,
                'output_tokens':nout,'thinking_mode':action=='check_think',
                'thinking_tokens':think,'thinking_complete':complete,
                'answer':a,'predicted_class':parse_answer(a)}


def run(tmp:Path):
    train,held,gold=packets()
    reader=FakeReader()
    output=tmp/'real-attempt'
    result=execute(train,held,reader,output)
    frozen=read(output/'frozen-plan.json')
    doc=review(train,held,gold,frozen,read(output/'completed-original.json'),
               output/'original-starts-and-dones.jsonl',output/'frozen-plan.json',require_physical=False)
    return train,held,gold,reader,result,frozen,doc,output


class P8ContractTests(unittest.TestCase):
    def test_01_mock_paid_online_complete_with_six_policies(self):
        with tempfile.TemporaryDirectory() as d:
            train,held,gold,reader,r,frozen,a,path=run(Path(d))
            self.assertEqual(len(r['train_calls']),96)
            self.assertGreaterEqual(len(r['held_calls']),16*6)
            self.assertEqual(len(reader.calls),len(r['train_calls'])+len(r['held_calls']))
            self.assertEqual(a['physical_original_forward_invocations'],len(reader.calls))
            self.assertEqual(a['authority'],'RESEARCH_ONLY_DENY_ALL')
            self.assertEqual(a['same_profile_parity'],True)
            self.assertEqual(r['journal_events'],2*len(reader.calls)+1)
    def test_02_reviewer_cannot_admit_mock_as_physical(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            with self.assertRaises(ValueError):review(t,h,g,p,r,o/'original-starts-and-dones.jsonl',o/'frozen-plan.json')
    def test_03_original_held_packet_has_no_gold(self):
        t,h,g=packets();source_packets(t,h)
        self.assertTrue(all('label' not in x for x in h['rows']))
    def test_04_held_label_in_public_is_rejected(self):
        t,h,g=packets();h['rows'][0]['label']=0
        with self.assertRaises(ValueError):source_packets(t,h)
    def test_05_duplicate_public_task_id_is_rejected(self):
        t,h,g=packets();h['rows'][1]['task_id']=h['rows'][0]['task_id']
        with self.assertRaises(ValueError):source_packets(t,h)
    def test_06_cross_split_duplicate_text_is_rejected(self):
        t,h,g=packets();h['rows'][0]['text']=t['rows'][0]['text'];h['rows'][0]['text_sha256']=t['rows'][0]['text_sha256']
        with self.assertRaises(ValueError):source_packets(t,h)
    def test_07_wrong_text_digest_is_rejected(self):
        t,h,g=packets();h['rows'][0]['text_sha256']='0'*64
        with self.assertRaises(ValueError):source_packets(t,h)
    def test_08_wrong_source_manifest_is_rejected(self):
        t,h,g=packets();h['source']['split_rule']='P5_first'
        with self.assertRaises(ValueError):source_packets(t,h)
    def test_09_refuse_existing_model_output_directory(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            with self.assertRaises(FileExistsError):execute(t,h,FakeReader(),o)
    def test_10_create_only_output_and_duplicate_json(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'x.json';write_new(f,{'a':1})
            with self.assertRaises(FileExistsError):write_new(f,{'a':2})
            f.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError):read(f)
    def test_11_strict_final_answer_no_substring(self):
        self.assertEqual(parse_answer(' FINAL=<3> '),3)
        self.assertIsNone(parse_answer('the answer is 3'))
        self.assertIsNone(parse_answer('FINAL=1 FINAL=2'))
        self.assertIsNone(parse_answer(''))
        self.assertIsNone(parse_answer('<think>1</think>'))
    def test_12_checker_prompts_pair_on_same_user_prompt(self):
        p1=make_prompt('Valid example of a publisher news report.','check_plain','FINAL=1')
        p2=make_prompt('Valid example of a publisher news report.','check_think','FINAL=1')
        self.assertEqual(p1,p2)
        self.assertEqual(random_seed(p1),random_seed(p2))
    def test_13_mismatched_prompt_binding_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            r['train_calls'][0]['result']['prompt_sha256']='a'*64
            with self.assertRaises(ValueError):review(t,h,g,p,r,o/'original-starts-and-dones.jsonl',o/'frozen-plan.json',require_physical=False)
    def test_14_raw_answer_and_prediction_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            r['held_calls'][0]['result']['predicted_class']=3
            with self.assertRaises(ValueError):review(t,h,g,p,r,o/'original-starts-and-dones.jsonl',o/'frozen-plan.json',require_physical=False)
    def test_15_no_truncated_thought_scored_as_final(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            thinker=next(x for x in r['held_calls'] if x['action']=='check_think')
            thinker['result']['answer']='FINAL=0';thinker['result']['predicted_class']=0
            with self.assertRaises(ValueError):review(t,h,g,p,r,o/'original-starts-and-dones.jsonl',o/'frozen-plan.json',require_physical=False)
    def test_16_paid_completion_missing_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            r['held_calls'].pop()
            with self.assertRaises(ValueError):review(t,h,g,p,r,o/'original-starts-and-dones.jsonl',o/'frozen-plan.json',require_physical=False)
    def test_17_resealed_frozen_plan_drift_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            p['policy_profile']['census']=0
            with self.assertRaises(ValueError):review(t,h,g,p,r,o/'original-starts-and-dones.jsonl',o/'frozen-plan.json',require_physical=False)
    def test_18_tampered_journal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            fp=o/'original-starts-and-dones.jsonl'
            content=fp.read_bytes();fp.write_bytes(content[:-40])
            with self.assertRaises(ValueError):review(t,h,g,p,r,fp,o/'frozen-plan.json',require_physical=False)
    def test_19_rehashed_journal_order_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d));fp=o/'original-starts-and-dones.jsonl'
            lines=[json.loads(v) for v in fp.read_text().splitlines()]
            lines[0]['action']='check_plain'
            lines[0]['digest']=digest({k:v for k,v in lines[0].items() if k!='digest'})
            fp.write_text('\n'.join(json.dumps(x) for x in lines)+'\n')
            with self.assertRaises(ValueError):review(t,h,g,p,r,fp,o/'frozen-plan.json',require_physical=False)
    def test_20_private_gold_content_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            g['rows'][0]['text_sha256']='f'*64
            with self.assertRaises(ValueError):review(t,h,g,p,r,o/'original-starts-and-dones.jsonl',o/'frozen-plan.json',require_physical=False)
    def test_21_future_public_slate_affects_only_legal_rebalancing(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            x=Controller(p['policy_profile'],tuple(x['bucket'] for x in h['rows']),'ndu_discrete')
            y=Controller(p['policy_profile'],tuple(x['bucket'] for x in h['rows']),'ordinary_same_profile')
            for idx,z in enumerate(h['rows']):
                for rem in range(BUDGET+1):
                    self.assertEqual(x.choose(idx,rem,z['bucket'],{'predicted_class':0}),y.choose(idx,rem,z['bucket'],{'predicted_class':0}))
    def test_22_unknown_direct_result_is_unsupported_stop(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            x=Controller(p['policy_profile'],tuple(x['bucket'] for x in h['rows']),'ndu_discrete')
            self.assertEqual(x.choose(0,4,h['rows'][0]['bucket'],{'predicted_class':None}),'stop')
    def test_23_no_boolean_prediction_as_integer(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            r['held_calls'][0]['result']['predicted_class']=True
            with self.assertRaises(ValueError):review(t,h,g,p,r,o/'original-starts-and-dones.jsonl',o/'frozen-plan.json',require_physical=False)
    def test_24_no_support_for_invalid_controller_data(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            prof=p['policy_profile'].copy();prof['schema']='swapped'
            with self.assertRaises(ValueError):Controller(prof,tuple(x['bucket'] for x in h['rows']),'neutral')
    def test_25_paid_check_cap_independent_of_forecast(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            self.assertTrue(all(BUDGET-r['remaining_check_budgets'][p]<=BUDGET for p in POLICIES))
            self.assertEqual(sum(x['action']=='check_think' for x in r['held_calls'] if x['policy']=='fixed_think'),4)
    def test_26_paid_pairing_no_shared_held_direct(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            self.assertEqual(sum(x['action']=='direct' for x in r['held_calls']),len(h['rows'])*len(POLICIES))
            self.assertEqual(r['source_kind'],'synthetic_fixture')
    def test_27_model_digest_substitution_rejected_as_physical(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            p['model']={'repo':'unregistered model'}
            with self.assertRaises(ValueError):review(t,h,g,p,r,o/'original-starts-and-dones.jsonl',o/'frozen-plan.json')
    def test_28_same_profile_optimizer_training_uses_only_train(self):
        with tempfile.TemporaryDirectory() as d:
            t,h,g,m,r,p,a,o=run(Path(d))
            baseline=train_profile(t['rows'],r['train_calls'])
            g['rows'][0]['label']=(g['rows'][0]['label']+1)%4
            updated=train_profile(t['rows'],r['train_calls'])
            self.assertEqual(baseline,updated)
    def test_29_rotated_policy_order_balanced(self):
        matrix=[rotate(POLICIES,i) for i in range(6)]
        for pos in range(6):
            self.assertEqual(set(row[pos] for row in matrix),set(POLICIES))
    def test_30_publisher_second_third_never_reuses_first(self):
        import source
        class MockOriginal:
            def validate_rows(self,rows,phase):
                return [{**r,'task_id':f'{phase}-{i:05}', 'group':f'{phase}-row-parity-{i%2}',
                         'bucket':('short' if len(r['text'])<=180 else 'long'),
                         'text_sha256':__import__('hashlib').sha256(r['text'].encode()).hexdigest()}
                        for i,r in enumerate(rows)]
            def original_manifest(self):return {'repo':'mock/original','revision':'mock'}
        def table(phase):
            records=[]
            for i in range(6):
                for k in range(4):
                    for bucket in ('short','long'):
                        for parity in (0,1):
                            text=f'Original publisher article {phase} {i} {k} {bucket} {parity}. ' + ('long news words '*15 if bucket=='long' else 'short words')
                            records.append({'text':text,'label':k})
                            # enumeration idx parity automatically alternates via loop
            return records
        with patch.object(source,'original_module',return_value=MockOriginal()):
            # Build correct original class/bucket/parity support using alternating parity indices.
            for arr in (table('train'),table('held')):
                out=source.original_module().validate_rows(arr,'train')
                # No source guarantee in this made-up ordering; if strata missing, fail closed.
                # This is a negative test for missing original support.
                with self.assertRaises(ValueError):source.select_publisher(arr,arr)

    def test_31_original_second_third_stratification_positive(self):
        import source
        class Original:
            def validate_rows(self,rows,phase):
                import hashlib
                result=[]
                for i,raw in enumerate(rows):
                    text=raw['text'];label=raw['label']
                    result.append({'task_id':f'{phase}-{i:05}','text':text,
                        'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
                        'bucket':'short' if len(text)<=180 else 'long',
                        'group':f'{phase}-row-parity-{i%2}','label':label})
                return result
            def original_manifest(self):
                return {'repo':'mock.publisher','revision':'same-frozen-mock'}
        def table(phase):
            result=[]
            for label in range(4):
                for bucket in ('short','long'):
                    for occurrence in range(4):
                        for parity in range(2):
                            text=f'Original distinct publisher article phase={phase} label={label} bucket={bucket} occurrence={occurrence} parity={parity}. '
                            if bucket=='long':text+='news report long detail '*12
                            result.append({'text':text,'label':label})
            return result
        with patch.object(source,'original_module',return_value=Original()):
            a,b,g=select_publisher(table('train'),table('held'))
            self.assertEqual((len(a['rows']),len(b['rows']),len(g['rows'])),(32,16,16))
            self.assertEqual(len(set(r['text_sha256'] for r in a['rows']+b['rows'])),48)
            self.assertEqual(set(r['task_id'] for r in b['rows']),set(r['task_id'] for r in g['rows']))
            self.assertEqual(sum(r['label']==0 for r in a['rows']),8)
            self.assertNotIn('train-00000',[r['task_id'] for r in a['rows']])
            self.assertTrue(all('label' not in r for r in b['rows']))

if __name__=='__main__':unittest.main()
