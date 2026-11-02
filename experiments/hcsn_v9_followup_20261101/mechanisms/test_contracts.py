"""Behavioral service-risk and attribution contracts."""
import unittest
from unittest.mock import patch
import numpy as np
from . import campaign as study


class Contracts(unittest.TestCase):
    def episode(self):
        config = study.old.Config()
        episode = study.old.make_episode(974381, config)
        episode['service_uniform'] = [1.0]*21
        return config, episode

    def test_failed_read_is_charged_and_reveals_nothing(self):
        config, episode = self.episode()
        run = study.rollout(study.FittedAnalytic('original', 1.), 'task_value', episode,
                            config, [.5]*21, forced={0: 'READ', 1: 'STOP'})
        self.assertEqual(run['summary']['reads'], 1)
        self.assertEqual(run['summary']['read_fees'], .04)
        self.assertFalse(run['access'][0]['success'])
        self.assertTrue(all(not p['observed_state']['has_read'] for p in run['predictions']))

    def test_successful_read_reveals_only_arrival_state(self):
        config, episode = self.episode()
        episode['service_uniform'][1] = 0.
        run = study.rollout(study.FittedAnalytic('original', 1.), 'task_value', episode,
                            config, [.5]*21, forced={0: 'READ', 1: 'STOP'})
        obs = run['access'][0]['observed_state_after']
        self.assertTrue(run['access'][0]['success'])
        self.assertEqual(obs['time'], config.dt)
        self.assertEqual(obs['x'], episode['path']['x'][1])
        self.assertEqual(np.argmax(obs['content_probs']), episode['path']['content'][1])

    def test_risk_omission_does_not_change_fixed_schedule_or_outputs(self):
        config, episode = self.episode()
        episode['service_uniform'][1] = 0.
        left = study.rollout(study.FittedAnalytic('original', 1.), 'task_value', episode,
                             config, [.5]*21, True, forced={0: 'READ', 1: 'STOP'})
        right = study.rollout(study.FittedAnalytic('original', 1.), 'task_value', episode,
                              config, [.5]*21, False, forced={0: 'READ', 1: 'STOP'})
        self.assertEqual(left['predictions'], right['predictions'])
        self.assertEqual(left['trace'], right['trace'])
        self.assertEqual(left['access'], right['access'])
        self.assertEqual(left['summary']['net_reward'], right['summary']['net_reward'])

    def test_risk_changes_only_expected_read_gain(self):
        config = study.old.Config()
        obs = study.old.Observation(0., .5, 0., [.2]*5, False)
        detail = {'candidate_values': [{'arrival_tick': 1, 'net_value': .06},
                                       {'arrival_tick': 5, 'net_value': .08}]}
        forecast = [.5]*21
        forecast[5] = .1
        with patch.object(study.old, 'choose_action', return_value=('WAIT', detail)):
            action, actual = study.choose(None, 'task_value', obs, 0, 3, None, None,
                                          config, 1, forecast, True)
        self.assertEqual(action, 'READ')
        self.assertAlmostEqual(actual['candidate_values'][0]['net_value'], .01)
        self.assertAlmostEqual(actual['candidate_values'][1]['net_value'], -.028)
        self.assertEqual(detail['candidate_values'][0]['net_value'], .06)


if __name__ == '__main__':
    unittest.main()
