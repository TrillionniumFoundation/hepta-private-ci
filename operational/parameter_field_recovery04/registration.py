"""Metadata-only execution04 registration; never activate a worker queue.

The original public helpers retain source, artifact, population and completion
checks. Only dependency metadata before serialization, restored historical input
locations, and an explicitly registered historical cost layer are adapted.
"""

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import importlib
import json
import os
from pathlib import Path
import re
import resource
import sys
import time
from types import SimpleNamespace

SOURCE_ROOT = Path(__file__).resolve().parents[2]
WORK_ROOT = SOURCE_ROOT.parent
sys.path.insert(0, str(SOURCE_ROOT))
from operational.parameter_field_recovery04 import historical_costs as history

PACKAGE = 'experiments.parameter_field_fullstudy_20261029.'
SCHEMA = 'hepta.fullstudy.durable-registration-config.1'
EPISODE = 'execution04_durable_20261030'
ORDER = ('A-17', 'A-29', 'A-43', 'C', 'B-17', 'B-29', 'B-43', 'W', 'R-17', 'R-29', 'R-43',
         'A_endpoint', 'B_endpoint', 'C_endpoint')
HELPER_SHA = {
    'register_followups_v2.py': '915e7a012b321add3db081367796c0d8eb22555a5bd429da8ebc8c99828b9112',
    'register_summary_v2.py': 'b20351ee0a242bf25352d67a912af3a3dcb6d7503c8e38f9973a437bb3d20184',
    'report_results.py': history.REPORT_SHA}
require, descriptor, checked, read = history.require, history.descriptor, history.checked, history.read


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def write_new(path, value):
    with Path(path).open('xb') as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())


def original_requires(name):
    if name.endswith('_endpoint'):
        return set(ORDER[:11])
    if name[0] in ('B', 'R') or name == 'W':
        return set(ORDER[:3])
    return set()


def exact_requires(name):
    index = ORDER.index(name)
    return sorted(original_requires(name) | ({ORDER[index - 1]} if index else set()))


def validate_canonical_queue(queue, expected_count=None):
    jobs = queue['jobs']
    require(queue.get('schema') == 'hepta.fullstudy.queue.2' and queue.get('attempt_id') == 'attempt02'
            and len(jobs) in (4, 11, 14) and (expected_count is None or len(jobs) == expected_count)
            and [job['id'] for job in jobs] == list(ORDER[:len(jobs)])
            and queue.get('finalize') is (len(jobs) == 14), 'Not a complete canonical 4/11/14 prefix')
    for job in jobs:
        require(job.get('requires', []) == exact_requires(job['id']), 'Fixed serial dependencies differ: ' + job['id'])
    return jobs


@contextmanager
def serial_queue_extension(helper):
    original = helper.queue_extension

    def extension(queue, additions, root, final):
        accepted = deepcopy(queue)
        validate_canonical_queue(queue, 11 if final else 4)
        require([job['id'] for job in additions] == list(ORDER[11:] if final else ORDER[4:11]),
                'Original helper supplied a different addition population')
        projected = []
        for job in additions:
            require(job.get('requires', []) == sorted(original_requires(job['id'])),
                    'Original helper dependency definition changed')
            projected.append({**job, 'requires': exact_requires(job['id'])})
        result = original(queue, projected, root, final)
        require(queue == accepted and result['jobs'][:len(accepted['jobs'])] == accepted['jobs'],
                'An already accepted job definition changed')
        validate_canonical_queue(result, 14 if final else 11)
        return result

    helper.queue_extension = extension
    try:
        yield
    finally:
        helper.queue_extension = original


def load_config(path, expected_sha):
    item = descriptor(Path(path).absolute())
    require(re.fullmatch(r'[0-9a-f]{64}', expected_sha) and item['sha256'] == expected_sha, 'Registration config SHA differs')
    config = read(path)
    require(config.get('schema') == SCHEMA and config.get('execution_episode') == EPISODE,
            'Wrong durable episode configuration')
    require(Path(config['source_root']) == SOURCE_ROOT and Path(config['source_git_root']) == SOURCE_ROOT,
            'Use the actual restored Git source root')
    require(Path(config['raw_root']) == WORK_ROOT / 'fullstudy_execution04_durable_raw'
            and Path(config['registrations_root']) == WORK_ROOT / 'fullstudy_execution04_ops/registrations',
            'Wrong execution04 RAW or registration destination')
    require(re.fullmatch(r'[0-9a-f]{40}', config['source_commit']) and len(set(config['source_commit'])) > 1,
            'An actual full source commit must be explicitly registered')
    require(isinstance(config['analysis_id'], str) and config['analysis_id'].isalnum(), 'Invalid analysis identity')
    for key in ('amendment', 'a_freeze', 'c_freeze', 'controller_freeze', 'initial_queue', 'historical_inputs',
                'driver_source', 'history_adapter_source'):
        checked(config[key])
    require(checked(config['driver_source']) == Path(__file__).resolve(), 'Driver source identity differs')
    require(checked(config['history_adapter_source']) == Path(history.__file__).resolve(), 'Cost adapter source identity differs')
    study = SOURCE_ROOT / 'experiments/parameter_field_fullstudy_20261029'
    for name, digest in HELPER_SHA.items():
        helper = config['helper_pins'][name]
        require(checked(helper) == study / name and helper['sha256'] == digest, 'Frozen public helper bytes differ: ' + name)
    require(Path(config['raw_root']).is_dir() and Path(config['assets']).is_dir(), 'Actual RAW/assets directories are required')
    validate_canonical_queue(read(config['initial_queue']['path']), 4)
    return config, item


