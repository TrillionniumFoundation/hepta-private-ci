"""P0.4 exact original prelabel/late review and hostile source-material tests."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fabric import Denied, sha
from causal_audit import (ARCHIVES, _load_archive, _read_sealed, _write_private_new,
                          canonical_bytes, produce_unlabeled, review_late_labels,
                          type_from_case_id)

ARCHIVE_ROOT = os.getenv('HDCF_ORIGINAL_ARCHIVE_DIR')


class SourceOnlyCases(unittest.TestCase):
    def test_known_route_is_publisher_id_hash_not_semantic(self):
        self.assertIn(type_from_case_id('literal_id'), ('hash0', 'hash1'))
        with self.assertRaises(Denied):
            type_from_case_id('')
        with self.assertRaises(Denied):
            type_from_case_id('\u4e00')

    def test_producer_refuses_label_archive_open_attempt(self):
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaises(Denied):
                _load_archive(Path(path), 'hdcf-original-targets-bad.zip')

    def test_create_only_private_seal_lifecycle(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root) / 'private'
            parent.mkdir(mode=0o700)
            file = parent / 'seal.json'
            content = canonical_bytes({'x': 2, 'authority': 'DENY_ALL'})
            _write_private_new(file, content)
            self.assertEqual(_read_sealed(file), {'x': 2, 'authority': 'DENY_ALL'})
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(Denied):
                _write_private_new(file, content)

    def test_symlink_seal_denied(self):
        with tempfile.TemporaryDirectory() as root:
            d = Path(root)
            tgt = d / 'genuine'
            tgt.write_bytes(canonical_bytes({'ok': True}))
            (d / 'alias').symlink_to(tgt)
            with self.assertRaises(Denied):
                _read_sealed(d / 'alias')

    def test_noncanonical_prelabel_denied(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'bad.json'
            file.write_bytes(b'{"x":1, "y":2}')
            with self.assertRaises(Denied):
                _read_sealed(file)

    def test_writable_seal_dir_denied(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root).chmod(0o755)
            with self.assertRaises(Denied):
                _write_private_new(Path(root) / 'seal', b'a')

    def test_outer_original_digest_required(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'hdcf-original-features.zip'
            file.write_bytes(b'wrong ZIP bytes')
            with self.assertRaises(Denied):
                _load_archive(Path(root), file.name)


@unittest.skipUnless(ARCHIVE_ROOT, 'requires genuine SHA-bound original GitHub Actions ZIPs')
class RealSourceCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(ARCHIVE_ROOT)
        cls.pre = produce_unlabeled(cls.root)

    def test_all_160_original_predictions_recomputed_and_weights_exact(self):
        self.assertEqual(self.pre['original_predictions_independently_reconstructed'], 160)
        self.assertEqual(self.pre['training_parameter_touches'], {
            'frozen': 0, 'shared_dense': 393728, 'shared_one_touch': 196864,
            'split': 196864, 'swapped': 0,
        })
        self.assertEqual(self.pre['recomputed_weight_hashes']['split'],
                         '6509ed11abbc91c85226c124025ac8157504a1ac7420f9e72fb844698203909d')
        self.assertEqual(self.pre['new_pretrained_forwards'], 0)

    def test_original_zero_feature_intervention_physically_scored(self):
        result = review_late_labels(self.pre, self.root)
        self.assertTrue(result['zero_feature_model_forward_reexecuted_on_reconstructed_head'])
        self.assertEqual(result['split_vs_zero_feature_decision_agreement'], 32)
        self.assertEqual(result['metrics']['zero_features']['correct'], 20)
        self.assertEqual(result['metrics']['type_prior']['correct'], 20)
        self.assertEqual(result['metrics']['split']['correct'], 20)
        self.assertEqual(result['split_vs_prior_decision_agreement'], 32)
        self.assertAlmostEqual(result['split_vs_shared_equal_touch_p_exact'], .5034446716308594)
        self.assertFalse(result['learned_cell_gain_verified'])
        self.assertEqual(result['disposition'], 'HOLD_NO_GO')

    def test_original_outer_tamper_denied(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'hdcf-original-head-trial.zip'
            file.write_bytes((self.root / file.name).read_bytes() + b'TAMPER')
            with self.assertRaises(Denied):
                _load_archive(Path(root), file.name)

    def test_prediction_mutation_rejected_at_late_review(self):
        tampered = copy.deepcopy(self.pre)
        tampered['predictions']['split'][0]['p'] = float('nan')
        with self.assertRaises(Denied):
            review_late_labels(tampered, self.root)

    def test_wrong_case_id_rejected_at_late_review(self):
        tampered = copy.deepcopy(self.pre)
        tampered['predictions']['zero_features'][1]['id'] = 'invented'
        with self.assertRaises(Denied):
            review_late_labels(tampered, self.root)

    def test_two_separate_os_processes_and_payload_seal(self):
        # Deliberately invoke the real producer/reviewer on different processes,
        # with output before any private target archive is opened by producer.
        with tempfile.TemporaryDirectory() as root:
            d = Path(root) / 'private'
            d.mkdir(mode=0o700)
            producer = d / 'pre.json'
            reviewed = d / 'review.json'
            cmd = [sys.executable, str(Path(__file__).with_name('causal_audit.py'))]
            proc = subprocess.run(cmd + ['prelabel', '--archive-dir', str(self.root),
                                         '--output', str(producer)], capture_output=True, text=True,
                                  check=True, timeout=20)
            self.assertEqual(json.loads(proc.stdout)['phase'], 'prelabel')
            self.assertEqual(_read_sealed(producer), self.pre)
            post = subprocess.run(cmd + ['review', '--archive-dir', str(self.root),
                                          '--prelabel', str(producer), '--output', str(reviewed)],
                                  capture_output=True, text=True, check=True, timeout=20)
            self.assertEqual(json.loads(post.stdout)['phase'], 'review')
            receipt = _read_sealed(reviewed)
            self.assertEqual(receipt['metrics']['split']['correct'], 20)
            self.assertEqual(receipt['prelabel_seal_sha256'], sha(producer.read_bytes()))
            self.assertEqual(reviewed.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('predictions', receipt)

    def test_forged_seal_rejected_in_separate_reviewer_process(self):
        with tempfile.TemporaryDirectory() as root:
            d = Path(root) / 'private'; d.mkdir(mode=0o700)
            pre = d / 'pre.json'
            forged = copy.deepcopy(self.pre)
            forged['predictions']['split'][0]['p'] = .456789
            pre.write_bytes(canonical_bytes(forged))
            command = [sys.executable, str(Path(__file__).with_name('causal_audit.py')),
                       'review', '--archive-dir', str(self.root), '--prelabel', str(pre),
                       '--output', str(d / 'new.json')]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse((d / 'new.json').exists())

    def test_producer_opens_no_held_labels(self):
        original = _load_archive
        names = []
        def tracked(path, name):
            names.append(name)
            if name in ('hdcf-original-targets.zip', 'hdcf-original-public.zip'):
                raise AssertionError('label data entered producer')
            return original(path, name)
        with patch('causal_audit._load_archive', side_effect=tracked):
            produce_unlabeled(self.root)
        self.assertEqual(names, ['hdcf-original-features.zip', 'hdcf-original-head-trial.zip'])


if __name__ == '__main__':
    unittest.main()
