"""Pure-stdlib checks of the sixfold science report, not pretrained evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from cross_fact_sixfold_review import review, COMPOSITIONS, ARMS, SEEDS


def record(composition):
    return dict(schema='hepta.cross-fact.composition-transfer.cpu.v1',
        heldout_composition=list(composition),production_authorized=False,
        pretrained_improvement_established=False,encoder_pretrained=False,
        model_selection_permitted=False,training_graphs=30,heldout_graphs=6,
        heldout_rows=54,train_rows=270,updates_per_arm=800,batch_size=64,
        seed_results=[dict(seed=seed,parameter_count=17402,
          added_adapter_parameters=2304,schedule_sha256='a'*64,
          arms={name:dict(completed_updates=800,exposures=51200,
            cpu_ns=10,optimizer_tensor_bytes=100,
            heldout=dict(correct=36,complete_questions=0,total=54,
              questions=18,positive_f1=0.,brier=.3)) for name in ARMS})
          for seed in SEEDS])


class SixfoldReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.files=[]
        for i,p in enumerate(COMPOSITIONS):
            name=self.root/f'{i}.json'
            name.write_text(json.dumps(record(p)))
            self.files.append(name)

    def test_all_folds_retained_without_a_winner(self):
        result=review(self.files)
        self.assertEqual(result['candidate_observations'],972)
        self.assertEqual(result['totals']['cross_fact']['correct'],648)
        self.assertEqual(result['totals']['local']['correct'],648)
        self.assertEqual(len(result['folds']),6)
        self.assertFalse(result['production_authorized'])
        self.assertFalse(result['selected_model'])

    def test_duplicate_fold_and_missing_composition_fail(self):
        with self.assertRaisesRegex(ValueError,'six complete'):
            review(self.files[:-1])
        with self.assertRaisesRegex(ValueError,'missing or repeated'):
            review(self.files[:5]+[self.files[0]])

    def test_forged_production_acceptance_rejected(self):
        value=record(COMPOSITIONS[0]);value['production_authorized']=True
        self.files[0].write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'incompatible experimental'):
            review(self.files)

    def test_different_optimizer_state_denied(self):
        value=record(COMPOSITIONS[0]);value['seed_results'][0]['arms']['local']['optimizer_tensor_bytes']=99
        self.files[0].write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'unequal optimizer'):
            review(self.files)

if __name__=='__main__':unittest.main()