def helpers(config):
    followups = importlib.import_module(PACKAGE + 'register_followups_v2')
    summary = importlib.import_module(PACKAGE + 'register_summary_v2')
    for module in (followups, summary):
        require(module.ROOT == SOURCE_ROOT
                and descriptor(Path(module.__file__).resolve()) == config['helper_pins'][Path(module.__file__).name],
                'A helper was loaded from a different checkout')
    # The adapter modules are prospective source, not code silently outside the
    # declared Git identity. The original helper performs its own full check too.
    followups.committed_sources(config['source_git_root'], config['source_commit'], {
        str(Path(config[key]['path']).relative_to(SOURCE_ROOT)): config[key]['sha256']
        for key in ('driver_source', 'history_adapter_source')})
    return followups, summary


def verify_bundle(stage, directory, config):
    bundle = read(directory / 'BUNDLE.json')
    require(bundle['stage'] == stage and bundle['registered_commit'] == config['source_commit']
            and bundle['workers_started'] == 0, 'Registration bundle identity differs')
    require(bundle['files'] and all(Path(name).name == name for name in bundle['files']), 'Unsafe bundle file name')
    files = {}
    for name, item in bundle['files'].items():
        actual = descriptor(directory / name)
        require(actual == {'path': str(directory / name), **item}, 'Sealed bundle file differs: ' + name)
        files[name] = actual
    cost = read(directory / 'REGISTRATION_COST.json')
    require(cost['bundle'] == descriptor(directory / 'BUNDLE.json'), 'Helper cost does not bind this bundle')
    if stage in ('followups', 'endpoints'):
        require(bundle['queue_activated'] is False, 'Helper unexpectedly activated a queue')
        validate_canonical_queue(read(files['QUEUE_EXTENDED.json']['path']), 11 if stage == 'followups' else 14)
    return bundle, files


def queue_for_stage(stage, config, config_item):
    if stage == 'followups':
        return config['initial_queue']
    previous = 'followups' if stage == 'endpoints' else 'endpoints'
    folder = Path(config['registrations_root']) / previous
    bundle, files = verify_bundle(previous, folder, config)
    receipt = read(folder / 'DURABLE_REGISTRATION.json')
    require(receipt['configuration'] == config_item and receipt['driver'] == config['driver_source']
            and receipt['bundle'] == descriptor(folder / 'BUNDLE.json')
            and receipt['canonical_queue'] == files['QUEUE_EXTENDED.json']
            and receipt['queue_activated'] is False, 'Previous canonical registration provenance differs')
    cost = read(folder / 'DRIVER_COST.json')
    require(cost['schema'] == 'hepta.fullstudy.durable-registration-driver-cost.1'
            and cost['stage'] == previous and cost['configuration'] == config_item
            and cost['driver'] == config['driver_source'] and cost['scheduled_gradient_microsteps'] == 0
            and cost['workers_started'] == 0 and cost['endpoint_scoring_performed'] is False
            and cost['result']['bundle'] == receipt['bundle']
            and cost['result']['driver_receipt'] == descriptor(folder / 'DURABLE_REGISTRATION.json')
            and cost['result']['canonical_queue'] == files['QUEUE_EXTENDED.json']
            and cost['result']['files'] == files, 'Previous driver cost/provenance binding differs')
    return files['QUEUE_EXTENDED.json']


def ensure_history_projection(config, config_item):
    plan, restored = history.history_plan(config, config_item)
    directory = Path(config['registrations_root']) / 'history'
    path = directory / 'HISTORICAL_COST_PROJECTION.json'
    if path.exists():
        require(path.read_bytes() == encode(plan), 'Existing historical projection differs; never overwrite it')
    else:
        directory.mkdir(exist_ok=True)
        write_new(path, plan)
    return descriptor(path), plan, restored


