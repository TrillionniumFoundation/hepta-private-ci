"""Source-only, adversarial, paid-call-shape and token escrow regressions.

All model outputs in these tests are constructed; never original pretrained Qwen.
"""
from __future__ import annotations
import copy
import tempfile
import unittest
from pathlib import Path

import audit
import portfolio
import runner
import source
from parent import load_p8


def original_rows(phase):
    data=[]
    for i in range(160):
        pair=(i//2)%8
        label=pair//2
        bucket='long' if pair%2 else 'short'
        text=f'Original {phase} publisher example {i} with world, sports, business, science context.'
        if bucket=='long':text+=' Repeated descriptive source passage.'*8
        data.append({'text':text,'label':label})
    return data


def packets():
    return source.select_publisher(original_rows('train'),original_rows('held'))


class FakeReader:
    physical=False
    identity={'mock':True,'runtime':runner.ORIGINAL_RUNTIME}
    load_cpu=0.0
    load_wall=0.0
    def __init__(self):self.calls=[]
    def quote(self,text,action,previous):
        if action not in ('check_plain','check_think'):
            raise ValueError('not a checker quote')
        return 155+min(len(text)//25,90)
    def infer(self,text,action,previous=None):
        p=runner.P8.make_prompt(text,action,previous)
        think=action=='check_think'
        n=256 if think else 4
        ans='' if think else ('FINAL=0' if action=='direct' else 'FINAL=<1>')
        self.calls.append((text,action,previous))
        return {'prompt_sha256':runner.digest(p),
                'input_ids_sha256':runner.digest([17]),
                'output_ids_sha256':runner.digest([23]*n),
                'sampling_seed':runner.P8.random_seed(p),
                'input_tokens':101 if action=='direct' else self.quote(text,action,previous),
                'output_tokens':n,'thinking_mode':think,
                'thinking_tokens':n if think else 0,'thinking_complete':False,
                'answer':ans,'predicted_class':runner.P8.parse_answer(ans)}


def synthetic(tmp):
    train,held,gold=packets()
    r=FakeReader()
    out=tmp/'p9-attempt'
    completed=runner.execute(train,held,r,out)
    frozen=runner.read(out/'frozen-plan.json')
    review=audit.audit(train,held,gold,frozen,completed,out/'original-starts-and-dones.jsonl',
                       out/'frozen-plan.json',quote_fn=r.quote,require_physical=False)
    return train,held,gold,r,completed,frozen,review,out


class TokenEscrowTests(unittest.TestCase):
    def test_01_exact_quote_and_actual_refund(self):
        wallet=portfolio.TokenEscrow()
        q=wallet.reserve('a',200)
        self.assertEqual(q['reserved_tokens'],456)
        self.assertEqual(wallet.available,portfolio.TOKEN_ENDOWMENT-456)
        receipt=wallet.settle('a',200,6)
        self.assertEqual(receipt['unused_refund'],250)
        self.assertEqual(wallet.available,portfolio.TOKEN_ENDOWMENT-206)
        wallet.invariant()

    def test_02_allocation_beyond_actual_token_budget_refused(self):
        w=portfolio.TokenEscrow(available=300)
        self.assertFalse(w.can_reserve(100))
        with self.assertRaises(ValueError):w.reserve('no',100)
    def test_03_illegal_negative_integer_and_bool_price_refused(self):
        w=portfolio.TokenEscrow()
        for value in (0,True,-1,1025,1.5):
            with self.assertRaises(ValueError):w.can_reserve(value)
    def test_04_duplicate_or_pending_reservation_refused(self):
        w=portfolio.TokenEscrow();w.reserve('a',100)
        with self.assertRaises(ValueError):w.reserve('a',100)
        w.settle('a',100,1)
        with self.assertRaises(ValueError):w.reserve('a',100)
    def test_05_real_unquoted_input_poisoned(self):
        w=portfolio.TokenEscrow();w.reserve('a',100)
        with self.assertRaises(ValueError):w.settle('a',101,1)
        self.assertTrue(w.poisoned)
        with self.assertRaises(ValueError):w.wire()
    def test_06_failed_physical_call_never_refunded(self):
        w=portfolio.TokenEscrow();w.reserve('lost-ack',100)
        with self.assertRaises(ValueError):w.wire()
        self.assertEqual(w.available,portfolio.TOKEN_ENDOWMENT-356)
    def test_07_reserve_after_exhausted_call_budget_refused(self):
        w=portfolio.TokenEscrow()
        for i in range(portfolio.MAX_CHECKS):w.reserve(str(i),100);w.settle(str(i),100,1)
        self.assertFalse(w.can_reserve(100))
    def test_08_overcap_output_poisoned(self):
        w=portfolio.TokenEscrow();w.reserve('a',100)
        with self.assertRaises(ValueError):w.settle('a',100,portfolio.CHECK_CAP+1)
        self.assertTrue(w.poisoned)
    def test_09_reward_ignores_held_truth(self):
        p=portfolio.Controller({'census':32,'entries':{},'features':{}},('short',)*16,'direct')
        self.assertEqual(p.choose(0,portfolio.TokenEscrow(),'short',None,{'check_plain':100,'check_think':100}),'stop')
    def test_10_unsupported_feature_produces_abstention(self):
        p=portfolio.Controller({'census':32,'entries':{},'features':{}},('short',)*16,'neutral_shadow')
        self.assertEqual(p.choose(0,portfolio.TokenEscrow(),'short',2,{'check_plain':100,'check_think':100}),'stop')
    def test_11_fixed_uses_actual_quote_admission(self):
        p=portfolio.Controller({'census':32,'entries':{},'features':{}},('short',)*16,'fixed_think')
        self.assertEqual(p.choose(0,portfolio.TokenEscrow(available=300),'short',1,{'check_plain':100,'check_think':100}),'stop')
    def test_12_no_label_or_unknown_quote_fields_allowed(self):
        p=portfolio.Controller({'census':32,'entries':{},'features':{}},('short',)*16,'direct')
        with self.assertRaises(ValueError):p.choose(0,portfolio.TokenEscrow(),'short',7,{'check_plain':100,'check_think':100})
        with self.assertRaises(ValueError):p.choose(0,portfolio.TokenEscrow(),'short',1,{'check_plain':100,'check_think':100,'label':1})


class OriginalSourceTests(unittest.TestCase):
    def test_13_original_selection_independent_and_stratified(self):
        t,h,g=packets()
        runner.source_packets(t,h)
        self.assertEqual((len(t['rows']),len(h['rows']),len(g['rows'])),(32,16,16))
        self.assertNotIn('label',h['rows'][0])
        self.assertEqual(len({r['text_sha256'] for r in t['rows']+h['rows']}),48)
    def test_14_stale_source_manifest_rejected(self):
        t,h,g=packets();h['source']['split_rule']='P8'
        with self.assertRaises(ValueError):runner.source_packets(t,h)
    def test_15_held_label_leak_rejected(self):
        t,h,g=packets();h['rows'][0]['label']=3
        with self.assertRaises(ValueError):runner.source_packets(t,h)
    def test_16_insufficient_fourth_fifth_original_support(self):
        tr=original_rows('train')[:70]
        with self.assertRaises(ValueError):source.select_publisher(tr,original_rows('held'))
    def test_17_old_first_cohort_content_duplicate_rejected(self):
        tr=original_rows('train')
        # This alters a fourth-occurrence source to duplicate first-occurrence
        # text with a different row ID and matching label/length/parity.
        tr[48]['text']=tr[0]['text']
        with self.assertRaises(ValueError):source.select_publisher(tr,original_rows('held'))
    def test_18_duplicate_source_text_rejected(self):
        t,h,g=packets();h['rows'][0]['text']=t['rows'][0]['text'];h['rows'][0]['text_sha256']=t['rows'][0]['text_sha256']
        with self.assertRaises(ValueError):runner.source_packets(t,h)


class OriginalPaidReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.evidence=synthetic(Path(cls.tmp.name))
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def review(self,completed=None,plan=None,train=None,held=None,gold=None,quote=None):
        t,h,g,r,c,p,report,out=self.evidence
        return audit.audit(train or t,held or h,gold or g,plan or p,completed or c,
             out/'original-starts-and-dones.jsonl',out/'frozen-plan.json',
             quote_fn=quote or r.quote,require_physical=False)
    def test_19_full_two_stage_mock_census_and_zero_claim(self):
        t,h,g,reader,c,p,a,out=self.evidence
        self.assertEqual(len(c['train_calls']),96)
        self.assertEqual(len(c['policy_decisions']),16*len(portfolio.POLICIES))
        self.assertEqual(len(reader.calls),len(c['train_calls'])+len(c['held_calls']))
        self.assertEqual(a['status'],'RESEARCH_ONLY_DENY_ALL')
        self.assertEqual(a['original_reader_model_calls'],len(reader.calls))
        self.assertTrue(a['ndu_ordinary_same_profile_parity'])
    def test_19_mock_source_cannot_claim_physical(self):
        t,h,g,r,c,p,a,out=self.evidence
        with self.assertRaises(ValueError):audit.audit(t,h,g,p,c,out/'original-starts-and-dones.jsonl',out/'frozen-plan.json',quote_fn=r.quote)
    def test_20_original_journal_tampering_is_rejected(self):
        t,h,g,r,c,p,a,out=self.evidence
        bad=copy.deepcopy(c);bad['journal_events']+=1
        with self.assertRaises(ValueError):self.review(completed=bad)
    def test_21_resealed_wrong_decision_rejected(self):
        t,h,g,r,c,p,a,out=self.evidence
        bad=copy.deepcopy(c);bad['policy_decisions'][0]['choice']='check_plain'
        with self.assertRaises(ValueError):self.review(completed=bad)
    def test_22_false_unselected_quote_is_rejected(self):
        t,h,g,r,c,p,a,out=self.evidence
        bad=copy.deepcopy(c);bad['policy_decisions'][0]['input_quotes']['check_think']+=1
        with self.assertRaises(ValueError):self.review(completed=bad)
    def test_23_stolen_held_truth_rejected(self):
        t,h,g,r,c,p,a,out=self.evidence
        bad=copy.deepcopy(h);bad['rows'][0]['label']=2
        with self.assertRaises(ValueError):self.review(held=bad)
    def test_24_forged_extra_physical_call_rejected(self):
        t,h,g,r,c,p,a,out=self.evidence
        bad=copy.deepcopy(c);bad['held_calls'].append(bad['held_calls'][0])
        with self.assertRaises(ValueError):self.review(completed=bad)
    def test_25_undercounted_paid_output_rejected(self):
        t,h,g,r,c,p,a,out=self.evidence
        bad=copy.deepcopy(c);bad['held_calls'][0]['result']['output_tokens']-=1
        with self.assertRaises(ValueError):self.review(completed=bad)
    def test_26_escrow_refund_forgery_rejected(self):
        t,h,g,r,c,p,a,out=self.evidence
        bad=copy.deepcopy(c);w=bad['wallets']['fixed_plain'];w['remaining_tokens']+=1
        with self.assertRaises(ValueError):self.review(completed=bad)
    def test_27_wrong_observer_gold_rejected(self):
        t,h,g,r,c,p,a,out=self.evidence
        wrong=copy.deepcopy(g);wrong['rows'][0]['label']=9
        with self.assertRaises(ValueError):self.review(gold=wrong)
    def test_28_wrong_trained_policy_rejected(self):
        t,h,g,r,c,p,a,out=self.evidence
        wrong=copy.deepcopy(p);wrong['train_profile']['census']=16
        with self.assertRaises(ValueError):self.review(plan=wrong)
    def test_29_original_tokenizer_requirement_for_physical_claim(self):
        t,h,g,r,c,p,a,out=self.evidence
        with self.assertRaises(ValueError):audit.audit(t,h,g,p,c,out/'original-starts-and-dones.jsonl',out/'frozen-plan.json',quote_fn=None)
    def test_30_report_counts_explicit_full_service_cost(self):
        a=self.evidence[6]
        for n,stats in a['per_policy'].items():
            self.assertEqual(stats['total'],16)
            self.assertGreater(stats['full_serving_tokens'],16*100)
            self.assertLessEqual(stats['checker_calls'],4)
            self.assertEqual(stats['checker_tokens']+stats['checker_remaining_tokens'],1500)
    def test_31_source_truth_file_digest_cross_binding(self):
        t,h,g,r,c,p,a,out=self.evidence
        wrong=copy.deepcopy(g);wrong['rows'][0]['text_sha256']='0'*64
        with self.assertRaises(ValueError):self.review(gold=wrong)
    def test_32_model_identity_mutation_after_freeze_rejected(self):
        t,h,g,r,c,p,a,out=self.evidence
        wrong=copy.deepcopy(c);wrong['model']={'replacement':True}
        with self.assertRaises(ValueError):self.review(completed=wrong)
    def test_33_immutable_frozen_plan_sha_verification(self):
        t,h,g,r,c,p,a,out=self.evidence
        wrong=copy.deepcopy(c);wrong['frozen_plan_sha256']='0'*64
        with self.assertRaises(ValueError):self.review(completed=wrong)


if __name__=='__main__':unittest.main()
