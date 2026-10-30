"""Low-memory execution06 import-probe fixtures; no Torch, model or science run.

The eight real source-pinned factories and installed resource aliases are tested
with an explicitly unvalidated fixture owner. Full CLI control flow uses fake
scientific imports. No synthetic receipt is offered as a real admission proof.
"""

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from operational.parameter_field_recovery06 import import_probe as probe
from operational.parameter_field_recovery06 import resource_backpressure as rb
from operational.parameter_field_recovery06 import producer_adapter, registration, historical_costs


class ImportProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='hepta-probe06-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.raw, self.ops = self.base / 'raw-fixture', self.base / 'ops-fixture'
        self.empty = self.ops / 'empty'
        self.raw.mkdir()
        self.empty.mkdir(parents=True)
        (self.raw / 'imported-metadata.txt').write_text('fixture, no scientific values\n')
        self.output = self.ops / 'probe/IMPORT.json'
        self.policy = {'raw_root': str(self.raw), 'ops_root': str(self.ops), 'empty_cwd': str(self.empty),
            'source_root': str(probe.SOURCE), 'capacity_wait_seconds': 300,
            'execution_episode': probe.cwd_runner.EPISODE,
            'source_files': {name: rb.file_hash(probe.SOURCE / name) for name in rb.REQUIRED_SOURCES},
            'amendment': {'fixture': 'no actual registration'}, 'producer_config': {'fixture': 'unvalidated owner'}}
        own = Path(probe.__file__).resolve()
        self.policy['source_files'][own.relative_to(probe.SOURCE).as_posix()] = rb.file_hash(own)
        self.policy_item = self.write('policy.json', self.policy)
        self.frozen = {'source_files': deepcopy(self.policy['source_files'])}
        self.freeze_item = self.write('freeze.json', self.frozen)
        self.config_item = self.write('config.json', {'test_only': True})
        self.args = SimpleNamespace(policy=self.policy_item['path'], expected_policy_sha256=self.policy_item['sha256'],
            freeze=self.freeze_item['path'], expected_freeze_sha256=self.freeze_item['sha256'],
            registration_config=self.config_item['path'], expected_registration_config_sha256=self.config_item['sha256'],
            output=str(self.output))

    def write(self, name, value):
        path = self.ops / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + '\n')
        return probe.cwd_runner.descriptor(path)

    def real_policy(self, name):
        profile = rb.RESOURCE.memory_profile()
        return rb.BackpressurePolicy(root=self.raw, journal_directory=self.ops / name,
            source_root=probe.SOURCE, expected_sources=self.policy['source_files'],
            deadline_monotonic=time.monotonic() + 30,
            oom_baseline={key: profile[key] for key in ('oom', 'oom_kill')},
            health_check=lambda: None, max_wait_seconds=1)

    def test_all_eight_real_factories_capture_installed_aliases_and_restore(self):
        before = rb.RESOURCE.StorageBudget
        owner = producer_adapter.ProducerAdapter.__new__(producer_adapter.ProducerAdapter)
        with rb.installed(self.real_policy('real-factories')) as installation:
            owner.controller = SimpleNamespace(StorageBudget=installation['budget_type'])
            clones, audit = probe.factory_closure(owner, installation)
            self.assertEqual(set(audit), set(probe.FACTORIES))
            self.assertEqual(len(clones), 8)
            self.assertTrue(all(row['scientific_entrypoint_called'] is False for row in audit.values()))
            self.assertIs(clones['for_endpoint'].StorageBudget, rb.RESOURCE.StorageBudget)
        self.assertIs(rb.RESOURCE.StorageBudget, before)
        self.assertNotIn('torch', sys.modules)
        self.assertNotIn('numpy', sys.modules)

    def test_controller_constructed_before_alias_install_fails_closed(self):
        owner = producer_adapter.ProducerAdapter.__new__(producer_adapter.ProducerAdapter)
        owner.controller = SimpleNamespace(StorageBudget=rb.RESOURCE.StorageBudget)
        with rb.installed(self.real_policy('wrong-order')) as installation:
            with self.assertRaisesRegex(ValueError, 'constructed before'):
                probe.factory_closure(owner, installation)

    def metadata_fixture(self):
        commit = '1234567890abcdef1234567890abcdef12345678'
        common = {'source_files': deepcopy(self.policy['source_files']), 'registered_commit': commit,
            'execution_episode': self.policy['execution_episode'], 'operational_amendment_sha256': 'a' * 64}
        self.policy['amendment'] = {'path': 'not-read-in-this-isolated-contract-test', 'bytes': 0, 'sha256': 'a' * 64}
        controller = {**common, 'artifacts': {self.policy_item['path']: self.policy_item['sha256'],
            '/fixture-producer-config': 'b' * 64}}
        self.policy['producer_config'] = {'path': '/fixture-producer-config', 'bytes': 0, 'sha256': 'b' * 64}
        config = {'source_root': self.policy['source_root'], 'raw_root': str(self.raw), 'source_commit': commit,
            'producer_config': self.policy['producer_config'], 'amendment': self.policy['amendment'],
            'a_freeze': self.write('a.json', common), 'c_freeze': self.write('c.json', common),
            'controller_freeze': self.write('controller.json', controller), 'history_adapter_source': {'test_only': True}}
        roots = []
        for index in range(32):
            support = {key: self.write(f'support/{index}/{key}.json', {'test_only': key})
                       for key in ('intent', 'stdout', 'stderr')}
            roots.append({'receipt': self.write(f'support/{index}/WAIT4.json', support), 'scope': 'test_only'})
        config['execution04_cost_facts'] = self.write('facts.json', {'root_io': roots})
        config['execution05_cost_facts'] = self.write('facts05.json', {'test_only': True})
        config['execution05_costs_source'] = {'test_only': True}
        item = self.write('registration.json', config)
        plan = {'actual_file_bindings': [item], 'execution04_cost_plan': {
            'root_io_rows': [{'disjoint_cpu_seconds_lower_bound': .25} for _ in range(32)],
            'a29_failure': {'costs': {'scheduled_gradient_microsteps': 14784}},
            'imported_A17_is_counted_only_in_current_completed_scientific_rows': True},
            'execution05_cost_plan': {
                'a29_failure': {'costs': {'scheduled_gradient_microsteps': 17280, 'optimizer_steps': 15984}},
                'actual_outer_wait4_missing': True, 'whole_execution05_cpu_total_or_upper_bound_known': False,
                'execution05_imported_A17_new_scientific_work': 0,
                'failure_sources': {'test_only': True}, 'measured_disjoint_cpu_seconds_lower_bound': 1555.961190367}}
        return config, item, plan

    def call_metadata(self, config, item, plan):
        with mock.patch.object(registration, 'load_config', return_value=(config, item)), \
             mock.patch.object(registration, 'producer_configuration', return_value={'test_only': True}), \
             mock.patch.object(historical_costs, 'history_plan', return_value=(plan, {})):
            return probe.metadata_closure(self.policy, self.policy_item, config['a_freeze'], item)

    def test_registration_contract_requires_full_32_wait4_and_96_support_population(self):
        config, item, plan = self.metadata_fixture()
        _, _, result = self.call_metadata(config, item, plan)
        self.assertEqual(result['verified_execution04_root_wait4_receipts'], 32)
        self.assertEqual(result['verified_execution04_root_support_receipts'], 96)
        self.assertEqual(result['execution04_root_disjoint_cpu_seconds_lower_bound'], 8)
        plan['execution04_cost_plan']['root_io_rows'].pop()
        with self.assertRaisesRegex(ValueError, 'WAIT4 population'):
            self.call_metadata(config, item, plan)

    def test_later_policy_and_producer_must_be_bound_by_ops_freeze(self):
        config, item, plan = self.metadata_fixture()
        value = probe.cwd_runner.read_json(config['controller_freeze'])
        value['artifacts'].pop(self.policy_item['path'])
        config['controller_freeze'] = self.write('wrong-controller.json', value)
        with self.assertRaisesRegex(ValueError, 'OPS freeze'):
            self.call_metadata(config, item, plan)

    def test_c_source_closure_must_match_a_and_policy(self):
        config, item, plan = self.metadata_fixture()
        value = probe.cwd_runner.read_json(config['c_freeze'])
        value['source_files'] = {}
        config['c_freeze'] = self.write('wrong-c.json', value)
        with self.assertRaisesRegex(ValueError, 'source closure'):
            self.call_metadata(config, item, plan)

    @contextmanager
    def fake_runtime(self, *, admission=True, oom_change=False, mutate_raw=False, wrong_runtime=False):
        """Use fake imports, real temp files, real receipt encoding, no science."""
        calls = []
        baseline = {'oom': 0, 'oom_kill': 0, 'allowed': admission, 'effective_current': 0, 'limit': 8 * rb.GiB}
        resources = SimpleNamespace(StorageBudget=object(), memory_admission=lambda: dict(baseline),
            memory_profile=lambda: {**baseline, 'oom': int(oom_change)})
        runner = SimpleNamespace(verify_files=mock.Mock(), ensure_loaded_closure=mock.Mock())
        architecture = SimpleNamespace(reference_modules=mock.Mock())
        modules = {probe.PREFIX + name: SimpleNamespace() for name in probe.MODULES}
        modules.update({probe.PREFIX + 'resource_v2': resources, probe.PREFIX + 'run_v2': runner,
            probe.PREFIX + 'architecture': architecture,
            'torch': SimpleNamespace(__version__='wrong' if wrong_runtime else probe.RUNTIME['torch']),
            'numpy': SimpleNamespace(__version__=probe.RUNTIME['numpy']),
            'PIL': SimpleNamespace(__version__=probe.RUNTIME['pillow'])})
        def import_module(name):
            calls.append(name)
            self.assertIn(name, modules, 'Unexpected import in explicitly fake full-pipeline test')
            return modules[name]
        class FakePolicy:
            def __init__(inner, **kwargs):
                calls.append('policy-created')
                inner.journal_path = Path(kwargs['journal_directory']) / 'CAPACITY_EVENTS.jsonl'
                inner.journal_path.parent.mkdir(parents=True)
                inner.journal_path.write_text('{"test_only":true}\n')
                inner.wait_count = 0
        @contextmanager
        def installed(policy):
            previous = resources.StorageBudget
            resources.StorageBudget = object()
            calls.append('resource-installed')
            try:
                yield {'budget_type': resources.StorageBudget}
            finally:
                resources.StorageBudget = previous
                calls.append('resource-restored')
        def producer(*args):
            self.assertEqual(calls[-1], 'resource-installed')
            calls.append('producer-created')
            return object()
        def factories(*args):
            calls.append('factories-created')
            if mutate_raw:
                (self.raw / 'imported-metadata.txt').write_text('test-only unexpected mutation\n')
            return {}, {'fixture': {'scientific_entrypoint_called': False}}
        producer_config = {'producer_map': {}, 'import_receipt': {}, 'fresh_registration': {}}
        previous = Path.cwd()
        os.chdir(self.empty)
        try:
            with mock.patch.object(probe.cwd_runner, 'validate_policy', return_value=self.policy), \
                 mock.patch.object(probe.importlib, 'import_module', side_effect=import_module), \
                 mock.patch.object(probe.platform, 'python_version', return_value=probe.RUNTIME['python']), \
                 mock.patch.object(probe, 'metadata_closure', return_value=({}, producer_config, {'test_only': True})), \
                 mock.patch.object(probe, 'factory_closure', side_effect=factories), \
                 mock.patch.object(probe, 'original_registration_checks', return_value={'test_only': True}), \
                 mock.patch.object(rb, 'BackpressurePolicy', FakePolicy), \
                 mock.patch.object(rb, 'installed', installed), \
                 mock.patch.object(producer_adapter, 'ProducerAdapter', side_effect=producer):
                yield calls, runner, architecture
        finally:
            os.chdir(previous)

    def test_full_fake_runtime_writes_only_external_probe_receipt_after_closed_checks(self):
        before = probe.raw_snapshot(self.raw)
        with self.fake_runtime() as (calls, runner, architecture):
            item = probe.run_probe(self.args)
        receipt = probe.cwd_runner.read_json(item)
        self.assertTrue(receipt['complete'])
        self.assertEqual(receipt['workers_started'], 0)
        self.assertEqual(receipt['model_instances_created'], 0)
        self.assertEqual(probe.raw_snapshot(self.raw), before)
        self.assertLess(calls.index('resource-installed'), calls.index('producer-created'))
        self.assertLess(calls.index('producer-created'), calls.index('factories-created'))
        runner.ensure_loaded_closure.assert_called_once()
        architecture.reference_modules.assert_called_once_with(probe.SOURCE)
        self.assertEqual(calls[-1], 'resource-restored')
        self.assertFalse(any(self.empty.iterdir()))

    def test_original_memory_admission_rejects_before_any_scientific_import(self):
        with self.fake_runtime(admission=False) as (calls, _, __):
            with self.assertRaisesRegex(ValueError, 'Original 768 MiB'):
                probe.run_probe(self.args)
        self.assertEqual(calls, [probe.PREFIX + 'resource_v2'])
        self.assertFalse(self.output.exists())

    def test_oom_change_fails_before_factories_or_completion_receipt(self):
        with self.fake_runtime(oom_change=True) as (calls, _, __):
            with self.assertRaisesRegex(ValueError, 'OOM counter'):
                probe.run_probe(self.args)
        self.assertNotIn('policy-created', calls)
        self.assertFalse(self.output.exists())

    def test_runtime_mismatch_fails_before_factory_construction(self):
        with self.fake_runtime(wrong_runtime=True) as (calls, _, __):
            with self.assertRaisesRegex(ValueError, 'restored runtime'):
                probe.run_probe(self.args)
        self.assertNotIn('producer-created', calls)
        self.assertFalse(self.output.exists())

    def test_raw_mutation_fails_and_preserves_scoped_alias_cleanup(self):
        with self.fake_runtime(mutate_raw=True) as (calls, _, __):
            with self.assertRaisesRegex(ValueError, 'RAW changed'):
                probe.run_probe(self.args)
        self.assertIn('resource-restored', calls)
        self.assertFalse(self.output.exists())

    def test_output_cannot_pollute_worker_token_population_or_raw(self):
        for path in (self.raw / 'probe.json', self.ops / 'resource_backpressure/extra/probe.json',
                     self.ops / 'wrapper_runs/extra/probe.json'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                probe.output_path(self.policy, path)

    def test_cli_requires_external_registration_pin_and_preserves_exact_arguments(self):
        with mock.patch.object(probe, 'run_probe', return_value={'test_only': True}) as run, \
             mock.patch('builtins.print'):
            probe.main(['--policy', self.args.policy, '--expected-policy-sha256', self.args.expected_policy_sha256,
                '--freeze', self.args.freeze, '--expected-freeze-sha256', self.args.expected_freeze_sha256,
                '--registration-config', self.args.registration_config,
                '--expected-registration-config-sha256', self.args.expected_registration_config_sha256,
                '--output', self.args.output])
        self.assertEqual(vars(run.call_args.args[0]), vars(self.args))


if __name__ == '__main__':
    unittest.main(verbosity=2)
