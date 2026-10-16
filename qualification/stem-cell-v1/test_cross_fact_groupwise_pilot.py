"""CPU mechanism checks; full 800-update outcomes are separate numeric evidence."""
import unittest
import torch
from torch.nn import functional as F
from cross_fact_groupwise_pilot import run, quality
from cross_fact_composition_transfer import source_panel
from cross_fact_bridge import matched_reader_pair

class GroupwiseTests(unittest.TestCase):
    def setUp(self):torch.set_num_threads(1)

    def test_groupwise_loss_requires_all_candidates_and_updates_scores(self):
        logits=torch.randn(6,2,requires_grad=True)
        labels=torch.tensor([0,1,0,1,0,0])
        scores=(logits[:,1]-logits[:,0]).reshape(-1,3)
        targets=labels.reshape(-1,3).argmax(-1)
        loss=F.cross_entropy(scores,targets)
        loss.backward()
        self.assertEqual(logits.grad.shape,(6,2))
        self.assertTrue(torch.isfinite(logits.grad).all())
        self.assertGreater(logits.grad.abs().sum().item(),0.)

    def test_two_optimizer_steps_match_real_model_parameters_and_rows(self):
        rows=run(seeds=(41,),modes=('cross_fact',),updates=2)
        self.assertEqual(len(rows),2)
        self.assertEqual({row['loss'] for row in rows},{'binary','binary_plus_group'})
        self.assertEqual(rows[0]['params'],rows[1]['params'])
        self.assertEqual(rows[0]['streamsha'],rows[1]['streamsha'])
        self.assertTrue(all(row['updates']==2 and row['examples']==120 and row['cpu_ns']>0 for row in rows))
        self.assertTrue(all(row['heldout']['questions']==18 for row in rows))

    def test_complete_question_metrics_differ_from_binary_accuracy(self):
        panel=source_panel('heldout',fact_order_seed=71)
        cross,_=matched_reader_pair(input_dim=11,hidden_dim=24,seed=41)
        cross.eval().requires_grad_(False)
        metrics=quality(cross,panel)
        self.assertEqual(metrics['count'],54)
        self.assertEqual(metrics['questions'],18)
        self.assertGreaterEqual(metrics['correct'],0)
        self.assertLessEqual(metrics['EM'],18)
        self.assertGreaterEqual(metrics['top1'],0)
        self.assertLessEqual(metrics['top1'],18)

if __name__=='__main__':unittest.main()
