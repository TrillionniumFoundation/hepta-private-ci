"""Actual three tiny-Head fits on simulator data; NOT pretrained qualification."""
import json
from pathlib import Path
import tempfile
import unittest
from fbsde_tracking_challenge_study import run
from fbsde_tracking_tied_audit import audit


class TiedChallengeTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)/'study'
        cls.result=run(cls.root)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def mutate(self,name,change,pattern):
        path=self.root/(name+'.json');raw=path.read_bytes()
        try:
            data=json.loads(raw);change(data);path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,pattern):audit(self.root)
        finally:path.write_bytes(raw)

    def test_original_records_independently_recompute(self):
        result=audit(self.root)
        self.assertEqual(result['audited_outputs'],1440)
        self.assertFalse(result['risk_certificate'])
        self.assertEqual(self.result['summary']['exact_reverse']['correct'],144)

    def test_fit_changes_parameters_and_keeps_small_shared_heads(self):
        fit=json.loads((self.root/'fit.json').read_text())
        self.assertEqual(fit['parameters'],6219)
        self.assertTrue(all(r['final_loss']<r['initial_loss'] for r in fit['jobs']))
        self.assertFalse(self.result['real_pretrained_executed'])

    def test_template_shift_is_not_assumed_correct(self):
        result=audit(self.root)
        self.assertGreater(result['all_members_agree_but_wrong'],0)
        self.assertFalse(self.result['risk_calibrated'])

    def test_relabelled_gold_rejects(self):
        self.mutate('targets',lambda d:d.__setitem__(next(iter(d)),(d[next(iter(d))]+1)%3),'source answer')

    def test_forged_input_tie_rejects(self):
        self.mutate('priors',lambda d:d[0]['keys'].__setitem__(0,'f'*64),'input identity')

    def test_changed_decode_rejects(self):
        self.mutate('tied_ndu',lambda d:d[0].__setitem__('text','unsupported answer'),'decoded')

    def test_fake_cost_rejects(self):
        self.mutate('results',lambda d:d.__setitem__('shared_proposal_cpu_ns',0),'unpaid')

    def test_missing_cheap_control_rejects(self):
        self.mutate('design',lambda d:d['arms'].pop('exact_reverse'),'controls')

    def test_wrong_temperature_rejects(self):
        self.mutate('calibration',lambda d:d['temperatures'][0].__setitem__('selected',4.),'temperature')

if __name__=='__main__':unittest.main()
