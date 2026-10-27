"""Counterexamples verify density improvements cannot override deployment harm."""

import unittest

import numpy as np

from .deployment_selection import decisions, select, summarize


class ProtectedSelectionTests(unittest.TestCase):
    def panel(self, name, table):
        observed = np.array([0]*70+[1]*30+[0]*20+[1]*80)
        targets = np.array([0]*100+[1]*100)
        observed, targets = np.tile(observed, 4), np.tile(targets, 4)
        sources = [f'source-{i//200}' for i in range(len(targets))]
        identities = [str(i) for i in range(len(targets))]
        likelihood = np.asarray(table)[observed]
        posterior = likelihood/likelihood.sum(1, keepdims=True)
        return summarize(name, likelihood, posterior, targets, sources, identities, decisions(posterior))

    def test_better_conditional_density_with_worse_posterior_and_risk_is_rejected(self):
        baseline = self.panel('baseline', [[.5, .1], [.5, .9]])
        candidate = self.panel('coupled', [[.75, .4], [.25, .6]])
        self.assertLess(candidate['means']['conditional_nll'], baseline['means']['conditional_nll'])
        self.assertGreater(candidate['means']['posterior_nll'], baseline['means']['posterior_nll'])
        choice = select([candidate, baseline], 'baseline')
        self.assertEqual(choice['selected'], 'baseline')
        self.assertFalse(choice['admission']['coupled']['eligible'])

    def test_calibrated_joint_prediction_can_be_promoted_without_reducing_map(self):
        baseline = self.panel('baseline', [[.5, .1], [.5, .9]])
        calibrated = self.panel('calibrated', [[.7, .2], [.3, .8]])
        choice = select([baseline, calibrated], 'baseline')
        self.assertEqual(choice['selected'], 'calibrated')
        self.assertEqual(calibrated['means']['map_accuracy'], baseline['means']['map_accuracy'])
        self.assertGreater(calibrated['means']['risk_ce'], baseline['means']['risk_ce'])

    def test_a_better_model_on_a_different_panel_cannot_be_promoted(self):
        baseline = self.panel('baseline', [[.5, .1], [.5, .9]])
        candidate = self.panel('calibrated', [[.7, .2], [.3, .8]])
        candidate['case_sha256'] = 'different measurement panel'
        choice = select([candidate, baseline], 'baseline')
        self.assertEqual(choice['selected'], 'baseline')
        self.assertIn('Validation panels differ', choice['admission']['calibrated']['reasons'])


if __name__ == '__main__':
    unittest.main()
