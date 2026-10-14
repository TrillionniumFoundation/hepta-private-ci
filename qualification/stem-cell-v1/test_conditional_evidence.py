"""Execute conditional token reading and its evidence/cost/causal controls."""
import copy
import unittest

import torch

from conditional_evidence import (
    ConditionedReader, Evidence, Question, TrainingCase, admit_questions,
    compare_conditioned, evidence_digest, fit_reader)
from execution_meter import CONDITIONAL_READER_POLICY_SCHEMA, WorkLedger
from reader_work_v1 import PROFILE

POLICY = dict(schema=CONDITIONAL_READER_POLICY_SCHEMA, arithmetic_profile=PROFILE,
              mode='strict', wall_time_ns=20_000_000_000,
              max_process_rss_bytes=None, rapl_zone=None, rapl_max_power_watts=None)


def evidence():
    return Evidence('principal-A', 'doc-001', 'Two independent facts A and B', 4, 'a'*64)


def states(a=1,b=0,noise=0.):
    return torch.tensor([[1., 0., 1. if a else -1., noise],
                         [0., 1., 1. if b else -1., -noise]],dtype=torch.float32)


def vector(text,options):
    if text=='What is A?': return torch.tensor([8.,0.,0.,0.])
    if text=='What is B?': return torch.tensor([0.,8.,0.,0.])
    raise ValueError('unregistered question')


class FrozenEncoder:
    def __init__(self, values=None):
        self.calls=0
        self.values=states() if values is None else values
        with torch.random.fork_rng():
            torch.manual_seed(5)
            self.layer=torch.nn.Linear(4,4,bias=True).eval()
        self.layer.requires_grad_(False)

    def __call__(self,ev):
        self.calls+=1
        # One ACTUAL tensor forward per invocation, not a multiply-by-N report.
        return self.layer(self.values).detach()


def jobs(reader=None):
    ev=evidence(); digest=evidence_digest(ev)
    question_texts=['What is A?','What is B?']
    return ev, [Question(f'task-{i}',ev.principal,digest,q,('no','yes'),7,
                         copy.deepcopy(reader) if reader is not None else ConditionedReader(4,2).eval())
                for i,q in enumerate(question_texts)]


