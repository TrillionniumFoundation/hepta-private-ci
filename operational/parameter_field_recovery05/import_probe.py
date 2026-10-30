"""Execution05 import and metadata closure probe; never run scientific entrypoints.

Mechanical successor to the frozen execution04 probe. Original memory admission,
loaded-source closure and restored runtime checks remain. The additional factory
and history checks construct only private metadata namespaces; no model, dataset,
checkpoint tensor, controller run loop or worker is opened or executed here.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import resource
import stat
import sys
import time
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[2]
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
sys.dont_write_bytecode = True
from operational.parameter_field_recovery05 import cwd_runner

PREFIX = 'experiments.parameter_field_fullstudy_20261029.'
MODULES = ('run', 'architecture_run', 'endpoint_v2', 'endpoints', 'architecture_endpoints',
           'replay_terminals', 'witness', 'analysis_launch_v2', 'report_results')
FACTORIES = {
    'for_runner': PREFIX + 'run_v2',
    'for_endpoint': PREFIX + 'endpoint_v2',
    'for_analysis_launcher': PREFIX + 'analysis_launch_v2',
    'for_finalizer': PREFIX + 'finalize_v2',
    'for_followups': PREFIX + 'register_followups_v2',
    'for_summary': PREFIX + 'register_summary_v2',
    'for_report': PREFIX + 'report_results',
    'for_postseal': 'supplements.parameter_field_fullstudy_20261030.postseal_supplement',
}
RUNTIME = {'python': '3.12.14', 'torch': '2.8.0+cpu', 'numpy': '2.3.5', 'pillow': '12.3.0'}
PROBE_SECONDS = 300
require = cwd_runner.require


def selected_descriptor(path, expected, label):
    item = cwd_runner.descriptor(Path(path).absolute())
    require(item['sha256'] == expected, label + ' bytes differ')
    return item


def output_path(policy, value):
    output = Path(value).absolute()
    ops, raw = Path(policy['ops_root']), Path(policy['raw_root'])
    require(output.resolve() == output and output.is_relative_to(ops)
            and not output.is_relative_to(raw) and not output.is_relative_to(SOURCE)
            and not output.is_relative_to(ops / 'resource_backpressure')
            and not output.is_relative_to(ops / 'wrapper_runs')
            and not output.exists(), 'Probe receipt must be a fresh separate OPS artifact')
    return output


def raw_snapshot(root):
    """File identities only; no scientific values are decoded for this check."""
    root = Path(root)
    require(root.is_dir() and root.resolve(strict=True) == root, 'Actual imported RAW root required')
    result = {}
    for path in (root, *sorted(root.rglob('*'))):
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode), 'Unexpected imported RAW file type')
        result[path.relative_to(root).as_posix()] = (
            info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return result


def metadata_closure(policy, policy_item, frozen_item, config_item):
    from operational.parameter_field_recovery05 import historical_costs, registration
    config, actual_item = registration.load_config(config_item['path'], config_item['sha256'])
    require(actual_item == config_item and config['producer_config'] == policy['producer_config']
            and config['amendment'] == policy['amendment']
            and config['source_root'] == policy['source_root'] and config['raw_root'] == policy['raw_root'],
            'Probe registration is not the exact policy registration')
    require(frozen_item in [config[key] for key in ('a_freeze', 'c_freeze', 'controller_freeze')],
            'Probe freeze is outside the registered initial A/C/controller set')
    for key in ('a_freeze', 'c_freeze', 'controller_freeze'):
        frozen = cwd_runner.read_json(config[key])
        require(frozen['source_files'] == policy['source_files']
                and frozen['registered_commit'] == config['source_commit']
                and frozen['execution_episode'] == policy['execution_episode']
                and frozen['operational_amendment_sha256'] == policy['amendment']['sha256'],
                'Initial source closure/producer differs: ' + key)
    controller = cwd_runner.read_json(config['controller_freeze'])
    for item in (policy_item, policy['producer_config']):
        require(controller['artifacts'].get(item['path']) == item['sha256'],
                'OPS freeze does not bind the exact later policy/producer artifact')
    producer = registration.producer_configuration(config)
    plan, unused_restored_inputs = historical_costs.history_plan(config, config_item)
    history = plan['execution04_cost_plan']
    require(len(history['root_io_rows']) == 32, 'Execution04 root WAIT4 population is incomplete')
    facts = cwd_runner.read_json(config['execution04_cost_facts'])
    supports = []
    for row in facts['root_io']:
        record = cwd_runner.read_json(row['receipt'])
        supports.extend(record[key] for key in ('intent', 'stdout', 'stderr'))
    require(len(supports) == 96 and len({item['path'] for item in supports}) == 96,
            'Execution04 root WAIT4 support population differs')
    return config, producer, {
        'registration_config': config_item,
        'source_commit': config['source_commit'],
        'history_adapter_source': config['history_adapter_source'],
        'execution04_cost_facts': config['execution04_cost_facts'],
        'verified_history_file_bindings': len(plan['actual_file_bindings']),
        'verified_execution04_root_wait4_receipts': len(history['root_io_rows']),
        'verified_execution04_root_support_receipts': len(supports),
        'execution04_root_disjoint_cpu_seconds_lower_bound': sum(
            row['disjoint_cpu_seconds_lower_bound'] for row in history['root_io_rows']),
        'execution04_a29_failed_gradient_microsteps': history['a29_failure']['costs']['scheduled_gradient_microsteps'],
        'execution04_inclusive_outer_cpu_added': False,
        'imported_A17_counted_once_in_current_scientific_rows':
            history['imported_A17_is_counted_only_in_current_completed_scientific_rows'],
    }


def factory_closure(producer, installation):
    """Construct all eight real factories after installation; invoke no main."""
    originals = {name: importlib.import_module(module) for name, module in FACTORIES.items()}
    clones = {name: getattr(producer, name)(module) for name, module in originals.items()}
    for name, module in originals.items():
        clone = clones[name]
        require(clone is not module and clone._producer is producer
                and clone.__file__ == module.__file__ and clone.__name__ == module.__name__,
                'Producer factory did not create its isolated module: ' + name)
    budget = installation['budget_type']
    require(producer.controller.StorageBudget is budget,
            'Controller was constructed before resource aliases were installed')
    for name in ('for_endpoint', 'for_analysis_launcher', 'for_finalizer'):
        require(clones[name].StorageBudget is budget, 'Factory lost installed StorageBudget: ' + name)
    for name, attributes in {
        'for_runner': ('phase_budget_type', 'replay_budget_type'),
        'for_endpoint': ('guarded_writes', 'training_slot', 'EndpointBudget'),
        'for_analysis_launcher': ('guarded_writes', 'monitor'),
        'for_finalizer': ('verify_logical_paths',),
    }.items():
        for attribute in attributes:
            require(getattr(clones[name], attribute) is getattr(originals[name], attribute),
                    'Factory captured a stale resource alias: ' + name + '.' + attribute)
    return clones, {name: {'module': module.__name__, 'source': cwd_runner.descriptor(Path(module.__file__).resolve()),
                          'metadata_rewrites': clones[name].producer_adapter_audit,
                          'factory_constructed': True, 'scientific_entrypoint_called': False}
                    for name, module in originals.items()}


def original_registration_checks(config, producer, clones, resources):
    registration = resources.load_registration(config['amendment']['path'], config['amendment']['sha256'])
    common = {'root': config['raw_root'], 'protocol': str(SOURCE / 'experiments/parameter_field_fullstudy_20261029/PROTOCOL.json')}
    for seed in (29, 43):
        clones['for_runner'].validate_freeze(SimpleNamespace(
            **common, phase='A', seed=seed, freeze=config['a_freeze']['path']), registration)
    architecture = importlib.import_module(PREFIX + 'architecture_run_v2')
    architecture.validate_freeze(SimpleNamespace(**common, freeze=config['c_freeze']['path']), registration)
    envelope = importlib.import_module(PREFIX + 'controller_envelope_v2')
    envelope.validate(SimpleNamespace(root=config['raw_root'], amendment=config['amendment']['path'],
        amendment_sha256=config['amendment']['sha256'], freeze=config['controller_freeze']['path'],
        freeze_sha256=config['controller_freeze']['sha256'], resume_admission=False, recover_zero_work=False))
    jobs = producer.controller.validate_queue(cwd_runner.read_json(config['initial_queue']), Path(config['raw_root']))
    require([job['id'] for job in jobs] == ['A-17', 'A-29', 'A-43', 'C'], 'Initial queue population differs')
    check_job = producer.verify_job(producer.controller.verify_job)
    for job in jobs:
        check_job(job, registration)
    return {'a29_a43_original_training_freeze_checks': True, 'c_original_training_freeze_check': True,
            'original_controller_envelope_check': True, 'initial_queue_job_metadata_verified': len(jobs),
            'imported_A17_original_profile_verified': True}


def run_probe(args):
    wall, cpu = time.monotonic(), time.process_time()
    policy = cwd_runner.validate_policy(args.policy, args.expected_policy_sha256)
    policy_item = selected_descriptor(args.policy, args.expected_policy_sha256, 'Policy')
    require(Path.cwd().resolve() == cwd_runner.empty_directory(policy), 'Probe cwd differs')
    frozen_item = selected_descriptor(args.freeze, args.expected_freeze_sha256, 'Probe freeze')
    frozen = cwd_runner.read_json(frozen_item)
    require(frozen['source_files'] == policy['source_files'], 'Probe and policy source closure differ')
    own_relative = Path(__file__).resolve().relative_to(SOURCE).as_posix()
    require(frozen['source_files'].get(own_relative) == cwd_runner.descriptor(Path(__file__).resolve())['sha256'],
            'Import probe itself is not source-frozen')
    config_item = selected_descriptor(args.registration_config, args.expected_registration_config_sha256,
                                      'Registration configuration')
    output = output_path(policy, args.output)
    require(not (Path(policy['ops_root']) / 'supervisor_run/START_POLICY.json').exists()
            and not (Path(policy['raw_root']) / 'controller/START.json').exists(),
            'Import probe must precede the execution05 supervisor/controller')
    before_raw = raw_snapshot(policy['raw_root'])
    resources = importlib.import_module(PREFIX + 'resource_v2')
    admission = resources.memory_admission()
    require(admission['allowed'], 'Original 768 MiB plus 1 GiB margin not available for import probe')
    baseline = {name: admission[name] for name in ('oom', 'oom_kill')}
    deadline = wall + PROBE_SECONDS

    def health():
        require(time.monotonic() <= deadline, 'Import-only probe deadline exhausted')
        current = resources.memory_profile()
        require(all(current[name] == baseline[name] for name in baseline), 'An OOM counter changed during the import probe')
        return current

    runner = importlib.import_module(PREFIX + 'run_v2')
    runner.verify_files(frozen, SOURCE)
    for name in MODULES:
        importlib.import_module(PREFIX + name)
        health()
    architecture = importlib.import_module(PREFIX + 'architecture')
    architecture.reference_modules(SOURCE)
    np, torch, pillow = [importlib.import_module(name) for name in ('numpy', 'torch', 'PIL')]
    runtime = {'python': platform.python_version(), 'torch': str(torch.__version__),
               'numpy': np.__version__, 'pillow': pillow.__version__}
    require(runtime == RUNTIME, 'Exact restored runtime differs')
    health()
    config, producer_config, metadata = metadata_closure(policy, policy_item, frozen_item, config_item)
    from operational.parameter_field_recovery05 import resource_backpressure
    from operational.parameter_field_recovery05.producer_adapter import ProducerAdapter
    old_budget = resources.StorageBudget
    journal = output.parent / (output.stem + '_BACKPRESSURE')
    budget_policy = resource_backpressure.BackpressurePolicy(
        root=policy['raw_root'], journal_directory=journal, source_root=policy['source_root'],
        expected_sources=policy['source_files'], deadline_monotonic=deadline, oom_baseline=baseline,
        health_check=health, max_wait_seconds=policy['capacity_wait_seconds'])
    with resource_backpressure.installed(budget_policy) as installation:
        producer = ProducerAdapter(producer_config['producer_map'], producer_config['import_receipt'],
                                   producer_config['fresh_registration'])
        clones, factories = factory_closure(producer, installation)
        original_checks = original_registration_checks(config, producer, clones, resources)
        require(budget_policy.wait_count == 0, 'Metadata-only probe unexpectedly entered a persistence wait')
        health()
    require(resources.StorageBudget is old_budget, 'Scoped resource aliases were not restored')
    runner.verify_files(frozen, SOURCE)
    runner.ensure_loaded_closure(frozen)
    require(raw_snapshot(policy['raw_root']) == before_raw, 'Imported RAW changed during the read-only probe')
    require(Path.cwd().resolve() == cwd_runner.empty_directory(policy), 'Probe polluted the registered empty cwd')
    after = health()
    receipt = {'schema': 'hepta.fullstudy.import-closure-probe.5', 'complete': True,
        'execution_episode': policy['execution_episode'], 'at_utc': datetime.now(timezone.utc).isoformat(),
        'policy': policy_item, 'freeze': frozen_item, 'registration_config': config_item,
        'producer_config': policy['producer_config'], 'cwd': str(Path.cwd()),
        'python_executable': os.path.abspath(sys.executable), 'runtime': runtime,
        'modules_imported': list(MODULES), 'producer_factories': factories,
        'producer_factories_constructed_after_resource_installation': True,
        'resource_aliases_restored_after_probe': True,
        'backpressure_probe_journal': cwd_runner.descriptor(budget_policy.journal_path),
        'registration_metadata': metadata, 'original_registration_checks': original_checks,
        'original_loaded_closure_check_passed': True, 'pinned_hcsn_modules_imported_without_instantiation': True,
        'raw_file_identities_unchanged': True, 'raw_inventory_entries': len(before_raw),
        'raw_identity_inventory_sha256': hashlib.sha256(json.dumps(before_raw, sort_keys=True).encode()).hexdigest(),
        'model_instances_created': 0, 'checkpoints_decoded': 0, 'dataset_values_read': 0,
        'scheduled_gradient_microsteps': 0, 'workers_started': 0,
        'admission': admission, 'resources_after': after, 'probe_deadline_monotonic': deadline,
        'probe_deadline_scope': 'Import-only 300 second window; execution05 supervisor has not started its separate 12 hour window.',
        'wall_seconds': time.monotonic() - wall, 'own_cpu_seconds': time.process_time() - cpu,
        'process_cpu_seconds_total': time.process_time(),
        'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        'not_a_successful_scientific_resource_qualification': True}
    cwd_runner.write_new(output, receipt)
    return cwd_runner.descriptor(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('policy', 'expected-policy-sha256', 'freeze', 'expected-freeze-sha256',
                 'registration-config', 'expected-registration-config-sha256', 'output'):
        parser.add_argument('--' + flag, required=True)
    item = run_probe(parser.parse_args(argv))
    print(json.dumps({'status': 'REAL_IMPORT_AND_METADATA_CLOSURE_VERIFIED_ONLY',
                      'receipt': item, 'workers_started': 0}, sort_keys=True))


if __name__ == '__main__':
    main()