@contextmanager
def historical_summary_inputs(helper, config, config_item, projection_item, plan, restored):
    original_history, original_inputs = helper.historical_inputs, helper.analysis_inputs

    def historical(args, artifacts):
        require(descriptor(args.historical_inputs) == config['historical_inputs']
                and args.expected_historical_sha256 == helper.HISTORY_SHA == history.HISTORY_SHA,
                'Original historical manifest binding differs')
        # history_plan preserves the exact original manifest SHA and V5 FAIL.
        # Strict mode checks all actual original receipt bytes; projection mode
        # instead checks its explicitly registered summary-only contract.
        current, current_restored = history.history_plan(config, config_item)
        require(current == plan and current_restored == restored, 'Historical evidence changed during registration')
        bindings = [*plan['actual_file_bindings'], projection_item, config['driver_source']]
        for phase in ('followups', 'endpoints'):
            folder = Path(config['registrations_root']) / phase
            for name in ('DURABLE_REGISTRATION.json', 'DRIVER_COST.json'):
                bindings.append(descriptor(folder / name))
        for item in bindings:
            require(helper.add(artifacts, item['path']) == item, 'Historical/operational artifact changed')
        return deepcopy(restored), config['historical_inputs']

    def inputs(args, registration, stages, artifacts, provenance):
        value = original_inputs(args, registration, stages, artifacts, provenance)
        value['historical_cost_compatibility'] = {
            'schema': history.BINDING_SCHEMA, 'configuration': config_item,
            'projection': projection_item, 'adapter_source': config['history_adapter_source']}
        value['registration_provenance']['durable_episode'] = {
            'execution_episode': EPISODE, 'canonical_queue_only': True,
            'actual_queue_activation_and_durable_ACK_owned_by_external_supervisor': True,
            'configuration': config_item, 'driver': config['driver_source'],
            'historical_cost_mode': plan['history_mode'],
            'original_preflight_bytes_missing': plan['original_preflight_bytes_missing'],
            'historical_V5_FAIL_preserved': True}
        return value

    helper.historical_inputs, helper.analysis_inputs = historical, inputs
    try:
        yield
    finally:
        helper.historical_inputs, helper.analysis_inputs = original_history, original_inputs


