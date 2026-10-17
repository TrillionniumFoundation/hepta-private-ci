"""Source-only mechanics tests using a fake Reader. NEVER physical model evidence."""
import copy
import os
import stat
from unittest import mock
from collections import Counter
from fractions import Fraction
import json
import tempfile
import unittest
from pathlib import Path

from portfolio import Invalid, POLICIES
from public_source import SCHEMA as SRC, split_original, encoded, sha, new_json
from physical_online import (ACTION_MAX, MODEL_REPO, MODEL_REV, MODEL_WEIGHTS_SHA256,
    MODEL_TOKENIZER_SHA256, assert_original_checkpoint_hashes, run_online,
    validate_source, parse_answer, make_prompt, prompt_seed, final_after_thinking, READER_PROFILE, QwenReader)
from physical_review import review


class MockReader:
    # Deliberately imitates original physical response schema to test verifier's
    # inability to independently attest hardware. This MUST NOT be published as a run.
    physical=True
    identity={'repo':MODEL_REPO,'revision':MODEL_REV,
       'weights_sha256':MODEL_WEIGHTS_SHA256,'tokenizer_sha256':MODEL_TOKENIZER_SHA256,
       'actual_pretrained_model_loaded':True,'runtime':READER_PROFILE}
    load_cpu=0.01;load_wall=0.01
    def __init__(self):
        self.identity=copy.deepcopy(type(self).identity)
        self.calls=[]
    def infer(self,article,action):
        self.calls.append((sha(article.encode()),action))
        prompt=make_prompt(article,action)
        result='FINAL=0' if action=='direct' else 'FINAL=1' if action in ('reason','reason_equalcap') else 'FINAL=2'
        mode = action == 'reason'
        return {'prompt_sha256':sha(encoded(prompt)),
          'input_token_ids_sha256':sha(encoded([4,5])),
          'output_token_ids_sha256':sha(encoded([6,7])),
          'input_tokens':40,'output_tokens':3,'answer':result,
          'thinking_mode':mode, 'thinking_segment_tokens':1 if mode else 0,
          'thinking_complete':mode, 'sampling_seed':prompt_seed(prompt),
          'answer_sha256':sha(result.encode()),'predicted_class':parse_answer(result)}


