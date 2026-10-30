"""Bounded synthetic metadata checks; no real training, scoring or old outcomes."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import resource
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE))
from operational.parameter_field_recovery04 import historical_costs as costs
from operational.parameter_field_recovery04 import registration as driver
from experiments.parameter_field_fullstudy_20261029 import register_followups_v2 as helper
from experiments.parameter_field_fullstudy_20261029 import report_results as report


def saved(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(driver.encode(value))
    return costs.descriptor(path)


class CanonicalQueueChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='execution04-synthetic-queue-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.args = SimpleNamespace(root=self.root, assets=self.root, amendment=self.root / 'SYNTHETIC_AMENDMENT.json', amendment_sha256='c' * 64)
        self.initial = {'schema': 'hepta.fullstudy.queue.2', 'attempt_id': 'attempt02', 'finalize': False, 'jobs': []}
        for seed in (17, 29, 43):
            self.initial['jobs'].append(helper.job('A', self.root / 'SYNTHETIC_A_FREEZE.json', 'a' * 64, self.args, [], seed, False))
        public = helper.read(SOURCE / 'experiments/parameter_field_fullstudy_20261029/registrations/QUEUE_ATTEMPT02_DISK_INITIAL.json')
        c = deepcopy(next(row for row in public['jobs'] if row['id'] == 'C'))
        c['argv'][c['argv'].index('--root') + 1] = str(self.root)
        self.initial['jobs'].append(c)
        for row in self.initial['jobs']:
            row['requires'] = driver.exact_requires(row['id'])

    def additions(self):
        result = []
        for phase in ('B', 'W', 'R'):
            for seed in ((None,) if phase == 'W' else (17, 29, 43)):
                result.append(helper.job(phase, self.root / ('SYNTHETIC_' + phase + '.json'), 'b' * 64,
                                         self.args, set(driver.ORDER[:3]), seed, False))
        return result

    def test_original_helper_builds_serial_4_11_14_without_activation(self):
        accepted, additions = deepcopy(self.initial), self.additions()
        original = helper.queue_extension
        with driver.serial_queue_extension(helper):
            eleven = helper.queue_extension(self.initial, additions, self.root, False)
        endpoints = [helper.job(phase, self.root / ('SYNTHETIC_' + phase + '_ENDPOINT.json'), 'd' * 64,
                     self.args, set(driver.ORDER[:11]), None, True) for phase in ('A', 'B', 'C')]
        with driver.serial_queue_extension(helper):
            fourteen = helper.queue_extension(eleven, endpoints, self.root, True)
        self.assertIs(helper.queue_extension, original)
        self.assertEqual(self.initial, accepted)
        self.assertEqual(eleven['jobs'][:4], accepted['jobs'])
        self.assertEqual(fourteen['jobs'][:11], eleven['jobs'])
        for actual, supplied in zip(eleven['jobs'][4:], additions):
            self.assertEqual({k: v for k, v in actual.items() if k != 'requires'},
                             {k: v for k, v in supplied.items() if k != 'requires'})
        for queue in (self.initial, eleven, fourteen):
            driver.validate_canonical_queue(queue)
            for count in range(len(queue['jobs']) + 1):
                done = set(driver.ORDER[:count])
                ready = [row['id'] for row in queue['jobs'] if row['id'] not in done and set(row['requires']) <= done]
                self.assertLessEqual(len(ready), 1)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_dependency_drift_refuses_and_restores_helper(self):
        additions = self.additions()
        additions[0]['requires'] = []
        original = helper.queue_extension
        with self.assertRaisesRegex(ValueError, 'Original helper dependency'):
            with driver.serial_queue_extension(helper):
                helper.queue_extension(self.initial, additions, self.root, False)
        self.assertIs(helper.queue_extension, original)
        weakened = deepcopy(self.initial)
        weakened['jobs'][2]['requires'] = []
        with self.assertRaisesRegex(ValueError, 'serial dependencies'):
            driver.validate_canonical_queue(weakened)


class HistoricalCostChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='execution04-synthetic-history-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.missing = [{'path': str(self.root / ('UNAVAILABLE_ORIGINAL_PREFLIGHT_' + str(i) + '.json')),
                         'bytes': 100 + i, 'sha256': str(i + 1) * 64} for i in range(2)]
        original_failure = saved(self.root / 'SYNTHETIC_PRESERVED_FAILURE.json', {
            'schema': 'hepta.fullstudy.infrastructure-failure.1',
            'known_scheduled_gradient_microsteps_lower_bound': {'attempt01_training_total': 102320}})
        original = {'schema': 'hepta.fullstudy.report-inputs.1', 'engineering_preflights': self.missing,
            'failed_attempts': [{'receipt': original_failure, 'training_microsteps_lower_bound': 102320,
                                 'engineering_microsteps_included': 0, 'unknown_additional_work': True}],
            'integrity': {'historical_exact_regression_gate': 'FAIL -- SYNTHETIC unchanged historical gate'}}
        historical = saved(self.root / 'SYNTHETIC_HISTORY.json', original)
        self.addCleanup(patch.stopall)
        patch.object(costs, 'HISTORY_SHA', historical['sha256']).start()
        summary = saved(self.root / 'SYNTHETIC_PUBLIC_SUMMARY.json', {'schema': 'hepta.fullstudy.engineering-summary.1',
            'preflights': [{'source': item, 'gradient_microsteps': 432, 'unused_outcomes': {'must_not_be_returned': 999}} for item in self.missing]})
        support = saved(self.root / 'SYNTHETIC_SUPPORT.json', {'scope': 'Synthetic test metadata; no work occurred'})
        episodes = []
        for key, amount in costs.EXPECTED_EPISODES.items():
            native = saved(self.root / ('SYNTHETIC_' + key + '.json'), {
                'schema': 'hepta.fullstudy.explicit-historical-cost-facts.1', 'actual_attempt_id': 'synthetic-attempt',
                'execution_episode': 'synthetic-' + key, 'scheduled_microsteps_lower_bound': amount,
                'engineering_microsteps_included': 0, 'unknown_additional_work': True,
                'original_receipt_impersonation': False, 'underlying_evidence_available_now': key == 'episode02',
                'observation_basis': 'Synthetic contract fixture; not an execution receipt', 'supporting_evidence': [support]})
            episodes.append({'key': key, 'native_fact_receipt': native})
        self.config = {'execution_episode': driver.EPISODE, 'history_mode': costs.PROJECTED,
            'historical_inputs': historical, 'historical_summary': summary,
            'missing_preflight_receipts': [{'original_receipt': item, 'gradient_microsteps': 432} for item in self.missing],
            'additional_failed_episodes': episodes, 'history_adapter_source': costs.descriptor(Path(costs.__file__).resolve()),
            'helper_pins': {'report_results.py': costs.descriptor(Path(report.__file__).resolve())}}
        self.config_item = saved(self.root / 'SYNTHETIC_CONFIG.json', self.config)

    def inputs(self):
        plan, original = costs.history_plan(self.config, self.config_item)
        projection = saved(self.root / 'SYNTHETIC_PROJECTION.json', plan)
        return {**original, 'historical_cost_compatibility': {'schema': costs.BINDING_SCHEMA,
            'configuration': self.config_item, 'projection': projection, 'adapter_source': self.config['history_adapter_source']}}

    def test_default_strict_refuses_missing_real_preflight(self):
        self.config.pop('history_mode')
        self.config_item = saved(self.root / 'SYNTHETIC_CONFIG.json', self.config)
        with self.assertRaises((ValueError, FileNotFoundError)):
            costs.history_plan(self.config, self.config_item)

    def test_summary_mismatch_and_duplicate_episode_refuse(self):
        self.config['missing_preflight_receipts'][0]['gradient_microsteps'] = 433
        self.config_item = saved(self.root / 'SYNTHETIC_CONFIG.json', self.config)
        with self.assertRaisesRegex(ValueError, '432-step'):
            costs.history_plan(self.config, self.config_item)
        self.config['missing_preflight_receipts'][0]['gradient_microsteps'] = 432
        self.config['additional_failed_episodes'][1]['key'] = 'episode02'
        self.config_item = saved(self.root / 'SYNTHETIC_CONFIG.json', self.config)
        with self.assertRaisesRegex(ValueError, 'episode population'):
            costs.history_plan(self.config, self.config_item)

    def test_cost_only_parser_skips_unselected_outcome_numbers(self):
        path = self.root / 'SYNTHETIC_LARGE_UNUSED_NUMBER.json'
        path.write_text('{"schema":"hepta.fullstudy.engineering-summary.1","preflights":[],"outcome_number":' + '9' * 5000 + '}')
        self.assertEqual(costs.summary_cost_metadata(path), {'schema': 'hepta.fullstudy.engineering-summary.1', 'preflights': []})

    def test_projection_is_once_and_never_a_fake_complete_receipt(self):
        spec = self.inputs()
        original = (report.prior_costs, report.cost_rows, report.render)
        with costs.apply_cost_adapter(spec):
            prior = report.prior_costs(spec)
            self.assertEqual(prior['gradient_microsteps_known_lower_bound'], 182096)
            self.assertEqual(report.prior_costs(spec), prior)
            self.assertEqual(prior['engineering_receipts'], [])
            self.assertEqual(len(prior['failed_attempts']), 3)
            for row in prior['summary_backed_engineering_projections']:
                self.assertNotIn('complete', row)
                self.assertNotEqual(row['schema'], 'hepta.fullstudy.real-kernel-preflight.1')
                self.assertTrue(row['cannot_reverify_original_preflight'])
            changed = deepcopy(spec)
            changed['integrity']['historical_exact_regression_gate'] = 'PASS'
            with self.assertRaisesRegex(ValueError, 'different report input'):
                report.prior_costs(changed)
        self.assertEqual((report.prior_costs, report.cost_rows, report.render), original)

    def test_current_scientific_ledgers_identical_and_summary_excluded_from_completed(self):
        spec = self.inputs()
        complete, operations = {}, {}
        for phase, amount in [('A', 100), ('B', 40), ('C', 60), ('W', 3), ('R', 20)]:
            key = (phase, None if phase in ('C', 'W') else 17)
            ledger_key = 'work' if phase == 'C' else 'reconstruction_work' if phase == 'R' else 'costs'
            complete[key] = {ledger_key: {'counts': {'scheduled_gradient_microsteps': amount}}, 'wall_seconds': 1., 'cpu_seconds': 2.}
            operations[key] = {'process_peak_rss_bytes': 1234}
        endpoint = {'A': {'scoring_costs': {'scheduled_gradient_microsteps': 7}},
                    'C': {'scoring_work': {'scheduled_gradient_microsteps': 11}}}
        real_fixture_spec = deepcopy(spec)
        real_fixture_spec['engineering_preflights'] = [saved(self.root / ('SYNTHETIC_REAL_SCHEMA_FIXTURE_' + str(i) + '.json'),
            {'schema': 'hepta.fullstudy.real-kernel-preflight.1', 'complete': True,
             'synthetic_fixture_id': i,
             'costs': {'scheduled_gradient_microsteps': 432}, 'wall_seconds': 1.}) for i in range(2)]
        reference = report.cost_rows(complete, operations, endpoint, real_fixture_spec)
        with costs.apply_cost_adapter(spec):
            result = report.cost_rows(complete, operations, endpoint, spec)
            self.assertEqual(result['rows'], reference['rows'][:-2])
            self.assertEqual(result['completed_receipt_gradient_microsteps'], 241)
            self.assertEqual(result['summary_backed_historical_engineering_microsteps'], 864)
            self.assertEqual(result['all_attempts_gradient_microsteps_known_lower_bound'], 182337)
            self.assertTrue(result['unknown_partial_work'])

    def test_adapter_restores_on_failure_and_refuses_nested_use(self):
        spec = self.inputs()
        original = (report.prior_costs, report.cost_rows, report.render)
        with self.assertRaisesRegex(RuntimeError, 'synthetic caller failure'):
            with costs.apply_cost_adapter(spec):
                with self.assertRaisesRegex(ValueError, 'Nested'):
                    with costs.apply_cost_adapter(spec):
                        self.fail('Nested adapter entered')
                raise RuntimeError('synthetic caller failure')
        self.assertEqual((report.prior_costs, report.cost_rows, report.render), original)
        self.assertFalse(hasattr(report, '_durable_historical_cost_adapter'))


if __name__ == '__main__':
    wall, cpu = time.monotonic(), time.process_time()
    run = unittest.main(exit=False, verbosity=2)
    forbidden = [name for name in ('torch', 'numpy') if name in sys.modules]
    print(json.dumps({'synthetic_only': True, 'tests': run.result.testsRun, 'success': run.result.wasSuccessful(),
        'forbidden_scientific_imports': forbidden, 'science_workers_started': 0,
        'own_wall_seconds': time.monotonic() - wall, 'own_cpu_seconds': time.process_time() - cpu,
        'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}, sort_keys=True))
    raise SystemExit(0 if run.result.wasSuccessful() and not forbidden else 1)
