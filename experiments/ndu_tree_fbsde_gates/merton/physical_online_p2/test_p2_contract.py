"""Source-only mechanics tests using a fake Reader. NEVER physical model evidence."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from portfolio import Invalid, POLICIES
from public_source import SCHEMA as SRC, split_original, encoded, sha, new_json
from physical_online import ACTION_MAX, MODEL_REPO,MODEL_REV, run_online, validate_source, parse_answer, make_prompt
from physical_review import review


class MockReader:
    # Deliberately imitates original physical response schema to test verifier's
    # inability to independently attest hardware. This MUST NOT be published as a run.
    physical=True
    identity={'repo':MODEL_REPO,'revision':MODEL_REV,
       'weights_sha256':'a'*64,'tokenizer_sha256':'b'*64,
       'actual_pretrained_model_loaded':True,'runtime':'FAKE CONTRACT TEST NOT PHYSICAL'}
    load_cpu=0.01;load_wall=0.01
    def __init__(self):self.calls=[]
    def infer(self,article,action):
        self.calls.append((sha(article.encode()),action))
        prompt=make_prompt(article,action)
        result='FINAL=0' if action=='direct' else 'FINAL=1' if action=='reason' else 'FINAL=2'
        return {'prompt_sha256':sha(encoded(prompt)),
          'input_token_ids_sha256':sha(encoded([4,5])),
          'output_token_ids_sha256':sha(encoded([6,7])),
          'input_tokens':40,'output_tokens':3,'answer':result,
          'answer_sha256':sha(result.encode()),'predicted_class':parse_answer(result)}


def fake_data():
    train=[];held=[]
    for split_name,target in (("train",train),("held",held)):
        for i in range(48):
            islong=i%4 in (2,3)
            text=('International business and sports headline '+split_name+' '+str(i)+' ' + 'X'*20 +
                  (' reports further factual news details '*10 if islong else ' reports news.'))
            target.append({'text':text,'label':i%4})
    return split_original(train,held)


def manifest():
    return {'schema':'hepta.ndu-merton.token-portfolio-p1.v1',
      'actions':[{'name':'direct','token_ceiling':0,'latency_ceiling_ms':0},
                 {'name':'reason','token_ceiling':96,'latency_ceiling_ms':4096},
                 {'name':'verify','token_ceiling':128,'latency_ceiling_ms':4096}],
      'token_budget':256,'latency_budget_ms':8192,'token_tariff':'1/2048'}


class PhysicalContractTests(unittest.TestCase):
    def setUp(self):
        self.train,self.held,self.gold=fake_data()
        self.manifest=manifest()
        self.reader=MockReader()

    def run_complete(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        out=Path(self.tmp.name)/'output'
        completed=run_online(self.manifest,self.train,self.held,self.reader,out)
        plan=json.loads((out/'frozen-plan.json').read_text())
        summary=review(self.manifest,self.train,self.held,self.gold,plan,completed,out/'original-starts-and-dones.jsonl')
        return out,plan,completed,summary

    def test_original_source_partition(self):
        self.assertEqual(len(self.train['rows']),16)
        self.assertEqual(len(self.held['rows']),8)
        self.assertEqual(len(self.gold['rows']),8)
        self.assertTrue(all('label' not in r for r in self.held['rows']))
        self.assertTrue(all('text' not in r for r in self.gold['rows']))
        self.assertEqual(len({r['task_id'] for r in self.train['rows']+self.held['rows']}),24)

    def test_all_real_action_slots_are_physically_called_after_freeze_in_contract(self):
        out,plan,completed,summary=self.run_complete()
        self.assertEqual(completed['actual_training_requests'],48)
        self.assertEqual(completed['actual_online_policy_requests'],56)
        self.assertEqual(len(self.reader.calls),104)
        self.assertEqual(summary['physical_on_policy_generation_invocations_self_reported'],104)
        self.assertEqual(len(summary['seven_policy_results']),7)
        self.assertEqual([r['policy'] for r in summary['seven_policy_results']],list(POLICIES))
        self.assertFalse(summary['actual_model_savings_proven'])
        self.assertIn('FAKE CONTRACT',str(summary['model_identity']))
        self.assertTrue(out.joinpath('frozen-plan.json').exists())

    def test_no_reader_output_shortcut_or_policy_cache(self):
        out,plan,completed,summary=self.run_complete()
        traces=completed['actual_policy_trace']
        self.assertEqual(len(traces),len(POLICIES)*8)
        self.assertEqual(len({(x['policy'],x['task_id']) for x in traces}),len(traces))
        self.assertEqual([x['policy'] for x in traces].count('direct'),8)
        self.assertEqual([x['policy'] for x in traces].count('ndu_discrete'),8)
        self.assertEqual([x['policy'] for x in traces].count('ordinary_same_profile'),8)

    def test_held_label_in_worker_packet_refused(self):
        self.held['rows'][0]['label']=0
        with self.assertRaises(Invalid):validate_source(self.train,self.held)

    def test_future_label_in_source_metadata_refused(self):
        self.held['rows'][0]['outcome']=1
        with self.assertRaises(Invalid):validate_source(self.train,self.held)

    def test_train_and_held_group_collision(self):
        self.held['rows'][0]['group']=self.train['rows'][0]['group']
        with self.assertRaises(Invalid):validate_source(self.train,self.held)

    def test_text_sha_substitution_refused(self):
        self.held['rows'][0]['text']='forged altered newspaper paragraph 123'
        with self.assertRaises(Invalid):validate_source(self.train,self.held)

    def test_publisher_truth_changed_after_seal_refused(self):
        out,plan,completed,summary=self.run_complete()
        self.gold['rows'][0]['text_sha256']='0'*64
        with self.assertRaises(Invalid):review(self.manifest,self.train,self.held,self.gold,plan,completed,out/'original-starts-and-dones.jsonl')

    def test_sealed_plan_changed_after_original_call_refused(self):
        out,plan,completed,summary=self.run_complete()
        plan['reader']['revision']='forged'
        with self.assertRaises(Invalid):review(self.manifest,self.train,self.held,self.gold,plan,completed,out/'original-starts-and-dones.jsonl')

    def test_unplanned_held_call_refused(self):
        out,plan,completed,summary=self.run_complete()
        completed['actual_policy_trace'][0]['action']='verify'
        with self.assertRaises(Invalid):review(self.manifest,self.train,self.held,self.gold,plan,completed,out/'original-starts-and-dones.jsonl')

    def test_missing_original_inference_refused(self):
        out,plan,completed,summary=self.run_complete()
        completed['actual_policy_trace'].pop()
        with self.assertRaises(Invalid):review(self.manifest,self.train,self.held,self.gold,plan,completed,out/'original-starts-and-dones.jsonl')

    def test_disguised_synthetic_output_refused(self):
        out,plan,completed,summary=self.run_complete()
        completed['actual_policy_trace'][0]['source_kind']='synthetic_fixture'
        with self.assertRaises(Invalid):review(self.manifest,self.train,self.held,self.gold,plan,completed,out/'original-starts-and-dones.jsonl')

    def test_journal_missing_refused(self):
        out,plan,completed,summary=self.run_complete()
        with (out/'original-starts-and-dones.jsonl').open('a') as f:
            f.write('{"event":"false_success"}\n')
        with self.assertRaises(Invalid):review(self.manifest,self.train,self.held,self.gold,plan,completed,out/'original-starts-and-dones.jsonl')

    def test_held_labels_must_be_opened_only_by_review(self):
        out,plan,completed,summary=self.run_complete()
        self.assertNotIn('held-private-labels',json.dumps(completed))
        self.assertNotIn('held-private-labels',json.dumps(plan))
        self.assertNotIn('label',json.dumps(plan['public_record']))

    def test_budget_manifest_changed_after_plan_rejected(self):
        out,plan,completed,summary=self.run_complete()
        self.manifest['token_budget']=100
        with self.assertRaises(Invalid):review(self.manifest,self.train,self.held,self.gold,plan,completed,out/'original-starts-and-dones.jsonl')

    def test_physical_flag_false_refused(self):
        out,plan,completed,summary=self.run_complete()
        completed['original_pretrained_reader_execution']=False
        with self.assertRaises(Invalid):review(self.manifest,self.train,self.held,self.gold,plan,completed,out/'original-starts-and-dones.jsonl')

    def test_no_preplanted_result_directory(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'old').mkdir()
            with self.assertRaises(FileExistsError):run_online(self.manifest,self.train,self.held,self.reader,Path(d,'old'))

    def test_wrong_original_publisher_data_split(self):
        copytrain=copy.deepcopy(self.train)
        copytrain['rows'][0]['label']=True
        with self.assertRaises(Invalid):validate_source(copytrain,self.held)

    def test_strict_answer_parser(self):
        self.assertEqual(parse_answer('FINAL=3'),3)
        self.assertEqual(parse_answer('2'),2)
        self.assertIsNone(parse_answer('I think FINAL=1'))
        self.assertIsNone(parse_answer('FINAL=4'))
        self.assertIsNone(parse_answer('FINAL=1; FINAL=2'))

    def test_create_only_source_packets(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'data.json'
            new_json(p,{'x':'y'})
            with self.assertRaises(FileExistsError):new_json(p,{'x':'z'})

if __name__=='__main__':unittest.main()
