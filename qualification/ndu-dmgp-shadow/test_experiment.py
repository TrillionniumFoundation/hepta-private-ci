import unittest
from dataclasses import replace
from statistics import mean
from unittest.mock import patch
from experiment import (ARMS, FREEZE, Prompt, decide, decide_detail, gains, run,
                        training_risk, frozen_training_signals, prompts,
                        independent_synthetic_score)
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

    def test_portfolio_executes_sampled_route_and_records_behavior_propensity(self):
        risk = training_risk()
        result = []
        for i in range(10000, 10100):
            p = Prompt(i, 'simple', 'future')
            chosen, probability = decide_detail('A4', p, risk['simple'])
            self.assertEqual((chosen, probability), decide_detail('A4', p, risk['simple']))
            self.assertGreater(probability, 0)
            self.assertLessEqual(probability, 1)
            result.append(chosen)
        self.assertEqual(set(result), {('text',), ('image',)})

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


    def test_policy_reads_frozen_training_only_not_future_outcome_oracle(self):
        fitted = frozen_training_signals()
        risk = training_risk()
        self.assertEqual({s.context for s in fitted}, {'simple', 'complex'})
        self.assertTrue(all(0 <= i < 10000 for s in fitted for i in s.train_episodes))
        self.assertTrue(all(s.train_episodes for s in fitted))
        # Even for the heldout future cohort, A0-A5 cannot query either the
        # hidden true-gain function or the evaluator during route selection.
        with patch('experiment.gains', side_effect=AssertionError('future oracle leaked')):
            with patch('experiment.independent_synthetic_score',
                       side_effect=AssertionError('future outcome leaked')):
                for arm in ARMS:
                    for prompt in (Prompt(10010, 'simple', 'future'),
                                   Prompt(10011, 'complex', 'future')):
                        actions, prob = decide_detail(arm, prompt, risk[prompt.context])
                        self.assertTrue(set(actions) <= {'text', 'image'})
                        self.assertGreater(prob, 0)

    def test_training_risk_uses_realized_simulator_returns_not_forecast_jitter(self):
        risk = training_risk()
        for context in ('simple', 'complex'):
            samples = tuple(p for p in prompts('train', 80) if p.context == context)
            for j, action in enumerate(('text', 'image')):
                m = mean(independent_synthetic_score(p, (action,)) -
                         independent_synthetic_score(p, ()) for p in samples)
                self.assertAlmostEqual(risk[context].means[j], m, places=12)
            self.assertEqual(risk[context].sample_count, len(samples))
            self.assertTrue(all(p.episode < 10000 for p in samples))


if __name__ == '__main__':
    unittest.main()