def register(stage, config, config_item):
    followups, summary = helpers(config)
    directory = Path(config['registrations_root']) / stage
    require(not directory.exists(), 'Registration output exists; preserve partial/complete evidence, do not automatically retry')
    canonical = queue_for_stage(stage, config, config_item)
    checked(canonical)
    accepted = read(canonical['path'])
    validate_canonical_queue(accepted, 4 if stage == 'followups' else 11 if stage == 'endpoints' else 14)
    common = dict(stage=stage, root=config['raw_root'], output=str(directory),
        source_git_root=config['source_git_root'], source_commit=config['source_commit'],
        amendment=config['amendment']['path'], amendment_sha256=config['amendment']['sha256'],
        queue=canonical['path'], expected_queue_sha256=canonical['sha256'])
    projection = None
    if stage in ('followups', 'endpoints'):
        common.update(assets=config['assets'], a_freeze=config['a_freeze']['path'], a_freeze_sha256=config['a_freeze']['sha256'],
                      c_freeze=config['c_freeze']['path'], c_freeze_sha256=config['c_freeze']['sha256'])
        with serial_queue_extension(followups):
            result = followups.register(SimpleNamespace(**common))
    else:
        projection, plan, restored = ensure_history_projection(config, config_item)
        analysis = Path(config['registrations_root']) / 'analysis/ANALYSIS_SOURCE_FREEZE.json'
        common.update(controller_freeze=config['controller_freeze']['path'], controller_freeze_sha256=config['controller_freeze']['sha256'],
            historical_inputs=config['historical_inputs']['path'], expected_historical_sha256=config['historical_inputs']['sha256'],
            analysis_id=config['analysis_id'], analysis_freeze=str(analysis) if stage == 'finalizer' else None,
            analysis_freeze_sha256=descriptor(analysis)['sha256'] if stage == 'finalizer' else None)
        with historical_summary_inputs(summary, config, config_item, projection, plan, restored):
            result = summary.register(SimpleNamespace(**common))
    checked(canonical)
    bundle, files = verify_bundle(stage, directory, config)
    require(result['bundle'] == descriptor(directory / 'BUNDLE.json')
            and result['registration_cost'] == descriptor(directory / 'REGISTRATION_COST.json'), 'Helper returned another bundle/cost receipt')
    if stage in ('followups', 'endpoints'):
        proposed = files['QUEUE_EXTENDED.json']
        require(bundle['previous_queue_sha256'] == canonical['sha256'] and result['queue'] == proposed,
                'Final serial queue is not bound to the accepted canonical parent')
        require(read(proposed['path'])['jobs'][:len(accepted['jobs'])] == accepted['jobs'], 'Accepted canonical jobs changed')
    else:
        proposed = canonical
        freeze = read(files['ANALYSIS_SOURCE_FREEZE.json' if stage == 'analysis' else 'FINALIZER_SOURCE_FREEZE.json']['path'])
        require(freeze['artifacts'].get(projection['path']) == projection['sha256'], 'Summary freeze omits its historical cost projection')
        if stage == 'analysis':
            require(freeze['report_inputs'] == files['REPORT_INPUTS.json'], 'Analysis freeze does not bind final report inputs')
            spec = read(files['REPORT_INPUTS.json']['path'])
            with history.apply_cost_adapter(spec) as check:
                report = importlib.import_module(PACKAGE + 'report_results')
                prior = report.prior_costs(spec)  # Costs only; never assemble or decode outcomes here.
                require(prior['historical_evidence_tiers']['recovered_partial_raw_audit_lower_bound'] == 576
                        and prior['historical_evidence_tiers']['historical_observation_missing_original_episode03_receipts_lower_bound'] == 78336,
                        'Additional historical costs were not included once')
    receipt = {'schema': 'hepta.fullstudy.durable-canonical-registration.1', 'at_utc': datetime.now(timezone.utc).isoformat(),
        'stage': stage, 'execution_episode': EPISODE, 'configuration': config_item, 'driver': config['driver_source'],
        'bundle': result['bundle'], 'registration_cost': result['registration_cost'], 'input_canonical_queue': canonical,
        'canonical_queue': proposed, 'queue_activated': False, 'workers_started': 0,
        'historical_cost_projection': projection, 'accepted_job_definitions_unchanged': True,
        'dependency_projection_preceded_original_bundle_serialization': True,
        'sealed_helper_artifacts_rewritten': False, 'actual_prefix_activation_requires_external_durable_backup_ACK': True}
    write_new(directory / 'DURABLE_REGISTRATION.json', receipt)
    return {'schema': 'hepta.fullstudy.durable-registration-result.1', 'stage': stage,
        'bundle': result['bundle'], 'canonical_queue': proposed, 'registration_cost': result['registration_cost'],
        'driver_receipt': descriptor(directory / 'DURABLE_REGISTRATION.json'),
        'files': files, 'historical_cost_projection': projection, 'queue_activated': False, 'workers_started': 0}


def main():
    wall, cpu = time.monotonic(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--expected-config-sha256', required=True)
    parser.add_argument('--stage', choices=('followups', 'endpoints', 'analysis', 'finalizer'), required=True)
    parser.add_argument('--check-history-only', action='store_true')
    args = parser.parse_args()
    config, item = load_config(args.config, args.expected_config_sha256)
    if args.check_history_only:
        plan, unused = history.history_plan(config, item)
        print(json.dumps({'status': 'HISTORY_METADATA_VERIFIED_ONLY', 'history_mode': plan['history_mode'],
            'original_preflight_bytes_missing': plan['original_preflight_bytes_missing'],
            'native_episode_lower_bounds': EXPECTED_EPISODE_COSTS, 'workers_started': 0}, sort_keys=True))
        return 0
    root = Path(config['registrations_root'])
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'registration.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = register(args.stage, config, item)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cost = {'schema': 'hepta.fullstudy.durable-registration-driver-cost.1', 'stage': args.stage,
            'wall_seconds_including_original_helper': time.monotonic() - wall,
            'own_cpu_seconds_including_original_helper': time.process_time() - cpu,
            'process_cpu_seconds_total': time.process_time(),
            'waited_child_cpu_seconds_including_original_helper': after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
            'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            'original_helper_registration_cost_is_nested_do_not_add_again': True,
            'supervisor_inclusive_child_cpu_overlaps_do_not_add_again': True,
            'scheduled_gradient_microsteps': 0, 'endpoint_scoring_performed': False, 'workers_started': 0,
            'configuration': item, 'driver': config['driver_source'], 'result': result,
            'measurement_scope': 'This main interval including unchanged helper registration and adapter validation; excludes final cost-receipt serialization/write.'}
        target = root / args.stage / 'DRIVER_COST.json'
        write_new(target, cost)
        result['driver_cost'] = descriptor(target)
    print(json.dumps(result, sort_keys=True))
    return 0


EXPECTED_EPISODE_COSTS = history.EXPECTED_EPISODES

if __name__ == '__main__':
    raise SystemExit(main())
