import json
import tempfile
import unittest
from pathlib import Path
from paired_trial_replay import run


class ReplayTests(unittest.TestCase):
    def test_four_real_subprocesses_and_two_scoring_windows(self):
        with tempfile.TemporaryDirectory() as d:
            result=run(d,train_count=128,future_count=32)
            self.assertEqual(result['training_pairs_actually_fitted'],384)
            self.assertEqual(set(result['prospective_results']),{'future_1','future_2'})
            self.assertEqual(result['real_pretrained_encoder_forward_count'],0)
            self.assertFalse(result['p3_qualified'])
            self.assertFalse(result['p5_qualified'])
            for window in ('future_1','future_2'):
                self.assertTrue(Path(d,window+'.score.json').is_file())
                self.assertEqual(result['prospective_results'][window]['evaluated_cases'],32)
                self.assertEqual(result['prospective_results'][window]['arms']['exact_tree']['expected_regret_to_exact_tree'],0)
            self.assertTrue(Path(d,'seal.json').is_file())
            self.assertEqual(json.loads(Path(d,'report.json').read_text())['seal_sha256'],result['seal_sha256'])

    def test_reject_non_empty_destination(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'prior.txt').write_text('unchanged')
            with self.assertRaises(ValueError):run(d,train_count=128,future_count=32)

    def test_reject_unbounded_plan(self):
        with tempfile.TemporaryDirectory() as d:
            for a,b in [(8193,32),(128,2001),(0,32),(128,0)]:
                with self.assertRaises(ValueError):run(d,train_count=a,future_count=b)

if __name__=='__main__':unittest.main()
