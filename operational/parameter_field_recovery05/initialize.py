"""Create an execution05 registration from committed sources and closed A17 ancestry.

This metadata-only initializer never launches a worker or opens model/data
values. A distinct source commit and original input/ancestry pins are verified before registration is
written. Original protocol and source-freeze bytes remain unmodified.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[2]
BASE = SOURCE.parent
STUDY = SOURCE / 'experiments/parameter_field_fullstudy_20261029'
OWN = Path(__file__).resolve().parent
LEGACY = SOURCE / 'operational/parameter_field_recovery04'
PINS = BASE / 'execution05_preregistration_inputs/IMPORT_A17_PINS.json'
RUNTIME = BASE / 'execution05_preregistration_inputs/RUNTIME_RESTORED.json'
OPS = BASE / 'fullstudy_execution05_ops'
RAW = BASE / 'fullstudy_execution05_durable_raw'
CAS = RAW.with_name(RAW.name + '_cas')
PYTHON = BASE / 'runtime_recovery_20261030/venv/bin/python'
EPISODE = 'execution05_backpressure_20261030'
BRANCH = 'research/parameter-field-backpressure-20261030'
PACKAGE = 'experiments.parameter_field_fullstudy_20261029.'
ORDER = ['A-17', 'A-29', 'A-43', 'C', 'B-17', 'B-29', 'B-43', 'W',
         'R-17', 'R-29', 'R-43', 'A_endpoint', 'B_endpoint', 'C_endpoint']


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def desc(path):
    path = Path(path).absolute()
    require(path.is_file() and not path.is_symlink(), 'Missing regular artifact: ' + str(path))
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def write(path, value):
    path = Path(path)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return desc(path)


def git(*args):
    return subprocess.run(['git', *args], cwd=SOURCE, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def committed_closure(commit):
    require(git('rev-parse', '--verify', commit + '^{commit}').decode().strip() == commit,
            'Use an actual full local Git source commit')
    require(git('rev-parse', 'HEAD').decode().strip() == commit, 'Source commit must be the actual current HEAD')
    expected = {}
    for path in sorted((STUDY / 'registrations').glob('*SOURCE_FREEZE.json')):
        for name, digest in read(path)['source_files'].items():
            require(name not in expected or expected[name] == digest, 'Original source freezes conflict')
            expected[name] = digest
    for name, digest in expected.items():
        require(sha(SOURCE / name) == digest, 'Original scientific source changed: ' + name)
    files = {SOURCE / name for name in expected}
    files.update(STUDY.glob('*.py'))
    files.update(OWN.glob('*.py'))
    files.update((OWN / 'postseal').glob('*.py'))
    files.update(LEGACY.glob('*.py'))
    files.update((SOURCE / 'supplements/parameter_field_fullstudy_20261030').glob('*.py'))
    result = {}
    for path in sorted(files):
        name, digest = path.relative_to(SOURCE).as_posix(), sha(path)
        require(hashlib.sha256(git('show', commit + ':' + name)).hexdigest() == digest,
                'Source is not present byte-exact in the committed tree: ' + name)
        result[name] = digest
    return result, len(expected)


def original_parent(phase):
    path = STUDY / 'registrations' / (phase + '_SOURCE_FREEZE.json')
    original = read(path)
    return {'path': str(path), 'sha256': sha(path),
        'registered_commit': original['registered_commit'],
        'protocol_sha256': original['protocol_sha256'], 'source_root': str(SOURCE)}


def amendment(commit, runtime, asset_receipt, pins):
    old_path = STUDY / 'OPS_ATTEMPT02_DISK.json'
    value = deepcopy(read(old_path))
    value.update(amendment_id='OPS_EXECUTION05_BACKPRESSURE_20261030', execution_episode=EPISODE,
        registered_utc=datetime.now(timezone.utc).isoformat(), repository_branch=BRANCH,
        operational_code_commit=commit, raw_root=str(RAW), content_addressed_store=str(CAS),
        scope='Exact-design continuation with a verified import of execution04 A17, full rerun of failed A29, bounded persistence backpressure and owned-child reaping.',
        original_protocol={'path': str(STUDY / 'PROTOCOL.json'), 'sha256': sha(STUDY / 'PROTOCOL.json'),
                           'preserve_bytes': True},
        original_source_freezes={phase: original_parent(phase) for phase in ('A', 'C')})
    value.pop('supersedes_unexecuted_operational_plan', None)
    value.pop('capacity_at_registration', None)
    value['restart'].update(
        kind='Only completed execution04 A17 is imported; failed A29 is rerun whole, with its previous work charged separately; execution03 checkpoints remain unavailable.',
        source_ancestry='New episode freezes identify actual committed execution sources and unchanged original scientific parents.',
        repeated_seeds_add_independent_samples=0)
    value['proposed_resource_contract'].update(
        persistence_scope='Per-stage external archives are required and verified before the next stage; current unfinished work is not promised durable.',
        external_raw_uploads=0,
        external_raw_uploads_scope='Unchanged original core only; external supervisor archives are separately measured and disclosed.')
    value['final_evidence_container'].update(
        primary='Original local CAS and complete literal restore, plus verified external stage archives with full path coverage.',
        optional_tar='Required bounded streaming stage archives outside RAW; actual remote readback SHA must match before ACK.',
        external_uploads=0,
        external_uploads_scope='Original core reports zero; execution05 supervisor and root record actual separate uploads.')
    value['failure_and_reporting'].update(
        infrastructure_failure='Stop new science and preserve each surviving original byte; known completed stages must have external verified archives.',
        mandatory_disclosure='Original V5/attempt01 failures remain. Execution02 partial failure bytes were recovered; execution03 was last observed after two A jobs, with later state unknown. Missing historical receipts are explicitly lower-bound evidence, never completed-receipt replacements. The former 1 GiB raw / 2 GiB reserve contract remains unfulfilled.')
    value['durable_execution'] = {
        'schema': 'hepta.fullstudy.durable-operation-plan.5',
        'attempt_id_compatibility_only': 'attempt02 is required by unchanged original validators; execution_episode is the new identity.',
        'source_amendment': desc(old_path), 'runtime': runtime, 'asset_restoration': asset_receipt,
        'effective_scientific_concurrency': 1, 'canonical_job_order': ORDER,
        'unchanged_numeric_resource_contract': True, 'initial_gate_samples': 3,
        'initial_gate_interval_seconds': 10, 'initial_ram_headroom_bytes': 1879048192,
        'initial_disk_headroom_bytes': 2415919104,
        'stage_barrier': 'Completed child exit and original seal, stable archive bytes, actual external upload/readback, then exact ACK.',
        'unknown_upload_outcome_retry': False, 'automatic_scientific_retry': False,
        'old_episode03_observation': desc(LEGACY / 'evidence/EXECUTION03_CONTINUITY_OBSERVATION.json'),
        'historical_cost_mode': 'preregistered_public_summary_projection',
        'historical_preflight_originals_missing': True,
        'preflight_public_summary_lower_bound_microsteps': 864,
        'historical_summary_is_not_completed_receipt_evidence': True,
        'public_engineering_summary_was_seen_during_cost_recovery': True,
        'no_new_episode_scientific_execution_at_registration': True,
        'completed_A17_raw_available_for_explicit_import': True,
        'import_pins': pins, 'import_method': 'copy',
        'imported_jobs': ['A-17'], 'new_scientific_jobs': ORDER[1:],
        'maximum_capacity_wait_seconds': 300,
        'capacity_wait_contract': 'Only explicit original pending-growth/margin rejection; release all persistence locks, retain the same payload and cursor, recheck all original limits, no gradient/scoring retry.',
        'owned_child_contract': 'Direct-child identity checked termination and real wait4 on success or failure; preserve original exception and signal outcome.',
        'worker_policy_binding': 'A/C freezes precede producer map and cwd policy to avoid a hash cycle; actual policy is bound by both OPS freezes and the pipeline configuration.',
        'old_scientific_thresholds_and_allocation_unchanged': True}
    return value


def freeze(commit, closure, amend, artifacts, phase, parent=None):
    value = {'schema': 'hepta.fullstudy.source-freeze.1', 'registered_commit': commit,
        'allowed_phases': [phase], 'attempt_id': 'attempt02', 'execution_episode': EPISODE,
        'execution_kind': 'controller' if phase == 'OPS' else 'training',
        'protocol_sha256': sha(STUDY / 'PROTOCOL.json'), 'operational_amendment_sha256': amend['sha256'],
        'created_at': datetime.now(timezone.utc).isoformat(), 'source_files': closure,
        'artifacts': {item['path']: item['sha256'] for item in artifacts},
        'source_git_root': str(SOURCE), 'source_registration_scope': 'COMMITTED_SOURCE_REMOTE_PUBLICATION_REQUIRED_BEFORE_SCIENCE',
        'scope': 'Exact original science; imported A17 keeps execution04 producer, other jobs use the explicit execution05 producer, resource backpressure and child ownership adapters.'}
    if parent is not None:
        value['scientific_parent'] = parent
    return value


def initial_queue(a, c, amend, imported_job):
    old = read(STUDY / 'registrations/QUEUE_ATTEMPT02_DISK_INITIAL.json')
    jobs = []
    replacements = {'--assets': str(BASE / 'assets_original'), '--root': str(RAW),
        '--amendment': amend['path'], '--amendment-sha256': amend['sha256'],
        '--protocol': str(STUDY / 'PROTOCOL.json'), '--reference-root': str(SOURCE)}
    for index, previous in enumerate(old['jobs']):
        job = deepcopy(previous)
        selected = c if job['phase'] == 'C' else a
        argv = list(job['argv'])
        for flag, target in {**replacements, '--freeze': selected['path']}.items():
            if flag in argv:
                argv[argv.index(flag) + 1] = target
        job.update(argv=argv, freeze_sha256=selected['sha256'], requires=[ORDER[index - 1]] if index else [])
        jobs.append(job)
    require(jobs[0]['id'] == imported_job['id'] == 'A-17', 'Wrong imported queue job')
    jobs[0] = deepcopy(imported_job)
    return {'schema': 'hepta.fullstudy.queue.2', 'attempt_id': 'attempt02', 'execution_episode': EPISODE,
        'jobs': jobs, 'finalize': False}


def registration_config(commit, amend, a, c, controller, queue, producer, cost_facts):
    evidence = STUDY / 'evidence'
    old = read(evidence / 'REPORT_INPUTS_BLOCKED.json')
    return {'schema': 'hepta.fullstudy.durable-registration-config.1', 'execution_episode': EPISODE,
        'source_root': str(SOURCE), 'source_git_root': str(SOURCE), 'source_commit': commit,
        'raw_root': str(RAW), 'registrations_root': str(OPS / 'registrations'),
        'assets': str(BASE / 'assets_original'), 'analysis_id': 'analysis05backpressure',
        'amendment': amend, 'a_freeze': a, 'c_freeze': c, 'controller_freeze': controller, 'initial_queue': queue,
        'producer_config': producer, 'execution04_cost_facts': cost_facts,
        'producer_adapter_source': desc(OWN / 'producer_adapter.py'),
        'historical_inputs': desc(evidence / 'REPORT_INPUTS_BLOCKED.json'),
        'driver_source': desc(OWN / 'registration.py'), 'history_adapter_source': desc(OWN / 'historical_costs.py'),
        'helper_pins': {name: desc(STUDY / name) for name in
            ('register_followups_v2.py', 'register_summary_v2.py', 'report_results.py')},
        'history_mode': 'preregistered_public_summary_projection',
        'historical_summary': desc(evidence / 'ENGINEERING_SUMMARY.json'),
        'missing_preflight_receipts': [{'original_receipt': row, 'gradient_microsteps': 432}
            for row in old['engineering_preflights']],
        'history_receipt_relocations': [{'original_receipt': old['failed_attempts'][0]['receipt'],
            'recovered_receipt': desc(evidence / 'INFRASTRUCTURE_FAILURE_01.json')}],
        'additional_failed_episodes': [{'key': key, 'native_fact_receipt': desc(LEGACY / 'evidence' / filename)}
            for key, filename in (('episode02', 'EPISODE02_COST_FACTS.json'), ('episode03', 'EPISODE03_COST_FACTS.json'))]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--expected-pins-sha256', required=True)
    parser.add_argument('--expected-runtime-sha256', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-amendment', action='store_true')
    mode.add_argument('--build', action='store_true')
    args = parser.parse_args()
    closure, original_count = committed_closure(args.source_commit)
    require(PYTHON.is_file() and (PYTHON.parent.parent / 'pyvenv.cfg').is_file(), 'Exact venv is absent')
    sys.path.insert(0, str(SOURCE))
    from operational.parameter_field_recovery05 import ancestry
    from operational.parameter_field_recovery05.controller import ControllerCore
    from operational.parameter_field_recovery05.execution04_costs import build_cost_facts
    from operational.parameter_field_recovery05.postseal.prepare_plan import build_plan
    pins, runtime = desc(PINS), desc(RUNTIME)
    require(pins['sha256'] == args.expected_pins_sha256
            and runtime['sha256'] == args.expected_runtime_sha256, 'Externally selected recovery input differs')
    runtime_value = read(RUNTIME)
    require(runtime_value['status'] == 'EXACT_RUNTIME_AND_SMALL_CPU_PROBES_VERIFIED'
            and runtime_value['runtime_sha256'] == '9d6ac19baf5234ed0d7d4ce98e63d550a1fea951126ea4dba0a591e04f65d52c'
            and runtime_value['science_started'] is False, 'Runtime compatibility was not actually verified')
    ancestry_pins = ancestry.load_pins(PINS, args.expected_pins_sha256)
    verified_import = ancestry.validate_import(ancestry_pins,
        BASE / 'fullstudy_execution04_durable_raw', BASE / 'fullstudy_execution04_ops')
    assets = desc(BASE / 'assets_original/RESTORATION.json')
    asset_recovery = desc(BASE / 'executor_recovery_20261030T1152/ORIGINAL_ASSETS_RESTORED.json')
    for name in ('cwd_runner.py', 'registration.py', 'historical_costs.py', 'supervisor.py',
                 'wait4_launcher.py', 'ancestry.py', 'producer_adapter.py', 'controller.py',
                 'owned_children.py', 'resource_backpressure.py', 'execution04_costs.py',
                 'import_probe.py', 'archive_io.py'):
        require((OWN / name).relative_to(SOURCE).as_posix() in closure, 'Required operational source missing: ' + name)
    for name in ('prepare_plan.py', 'prepare_pins.py', 'run_supplement.py', 'review.py', 'test_review.py',
                 'FIELD_MAP.json', 'C_SCOPE.json', 'FINAL_CONCLUSION_TEMPLATE.zh-CN.md'):
        path = OWN / 'postseal' / name
        item = desc(path)
        require(hashlib.sha256(git('show', args.source_commit + ':' + path.relative_to(SOURCE).as_posix())).hexdigest()
                == item['sha256'], 'Postseal input is not present byte-exact in the committed tree: ' + name)
    amendment_path = OWN / 'registrations/OPS_EXECUTION05_BACKPRESSURE.json'
    if args.prepare_amendment:
        amendment_path.parent.mkdir(parents=True, exist_ok=True)
        value = amendment(args.source_commit, runtime, assets, pins)
        value['durable_execution']['actual_asset_recovery'] = asset_recovery
        item = write(amendment_path, value)
        print(json.dumps({'status': 'AMENDMENT_PREPARED_REQUIRES_ITS_OWN_COMMIT',
            'amendment': item, 'operational_code_commit': args.source_commit, 'workers_started': 0}))
        return
    if not args.build:
        print(json.dumps({'status': 'COMMITTED_INPUTS_AND_ANCESTRY_VERIFIED_ONLY',
            'source_commit': args.source_commit, 'source_files': len(closure),
            'original_source_files': original_count, 'workers_started': 0}))
        return
    initial = OPS / 'registrations/initial'
    amend = desc(amendment_path)
    require(hashlib.sha256(git('show', args.source_commit + ':' + amendment_path.relative_to(SOURCE).as_posix())).hexdigest()
            == amend['sha256'], 'The amendment must be inside the actual committed source tree')
    registered = read(amendment_path)
    require(registered['execution_episode'] == EPISODE
            and registered['durable_execution']['runtime'] == runtime
            and registered['durable_execution']['asset_restoration'] == assets
            and registered['durable_execution']['actual_asset_recovery'] == asset_recovery
            and registered['durable_execution']['import_pins'] == pins, 'Amendment inputs differ')
    for name, digest in closure.items():
        require(hashlib.sha256(git('show', registered['operational_code_commit'] + ':' + name)).hexdigest() == digest,
                'Executable code changed after amendment preparation: ' + name)
    require(not initial.exists() and not RAW.exists() and not CAS.exists(),
            'The new registration, RAW and CAS must not already exist')
    OPS.mkdir(exist_ok=True)
    empty = OPS / 'empty_cwd'
    empty.mkdir(exist_ok=False)
    imported = ancestry.materialize_import(verified_import, RAW, method='copy')
    imported_core = ControllerCore(imported)
    initial.mkdir(parents=True, exist_ok=False)
    CAS.mkdir(exist_ok=False)
    artifacts = [amend, runtime, assets, asset_recovery, pins, imported]
    a = write(initial / 'A_SOURCE_FREEZE.json', freeze(args.source_commit, closure, amend, artifacts, 'A', original_parent('A')))
    c = write(initial / 'C_SOURCE_FREEZE.json', freeze(args.source_commit, closure, amend, artifacts, 'C', original_parent('C')))
    fresh = {'execution_episode': EPISODE, 'raw_root': str(RAW), 'source_root': str(SOURCE),
        'registered_commit': args.source_commit, 'protocol_sha256': sha(STUDY / 'PROTOCOL.json'),
        'runtime_sha256': runtime_value['runtime_sha256'], 'source_freeze': a, 'profile': amend}
    mapping = write(initial / 'PRODUCER_MAP.json', ancestry.producer_map(imported, fresh))
    producer = write(initial / 'PRODUCER_CONFIG.json', {'schema': 'hepta.execution05.producer-config.1',
        'execution_episode': EPISODE, 'producer_map': mapping, 'import_receipt': imported, 'fresh_registration': fresh})
    policy = write(initial / 'CWD_POLICY.json', {
        'schema': 'hepta.fullstudy.cwd-policy.5', 'execution_episode': EPISODE,
        'source_root': str(SOURCE), 'python': str(PYTHON), 'raw_root': str(RAW), 'ops_root': str(OPS),
        'empty_cwd': str(empty), 'amendment': amend, 'source_files': closure,
        'worker_modules': [PACKAGE + name for name in ('run_v2', 'architecture_run_v2', 'endpoint_v2')],
        'analysis_module': PACKAGE + 'analysis_launch_v2', 'producer_config': producer, 'capacity_wait_seconds': 300})
    ops_artifacts = [*artifacts, mapping, producer, policy]
    core = write(initial / 'OPS_CORE_SOURCE_FREEZE.json', freeze(args.source_commit, closure, amend, ops_artifacts, 'OPS'))
    envelope = freeze(args.source_commit, closure, amend, [*ops_artifacts, core], 'OPS')
    envelope.update(controller_envelope_schema='hepta.fullstudy.controller-envelope.1', controller_parent=core)
    controller = write(initial / 'OPS_ENVELOPE_SOURCE_FREEZE.json', envelope)
    queue = write(initial / 'QUEUE_INITIAL.json', initial_queue(a, c, amend, imported_core.imported_job))
    cost_facts = build_cost_facts(imported)
    reg = write(initial / 'REGISTRATION_CONFIG.json',
        registration_config(args.source_commit, amend, a, c, controller, queue, producer, cost_facts))
    postseal_plan = write(initial / 'PRE_ENDPOINT_PLAN05.json', build_plan(producer, args.source_commit))
    descriptors = {'amendment': amend, 'initial_queue': queue, 'controller_freeze': controller,
        'cwd_runner': desc(OWN / 'cwd_runner.py'), 'cwd_policy': policy,
        'registration_driver': desc(OWN / 'registration.py'), 'registration_config': reg,
        'runtime_receipt': runtime, 'own_supervisor': desc(OWN / 'supervisor.py'),
        'durable_archive': desc(LEGACY / 'durable_archive.py'),
        'wait4_launcher': desc(OWN / 'wait4_launcher.py'), 'import_receipt': imported,
        'producer_map': mapping, 'producer_config': producer, 'execution04_cost_facts': cost_facts,
        'import_pins': pins, 'asset_recovery': asset_recovery}
    config = write(initial / 'PIPELINE_CONFIG.json', {
        'schema': 'hepta.fullstudy.execution05.configuration.1', 'execution_episode': EPISODE,
        'source_root': str(SOURCE), 'source_commit': args.source_commit, 'python': str(PYTHON),
        'ops_root': str(OPS), 'raw_root': str(RAW), 'cas_root': str(CAS),
        'empty_cwd': str(empty), 'active_queue': str(OPS / 'ACTIVE_QUEUE.json'),
        'job_order': ORDER, 'descriptors': descriptors,
        'imported_jobs': ['A-17'], 'new_scientific_jobs': ORDER[1:],
        'initial_metadata': [a, c, core, assets, asset_recovery,
            desc(LEGACY / 'evidence/EXECUTION03_CONTINUITY_OBSERVATION.json'),
            desc(SOURCE / 'supplements/parameter_field_fullstudy_20261030/PRE_ENDPOINT_PLAN.json'),
            postseal_plan]})
    write(initial / 'INITIALIZATION.json', {'schema': 'hepta.fullstudy.initialization.5',
        'source_commit': args.source_commit, 'pipeline_config': config, 'original_source_files': original_count,
        'source_files': len(closure), 'imported_jobs': ['A-17'], 'workers_started': 0,
        'scheduled_gradient_microsteps_added': 0, 'endpoint_data_opened': False,
        'actual_import_closure_probe_and_remote_publication_still_required': True})
    print(json.dumps({'status': 'INITIAL_REGISTRATION_AND_EXPLICIT_IMPORT_CREATED_ONLY',
        'pipeline_config': config, 'registration_config': reg, 'import_receipt': imported, 'workers_started': 0}, sort_keys=True))


if __name__ == '__main__':
    main()
