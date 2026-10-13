"""Target/branch audit and fixed-dose tests; random weights are fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import torch
from torch.nn import functional as F
import five_causal_experiments as c
import five_reader_response_learning as learning
import five_reader_evidence_pairs as pairs
import test_five_reader_response as fixtures
import test_five_reader_evidence_pairs as pair_fixtures
import reader_fit_audit as audit
import reader_fit_budget_trial as study


def examples():
    rows=fixtures.examples()
    for row in rows:
        if row['kind']=='annotated_answer': row['response']+=' [E1]'
    return rows


def toy_batch():
    ids=torch.tensor([[1,2,3,4,2]])
    labels=ids.clone();labels[:,:2]=-100
    return {'input_ids':ids,'attention_mask':torch.ones_like(ids),'labels':labels},{
        'prefix_tokens':2,'response_tokens':3,'input_ids_sha256':'a'*64,'labels_sha256':'b'*64}


class SuffixTests(unittest.TestCase):
    def test_exact_suffix_keeps_bracketed_content(self):
        row=examples()[0];row['response']='Alpha [not] [2026] [E1]'
        self.assertEqual(audit.body_example(row)['response'],'Alpha [not] [2026]')

    def test_missing_suffix_rejected(self):
        row=examples()[0];row['response']='Alpha'
        with self.assertRaises(c.Invalid):audit.body_example(row)

    def test_undelivered_citation_not_removed(self):
        row=examples()[0];row['response']='Alpha [E2]'
        with self.assertRaises(c.Invalid):audit.body_example(row)

    def test_multiple_sources_require_order(self):
        row=examples()[0]
        row['request']['evidence'].append(row['request']['evidence'][0]|{'id':'E2'})
        row['response']='Alpha [E1] [E2]'
        self.assertEqual(audit.body_example(row)['response'],'Alpha')
        row['response']='Alpha [E2] [E1]'
        with self.assertRaises(c.Invalid):audit.body_example(row)

    def test_refusal_and_empty_body_rejected(self):
        row=examples()[0]
        for value in (' [E1]',learning.REFUSAL+' [E1]'):
            row['response']=value
            with self.assertRaises(c.Invalid):audit.body_example(row)

    def test_input_and_target_not_mutated(self):
        row=examples()[0];before=deepcopy(row)
        changed=audit.body_example(row)
        changed['request']['evidence'][0]['text']='different'
        self.assertEqual(row,before)


class TokenReadoutTests(unittest.TestCase):
    def setUp(self):torch.set_num_threads(1)

    def test_causal_shift_and_token_mean(self):
        batch,meta=toy_batch();logits=torch.arange(40,dtype=torch.float32).reshape(1,5,8)/7
        row=audit.token_readout(logits,batch,meta)
        expected=-F.cross_entropy(logits[0,1:4],batch['labels'][0,2:],reduction='none')
        torch.testing.assert_close(torch.tensor(row['logp_by_token']),expected)
        self.assertAlmostEqual(row['mean_response_logp'],float(expected.mean()),places=6)
        self.assertAlmostEqual(row['sum_response_logp'],float(expected.sum()),places=6)

    def test_prompt_and_last_logits_not_scored(self):
        batch,meta=toy_batch();logits=torch.zeros(1,5,8)
        old=audit.token_readout(logits,batch,meta)
        logits[:,0]=float('nan');logits[:,-1]=10000
        self.assertEqual(audit.token_readout(logits,batch,meta),old)

    def test_mask_hole_not_silently_ignored(self):
        batch,meta=toy_batch();batch['labels'][0,3]=-100
        with self.assertRaises(c.Invalid):audit.token_readout(torch.zeros(1,5,8),batch,meta)

    def test_nonfinite_scored_logits_rejected(self):
        batch,meta=toy_batch();logits=torch.zeros(1,5,8);logits[0,2,0]=float('nan')
        with self.assertRaises(c.Invalid):audit.token_readout(logits,batch,meta)

    def test_positive_pair_logit_is_not_greedy_choice(self):
        batch,meta=toy_batch();logits=torch.zeros(1,5,8)
        logits[0,1,3]=8;logits[0,2,4]=2;logits[0,2,6]=1;logits[0,2,7]=3
        branch=audit.token_readout(logits,batch,meta,alternative=[3,6,2])['first_branch']
        self.assertEqual(branch['response_index'],1)
        self.assertEqual(branch['good_minus_alternative_logit'],1.0)
        self.assertTrue(branch['greedy_picks_neither'])
        self.assertFalse(branch['greedy_picks_good'])
        self.assertTrue(branch['branch_prefix_reachable_by_greedy'])

    def test_teacher_forced_branch_can_be_unreachable(self):
        batch,meta=toy_batch();logits=torch.zeros(1,5,8)
        logits[0,1,7]=8;logits[0,2,4]=9
        row=audit.token_readout(logits,batch,meta,alternative=[3,6,2])
        self.assertTrue(row['first_branch']['greedy_picks_good'])
        self.assertFalse(row['first_branch']['branch_prefix_reachable_by_greedy'])
        self.assertEqual(row['matched_greedy_prefix_tokens'],0)

    def test_entire_path_includes_last_response_token(self):
        batch,meta=toy_batch();logits=torch.zeros(1,5,8)
        for i,target in enumerate((3,4,2)):logits[0,i+1,target]=10
        self.assertTrue(audit.token_readout(logits,batch,meta)['entire_teacher_forced_path_is_greedy'])
        logits[0,3,7]=11
        self.assertFalse(audit.token_readout(logits,batch,meta)['entire_teacher_forced_path_is_greedy'])

    def test_identical_or_prefix_targets_rejected(self):
        for a,b in (([1,2],[1,2]),([1],[1,2]),([1,2],[1])):
            with self.assertRaises(c.Invalid):audit.divergence(a,b)

    def test_invalid_alternative_and_batch_rejected(self):
        batch,meta=toy_batch()
        with self.assertRaises(c.Invalid):audit.token_readout(torch.zeros(1,5,8),batch,meta,alternative=[99])
        batch={k:v.expand(2,-1) for k,v in batch.items()}
        with self.assertRaises(c.Invalid):audit.token_readout(torch.zeros(2,5,8),batch,meta)


class ActualTinyModelTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.obj=pair_fixtures.backend()

    def test_six_sequences_preserve_original_four(self):
        pair=pairs.paired_examples(examples())[0]
        old,_=pairs.compile_pair(self.obj.tokenizer,pair,position_cap=128)
        variants,meta=audit.compile_audit(self.obj.tokenizer,pair,position_cap=128)
        self.assertEqual(meta['forwards_planned'],6)
        for (a,am),(b,bm) in zip(old['variants'],variants[:4]):
            self.assertEqual(am,bm)
            for key in a:self.assertTrue(torch.equal(a[key],b[key]))
        self.assertLess(variants[4][1]['response_tokens'],variants[0][1]['response_tokens'])
        self.assertFalse(meta['training_target_modified'])

    def test_real_six_forwards_preserve_weights(self):
        pair=pairs.paired_examples(examples())[0]
        before=learning.state_digest(self.obj.loaded.state_dict())
        with learning.count_forwards(self.obj.loaded.base_model) as counter:
            result=audit.audit_one(self.obj.loaded,self.obj.tokenizer,pair,position_cap=128)
        self.assertEqual(counter['model_calls'],6)
        self.assertEqual(learning.state_digest(self.obj.loaded.state_dict()),before)
        self.assertEqual(len(result['sequences']),6)
        self.assertFalse(result['candidate_admitted'])
        self.assertFalse(self.obj.loaded.base_model._forward_pre_hooks)

    def test_mean_equals_existing_hf_score(self):
        pair=pairs.paired_examples(examples())[0]
        compiled,_=pairs.compile_pair(self.obj.tokenizer,pair,position_cap=128)
        with torch.no_grad():expected=[float(pairs.sequence_score(self.obj.loaded,b)) for b,_ in compiled['variants']]
        result=audit.audit_one(self.obj.loaded,self.obj.tokenizer,pair,position_cap=128)
        actual=[result['sequences'][k]['mean_response_logp'] for k in pairs.ORDER]
        torch.testing.assert_close(torch.tensor(expected),torch.tensor(actual),rtol=1e-5,atol=1e-6)

    def test_trainable_or_training_mode_rejected_without_forward(self):
        pair=pairs.paired_examples(examples())[0]
        for mode in ('training','grad'):
            self.obj=pair_fixtures.backend()
            if mode=='training':self.obj.loaded.train()
            else:self.obj.loaded.requires_grad_(True)
            with learning.count_forwards(self.obj.loaded.base_model) as counter:
                with self.assertRaises(c.Invalid):audit.audit_one(self.obj.loaded,self.obj.tokenizer,pair,position_cap=128)
            self.assertEqual(counter['model_calls'],0)


class FixedDoseTests(unittest.TestCase):
    def test_two_by_two_controls(self):
        self.assertEqual({(e,s) for _,e,s in study.ARMS if e},{(2,False),(2,True),(8,False),(8,True)})
        self.assertEqual(len(study.ARMS),5)
        self.assertFalse(study.PLAN['automatic_selection'])
        self.assertFalse(study.PLAN['test_readout'])

    def test_shuffle_changes_only_positive_target(self):
        rows=examples();shuffled=learning.permuted_positive_targets(rows)
        study.assert_training_pair_identity(rows,shuffled,[])
        shuffled[1]['request']['question']='different'
        with self.assertRaises(c.Invalid):study.assert_training_pair_identity(rows,shuffled,[])

    def test_forbidden_family_rejected(self):
        rows=examples();shuffled=learning.permuted_positive_targets(rows)
        with self.assertRaises(c.Invalid):study.assert_training_pair_identity(rows,shuffled,['family0'])

    def test_unchanged_targets_not_shuffle(self):
        rows=examples()
        with self.assertRaises(c.Invalid):study.assert_training_pair_identity(rows,deepcopy(rows),[])

    def test_actual_schedule_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);short=root/'short';long=root/'long'
            rows=[{'record':{'event':'optimizer_started','epoch':i,'index':0,'example_id':'q'}} for i in range(8)]
            short.write_text('\n'.join(json.dumps(x) for x in rows[:2]))
            long.write_text('\n'.join(json.dumps(x) for x in rows))
            self.assertTrue(study.compare_schedules(short,long)['example_order_prefix_equal'])
            rows[1]['record']['example_id']='other';long.write_text('\n'.join(json.dumps(x) for x in rows))
            with self.assertRaises(c.Invalid):study.compare_schedules(short,long)

    def test_failed_audit_remains_in_denominator(self):
        row=audit.summarize([{'split':'train','status':'failed','audit':None}])[0]
        self.assertEqual(row['planned_pairs'],1)
        self.assertEqual(row['scored_pairs'],0)
        self.assertEqual(row['full_target_both_positive'],0)
        self.assertIsNone(row['support_mean_full_margin'])


if __name__=='__main__':unittest.main()
