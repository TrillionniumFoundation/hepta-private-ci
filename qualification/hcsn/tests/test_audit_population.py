"""Coverage and exact saved-checkpoint provenance for trained B audits."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch

TORCH_AVAILABLE = importlib.util.find_spec('torch') is not None
if TORCH_AVAILABLE:
    from ..audit_population import audit, main
    from ..benchmark import atomic_json, run


@unittest.skipUnless(TORCH_AVAILABLE, 'PyTorch not installed')
class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temporary.name)/'smoke.json'
        cls.config = json.loads((Path(__file__).parents[1]/'configs/smoke.json').read_text())
        cls.config.update(models=['population_flux'], seeds=[0, 1], train_steps=1,
                          latency_repeats=1, hidden_size=2, length=4, train_count=4,
                          validation_count=2, test_count=2, batch_size=2)
        cls.report = run(cls.config, cls.path.with_suffix('.runs'))
        if cls.report['accounting']['completed'] != 2:
            raise RuntimeError('real B checkpoint fixture did not train')

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        atomic_json(self.path, self.report)

    def test_actual_saved_weights_forward_buffers_dataset_and_original_mse(self):
        result = audit(self.path)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual((result['requested_b_runs'], result['completed_b_runs'], result['audited_b_runs']), (2, 2, 2))
        for row in result['records']:
            original = next(r for r in self.report['runs'] if r['seed'] == row['seed'])
            self.assertTrue(row['factor_one_forward_exact'])
            self.assertEqual(row['replayed_test_mse'], original['test_mse'])
            self.assertEqual(row['test_split_sha256'], self.report['datasets'][row['task']]['split_sha256'][2])

    def test_copied_report_and_runs_audit_uses_relative_verified_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            relocated = Path(directory)/'copied.json'
            shutil.copytree(self.path.with_suffix('.runs'), relocated.with_suffix('.runs'))
            report = copy.deepcopy(self.report)
            for run in report['runs']:
                run['best_checkpoint'] = '/unavailable/original/location.pt'
            atomic_json(relocated, report)
            result = audit(relocated)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['audited_b_runs'], 2)

    def test_empty_full_audit_retains_twenty_identities_and_exits_nonzero(self):
        config = json.loads((Path(__file__).parents[1]/'configs/full.json').read_text())
        records = [dict(task=t, model=m, seed=s, status='unavailable', reason='CUDA unavailable')
                   for t in config['tasks'] for m in config['models'] if m.startswith('population_flux')
                   for s in config['seeds']]
        atomic_json(self.path, dict(config=config, runs=records))
        output = self.path.with_name('audit.json')
        with patch('sys.argv', ['audit', '--benchmark', str(self.path), '--output', str(output)]):
            self.assertEqual(main(), 2)
        result = json.loads(output.read_text())
        self.assertEqual((result['requested_b_runs'], result['completed_b_runs'], result['audited_b_runs']), (20, 0, 0))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(len(result['records']), 20)
        self.assertTrue(all(r['reason'] == 'CUDA unavailable' for r in result['records']))

    def test_partial_coverage_retains_unavailable_identity(self):
        report = copy.deepcopy(self.report)
        report['runs'][1].update(status='unavailable', reason='injected unavailable')
        atomic_json(self.path, report)
        result = audit(self.path)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual((result['requested_b_runs'], result['completed_b_runs'], result['audited_b_runs']), (2, 1, 1))
        self.assertEqual(result['records'][1]['reason'], 'injected unavailable')

    def test_tampered_seed_dt_split_grid_and_validation_identity_are_rejected(self):
        for field in ('data_seed', 'dt', 'split', 'grid', 'validation', 'seed'):
            with self.subTest(field=field):
                report = copy.deepcopy(self.report)
                if field in {'data_seed', 'dt'}:
                    report['config'][field] += 1
                elif field == 'split':
                    report['datasets']['delayed_recall']['split_sha256'][2] = 'tampered'
                elif field == 'grid':
                    report['runs'][0]['population_discretization']['bins'] += 1
                elif field == 'validation':
                    report['runs'][0]['best_validation_mse'] += 1
                else:
                    # Retain an expected identity but point it at the other seed's
                    # genuine checkpoint and its valid SHA.
                    for key in ('best_checkpoint', 'best_checkpoint_relative', 'best_checkpoint_sha256'):
                        report['runs'][0][key] = report['runs'][1][key]
                atomic_json(self.path, report)
                result = audit(self.path)
                self.assertEqual(result['status'], 'failed')
                self.assertGreater(result['failed_b_audits'], 0)
