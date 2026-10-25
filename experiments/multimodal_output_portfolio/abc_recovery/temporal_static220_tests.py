"""Small mathematical fixtures; no original evaluation files or media are read."""

import copy
import unittest

from .temporal_static220 import FRAME, POLICIES, RATE, bind_environment_to_pinned_trace, descriptive_statistics, fixed_schedule


def fixture_events():
    events = []
    for index in range(4):
        for channel in ('video', 'audio'):
            release = (index + 1) * FRAME
            if channel == 'audio':
                release = min(release, 6084)
            delay = 220 if (index, channel) in ((0, 'video'), (3, 'audio')) else 20
            dropped = (index, channel) == (1, 'audio')
            events.append({'channel': channel, 'index': index, 'source_pts_ticks': index * FRAME,
                           'release_ticks': release, 'environment_dropped': dropped,
                           'arrival_ticks': None if dropped else release + delay * RATE // 1000})
    return events


class Static220Fixtures(unittest.TestCase):
    def test_exact_boundary_drop_backlog_and_partial_audio_grid(self):
        old = fixed_schedule(fixture_events(), 240, frame_count=4, audio_samples=6084)
        new = fixed_schedule(fixture_events(), 220, frame_count=4, audio_samples=6084)
        self.assertEqual(old['commit_ticks'], [11466, 14112, 14112, 15876])
        self.assertEqual(new['commit_ticks'], [11466, 13230, 13230, 15876])
        self.assertEqual(old['delivered'], {'video': [True] * 4, 'audio': [True, False, True, True]})
        self.assertEqual(new['delivered'], old['delivered'])
        self.assertAlmostEqual(old['mean_simulated_delivery_latency_seconds'], .215)
        self.assertAlmostEqual(new['mean_simulated_delivery_latency_seconds'], .205)
        self.assertAlmostEqual(old['q_audio'], 4320 / 6084)
        self.assertAlmostEqual(old['loss'] - new['loss'], 1 / 120)

    def test_reject_out_of_support_duplicate_or_unregistered_timeout(self):
        invalid = fixture_events()
        invalid[0]['arrival_ticks'] += 1
        with self.assertRaises(ValueError):
            fixed_schedule(invalid, 220, frame_count=4, audio_samples=6084)
        with self.assertRaises(ValueError):
            fixed_schedule(fixture_events() + [fixture_events()[0]], 220, frame_count=4, audio_samples=6084)
        with self.assertRaises(ValueError):
            fixed_schedule(fixture_events(), 200, frame_count=4, audio_samples=6084)

    def test_240_actions_do_not_identify_arrivals_but_pinned_headers_do(self):
        original = fixture_events()
        keys = ('channel', 'index', 'source_pts_ticks', 'release_ticks', 'arrival_ticks')
        headers = [[event[key] for key in keys] for event in original if event['arrival_ticks'] is not None]
        trace = {'public_trace': [{'public_state': {'arrived_headers': headers}}]}
        bind_environment_to_pinned_trace(original, trace)
        altered = copy.deepcopy(original)
        altered[5]['arrival_ticks'] = 3 * FRAME + 200 * RATE // 1000
        original240 = fixed_schedule(original, 240, frame_count=4, audio_samples=6084)
        altered240 = fixed_schedule(altered, 240, frame_count=4, audio_samples=6084)
        self.assertEqual(original240['commit_ticks'], altered240['commit_ticks'])
        self.assertEqual(original240['delivered'], altered240['delivered'])
        self.assertNotEqual(fixed_schedule(original, 220, frame_count=4, audio_samples=6084)['commit_ticks'],
                            fixed_schedule(altered, 220, frame_count=4, audio_samples=6084)['commit_ticks'])
        with self.assertRaises(ValueError):
            bind_environment_to_pinned_trace(altered, trace)

    def test_grouped_census_and_pairing_are_not_expanded_by_replays(self):
        rows = [{'speaker': speaker, 'scenario': scenario, 'policy': policy, 'loss': .1 + speaker * .01,
                 'joint_delivery_completion': .9, 'mean_simulated_delivery_latency_seconds': .1}
                for speaker in (1, 2) for scenario in range(4) for policy in POLICIES]
        result = descriptive_statistics(rows, [1, 2])
        self.assertEqual(result['independent_speaker_groups'], 2)
        self.assertEqual(result['feedback_minus_220_NDU_descriptive_95CI'], [0.0, 0.0])
        with self.assertRaises(ValueError):
            descriptive_statistics(rows + [copy.deepcopy(rows[0])], [1, 2])


if __name__ == '__main__':
    unittest.main()
