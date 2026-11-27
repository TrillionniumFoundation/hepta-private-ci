"""Exact postseal study tests, including forged costs/fields/held-out labels."""

from dataclasses import replace
from fractions import Fraction as Q
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from e12_nonlinear_cert import Law
from e12_continuation_field import fit_head, initial_y, solve_warm
from e12_continuation_study import (
    ARMS, CAL_X0, HELD_X0, TRAIN_X0, _check_splits, _plan_digest,
    _read_training, _verify_warm, propose, score, train,
)
from e12_study import write_once


class LearnedContinuationStudyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = TemporaryDirectory()
        cls.root = Path(cls.dir.name)
        cls.train_file = cls.root / 'train.json'
        cls.blind_file = cls.root / 'blind.json'
        cls.review_file = cls.root / 'review.json'
        cls.train_sha = train(str(cls.train_file))
        cls.blind_sha = propose(str(cls.train_file), cls.train_sha, str(cls.blind_file))
        cls.review_sha = score(str(cls.train_file), cls.train_sha,
                               str(cls.blind_file), cls.blind_sha, str(cls.review_file))

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_true_train_blind_review_closed_loop(self):
        tr = json.loads(self.train_file.read_bytes())
        bd = json.loads(self.blind_file.read_bytes())
        rv = json.loads(self.review_file.read_bytes())
        self.assertEqual(tr['train_only_teacher_solves'], 114)
        self.assertEqual(tr['rows'], 418)
        self.assertEqual(len(bd['cases']), 60)
        self.assertEqual(set(rv['summary']), set(ARMS))
        self.assertEqual(rv['source_groups_held'], 10)
        self.assertEqual(rv['cases_per_arm'], 60)
        self.assertTrue(rv['all_e12_discrete_global_certificates_replayed'])
        self.assertFalse(rv['cost_adjusted_online_reasoning_gain_qualified'])
        self.assertFalse(rv['independent_natural_task_outcomes'])
        self.assertFalse(rv['production_accepted'])
        self.assertEqual(rv['authority'], 'DENY_ALL')

    def test_experiment_rosters_do_not_share_sources(self):
        _check_splits()
        self.assertFalse(set(TRAIN_X0) & set(HELD_X0))
        self.assertFalse(set(CAL_X0) & set(HELD_X0))
        self.assertFalse(set(TRAIN_X0) & set(CAL_X0))
        self.assertEqual(len(HELD_X0), 10)

    def test_neural_is_real_fitted_not_frozen_random_weights(self):
        tr, heads = _read_training(str(self.train_file), self.train_sha)
        self.assertEqual(set(heads), {'constant','linear','neural'})
        self.assertEqual(heads['neural'].updates, tr['rows'] * 80)
        self.assertGreater(heads['neural'].fit_cpu_ns, heads['linear'].fit_cpu_ns)
        self.assertGreater(heads['linear'].fit_cpu_ns, 0)
        self.assertGreater(tr['teacher_cpu_ns'], 0)

    def test_zero_control_and_learned_report_actual_causal_work(self):
        score_doc = json.loads(self.review_file.read_bytes())
        zero, net = score_doc['summary']['zero'], score_doc['summary']['neural']
        self.assertEqual(zero['head_calls'], 0)
        self.assertEqual(net['head_calls'], 220)
        self.assertEqual(net['params_fp64'], 145)
        self.assertEqual(zero['params_fp64'], 0)
        self.assertGreater(net['one_panel_training_plus_inference_cpu_ns'],
                           net['inclusive_cpu_ns'])
        self.assertGreater(zero['cell_updates'], 0)

    def test_training_rejects_same_destination_replay(self):
        with self.assertRaises(FileExistsError):
            train(str(self.train_file))
        with self.assertRaises(FileExistsError):
            propose(str(self.train_file), self.train_sha, str(self.blind_file))
        with self.assertRaises(FileExistsError):
            score(str(self.train_file), self.train_sha,
                  str(self.blind_file), self.blind_sha, str(self.review_file))

    def test_blind_phase_is_forbidden_from_teacher_or_original_operator(self):
        out = self.root / 'blind-without-oracle.json'
        with patch('e12_continuation_study.solve', side_effect=RuntimeError('held leak')), \
             patch('e12_nonlinear_cert.solve', side_effect=RuntimeError('held leak')), \
             patch('e12_nonlinear_cert.operator', side_effect=RuntimeError('held leak')):
            digest = propose(str(self.train_file), self.train_sha, str(out))
        self.assertEqual(sha256(out.read_bytes()).hexdigest(), digest)
        self.assertFalse(json.loads(out.read_bytes())['held_truth_or_reference_accessed'])

    def test_original_training_bytes_change_rejected(self):
        with self.assertRaises(ValueError):
            propose(str(self.train_file), '0' * 64, str(self.root/'forged-sha.json'))

    def test_modified_neural_weights_cannot_pass_independent_refit(self):
        fake = json.loads(self.train_file.read_text())
        fake['heads']['neural']['out_bias'] += 0.3
        path = self.root / 'tampered-weights.json'
        digest = write_once(str(path), fake)
        with self.assertRaises(ValueError):
            score(str(path), digest, str(self.blind_file), self.blind_sha,
                  str(self.root/'bad-scorer.json'))

    def test_injected_held_label_and_authority_fail_closed(self):
        for field, value in [('held_truth_or_reference_accessed', True),
                             ('authority', 'ALLOW'),
                             ('production_accepted', True),
                             ('global_solution_calls', 1),
                             ('secret_human_label', 1)]:
            with self.subTest(field=field):
                fake = json.loads(self.blind_file.read_text())
                fake[field] = value
                path = self.root / ('bad-'+field+'.json')
                digest = write_once(str(path), fake)
                with self.assertRaises(ValueError):
                    score(str(self.train_file), self.train_sha, str(path), digest,
                          str(self.root/('review-'+field+'.json')))

    def test_tamper_residual_z_or_work_is_detected_postseal(self):
        for kind in ('z', 'cost', 'solution', 'rounds'):
            with self.subTest(kind=kind):
                fake = json.loads(self.blind_file.read_text())
                arm = fake['cases'][1]['arms'][3]
                if kind == 'z':
                    arm['candidate']['trace']['z'][0] = '0'
                if kind == 'cost':
                    arm['total_cpu_ns'] = 1
                if kind == 'solution':
                    arm['candidate']['final_y'][0] = '0'
                if kind == 'rounds':
                    arm['candidate']['iterations'] += 1
                path = self.root / ('bad-'+kind+'.json')
                digest = write_once(str(path), fake)
                with self.assertRaises(ValueError):
                    score(str(self.train_file), self.train_sha, str(path), digest,
                          str(self.root/('review-'+kind+'.json')))

    def test_duplicate_reordered_source_and_missing_arm_rejected(self):
        for kind in ('duplicate', 'order', 'missing'):
            with self.subTest(kind=kind):
                fake = json.loads(self.blind_file.read_text())
                if kind == 'duplicate':
                    fake['cases'][1] = fake['cases'][0]
                if kind == 'order':
                    fake['cases'][0], fake['cases'][1] = fake['cases'][1], fake['cases'][0]
                if kind == 'missing':
                    fake['cases'][0]['arms'].pop()
                path = self.root / ('bad-'+kind+'.json')
                digest = write_once(str(path), fake)
                with self.assertRaises(ValueError):
                    score(str(self.train_file), self.train_sha, str(path), digest,
                          str(self.root/('review-'+kind+'.json')))

    def test_stochastic_terminal_modified_but_locally_plausible_fails(self):
        fake = json.loads(self.blind_file.read_text())
        states = fake['cases'][0]['arms'][3]['candidate']['trace']['states']
        states[-1]['y'] = '0'
        path = self.root / 'bad-terminal.json'
        digest = write_once(str(path), fake)
        with self.assertRaises(ValueError):
            score(str(self.train_file), self.train_sha, str(path), digest,
                  str(self.root/'review-bad-terminal.json'))

    def test_modified_study_parameters_rejected(self):
        tr = json.loads(self.train_file.read_text())
        tr['plan_digest'] = '0'*64
        path = self.root / 'wrong-plan.json'
        digest = write_once(str(path), tr)
        with self.assertRaises(ValueError):
            propose(str(path), digest, str(self.root/'wrong-plan-blind.json'))


if __name__ == '__main__':
    import unittest
    unittest.main()
