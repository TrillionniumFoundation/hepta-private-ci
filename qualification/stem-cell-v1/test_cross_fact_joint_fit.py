"""Actual CPU autodiff checks for synchronized equal-work Head training."""
from dataclasses import dataclass
from hashlib import sha256
import unittest
from unittest.mock import patch
import torch

from cross_fact_bridge import matched_reader_pair
from cross_fact_joint_fit import ARMS, JointFitFailure, _model_digest, _schedule, fit_joint_reader_pair


@dataclass(frozen=True)
class Case:
    case_id: str
    paragraph_id: str
    answer_id: str
    label: int
    facts: tuple
    question: str
    candidate: str
    segmentation: str
    source_hash: str


class Batch:
    def __init__(self, tensors, targets, groups):
        self.tensors, self.targets, self.source_groups = tensors, targets, groups
    def features(self):
        return self.tensors
    def take(self, indices):
        sub=torch.tensor(indices,dtype=torch.long)
        return Batch(tuple(value[sub] for value in self.tensors), self.targets[sub],
                     tuple(self.source_groups[i] for i in indices))
    def validate(self, input_dim):
        assert self.tensors[0].shape[-1] == input_dim
        assert len(self.targets) == len(self.source_groups)


def fixture():
    cases=[]
    for group in range(4):
        for world in (0,1):
            owners=('Ada','Ben') if world==0 else ('Ben','Ada')
            facts=(f'The token belongs to {owners[0]}.',
                   f'The bead belongs to {owners[1]}.',
                   'Ada stores all their possessions in the copper box.',
                   'Ben stores all their possessions in the silver box.')
            for answer in (0,1):
                cases.append(Case(f'group-{group}/world-{world}/answer-{answer}',
                       f'group-{group}/world-{world}',str(answer),int(answer==world),facts,
                       'Where is the token stored?', ('The copper box.','The silver box.')[answer],
                       'synthetic-ownership-storage-v1',sha256((' '.join(facts)).encode()).hexdigest()))
    torch.manual_seed(123)
    tensor=(torch.randn(16,4,2,8),torch.randn(16,2,8),torch.randn(16,2,8),
         torch.ones(16,4,2,dtype=torch.bool),torch.ones(16,2,dtype=torch.bool),
         torch.ones(16,2,dtype=torch.bool))
    return tuple(cases),Batch(tensor, torch.tensor([c.label for c in cases]),
                              tuple(c.source_hash for c in cases))


class JointTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.cases,self.data=fixture()
        c,l=matched_reader_pair(input_dim=8,hidden_dim=8,seed=41)
        self.models={'cross_fact':c.eval().requires_grad_(False),
                     'local':l.eval().requires_grad_(False)}

    def test_real_forward_and_backward_match_original_input_and_source_stream(self):
        initial={a:_model_digest(m) for a,m in self.models.items()}
        models,rows,joint=fit_joint_reader_pair(self.models,self.data,self.cases,
            steps=4,seed=41,batch_size=8,depth=2,diagnostic_interval=2,
            wall_time_ns=50_000_000_000)
        self.assertEqual(joint['completed_steps'],4)
        self.assertEqual(joint['status'],'max_updates_reached')
        self.assertEqual(joint['matched_parameter_count'],sum(p.numel() for p in self.models['local'].parameters()))
        self.assertEqual([x['indices'] for x in rows['cross_fact']['updates']],
                         [x['indices'] for x in rows['local']['updates']])
        self.assertEqual(rows['cross_fact']['schedule_sha256'],rows['local']['schedule_sha256'])
        self.assertEqual(rows['cross_fact']['actual_training_exposures'],32)
        self.assertEqual(rows['cross_fact']['optimizer_tensor_bytes'],rows['local']['optimizer_tensor_bytes'])
        self.assertTrue(all(all(not p.requires_grad for p in m.parameters()) for m in models.values()))
        self.assertTrue(all(_model_digest(self.models[a])==initial[a] for a in ARMS))
        self.assertTrue(all(rows[a]['model_sha256']!=initial[a] for a in ARMS))
        self.assertTrue(all(row['cpu_ns']>0 for a in ARMS for row in rows[a]['updates']))
        self.assertGreater(joint['cpu_ns'],0)

    def test_real_train_batch_is_materialized_once_for_two_head_updates(self):
        # Initial and final/interval diagnostics still have independent copies;
        # but one actual optimizer batch is shared by both Heads at every step.
        with patch.object(self.data, 'take', wraps=self.data.take) as take:
            _,_,joint=fit_joint_reader_pair(self.models,self.data,self.cases,
                 steps=4,seed=41,batch_size=8,depth=2,diagnostic_interval=2)
        self.assertEqual(joint['shared_input_batch_materializations'],4)
        self.assertEqual(take.call_count,16)  # 3 diagnostic pairs x4 + 4 train

    def test_stop_when_both_pass_not_when_only_one_passes(self):
        # Calls: two initial reports, two after update 2, two after update 4.
        call=[0]
        def diagnostic(_model,_data,_cases,_groups,_depth,_batch_size):
            index=call[0]
            call[0]+=1
            passed=index in (2,4,5)
            return dict(accuracy=1. if passed else .5,
                        both_worlds_correct=1. if passed else 0.,
                        binary_cross_entropy=.05 if passed else .69,
                        cpu_ns=1,wall_ns=1,probabilities=[],predictions=[])
        with patch('cross_fact_joint_fit._eval',side_effect=diagnostic):
            _,rows,joint=fit_joint_reader_pair(self.models,self.data,self.cases,
                  steps=6,seed=41,batch_size=8,depth=2,diagnostic_interval=2)
        self.assertEqual(joint['completed_steps'],4)
        self.assertEqual(joint['status'],'train_gate_passed')
        self.assertTrue(all(rows[a]['train_gate_passed'] for a in ARMS))
        self.assertEqual(len(rows['local']['updates']),4)
        self.assertEqual(call[0],6)

    def test_second_arm_failure_preserves_first_attempt_and_never_returns_artifact(self):
        import cross_fact_joint_fit as module
        original=module._step
        calls=[0]
        def failing(*args,**kwargs):
            calls[0]+=1
            if calls[0]==2:
                raise RuntimeError('simulated second arm optimizer error')
            return original(*args,**kwargs)
        failed=[]
        with patch('cross_fact_joint_fit._step',side_effect=failing):
            with self.assertRaises(JointFitFailure) as caught:
                fit_joint_reader_pair(self.models,self.data,self.cases,
                     steps=2,seed=41,batch_size=8,depth=2,diagnostic_interval=1,
                     failure_receipt_fn=failed.append)
        record=caught.exception.receipt
        self.assertEqual(record,failed[0])
        self.assertEqual(record['status'],'failed')
        self.assertEqual(record['completed_steps'],0)
        self.assertEqual(record['partial_attempts'],['cross_fact'])
        self.assertFalse(record['final_evaluation_authorized'])

    def test_granite97_width_384_two_step_real_tensor_training(self):
        # Physical 384D tensor geometry of the pinned real canary, without
        # claiming a pretrained forward in this CPU-only fixture.
        torch.manual_seed(384)
        cases=self.cases
        data=Batch((torch.randn(16,4,2,384),torch.randn(16,2,384),
              torch.randn(16,2,384),torch.ones(16,4,2,dtype=torch.bool),
              torch.ones(16,2,dtype=torch.bool),torch.ones(16,2,dtype=torch.bool)),
              self.data.targets, self.data.source_groups)
        cross,local=matched_reader_pair(input_dim=384,hidden_dim=32,seed=41)
        models={'cross_fact':cross.eval().requires_grad_(False),
                'local':local.eval().requires_grad_(False)}
        trained,receipts,joint=fit_joint_reader_pair(models,data,cases,
            steps=2,seed=41,batch_size=16,depth=3,diagnostic_interval=2)
        self.assertEqual(joint['shared_input_batch_materializations'],2)
        self.assertEqual(joint['completed_steps'],2)
        self.assertEqual(receipts['cross_fact']['actual_training_exposures'],32)
        self.assertEqual(receipts['local']['actual_training_exposures'],32)
        self.assertEqual(receipts['cross_fact']['parameter_count'],
                         receipts['local']['parameter_count'])
        self.assertEqual(receipts['local']['parameter_count'],42562)
        self.assertTrue(all(not p.requires_grad for m in trained.values() for p in m.parameters()))

    def test_unregistered_corrupt_pairing_rejected_before_training(self):
        corrupt=list(self.cases)
        c=corrupt[2]
        from dataclasses import replace
        corrupt[2]=replace(c,question="Where is the missing object?")
        with self.assertRaisesRegex(JointFitFailure,'truth inconsistency'):
            fit_joint_reader_pair(self.models,self.data,corrupt,
                  steps=2,seed=41,batch_size=8,depth=2,diagnostic_interval=1)


if __name__=='__main__':
    unittest.main()
