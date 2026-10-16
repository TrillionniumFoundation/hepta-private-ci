"""Original material-backed replay and adversarial tests. Never substitute synthetic rows."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
from v20_independent_numpy_training import Invalid, audit


class OriginalNumPySGD(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = {}
        for key, env in [('inputs', 'HEPTA_V20_ORIGINAL_INPUTS'),
                         ('report', 'HEPTA_V20_ORIGINAL_REPORT'),
                         ('private', 'HEPTA_V20_ORIGINAL_PRIVATE')]:
            s = os.environ.get(env)
            if not s:
                raise RuntimeError(f'Original V19 evidence required: {env}')
            cls.paths[key] = Path(s)
        cls.public = json.loads(cls.paths['report'].read_text())
        cls.private = json.loads(cls.paths['private'].read_text())

    def test_true_original_1200_updates_and_105_checkpoints(self):
        a = audit(self.paths['inputs'], self.paths['report'], self.paths['private'])
        self.assertEqual(a['independent_optimizer_updates_replayed'], 1200)
        self.assertEqual(a['complete_original_parameter_checkpoints_replayed'], 105)
        self.assertLess(a['max_abs_weight_difference'], 2e-6)
        self.assertLess(a['max_abs_logits_difference'], 2e-5)
        self.assertFalse(a['production_authorized'])
        self.assertEqual(a['decision'], 'NUMPY_SGD_REPLAY_CONSISTENT_NO_PROMOTION')

    def verify_bad(self, public=None, private=None):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / 'report.json'
            original = Path(tmp) / 'private.json'
            report.write_text(json.dumps(public if public is not None else self.public, allow_nan=False))
            original.write_text(json.dumps(private if private is not None else self.private, allow_nan=False))
            with self.assertRaises((Invalid, KeyError, ValueError)):
                audit(self.paths['inputs'], report, original)

    def test_fabricated_model_weight_and_matching_forged_hash(self):
        p = copy.deepcopy(self.private)
        r = p['records'][0]
        r['weight'][0][0] += 0.003
        w = np.asarray(r['weight'], '<f4')
        b = np.asarray(r['bias'], '<f4')
        r['weights_sha256'] = hashlib.sha256(w.tobytes() + b.tobytes()).hexdigest()
        self.verify_bad(private=p)

    def test_fabricated_prediction_and_matching_forged_hash(self):
        p = copy.deepcopy(self.private)
        r = p['records'][0]
        r['logits'][0][0] += 0.003
        z = np.asarray(r['logits'], '<f4')
        r['logit_sha256'] = hashlib.sha256(z.tobytes()).hexdigest()
        self.verify_bad(private=p)

    def test_missing_80_step_full_checkpoint(self):
        p = copy.deepcopy(self.private)
        p['records'] = [r for r in p['records']
                        if not (r['seed'] == 53 and r['kind'] == 'full' and r['budget'] == 80)]
        self.verify_bad(private=p)

    def test_duplicate_checkpoint_identity(self):
        p = copy.deepcopy(self.private)
        p['records'][1]['budget'] = p['records'][0]['budget']
        self.verify_bad(private=p)

    def test_corrupted_original_case_identity(self):
        p = copy.deepcopy(self.private)
        p['records'][0]['case_ids'][0] = 'forged-case'
        self.verify_bad(private=p)

    def test_wrong_replayed_training_cost(self):
        p = copy.deepcopy(self.private)
        p['records'][0]['cumulative_training_cpu_ns'] = 0
        self.verify_bad(private=p)

    def test_misreported_training_budget_choice(self):
        p = copy.deepcopy(self.public)
        p['seeds'][0]['train_only_chosen_budget'] = 80
        self.verify_bad(public=p)

    def test_spoofed_future_observations(self):
        p = copy.deepcopy(self.public)
        p['prospective_window_count'] = 2
        self.verify_bad(public=p)

    def test_spoofed_production_authority(self):
        p = copy.deepcopy(self.public)
        p['model_selection_authorized'] = True
        self.verify_bad(public=p)

    def test_mismatched_calibration_score(self):
        p = copy.deepcopy(self.public)
        p['seeds'][0]['historical_calibration_scores_exploratory']['4']['brier'] = 0.0
        self.verify_bad(public=p)

    def test_missing_original_research_fee(self):
        p = copy.deepcopy(self.public)
        p['seeds'][0]['oof_search_cpu_ns'] = 1
        self.verify_bad(public=p)


if __name__ == '__main__':
    unittest.main()
