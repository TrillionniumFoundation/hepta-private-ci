"""Historical-source checks before any new qualification model call."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from ...continuation_20261027.evidence.data import features as original_features
from ...repair_20261026.evidence.real_audio import DigitObserver as OriginalObserver
from .data import CHECKPOINT
from .encoder import DigitObserver, features
from .models import capture, fit_rank, rank_views, score
from . import run
from .risk import choose


OLD = Path('/workspace/scratch/95988d8d3ab1/ndu-continuation-evidence')


class DeliveryIntegrationTests(unittest.TestCase):
    def test_risk_choice_uses_expected_exponential_of_actual_payoff(self):
        posterior = np.array([.6, .4]+[0.]*8)
        self.assertEqual(choose(posterior, 0), 0)
        self.assertEqual(choose(posterior, 2), 10)
        posterior[:2] = [.9, .1]
        self.assertEqual(choose(posterior, 2), 0)
    def test_original_frozen_encoder_is_bitwise_preserved_on_historical_waveforms(self):
        torch.set_num_threads(1)
        first, second = DigitObserver().eval(), OriginalObserver().eval()
        state = torch.load(CHECKPOINT, map_location='cpu', weights_only=True)
        first.load_state_dict(state)
        second.load_state_dict(state)
        with torch.inference_mode():
            for index in range(4):
                path = OLD/f'source/data/01/0_01_{index}.wav'
                left, right = features(path), original_features(path)
                self.assertTrue(torch.equal(left, right))
                self.assertTrue(torch.equal(first(left[None]), second(right[None])))

    def test_public_only_transcript_roundtrip_matches_joint_probability(self):
        rows = json.loads((OLD/'study-002/observations_fit.json').read_text())
        validation = json.loads((OLD/'study-002/observations_validation.json').read_text())[:32]
        law = fit_rank(rows, 10., 50.)
        cases, captures = [], {}
        for index, row in enumerate(validation):
            event = capture(row)
            captures[event.event_id] = event
            cases.append({'sample_id': str(index), 'events': [event.event_id]*2,
                          'values': rank_views(row)})
        direct, posterior = score(law, [row['values'] for row in cases], [row['target'] for row in validation])
        with tempfile.TemporaryDirectory() as directory, patch.object(run, 'RUN', Path(directory)):
            receipt = run.deliver('historical', law, cases, captures)
            readback = run.readback('historical', cases)
            np.testing.assert_array_equal(readback, posterior.argmax(1))
            self.assertEqual(receipt['rows'], len(validation))
            self.assertEqual(float(direct[:, 2].mean()), float(np.mean(readback == [r['target'] for r in validation])))
            with self.assertRaises(ValueError):
                run.build_state(law, {**cases[0], 'target': validation[0]['target']}, captures, np.full(10, .1))


if __name__ == '__main__':
    unittest.main()