def fake_data():
    train=[];held=[]
    for split_name,target in (("train",train),("held",held)):
        for i in range(48):
            islong=i%4 in (2,3)
            text=('International business and sports headline '+split_name+' '+str(i)+' ' + 'X'*20 +
                  (' reports further factual news details '*10 if islong else ' reports news.'))
            target.append({'text':text,'label':(i//4)%4})
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

    def test_real_reader_infer_invokes_explicit_qwen3_thinking_switch(self):
        from contextlib import nullcontext
        class T:
            long = 'long'
            def manual_seed(self, seed):self.seed = seed
            def inference_mode(self):return nullcontext()
            def tensor(self, ids, dtype):return ids
        class Tokenizer:
            eos_token_id=0
            def apply_chat_template(self, messages, tokenize, add_generation_prompt, enable_thinking):
                self.thinking=enable_thinking
                return [42,43]
            def decode(self, ids, skip_special_tokens=True):
                assert skip_special_tokens
                return 'FINAL=1' if ids==[9] else ''
        class Model:
            def __init__(self,tok):self.tok=tok;self.kwargs=[]
            def generate(self, ids, **kwargs):
                self.kwargs.append(kwargs)
                class Output:
                    def __init__(self, ids):self.ids=ids
                    def tolist(self):return self.ids
                generated = [7,151668,9] if self.tok.thinking else [9]
                return [Output(ids[0] + generated)]
        r=object.__new__(QwenReader)
        r.tok=Tokenizer();r.torch=T();r.model=Model(r.tok)
        article='An ordinary public news item about a business development.'
        direct=r.infer(article,'direct')
        self.assertFalse(direct['thinking_mode'])
        self.assertEqual(direct['thinking_segment_tokens'],0)
        self.assertEqual(direct['answer'],'FINAL=1')
        reasoning=r.infer(article,'reason')
        self.assertTrue(reasoning['thinking_mode'])
        self.assertTrue(reasoning['thinking_complete'])
        self.assertEqual(reasoning['thinking_segment_tokens'],2)
        self.assertEqual(reasoning['output_tokens'],3)
        self.assertEqual(reasoning['answer'],'FINAL=1')
        self.assertNotIn('think',reasoning['answer'])
        self.assertEqual(r.model.kwargs[0]['max_new_tokens'],12)
        self.assertEqual(r.model.kwargs[1]['max_new_tokens'],96)
        self.assertTrue(r.model.kwargs[1]['do_sample'])
        self.assertEqual(r.model.kwargs[1]['temperature'],0.6)
        equalcap=r.infer(article,'reason_equalcap')
        self.assertFalse(equalcap['thinking_mode'])
        self.assertEqual(equalcap['thinking_segment_tokens'],0)
        self.assertEqual(equalcap['answer'],'FINAL=1')
        self.assertEqual(r.model.kwargs[2]['max_new_tokens'],96)
        self.assertEqual(direct['sampling_seed'],reasoning['sampling_seed'])
        self.assertEqual(reasoning['sampling_seed'],equalcap['sampling_seed'])

    def test_real_reader_truncated_thought_uses_no_final_class(self):
        from contextlib import nullcontext
        class T:
            long=1
            def manual_seed(self, value):pass
            def inference_mode(self):return nullcontext()
            def tensor(self, values, dtype):return values
        class Tok:
            eos_token_id=0
            def apply_chat_template(self, messages, tokenize, add_generation_prompt, enable_thinking):return [1,2]
            def decode(self, tokens, skip_special_tokens=True):return 'FINAL=1'
        class Model:
            def generate(self, ids, **kwargs):
                class Output:
                    def tolist(self):return [1,2,7,8,9]
                return [Output()]
        r=object.__new__(QwenReader)
        r.tok=Tok();r.model=Model();r.torch=T()
        o=r.infer('Another public news article describing sports and finance.','reason')
        self.assertEqual(o['thinking_segment_tokens'],3)
        self.assertEqual(o['answer'],'')
        self.assertIsNone(o['predicted_class'])
        self.assertFalse(o['thinking_complete'])

    def test_new_p5_protocol_does_not_alias_p4_artifacts(self):
        from physical_online import SCHEMA
        self.assertEqual(SCHEMA,'hepta.ndu-merton.p5.original-balanced-and-declared-parser.v1')

    def test_no_thinking_and_thinking_use_same_user_prompt(self):
        article = 'A sufficiently long public news article about current business and weather.'
        self.assertEqual(make_prompt(article, 'direct'), make_prompt(article, 'reason'))
        self.assertEqual(make_prompt(article, 'reason'), make_prompt(article,'reason_equalcap'))
        self.assertEqual(prompt_seed(make_prompt(article,'direct')),
                         prompt_seed(make_prompt(article,'reason')))

    def test_thought_is_never_exposed_to_postseal_answer(self):
        class FakeTokenizer:
            def decode(self, span, skip_special_tokens=True):
                return {5:'PRIVATE_THOUGHT', 7:'FINAL=1'}.get(span[-1], '')
        text, count, ended = final_after_thinking(FakeTokenizer(), [5,151668,7], 'reason')
        self.assertEqual((text,count,ended), ('FINAL=1',2,True))
        self.assertNotIn('PRIVATE_THOUGHT',text)

    def test_truncated_thinking_not_scored_as_final(self):
        class FakeTokenizer:
            def decode(self, span, skip_special_tokens=True):
                return 'FINAL=1'
        self.assertEqual(final_after_thinking(FakeTokenizer(),[17,18,19],'reason'), ('',3,False))

    def test_reasoning_closer_in_non_thinking_action_is_refused(self):
        class FakeTokenizer:
            def decode(self, span, skip_special_tokens=True):
                return 'FINAL=1'
        with self.assertRaises(Invalid):
            final_after_thinking(FakeTokenizer(),[151668,5],'direct')

    def test_duplicate_thinking_closer_refused(self):
        class FakeTokenizer:
            def decode(self, span, skip_special_tokens=True):
                return 'FINAL=1'
        with self.assertRaises(Invalid):
            final_after_thinking(FakeTokenizer(),[5,151668,6,151668,7],'reason')

    def test_forged_reasoning_meter_refused_by_postseal(self):
        out,plan,completed,summary=self.run_complete()
        rec=next(r for r in completed['actual_policy_trace'] if r['action']=='reason')
        rec['thinking_segment_tokens']=rec['output_tokens']+1
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_forged_sampling_seed_rejected_even_after_seal(self):
        out,plan,completed,summary=self.run_complete()
        rec=completed['actual_policy_trace'][0]
        rec['sampling_seed']=(rec['sampling_seed']+1) % (2**32)
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_original_checkpoint_sha256_pins(self):
        assert_original_checkpoint_hashes(MODEL_WEIGHTS_SHA256,MODEL_TOKENIZER_SHA256)
        with self.assertRaises(Invalid):
            assert_original_checkpoint_hashes('f'*64,MODEL_TOKENIZER_SHA256)
        with self.assertRaises(Invalid):
            assert_original_checkpoint_hashes(MODEL_WEIGHTS_SHA256,'0'*64)

    def test_held_source_group_alias_rejected(self):
        self.held['rows'][0]['group']='held-row-parity-0' if self.held['rows'][0]['group'] != 'held-row-parity-0' else 'held-row-parity-1'
        with self.assertRaises(Invalid):validate_source(self.train,self.held)

    def test_held_source_bucket_alias_rejected(self):
        self.held['rows'][0]['bucket']='long' if self.held['rows'][0]['bucket']=='short' else 'short'
        with self.assertRaises(Invalid):validate_source(self.train,self.held)

    def test_forged_checkpoint_identity_rejected_postseal(self):
        out,plan,completed,summary=self.run_complete()
        plan['reader']['weights_sha256']='0'*64
        completed['physical_model_identity']['weights_sha256']='0'*64
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_boolean_prediction_is_not_original_class(self):
        out,plan,completed,summary=self.run_complete()
        completed['actual_policy_trace'][0]['predicted_class']=True
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_total_model_latency_must_be_finite(self):
        out,plan,completed,summary=self.run_complete()
        completed['execution_wall_seconds']=float('nan')
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_total_model_cpu_cannot_be_boolean(self):
        out,plan,completed,summary=self.run_complete()
        completed['model_load_cpu_seconds']=False
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_equalcap_schedule_is_frozen_complete_and_alternating(self):
        out,plan,completed,summary=self.run_complete()
        schedule=plan['paired_equalcap_schedule']
        self.assertEqual(len(schedule),32)
        self.assertEqual(len(completed['paired_equalcap_trace']),32)
        for index in range(16):
            pair=schedule[2*index:2*index+2]
            self.assertEqual(pair[0]['task_id'],pair[1]['task_id'])
            self.assertEqual(set(x['action'] for x in pair),{'reason','reason_equalcap'})
            self.assertEqual(pair[0]['action'], 'reason' if index%2==0 else 'reason_equalcap')
            self.assertEqual(set(x['policy'] for x in pair),{'equal_cap'})
        self.assertEqual([(r['task_id'],r['action']) for r in completed['paired_equalcap_trace']],
                         [(r['task_id'],r['action']) for r in schedule])

    def test_equalcap_source_seed_and_prompt_identical(self):
        out,plan,completed,summary=self.run_complete()
        rows=completed['paired_equalcap_trace']
        for i in range(0,len(rows),2):
            self.assertEqual(rows[i]['prompt_sha256'],rows[i+1]['prompt_sha256'])
            self.assertEqual(rows[i]['sampling_seed'],rows[i+1]['sampling_seed'])
        self.assertTrue(all(r['thinking_mode']==(r['action']=='reason') for r in rows))

    def test_postseal_never_credits_unselected_equalcap_as_free(self):
        out,plan,completed,summary=self.run_complete()
        self.assertEqual(summary['additional_paid_equalcap_invocations'],32)
        self.assertEqual(summary['paired_equalcap_96_token_contrast']['paired_tasks'],16)
        stats=summary['paired_equalcap_96_token_contrast']['thinking_mode_vs_equalcap_nonthinking']
        self.assertEqual([r['action'] for r in stats],['reason','reason_equalcap'])
        self.assertEqual([r['actual_independent_model_invocations'] for r in stats],[16,16])
        self.assertEqual(sum(stats[0]['correct']==j for j in range(17)),1)
        self.assertTrue(stats[0]['total_thinking_tokens'] > 0)
        self.assertEqual(stats[1]['total_thinking_tokens'],0)
        self.assertEqual(sum(summary['paired_equalcap_96_token_contrast'][key] for key in (
            'taskwise_thinking_wins','taskwise_thinking_losses','taskwise_both_correct','taskwise_neither_correct')),16)

    def test_missing_equalcap_physical_request_fails_closed(self):
        out,plan,completed,summary=self.run_complete()
        completed['paired_equalcap_trace'].pop()
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_duplicate_equalcap_task_does_not_match_precommitted_schedule(self):
        out,plan,completed,summary=self.run_complete()
        completed['paired_equalcap_trace'][1]['task_id']=completed['paired_equalcap_trace'][0]['task_id']
        completed['paired_equalcap_trace'][1]['action']='reason'
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_resealed_equalcap_schedule_order_tampering_refused(self):
        out,plan,completed,summary=self.run_complete()
        plan['paired_equalcap_schedule'][0],plan['paired_equalcap_schedule'][1] = (
            plan['paired_equalcap_schedule'][1],plan['paired_equalcap_schedule'][0])
        from public_source import sha,encoded
        completed['frozen_plan_sha256']=sha(encoded(plan))
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_forged_equalcap_mode_meter_refused(self):
        out,plan,completed,summary=self.run_complete()
        rec=next(x for x in completed['paired_equalcap_trace'] if x['action']=='reason_equalcap')
        rec['thinking_mode']=True
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_forged_equalcap_prompt_sha_refused(self):
        out,plan,completed,summary=self.run_complete()
        completed['paired_equalcap_trace'][0]['prompt_sha256']='f'*64
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_missing_equalcap_original_journal_event_refused(self):
        out,plan,completed,summary=self.run_complete()
        journal=out/'original-starts-and-dones.jsonl'
        lines=journal.read_text().splitlines()
        lines.pop()
        journal.write_text('\n'.join(lines)+'\n')
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,journal)

    def test_equalcap_action_does_not_enter_p1_action_manifest(self):
        from physical_online import PORTFOLIO_ACTIONS, EQUAL_CAP_ACTIONS, ACTION_MAX
        self.assertEqual(set(PORTFOLIO_ACTIONS),{'direct','reason','verify'})
        self.assertEqual(EQUAL_CAP_ACTIONS,('reason','reason_equalcap'))
        self.assertEqual(ACTION_MAX['reason'],ACTION_MAX['reason_equalcap'])
        self.assertNotIn('reason_equalcap',{r['name'] for r in self.manifest['actions']})

    def test_original_source_partition(self):
        self.assertEqual(len(self.train['rows']),16)
        self.assertEqual(len(self.held['rows']),16)
        self.assertEqual(len(self.gold['rows']),16)
        self.assertTrue(all('label' not in r for r in self.held['rows']))
        self.assertTrue(all('text' not in r for r in self.gold['rows']))
        self.assertEqual(len({r['task_id'] for r in self.train['rows']+self.held['rows']}),32)
        from collections import Counter as C
        for group in (self.train['rows'], self.gold['rows']):
            self.assertEqual(C(r['label'] for r in group), C({k:4 for k in range(4)}))
        self.assertEqual(C(r['bucket'] for r in self.held['rows']),
                         C({'short':8, 'long':8}))

    def test_all_real_action_slots_are_physically_called_after_freeze_in_contract(self):
        out,plan,completed,summary=self.run_complete()
        self.assertEqual(completed['actual_training_requests'],48)
        self.assertEqual(completed['actual_online_policy_requests'],112)
        self.assertEqual(completed['actual_equalcap_contrast_requests'],32)
        self.assertEqual(len(self.reader.calls),192)
        self.assertEqual(summary['physical_on_policy_generation_invocations_self_reported'],192)
        self.assertEqual(summary['additional_paid_equalcap_invocations'],32)
        self.assertEqual(len(summary['seven_policy_results']),7)
        self.assertEqual([r['policy'] for r in summary['seven_policy_results']],list(POLICIES))
        self.assertFalse(summary['actual_model_savings_proven'])
        paired=summary['paired_equalcap_96_token_contrast']
        self.assertEqual(paired['paired_tasks'],16)
        self.assertEqual(paired['thinking_mode_vs_equalcap_nonthinking'][0]['max_generated_token_ceiling'],96)
        self.assertEqual(paired['thinking_mode_vs_equalcap_nonthinking'][1]['max_generated_token_ceiling'],96)
        self.assertFalse(paired['observed_saved_compute_claim'])
        self.assertGreater(summary['actual_training_input_output_tokens'],0)
        for row in summary['seven_policy_results']:
            self.assertTrue(row['cold_start_calibration_fee_shared_not_summable'])
            self.assertLessEqual(Fraction(row['illustrative_single_arm_cold_start_net_tokens_only']),
                                 Fraction(row['external_correct_minus_FULL_serving_token_tariff']))
        # This fixture deliberately SPOOFS the same metadata as a real model.
        # A self-issued model identity cannot establish independent attestation.
        self.assertEqual(summary['model_identity']['runtime'], READER_PROFILE)
        self.assertFalse(summary['independent_hardware_attestation'])
        self.assertTrue(out.joinpath('frozen-plan.json').exists())

    def test_no_reader_output_shortcut_or_policy_cache(self):
        out,plan,completed,summary=self.run_complete()
        traces=completed['actual_policy_trace']
        self.assertEqual(len(traces),len(POLICIES)*16)
        self.assertEqual(len({(x['policy'],x['task_id']) for x in traces}),len(traces))
        self.assertEqual([x['policy'] for x in traces].count('direct'),16)
        self.assertEqual([x['policy'] for x in traces].count('ndu_discrete'),16)
        self.assertEqual([x['policy'] for x in traces].count('ordinary_same_profile'),16)

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

    def test_postseal_rejects_unbalanced_publisher_gold(self):
        out,plan,completed,summary=self.run_complete()
        # A forged test-label distribution cannot be justified as the source
        # owner's predeclared four-class balanced sampling profile.
        self.gold['rows'][0]['label'] = (self.gold['rows'][0]['label'] + 1) % 4
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_publisher_truth_changed_after_seal_refused(self):
        out,plan,completed,summary=self.run_complete()
        self.gold['rows'][0]['text_sha256']='0'*64
        with self.assertRaises(Invalid):review(self.manifest,self.train,self.held,self.gold,plan,completed,out/'original-starts-and-dones.jsonl')

    def test_sealed_plan_changed_after_original_call_refused(self):
        out,plan,completed,summary=self.run_complete()
        plan['reader']['revision']='forged'
        with self.assertRaises(Invalid):review(self.manifest,self.train,self.held,self.gold,plan,completed,out/'original-starts-and-dones.jsonl')

    def test_train_prompt_substitution_refused(self):
        out,plan,completed,summary=self.run_complete()
        completed['original_train_trace'][0]['prompt_sha256']='f'*64
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

    def test_frozen_schedule_balances_policy_position_across_tasks(self):
        out,plan,completed,summary=self.run_complete()
        schedule=plan['selected_request_schedule']
        self.assertEqual(len(schedule),112)
        by_task={tid:[] for tid in sorted(r['task_id'] for r in self.held['rows'])}
        for item in schedule:
            by_task[item['task_id']].append(item['policy'])
        self.assertTrue(all(set(x)==set(POLICIES) for x in by_task.values()))
        counts=Counter((i,policy) for x in by_task.values() for i,policy in enumerate(x))
        self.assertTrue(all(2<=counts[i,p]<=3 for i in range(7) for p in POLICIES))
        self.assertEqual([(r['policy'],r['task_id'],r['action']) for r in completed['actual_policy_trace']],
            [(r['policy'],r['task_id'],r['action']) for r in schedule])

    def test_substituted_prelabel_schedule_denied_even_if_resealed(self):
        out,plan,completed,summary=self.run_complete()
        plan['selected_request_schedule'][0],plan['selected_request_schedule'][1] = (
            plan['selected_request_schedule'][1],plan['selected_request_schedule'][0])
        from public_source import encoded, sha
        completed['frozen_plan_sha256']=sha(encoded(plan))
        with self.assertRaises(Invalid):
            review(self.manifest,self.train,self.held,self.gold,plan,completed,
                   out/'original-starts-and-dones.jsonl')

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

    def test_source_owner_rejects_unbalanced_publisher_labels(self):
        from public_source import split_original
        cases = [{'text':'a valid news article about business and politics.','label':0} for _ in range(60)]
        with self.assertRaises(ValueError):
            split_original(cases,cases)

    def test_balanced_publisher_selection_is_deterministic(self):
        from public_source import split_original
        # Model outputs never enter the source owner's fixed selection.
        a,b=fake_data(),fake_data()
        self.assertEqual(a,b)
        self.assertNotIn('label',a[1]['rows'][0])
        self.assertEqual(a[0]['source']['split_rule'],
                         'first-per-original-publisher-class-bucket-index-parity')

    def test_strict_answer_parser(self):
        self.assertEqual(parse_answer('FINAL=3'),3)
        self.assertEqual(parse_answer('2'),2)
        self.assertEqual(parse_answer(' <1> '),1)
        self.assertEqual(parse_answer('FINAL=<3>'),3)
        self.assertEqual(parse_answer('final = <0>'),0)
        self.assertIsNone(parse_answer('<1><2>'))
        self.assertIsNone(parse_answer('FINAL=<1> extra'))
        self.assertIsNone(parse_answer('I think <1>'))
        self.assertIsNone(parse_answer('I think FINAL=1'))
        self.assertIsNone(parse_answer('FINAL=4'))
        self.assertIsNone(parse_answer('FINAL=1; FINAL=2'))

    def test_source_owner_requires_parent_directory_fsync(self):
        with tempfile.TemporaryDirectory() as d:
            seen=[]
            fsync_original=os.fsync
            def audited_fsync(fd):
                seen.append(stat.S_ISDIR(os.fstat(fd).st_mode))
                return fsync_original(fd)
            with mock.patch('public_source.os.fsync', side_effect=audited_fsync):
                new_json(Path(d)/'source.json',{'x':'y'})
            self.assertIn(True,seen)
            self.assertIn(False,seen)

    def test_directory_sync_failure_stops_before_original_forward(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch('physical_online.sync_dir', side_effect=OSError('lost directory fsync')):
                with self.assertRaises(OSError):
                    run_online(self.manifest,self.train,self.held,self.reader,Path(d)/'new')
            self.assertEqual(self.reader.calls,[])

    def test_create_only_source_packets(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'data.json'
            new_json(p,{'x':'y'})
            with self.assertRaises(FileExistsError):new_json(p,{'x':'z'})

if __name__=='__main__':unittest.main()
