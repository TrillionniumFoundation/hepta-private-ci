"""Pure public-fusion checks; no corpus, waveform or final outcome is read."""

from dataclasses import replace
import itertools
import unittest

import numpy as np

from .invariance_guard import public_fixed10_guard
from .state import Frame, SENSOR_QUALITY, chunk_text, incorporate, initial_frame
from .tasks import WORDS


def hypothetical_observation(decoded):
    # Hypothetical public category values, not a target or a source-owned cue.
    return {"transcript": " ".join(words[value] for words, value in zip(WORDS, decoded)
                                    if value is not None),
            "mean_word_confidence": .5}


def intended_chunks(frame):
    return (chunk_text(replace(frame, stage=0)), chunk_text(replace(frame, stage=1)))


class InvarianceGuardTests(unittest.TestCase):
    def setUp(self):
        self.frame = incorporate(initial_frame((0, 0, 0), 0),
                                 hypothetical_observation((0, 0, 0)), 1)

    def test_certified_route_matches_real_fusion_for_all_225_decoded_triples(self):
        for template in (0, 1):
            frame = replace(self.frame, template=template)
            decision = public_fixed10_guard(frame)
            self.assertEqual(decision.route, (0, 0))
            self.assertTrue(decision.skip_query_certified)
            self.assertEqual(decision.enumerated_cases_per_fact, (9, 5, 5))
            before = frame.detached()
            cases = 0
            for decoded in itertools.product(*((None, *range(len(words))) for words in WORDS)):
                acquired = incorporate(frame, hypothetical_observation(decoded), 2)
                self.assertEqual(intended_chunks(frame), intended_chunks(acquired))
                cases += 1
            self.assertEqual(cases, 225)
            self.assertEqual(frame.detached(), before)

    def test_conflicting_public_history_retains_fixed10_and_has_real_counterexample(self):
        conflict = incorporate(initial_frame((0, 0, 0), 0),
                               hypothetical_observation((1, 1, 1)), 1)
        decision = public_fixed10_guard(conflict)
        self.assertEqual(decision.route, (1, 0))
        self.assertFalse(decision.skip_query_certified)
        alternatives = [incorporate(conflict, hypothetical_observation(decoded), 2)
                        for decoded in itertools.product(*((None, *range(len(words))) for words in WORDS))]
        self.assertTrue(any(intended_chunks(other) != intended_chunks(conflict) for other in alternatives))

    def test_near_threshold_and_tie_cases_against_actual_fusion(self):
        size = len(WORDS[0])
        quality = .85 * SENSOR_QUALITY[1][0] + .15 / size
        ratio = quality * (size - 1) / (1 - quality)
        ratios = [ratio * (1 - 1e-8), np.nextafter(ratio, -np.inf), ratio,
                  np.nextafter(ratio, np.inf), ratio * (1 + 1e-8)]
        decisions = []
        for candidate in ratios:
            probability = np.array([candidate, 1., *([0.] * (size - 2))])
            probability /= probability.sum()
            frame = replace(self.frame, posterior=(tuple(probability), *self.frame.posterior[1:]))
            decision = public_fixed10_guard(frame)
            decisions.append(decision.skip_query_certified)
            actual_updates = [incorporate(frame, hypothetical_observation((value, None, None)), 2)
                              for value in (None, *range(size))]
            if decision.skip_query_certified:
                self.assertTrue(all(intended_chunks(frame) == intended_chunks(other) for other in actual_updates))
            self.assertEqual(decision.original_winners, frame.values())
        self.assertFalse(decisions[0])
        self.assertTrue(decisions[-1])
        tied = replace(self.frame, posterior=((.5, .5, *([0.] * (size - 2))), *self.frame.posterior[1:]))
        self.assertEqual(public_fixed10_guard(tied).route, (1, 0))
        self.assertGreater(public_fixed10_guard(tied).nonunique_winner_cases, 0)

    def test_wrong_gate_and_nonfinite_public_state_are_rejected(self):
        with self.assertRaises(TypeError):
            public_fixed10_guard(object())
        with self.assertRaises(ValueError):
            public_fixed10_guard(replace(self.frame, stage=1, first_action=1))
        bad = ((float('nan'), *self.frame.posterior[0][1:]), *self.frame.posterior[1:])
        with self.assertRaises(ValueError):
            public_fixed10_guard(replace(self.frame, posterior=bad))


if __name__ == "__main__":
    unittest.main()
