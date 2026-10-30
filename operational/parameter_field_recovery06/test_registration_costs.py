"""Synthetic execution06 registration/accounting checks; no real import or science."""

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
from operational.parameter_field_recovery06 import historical_costs as costs
from operational.parameter_field_recovery06 import registration as driver
from operational.parameter_field_recovery06 import execution05_costs as failed05
from operational.parameter_field_recovery06.test_execution05_costs import fixture as failed05_fixture
from experiments.parameter_field_fullstudy_20261029 import register_followups_v2 as helper
from experiments.parameter_field_fullstudy_20261029 import report_results as report


def saved(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(driver.encode(value))
    return costs.descriptor(path)


def cost_fixture(root):
    config = saved(root / 'fullstudy_execution04_ops/registrations/initial/PIPELINE_CONFIG.json', {'synthetic': True})
    imported = saved(root / 'SYNTHETIC_IMPORT.json', {'schema': 'hepta.execution06.a17-import.1',
        'complete': True, 'imported': True, 'executed_here': False, 'seed': 17,
        'source_episode': costs.SOURCE_EPISODE, 'target_episode': costs.TARGET_EPISODE,
        'scientific_cost_owner': costs.SOURCE_EPISODE + ':A-17', 'new_scheduled_gradient_microsteps': 0,
        'fresh_raw': str(root / 'fullstudy_execution06_durable_raw'), 'anchors': {'config': config,
        'scientific_complete': saved(root / 'ORIGINAL_A17_SYNTHETIC.json', {'synthetic_only': True})}})
    failure = saved(root / 'fullstudy_execution04_durable_raw/stage_A/seed-29/FAILED.json', {
        'complete': False, 'error_type': 'MemoryError',
        'message': 'Registered cgroup margin/pending-growth reserve exhausted',
        'partial_evidence_preserved': True, 'costs': {'scheduled_gradient_microsteps': 14784,
        'gradient_backward_calls': 14784, 'optimizer_steps': 13728},
        'cpu_seconds': 1270.1102759120001, 'wall_seconds': 675.1297257020015})
    outer = saved(root / 'fullstudy_execution04_ops/wait4_launcher/WAIT4_COMPLETE.json', {
        'schema': 'hepta.fullstudy.execution04-outer-wait4.1', 'config': config, 'exit_code': 1,
        'total_cpu_seconds_inclusive': 3290.208896, 'user_cpu_seconds': 3290.0, 'system_cpu_seconds': 0.208896,
        'launcher_cpu_seconds_separate': .002, 'child_identity': {'pid': 100, 'start_ticks': '1000'},
        'do_not_add_nested_science_driver_archive_or_supervisor_ledgers': True,
        'unwaited_orphan_costs_unknown_if_failure': True})
    # Use the same arithmetic as the real wait4 writer, avoiding decimal rounding assumptions.
    value=costs.read(outer['path'])
    value['total_cpu_seconds_inclusive']=value['user_cpu_seconds']+value['system_cpu_seconds']
    outer=saved(Path(outer['path']),value)
    root_dir = root / 'fullstudy_execution04_ops/root_steps/synthetic_step'
    io = saved(root_dir / 'WAIT4.json', {
        'schema': 'hepta.execution04.root-engineering-wait4.1', 'complete': True,
        'intent': saved(root_dir / 'INTENT.json', {'synthetic': True}),
        'stdout': saved(root_dir / 'helper.stdout.log', {'synthetic': True}),
        'stderr': saved(root_dir / 'helper.stderr.log', {'synthetic': True}),
        'child': {'exit_code': 1, 'identity': {'pid': 200, 'start_ticks': '2000'},
            'total_cpu_seconds': 3., 'user_cpu_seconds': 2., 'system_cpu_seconds': 1.,
            'unwaited_orphan_costs_unknown_if_failure': True},
        'measuring_parent_cpu_seconds': .25, 'command_success': False,
        'scope': 'Local helper and waited descendants; excludes remote service compute and other root commands'})
    facts = {'schema': costs.FACT_SCHEMA, 'execution_episode': costs.SOURCE_EPISODE,
        'accounted_in_execution_episode': costs.TARGET_EPISODE, 'a29_failed': failure,
        'outer_envelope': outer, 'import_receipt': imported,
        'root_io': [{'receipt': io, 'scope': 'independent_root_step'}], 'unknown_additional_work': True}
    return facts, config


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
        self.facts, old_config = cost_fixture(self.root)
        for name, value in (('WORK_ROOT', self.root), ('A29_FAILURE_SHA', self.facts['a29_failed']['sha256']),
                            ('OLD_CONFIG_SHA', old_config['sha256'])):
            patch.object(costs, name, value).start()
        self.facts_item = saved(self.root / 'SYNTHETIC_EXECUTION04_FACTS.json', self.facts)
        producer = saved(self.root / 'SYNTHETIC_PRODUCER_CONFIG.json', {
            'schema': costs.PRODUCER_CONFIG_SCHEMA, 'execution_episode': costs.TARGET_EPISODE,
            'producer_map': saved(self.root / 'SYNTHETIC_MAP.json', {'synthetic': True}),
            'import_receipt': self.facts['import_receipt'], 'fresh_registration': {}})
        self.failed05 = failed05_fixture(self.root, self.facts['import_receipt'])
        patch.object(failed05, 'BASE', self.root).start()
        patch.object(failed05, 'KNOWN', self.failed05['known']).start()
        self.config.update({'execution04_cost_facts': self.facts_item, 'producer_config': producer,
            'execution05_cost_facts': self.failed05['facts_descriptor'],
            'execution05_costs_source': costs.descriptor(Path(failed05.__file__).resolve())})
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
            self.assertEqual(prior['pre_execution04_gradient_microsteps_lower_bound'], 182096)
            self.assertEqual(prior['gradient_microsteps_known_lower_bound'], 214160)
            self.assertEqual(report.prior_costs(spec), prior)
            self.assertEqual(prior['engineering_receipts'], [])
            self.assertEqual(len(prior['failed_attempts']), 5)
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
            self.assertEqual(result['all_attempts_gradient_microsteps_known_lower_bound'], 214401)
            ledger = result['nonoverlapping_cost_ledger']
            self.assertEqual(ledger['a17_current_scientific_rows'], 1)
            self.assertEqual(ledger['a17_failed_increment_rows'], 0)
            self.assertAlmostEqual(ledger['known_disjoint_cpu_seconds_lower_bound'], 10. + 1270.1102759120001 + .002 + 3.25 + 1555.961190367)
            self.assertFalse(ledger['inclusive_cpu_observations_not_added'][0]['included_in_disjoint_cpu_sum'])
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


    def test_actual_failed_receipt_tamper_and_wrong_import_rejected(self):
        self.assertEqual(costs.execution04_cost_plan(self.facts_item, self.facts['import_receipt'])['a29_failure']['costs']['scheduled_gradient_microsteps'], 14784)
        failure = Path(self.facts['a29_failed']['path'])
        failure.write_bytes(failure.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            costs.execution04_cost_plan(self.facts_item, self.facts['import_receipt'])
        failure.write_bytes(failure.read_bytes()[:-1])
        other = saved(self.root / 'OTHER_IMPORT.json', {'synthetic': True})
        with self.assertRaisesRegex(ValueError, 'registered A17 import'):
            costs.execution04_cost_plan(self.facts_item, other)

    def test_completed_or_resumed_ancestry_cannot_be_presented_as_failed_a29(self):
        changed = deepcopy(self.facts)
        changed['a29_failed'] = self.facts['import_receipt']
        with self.assertRaisesRegex(ValueError, 'fixed failed'):
            costs.execution04_cost_plan(saved(self.root / 'WRONG_FACTS.json', changed), self.facts['import_receipt'])
        imported = costs.read(self.facts['import_receipt']['path'])
        imported['executed_here'] = True
        changed = deepcopy(self.facts)
        changed['import_receipt'] = saved(self.root / 'EXECUTED_IMPORT.json', imported)
        with self.assertRaisesRegex(ValueError, 'closed imported'):
            costs.execution04_cost_plan(saved(self.root / 'WRONG_FACTS.json', changed), changed['import_receipt'])

    def test_disjoint_root_receipts_keep_failed_command_cpu_and_reject_duplicates(self):
        plan = costs.execution04_cost_plan(self.facts_item, self.facts['import_receipt'])
        self.assertEqual(plan['root_io_rows'][0]['disjoint_cpu_seconds_lower_bound'], 3.25)
        self.assertFalse(plan['root_io_rows'][0]['command_success'])
        changed = deepcopy(self.facts)
        changed['root_io'].append(deepcopy(changed['root_io'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate root IO'):
            costs.execution04_cost_plan(saved(self.root / 'DUPLICATE_FACTS.json', changed), self.facts['import_receipt'])
        changed['root_io'] = []
        plan = costs.execution04_cost_plan(saved(self.root / 'EMPTY_IO_FACTS.json', changed), self.facts['import_receipt'])
        self.assertEqual(plan['root_io_rows'], [])
        self.assertTrue(plan['unknown_scopes'])

    def test_root_readback_location_and_same_child_identity_are_scoped(self):
        original = costs.read(self.facts['root_io'][0]['receipt']['path'])
        directory = self.root / 'continuation_recovery_20261030/current_readiness_0253/root_archive_io/01_A-17/readback_steps/000'
        duplicate = deepcopy(original)
        duplicate['child']['identity']['state'] = 'R'  # Different dictionary, same PID/start ticks.
        for key in ('intent', 'stdout', 'stderr'):
            duplicate[key] = saved(directory / Path(original[key]['path']).name, {'synthetic': True})
        item = saved(directory / 'WAIT4.json', duplicate)
        changed = deepcopy(self.facts)
        changed['root_io'] = [{'receipt': item, 'scope': 'independent_root_step'}]
        self.assertEqual(len(costs.execution04_cost_plan(saved(self.root / 'READBACK_FACTS.json', changed), self.facts['import_receipt'])['root_io_rows']), 1)
        changed['root_io'].append(self.facts['root_io'][0])
        with self.assertRaisesRegex(ValueError, 'Duplicate or nested'):
            costs.execution04_cost_plan(saved(self.root / 'DUPLICATE_CHILD_FACTS.json', changed), self.facts['import_receipt'])
        duplicate['child']['identity'] = {'pid': 100, 'start_ticks': '1000', 'state': 'R'}
        changed['root_io'] = [{'receipt': saved(directory / 'WAIT4.json', duplicate), 'scope': 'independent_root_step'}]
        with self.assertRaisesRegex(ValueError, 'Duplicate or nested'):
            costs.execution04_cost_plan(saved(self.root / 'NESTED_FACTS.json', changed), self.facts['import_receipt'])
        changed['root_io'] = [{'receipt': saved(self.root / 'unregistered/WAIT4.json', duplicate), 'scope': 'independent_root_step'}]
        with self.assertRaisesRegex(ValueError, 'registered execution04 locations'):
            costs.execution04_cost_plan(saved(self.root / 'OUTSIDE_FACTS.json', changed), self.facts['import_receipt'])

    def test_failure_projection_skips_outcome_numbers_and_unknown_fields_refuse(self):
        path = Path(self.facts['a29_failed']['path'])
        source = path.read_text().rstrip().rstrip('}')
        path.write_text(source + ', "unused_outcome": ' + '9' * 5000 + '}')
        changed = deepcopy(self.facts)
        changed['a29_failed'] = costs.descriptor(path)
        with patch.object(costs, 'A29_FAILURE_SHA', changed['a29_failed']['sha256']):
            plan = costs.execution04_cost_plan(saved(self.root / 'LARGE_UNSELECTED_FACTS.json', changed), self.facts['import_receipt'])
        self.assertNotIn('unused_outcome', plan['a29_failure'])
        changed['new_threshold'] = 1
        with self.assertRaisesRegex(ValueError, 'cost facts contract'):
            costs.execution04_cost_plan(saved(self.root / 'EXTRA_KEYS_FACTS.json', changed), self.facts['import_receipt'])

    def test_scoped_cost_functions_survive_the_private_report_factory(self):
        spec = self.inputs()
        original = (report.prior_costs, report.cost_rows, report.render)
        with costs.apply_cost_adapter(spec):
            copied = driver.producer_adapter.isolated_module(report, SimpleNamespace())
            self.assertIsNot(copied.__dict__, report.__dict__)
            self.assertEqual(copied.prior_costs(spec)['gradient_microsteps_known_lower_bound'], 214160)
            self.assertIs(copied.cost_rows, report.cost_rows)
        self.assertEqual((report.prior_costs, report.cost_rows, report.render), original)
        self.assertEqual(copied.prior_costs(spec)['gradient_microsteps_known_lower_bound'], 214160)
        self.assertNotEqual(copied.prior_costs, report.prior_costs)

    def test_nonfinite_cpu_never_enters_a_lower_bound(self):
        record = costs.read(self.facts['outer_envelope']['path'])
        record['launcher_cpu_seconds_separate'] = float('inf')
        path = Path(self.facts['outer_envelope']['path'])
        path.write_text(json.dumps(record))
        changed = deepcopy(self.facts)
        changed['outer_envelope'] = costs.descriptor(path)
        with self.assertRaisesRegex(ValueError, 'Invalid nonnegative'):
            costs.execution04_cost_plan(saved(self.root / 'NONFINITE_FACTS.json', changed), self.facts['import_receipt'])


class RegistrationConfigurationChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='execution06-registration-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        change = patch.object(driver, 'WORK_ROOT', self.root)
        change.start()
        self.addCleanup(change.stop)
        raw = self.root / 'fullstudy_execution06_durable_raw'
        raw.mkdir()
        assets = self.root / 'assets'
        assets.mkdir()
        source = driver.SOURCE_ROOT
        commit = 'abcde12345' * 4
        profile = saved(self.root / 'PROFILE.json', {'synthetic': True})
        freeze = saved(self.root / 'A_FREEZE.json', {'synthetic': True})
        self.fresh = {'execution_episode': driver.EPISODE, 'raw_root': str(raw), 'source_root': str(source),
            'registered_commit': commit, 'protocol_sha256': '1' * 64, 'runtime_sha256': '2' * 64,
            'source_freeze': freeze, 'profile': profile}
        self.producer = {'schema': costs.PRODUCER_CONFIG_SCHEMA, 'execution_episode': driver.EPISODE,
            'producer_map': saved(self.root / 'MAP.json', {'synthetic': True}),
            'import_receipt': saved(self.root / 'IMPORT.json', {'synthetic': True}), 'fresh_registration': self.fresh}
        self.config = {'schema': driver.SCHEMA, 'execution_episode': driver.EPISODE, 'source_root': str(source),
            'source_git_root': str(source), 'source_commit': commit, 'raw_root': str(raw),
            'registrations_root': str(self.root / 'fullstudy_execution06_ops/registrations'), 'assets': str(assets),
            'analysis_id': driver.ANALYSIS_ID, 'amendment': profile, 'a_freeze': freeze,
            'c_freeze': freeze, 'controller_freeze': freeze, 'historical_inputs': freeze,
            'initial_queue': saved(self.root / 'QUEUE.json', {'schema': 'hepta.fullstudy.queue.2',
                'attempt_id': 'attempt02', 'finalize': False,
                'jobs': [{'id': job, 'requires': driver.exact_requires(job)} for job in driver.ORDER[:4]]}),
            'driver_source': costs.descriptor(Path(driver.__file__).resolve()),
            'history_adapter_source': costs.descriptor(Path(costs.__file__).resolve()),
            'producer_adapter_source': costs.descriptor(Path(driver.producer_adapter.__file__).resolve()),
            'producer_config': saved(self.root / 'PRODUCER_CONFIG.json', self.producer),
            'execution04_cost_facts': saved(self.root / 'FACTS.json', {'synthetic': True}),
            'execution05_cost_facts': saved(self.root / 'FACTS05.json', {'synthetic': True}),
            'execution05_costs_source': costs.descriptor(Path(failed05.__file__).resolve()),
            'helper_pins': {name: costs.descriptor(source / 'experiments/parameter_field_fullstudy_20261029' / name)
                            for name in driver.HELPER_SHA}}
        self.item = saved(self.root / 'CONFIG.json', self.config)

    def test_exact_episode_paths_and_external_config_hash(self):
        self.assertEqual(driver.load_config(self.item['path'], self.item['sha256']), (self.config, self.item))
        with self.assertRaisesRegex(ValueError, 'config SHA'):
            driver.load_config(self.item['path'], '0' * 64)
        changed = deepcopy(self.config)
        changed['raw_root'] = str(self.root / 'fullstudy_execution04_durable_raw')
        item = saved(self.root / 'WRONG_CONFIG.json', changed)
        with self.assertRaisesRegex(ValueError, 'execution06 RAW'):
            driver.load_config(item['path'], item['sha256'])
        changed = deepcopy(self.config)
        changed['analysis_id'] = 'analysis02'
        item = saved(self.root / 'WRONG_CONFIG.json', changed)
        with self.assertRaisesRegex(ValueError, 'analysis identity'):
            driver.load_config(item['path'], item['sha256'])

    def test_producer_configuration_rejects_old_profile_and_unregistered_fields(self):
        self.assertEqual(driver.producer_configuration(self.config), self.producer)
        wrong = deepcopy(self.producer)
        wrong['fresh_registration']['profile'] = self.config['a_freeze']
        changed = {**self.config, 'producer_config': saved(self.root / 'WRONG_PRODUCER.json', wrong)}
        with self.assertRaisesRegex(ValueError, 'Fresh producer registration differs'):
            driver.producer_configuration(changed)
        wrong = deepcopy(self.producer)
        wrong['implicit_resume'] = True
        changed['producer_config'] = saved(self.root / 'WRONG_PRODUCER.json', wrong)
        with self.assertRaisesRegex(ValueError, 'producer configuration contract'):
            driver.producer_configuration(changed)

    def test_helpers_use_isolated_factories_and_commit_new_adapter_sources(self):
        summary = __import__('importlib').import_module(driver.PACKAGE + 'register_summary_v2')
        sentinel_a, sentinel_b = object(), object()
        factory = SimpleNamespace(for_followups=lambda module: sentinel_a if module is helper else None,
                                  for_summary=lambda module: sentinel_b if module is summary else None)
        before = (helper.register, summary.register)
        with patch.object(driver, 'configured_producer', return_value=factory):
            with patch.object(helper, 'committed_sources') as committed:
                self.assertEqual(driver.helpers(self.config), (sentinel_a, sentinel_b))
                files = committed.call_args.args[2]
                self.assertEqual(set(files), {'operational/parameter_field_recovery06/' + name
                    for name in ('registration.py', 'historical_costs.py', 'producer_adapter.py', 'execution05_costs.py')})
        self.assertEqual((helper.register, summary.register), before)



if __name__ == '__main__':
    wall, cpu = time.monotonic(), time.process_time()
    run = unittest.main(exit=False, verbosity=2)
    forbidden = [name for name in ('torch', 'numpy') if name in sys.modules]
    print(json.dumps({'synthetic_only': True, 'tests': run.result.testsRun, 'success': run.result.wasSuccessful(),
        'forbidden_scientific_imports': forbidden, 'science_workers_started': 0,
        'own_wall_seconds': time.monotonic() - wall, 'own_cpu_seconds': time.process_time() - cpu,
        'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}, sort_keys=True))
    raise SystemExit(0 if run.result.wasSuccessful() and not forbidden else 1)
