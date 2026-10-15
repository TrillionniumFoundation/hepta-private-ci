"""Cheap synthetic transfer tests; no pretrained model or validation optimization."""
import unittest
import torch
from cross_fact_composition_transfer import (
    source_panel, checked_panels, HELD_OUT_COMPOSITION, PERMUTATIONS, run,
)


class CompositionTransferTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.train=source_panel('train',fact_order_seed=17)
        self.heldout=source_panel('heldout',fact_order_seed=71)

    def test_strict_nonoverlapping_semantic_composition(self):
        checked_panels(self.train,self.heldout)
        self.assertEqual(len(set(self.train['graph_ids'])),30)
        self.assertEqual(len(set(self.heldout['graph_ids'])),6)
        self.assertEqual(set(self.heldout['composition_ids']),{HELD_OUT_COMPOSITION})
        self.assertEqual(len(set(self.train['composition_ids'])),5)
        self.assertEqual(set(self.train['composition_ids'])|set(self.heldout['composition_ids']),set(PERMUTATIONS))
        self.assertFalse(set(self.train['graph_ids'])&set(self.heldout['graph_ids']))

    def test_exact_two_hop_truth_from_original_edges(self):
        for panel in (self.train,self.heldout):
            (facts,questions,candidates,*masks),truth=panel['features'],panel['labels']
            self.assertTrue(all(x.all() for x in masks))
            for i in range(len(truth)):
                owns,stores={},{}
                for fact in facts[i,:,0,:]:
                    if fact[0]==1:
                        owns[int(fact[2:5].argmax())]=int(fact[5:8].argmax())
                    else:
                        stores[int(fact[5:8].argmax())]=int(fact[8:11].argmax())
                obj=int(questions[i,0,2:5].argmax())
                color=int(candidates[i,0,8:11].argmax())
                self.assertEqual(int(truth[i]),int(color==stores[owns[obj]]))

    def test_fresh_shuffle_preserves_truth_and_changes_feature_order(self):
        x=source_panel('heldout',fact_order_seed=71)
        y=source_panel('heldout',fact_order_seed=71)
        z=source_panel('heldout',fact_order_seed=72)
        self.assertTrue(torch.equal(x['features'][0],y['features'][0]))
        self.assertTrue(torch.equal(x['labels'],z['labels']))
        self.assertFalse(torch.equal(x['features'][0],z['features'][0]))

    def test_corrupt_composition_roster_denied(self):
        damaged=dict(self.heldout,composition_ids=self.heldout['composition_ids'][:-1])
        with self.assertRaises(ValueError):
            checked_panels(self.train,damaged)
        with self.assertRaises(ValueError):
            source_panel('test',fact_order_seed=71)

    def test_actual_three_step_cpu_training_stays_non_authorizing(self):
        observation=run(updates=3)
        self.assertFalse(observation['model_selection_permitted'])
        self.assertFalse(observation['production_authorized'])
        self.assertEqual(len(observation['seed_results']),3)
        for seed in observation['seed_results']:
            self.assertEqual(seed['arms']['cross_fact']['completed_updates'],3)
            self.assertEqual(seed['arms']['local']['completed_updates'],3)
            self.assertEqual(seed['arms']['cross_fact']['optimizer_tensor_bytes'],
                             seed['arms']['local']['optimizer_tensor_bytes'])
            self.assertGreater(seed['arms']['cross_fact']['cpu_ns'],0)
            self.assertEqual(seed['arms']['cross_fact']['exposures'],3*64)
            self.assertEqual(seed['arms']['local']['exposures'],3*64)

if __name__=='__main__':unittest.main()
