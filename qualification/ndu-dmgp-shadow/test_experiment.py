import unittest
from dataclasses import replace
from experiment import ARMS, FREEZE, Prompt, decide, gains, run, training_risk
from reference import Unavailable

class AblationTests(unittest.TestCase):
    def test_six_distinct_named_ablation_paths(self):
        risk = training_risk()
        p = Prompt(10000, 'simple', 'future')
        q = Prompt(10001, 'complex', 'future')
        for arm in ARMS:
            for row in (p, q):
                result = decide(arm, row, risk[row.context])
                self.assertTrue(set(result) <= {'text', 'image'})
                self.assertEqual(len(result), len(set(result)))
        self.assertEqual(decide('A0', q, risk[q.context]), ('text',))
        self.assertEqual(set(decide('A1', q, risk[q.context])), {'text','image'})
        self.assertEqual(decide('A2', q, risk[q.context]), ('image',))

    def test_reproducible_synthetic_quality_and_pairing(self):
        a, b = run(), run()
        self.assertEqual(tuple(a['arms']), ARMS)
        self.assertFalse(a['neural_decoding'])
        self.assertFalse(a['gpu_benchmark'])
        for arm in ARMS:
            self.assertEqual(a['arms'][arm]['mean_synthetic_quality'],
                             b['arms'][arm]['mean_synthetic_quality'])
            if arm != 'A0':
                self.assertEqual(a['arms'][arm]['paired_cases'], 40)
        self.assertGreater(a['arms']['A5']['mean_synthetic_quality'],
                           a['arms']['A0']['mean_synthetic_quality'])

if __name__ == '__main__':
    unittest.main()
