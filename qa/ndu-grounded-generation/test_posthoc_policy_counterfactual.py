"""Unit tests for held-out observational mechanism-only counterfactuals."""
import unittest
import torch
from policies import Policies
from posthoc_policy_counterfactual import probe, project_action


class PosthocCounterfactualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prev = torch.get_num_threads()
        torch.set_num_threads(1)
        cls.policy = Policies(seed=41)
        cls.policy.training_metadata = {'fixture_not_train_fitted': True}
        cls.state = [0.0] * 24
        cls.local_penalty = [0.0, 0.2, 0.01, 2.5, 0.2, 0.04]

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.prev)

    def test_original_zero_risk_matches_native_action_and_covariance_is_inert(self):
        native = self.policy.action(self.state, 'ndu', risk_weight=0, seed=13)
        probability, action = project_action(self.policy, self.state, self.local_penalty, 0, 13, True)
        self.assertEqual(action, native['action'])
        self.assertLess(max(abs(x-y) for x,y in zip(probability.tolist(),native['metadata']['action_probs'])),1e-7)
        absent, same_action = project_action(self.policy, self.state, self.local_penalty, 0, 13, False)
        self.assertTrue(torch.equal(probability, absent))
        self.assertEqual(action, same_action)

    def test_nonzero_risk_penalty_changes_distribution_and_low_penalty_exposure(self):
        penalty = [0., 0.1, 0.0, 40.0, 0.0, 0.0]
        with_cov, _ = project_action(self.policy, self.state, penalty, 5, 13, True)
        without_cov, _ = project_action(self.policy, self.state, penalty, 5, 13, False)
        self.assertGreater(float(torch.sum(torch.abs(with_cov - without_cov))),1e-4)
        self.assertLess(float(torch.dot(with_cov,torch.tensor(penalty))),float(torch.dot(without_cov,torch.tensor(penalty))))
        self.assertAlmostEqual(float(with_cov.sum()),1.0,places=6)

    def test_bad_inputs_rejected(self):
        for penalty in ([0.0]*5,[-1.0]*6,[float('nan')]*6):
            with self.assertRaisesRegex(ValueError,'bad recorded'):
                project_action(self.policy,self.state,penalty,0.5,1,True)
        for weight in (-1,float('nan'),float('inf')):
            with self.assertRaisesRegex(ValueError,'risk_weight'):
                project_action(self.policy,self.state,self.local_penalty,weight,1,True)

    def fixture_episode(self):
        native = self.policy.action(self.state,'ndu',risk_weight=0,seed=13)
        return {'method':'ndu','task_id':'fixture-17','score':{'quality':1.0},
                'controls':[{'step':0,'checkpoint_changed':True,'action':native['action'],
                             'extra':{'observed_features':self.state,
                                      'policy':{**native['metadata'],
                                                'local_disagreement_penalty':self.local_penalty}}},
                            {'step':1,'checkpoint_changed':False,'extra':{'policy':{}}}]}

    def test_probe_replays_only_real_checkpoints_and_ignores_score_labels(self):
        episode=self.fixture_episode()
        result=probe(self.policy,[episode,{'method':'base','task_id':'base','controls':[]}],weights=(0,1))
        self.assertEqual(result['original_NDU_checkpoints_replayed'],1)
        self.assertEqual(result['distinct_logged_seeds'],1)
        self.assertEqual(result['weights']['0']['covariance_changed_actions'],0)
        self.assertEqual(result['weights']['0']['mean_covariance_total_variation'],0)
        episode['score']={'quality':0.0,'severe':1.0}
        self.assertEqual(probe(self.policy,[episode],weights=(0,1)),result)

    def test_rejects_nonmatching_frozen_action_or_probabilities(self):
        episode=self.fixture_episode()
        episode['controls'][0]['action']=(episode['controls'][0]['action']+1)%6
        with self.assertRaisesRegex(ValueError,'original frozen action'):
            probe(self.policy,[episode])
        episode=self.fixture_episode()
        episode['controls'][0]['extra']['policy']['action_probs']=[1/6]*6
        with self.assertRaisesRegex(ValueError,'original frozen action'):
            probe(self.policy,[episode])

    def test_empty_ndu_trajectory_rejected(self):
        with self.assertRaisesRegex(ValueError,'no real NDU'):
            probe(self.policy,[{'method':'ndu','task_id':'x','controls':[]}])


if __name__=='__main__':unittest.main()