class ConditionalEvidenceTests(unittest.TestCase):
    def test_distinct_questions_reuse_one_real_encoder_with_reader_parity(self):
        ev,items=jobs()
        enc=FrozenEncoder()
        result=compare_conditioned(enc,vector,ev,items,policy=POLICY,as_of_ns=8)
        self.assertEqual((result['shared']['encoder_calls'],result['repeated']['encoder_calls']), (1,2))
        self.assertEqual((result['shared']['query_calls'],result['repeated']['query_calls']),(2,2))
        self.assertEqual(enc.calls,3)
        self.assertEqual(result['max_logit_abs_difference'],0.)
        self.assertGreater(result['formula_work_saved'],0)
        self.assertFalse(result['conditional_reader_accuracy_established'])

    def test_shared_vs_repeat_charges_actual_query_and_reader_work(self):
        ev,items=jobs()
        result=compare_conditioned(FrozenEncoder(),vector,ev,items,policy=POLICY,as_of_ns=8)
        for route in ('shared','repeated'):
            data=result[route]
            observed=data['work_observation']
            self.assertEqual(observed['unknown_operators'],{})
            self.assertEqual(sum(x['calls'] for x in observed['scopes'] if x['component']=='bank'),2)
            self.assertEqual(sum(x['calls'] for x in observed['scopes'] if x['component']=='material'),2)
            self.assertGreater(data['formula_flops'],0)

    def test_distinct_task_scores_are_not_alias_of_same_reader(self):
        ev,items=jobs()
        self.assertIsNot(items[0].reader,items[1].reader)
        bad=[items[0],Question('other',ev.principal,items[0].evidence_digest,'What is B?',('no','yes'),7,items[0].reader)]
        with self.assertRaisesRegex(ValueError,'independent Reader'):
            admit_questions(ev,bad,as_of_ns=8)

    def test_independent_reader_objects_with_shared_physical_weights_reject(self):
        ev,items=jobs()
        items[1].reader.classifier=items[0].reader.classifier
        with self.assertRaisesRegex(ValueError,'parameters alias'):
            admit_questions(ev,items,as_of_ns=8)

    def test_cross_principal_wrong_evidence_and_future_time_rejected_pre_encoder(self):
        ev,items=jobs()
        for mutation in ('principal','digest','future','future_document'):
            different=list(items)
            source=ev
            if mutation=='principal': different[0]=copy.copy(different[0]);different[0]=Question('other','principal-B',different[0].evidence_digest,'What is A?',('no','yes'),7,different[0].reader)
            if mutation=='digest': different[0]=Question('other',ev.principal,'f'*64,'What is A?',('no','yes'),7,different[0].reader)
            if mutation=='future': different[0]=Question('other',ev.principal,items[0].evidence_digest,'What is A?',('no','yes'),15,different[0].reader)
            if mutation=='future_document': source=Evidence(ev.principal,ev.document_id,ev.text,12,ev.checkpoint_sha256)
            enc=FrozenEncoder()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                compare_conditioned(enc,vector,source,different,policy=POLICY,as_of_ns=8)
            self.assertEqual(enc.calls,0)

    def test_different_doc_or_weight_version_cannot_reuse_identity(self):
        ev,items=jobs()
        for new in (Evidence(ev.principal,'other',ev.text,4,ev.checkpoint_sha256),
                    Evidence(ev.principal,ev.document_id,ev.text+' changed',4,ev.checkpoint_sha256),
                    Evidence(ev.principal,ev.document_id,ev.text,4,'b'*64)):
            with self.assertRaises(ValueError):
                admit_questions(new,items,as_of_ns=8)

    def test_options_are_ordered_and_not_training_labels(self):
        ev,items=jobs()
        wrong=Question('different',ev.principal,items[0].evidence_digest,'What is A?',('yes','no'),7,ConditionedReader(4,2).eval())
        # A differently ordered legal set is a different task, but requires its own
        # supervised label mapping. Unlike a reused per-query prediction, it is not
        # silently interpreted as the original task.
        report=compare_conditioned(FrozenEncoder(),vector,ev,[wrong],policy=POLICY,as_of_ns=8)
        self.assertEqual(report['question_count'],1)
        self.assertFalse(report['independent_question_answering_established'])
        with self.assertRaises(ValueError):
            admit_questions(ev,[dict(label=0)],as_of_ns=8)

    def test_unknown_encoder_arithmetic_does_not_become_zero(self):
        ev,items=jobs()
        class Unsupported(FrozenEncoder):
            def __call__(self,ev):
                return torch.atan(super().__call__(ev))
        p=dict(POLICY,mode='observe')
        result=compare_conditioned(Unsupported(),vector,ev,items,policy=p,as_of_ns=8)
        self.assertIsNone(result['formula_work_saved'])
        self.assertIsNone(result['shared']['formula_flops'])
        self.assertIn('aten.atan.default',result['shared']['work_observation']['unknown_operators'])

    def test_strict_unknown_refused_before_complete_claim(self):
        ev,items=jobs()
        class Unsupported(FrozenEncoder):
            def __call__(self,ev): return torch.atan(super().__call__(ev))
        with self.assertRaisesRegex(RuntimeError,'unsupported_operator'):
            compare_conditioned(Unsupported(),vector,ev,items,policy=POLICY,as_of_ns=8)

    def test_bounded_token_storage_and_budget_refuse(self):
        ev,items=jobs()
        class Big(FrozenEncoder):
            def __call__(self,ev):
                self.calls+=1
                return torch.ones(100000)[:8].reshape(2,4)
        with self.assertRaisesRegex(ValueError,'exceeds source/size'):
            compare_conditioned(Big(),vector,ev,items,policy=POLICY,as_of_ns=8,max_evidence_bytes=128)
        caps=dict.fromkeys(('train','search','evaluation','inference','migration'),2)
        with self.assertRaisesRegex(RuntimeError,'formula_flop_budget'):
            compare_conditioned(FrozenEncoder(),vector,ev,items,policy=POLICY,as_of_ns=8,caps=caps)

    def test_nondeterministic_encoder_is_rejected_by_output_comparison(self):
        ev,items=jobs()
        class Drift(FrozenEncoder):
            def __call__(self,ev):
                self.calls+=1
                return self.values+self.calls*.1
        with self.assertRaisesRegex(ValueError,'changed question-conditioned logits'):
            compare_conditioned(Drift(),vector,ev,items,policy=POLICY,as_of_ns=8)

    def test_training_rejects_future_labels_without_mutating_selected_readout(self):
        source=ConditionedReader(4,2).eval()
        before={k:v.clone() for k,v in source.state_dict().items()}
        data=[TrainingCase(states(),vector('What is A?',('no','yes')),1,'train-1',5)]
        with self.assertRaises(ValueError):fit_reader(source,data,cutoff_ns=4,steps=5)
        trained,receipt=fit_reader(source,data,cutoff_ns=5,steps=8)
        self.assertEqual(receipt['examples_seen'],8)
        self.assertFalse(receipt['independent_task_gain_established'])
        self.assertTrue(all(torch.equal(before[k],v) for k,v in source.state_dict().items()))
        self.assertTrue(any(not torch.equal(before[k],v) for k,v in trained.state_dict().items()))

    def test_training_meter_charges_real_optimization_without_claiming_qualification(self):
        source=ConditionedReader(4,2).eval()
        examples=[TrainingCase(states(a,b),vector('What is A?',('no','yes')),
                    a,f'train-{a}{b}',3) for a in (0,1) for b in (0,1)]
        meter=WorkLedger(POLICY,dict.fromkeys(('train','search','evaluation','inference','migration'),10**9))
        trained,report=fit_reader(source,examples,cutoff_ns=3,steps=8,meter=meter)
        self.assertEqual(report['meter_observation']['unknown_operators'],{})
        self.assertGreater(report['observed_training_aten_formula_flops'],0)
        self.assertFalse(report['prospective_evidence_sufficiency_established'])
        self.assertFalse(trained.training)

    def test_train_learns_two_independently_varying_facts_with_disjoint_groups(self):
        with torch.random.fork_rng():
            torch.manual_seed(11)
            source=ConditionedReader(4,2).eval()
        data=[]
        for group in range(12):
            for a in (0,1):
                for b in (0,1):
                    v=states(a,b,noise=(group-5)*.0125)
                    data.append(TrainingCase(v,vector('What is A?',('no','yes')),a,f'train-{group}',10))
                    data.append(TrainingCase(v,vector('What is B?',('no','yes')),b,f'train-{group}',10))
        trained,record=fit_reader(source,data,cutoff_ns=10,steps=450,learning_rate=.015,seed=7347)
        self.assertGreater(record['source_group_count'],1)
        correct=0
        with torch.inference_mode():
            for i in range(40):
                a,b=(i//2)%2,i%2
                v=states(a,b,noise=(i+10)*.004)
                for question,label in (('What is A?',a),('What is B?',b)):
                    pred=trained(v,vector(question,('no','yes'))).argmax().item()
                    correct+=int(pred==label)
        self.assertGreaterEqual(correct,76)
        # Mean-pool cannot distinguish A=0,B=1 from A=1,B=0,
        # even though the question asks a specific field.
        mean1=states(0,1).mean(dim=0)
        mean2=states(1,0).mean(dim=0)
        torch.testing.assert_close(mean1,mean2,rtol=0,atol=0)
        # Removing the selected premise changes the prediction for at least one
        # question; this is a test-only evidence ablation, not a real-model audit.
        changed=[]
        with torch.inference_mode():
            for a,b in ((0,0),(0,1),(1,0),(1,1)):
                original=states(a,b)
                for q in ('What is A?','What is B?'):
                    dropped=original.clone()
                    dropped[0 if q.endswith('A?') else 1,2]*=-1
                    before=trained(original,vector(q,('no','yes'))).argmax().item()
                    after=trained(dropped,vector(q,('no','yes'))).argmax().item()
                    changed.append(before!=after)
        self.assertTrue(any(changed))

    def test_repeated_query_and_shared_query_different_behaviors_counted(self):
        ev,items=jobs()
        qcalls=[0]
        def query(text, options):
            qcalls[0]+=1
            return vector(text,options)
        result=compare_conditioned(FrozenEncoder(),query,ev,items,policy=POLICY,as_of_ns=8)
        self.assertEqual(qcalls[0],4) # two questions in each comparison arm
        self.assertEqual(result['shared']['query_calls'],2)
        self.assertEqual(result['repeated']['query_calls'],2)


if __name__=='__main__':
    torch.set_num_threads(1)
    unittest.main()
