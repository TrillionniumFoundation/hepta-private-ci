"""Actual CPU fitting and end-to-end generated integration, not pretrained evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import torch
from four_gate_common import digest, write_once
from fbsde_tracking import make_gate, training_rows, lexical_vector
from fbsde_tracking_feedback import identity
from fbsde_tracking_feedback_study import run
from fbsde_tracking_feedback_audit import audit


class FeedbackTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Preserve the directory even if setUpClass encounters a budget rejection.
        retained = Path('feedback-test-evidence'); retained.mkdir(exist_ok=True)
        cls.root = Path(tempfile.mkdtemp(prefix='run-', dir=retained.resolve()))
        print('FEEDBACK_TEST_EVIDENCE='+str(cls.root), flush=True)
        parent = cls.root/'parent'; parent.mkdir(); torch.set_num_threads(2)
        data=training_rows(); x=torch.tensor([lexical_vector(t) for t,_ in data]); y=torch.tensor([v for _,v in data])
        members=[]
        for seed in (32452843,49979687,67867967):
            torch.manual_seed(seed); m=make_gate(torch); optim=torch.optim.AdamW(m.parameters(),lr=.01)
            for _ in range(160):
                optim.zero_grad(); loss=torch.nn.functional.binary_cross_entropy_with_logits(m(x),y)
                loss.backward(); optim.step()
            members.append(m.eval().requires_grad_(False))
        torch.save([m.state_dict() for m in members],parent/'heads.pt')
        import hashlib
        write_once(parent/'fit.json', {'members':[identity(m) for m in members],
            'training_sha256':digest(data),'heads_bytes_sha256':hashlib.sha256((parent/'heads.pt').read_bytes()).hexdigest(),
            'test_fixture_source':True})
        write_once(parent/'design.json', {'profile':'input_tied_challenge_v1','test_fixture_source':True})
        write_once(parent/'calibration.json', {'temperatures':[{'selected':1.}]*3,'test_fixture_source':True})
        cls.output=cls.root/'run'; cls.report=run(cls.output,parent)

    def mutate(self, name, fn, message):
        p=self.output/(name+'.json'); original=p.read_bytes()
        try:
            obj=json.loads(original);fn(obj);p.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ValueError,message): audit(self.output)
        finally: p.write_bytes(original)

    def test_complete_fit_and_independent_model_arithmetic(self):
        a=audit(self.output)
        self.assertEqual(a['audited_outputs'],2448)
        self.assertTrue(a['frozen_parent_unchanged']);self.assertFalse(a['model_or_planner_imported'])

    def test_same_feedback_and_unmodified_parent(self):
        f=json.loads((self.output/'fit.json').read_text())
        self.assertEqual([j['trainable_parameters'] for j in f['jobs']],[129,6219,129])
        self.assertEqual(len({j['feedback_sha256'] for j in f['jobs']}),1)
        self.assertTrue(all(j['losses'][-1]<j['losses'][0] for j in f['jobs']))

    def test_better_task_scores_do_not_grant_promotion(self):
        self.assertFalse(self.report['risk_certified'])
        self.assertFalse(self.report['production_promotion_permitted'])
        self.assertFalse(self.report['standalone_lifecycle_available'])

    def test_changed_text_rejected(self):
        self.mutate('residual_ndu',lambda o:o[0].update(text='unverified'),'decoded answer')

    def test_calibration_relabelling_rejected(self):
        self.mutate('calibration',lambda o:o['rows'][0].update(pair=[0,1] if o['rows'][0]['pair'] != [0,1] else [1,2]),
                    'calibration label')

    def test_cheaper_comparator_cannot_be_removed(self):
        self.mutate('plan',lambda o:o['arms'].pop('exact_reverse'),'cheaper-control')

    def test_parent_weights_cannot_be_relabelled(self):
        self.mutate('candidate-weights',lambda o:o['base'][0]['value.bias'].__setitem__(0,1e6),'snapshot')

    def test_invented_correct_count_rejected(self):
        self.mutate('results',lambda o:o['summary']['heldout']['residual_ndu'].__setitem__('correct',999),'aggregate')

    def test_feedback_future_split_swap_rejected(self):
        self.mutate('feedback',lambda o:o[0].__setitem__('sequence',-1),'feedback coverage')


if __name__=='__main__': unittest.main()
