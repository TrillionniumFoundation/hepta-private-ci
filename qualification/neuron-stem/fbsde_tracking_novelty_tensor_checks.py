"""Executed tensor/whole-study checks with random fixture Heads, not pretrained data."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import torch
from four_gate_common import digest, write_once
from four_gate_capture import tensor_digest
from fbsde_tracking import make_gate, training_rows
from fbsde_tracking_novelty_study import run
from fbsde_tracking_novelty_audit import audit


class NoveltyTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();root=Path(cls.tmp.name);src=root/'base';src.mkdir()
        torch.set_num_threads(2);torch.manual_seed(257)
        heads=[make_gate(torch).state_dict() for _ in range(3)];torch.save(heads,src/'heads.pt')
        write_once(src/'fit.json',{'members':[digest({k:tensor_digest(v) for k,v in h.items()}) for h in heads],
            'heads_bytes_sha256':hashlib.sha256((src/'heads.pt').read_bytes()).hexdigest(),
            'training_sha256':digest(training_rows())})
        write_once(src/'calibration.json',{'temperatures':[{'selected':1.}]*3})
        write_once(src/'design.json',{'profile':'input_tied_challenge_v1','fixture_not_trained_model':True})
        cls.output=root/'study';cls.result=run(cls.output,src)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def mutate(self,name,change,pattern):
        p=self.output/(name+'.json');original=p.read_bytes()
        try:
            data=json.loads(original);change(data);p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,pattern):audit(self.output)
        finally:p.write_bytes(original)

    def test_actual_training_and_full_output_audit(self):
        r=audit(self.output);self.assertEqual(r['outputs'],1560)
        c=json.loads((self.output/'calibration.json').read_text())
        self.assertEqual(c['gate']['parameters'],6)
        self.assertLess(c['gate']['losses'][-1],c['gate']['losses'][0])
        self.assertFalse(r['risk_certificate'])

    def test_fake_temperature_choice_rejected(self):
        self.mutate('calibration',lambda d:d.update(temperature=999),'control selection')

    def test_gate_parameter_change_rejected(self):
        self.mutate('calibration',lambda d:d['gate']['weights'].__setitem__(0,20.),'input binding')

    def test_false_decoded_answer_rejected(self):
        self.mutate('novelty_ndu',lambda d:d[0].update(text='Unverified invented fact.'),'decoded answer')

    def test_forged_overbudget_prediction_rejected(self):
        self.mutate('proposals',lambda d:d[0].update(cpu_ns=100_000_001),'budget failure')

    def test_dropped_cheap_comparator_rejected(self):
        self.mutate('plan',lambda d:d['arms'].pop('uniform_ndu'),'profile/limits')

    def test_changed_conditional_model_identity_rejected(self):
        self.mutate('priors',lambda d:d[0]['problem_ids'].update(novelty=digest('other')),'conditional model identity')

    def test_calibration_has_no_final_template(self):
        r=audit(self.output);self.assertTrue(r['no_calibration_heldout_template_overlap'])
        self.assertEqual(r['heldout_cases'],96)

if __name__=='__main__':unittest.main()
