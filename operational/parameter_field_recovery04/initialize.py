"""Create a prospective execution04 registration from committed, exact sources.

This metadata-only initializer never launches a worker or opens model/data
values. A distinct source commit is verified before any new registration is
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
OPS = BASE / 'fullstudy_execution04_ops'
RAW = BASE / 'fullstudy_execution04_durable_raw'
CAS = RAW.with_name(RAW.name + '_cas')
PYTHON = BASE / 'runtime_recovery_20261030/venv/bin/python'
EPISODE = 'execution04_durable_20261030'
BRANCH = 'research/parameter-field-fullstudy-recovery-20261030'
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


def amendment(commit, runtime, asset_receipt):
    old_path = STUDY / 'OPS_ATTEMPT02_DISK.json'
    value = deepcopy(read(old_path))
    value.update(amendment_id='OPS_EXECUTION04_DURABLE_20261030', execution_episode=EPISODE,
        registered_utc=datetime.now(timezone.utc).isoformat(), repository_branch=BRANCH,
        operational_code_commit=commit, raw_root=str(RAW), content_addressed_store=str(CAS),
        scope='Fresh exact-design execution after loss of access to the prior executor; serial durable stage barriers.',
        original_protocol={'path': str(STUDY / 'PROTOCOL.json'), 'sha256': sha(STUDY / 'PROTOCOL.json'),
                           'preserve_bytes': True},
        original_source_freezes={phase: original_parent(phase) for phase in ('A', 'C')})
    value.pop('supersedes_unexecuted_operational_plan', None)
    value.pop('capacity_at_registration', None)
    value['restart'].update(
        kind='Fresh run from exact pinned inputs and fixed seeds; no recovery of unavailable execution03 checkpoints.',
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
        external_uploads_scope='Original core reports zero; execution04 supervisor and root record actual separate uploads.')
    value['failure_and_reporting'].update(
        infrastructure_failure='Stop new science and preserve each surviving original byte; known completed stages must have external verified archives.',
        mandatory_disclosure='Original V5/attempt01 failures remain. Execution02 partial failure bytes were recovered; execution03 was last observed after two A jobs, with later state unknown. Missing historical receipts are explicitly lower-bound evidence, never completed-receipt replacements. The former 1 GiB raw / 2 GiB reserve contract remains unfulfilled.')
    value['durable_execution'] = {
        'schema': 'hepta.fullstudy.durable-operation-plan.4',
        'attempt_id_compatibility_only': 'attempt02 is required by unchanged original validators; execution_episode is the new identity.',
        'source_amendment': desc(old_path), 'runtime': runtime, 'asset_restoration': asset_receipt,
        'effective_scientific_concurrency': 1, 'canonical_job_order': ORDER,
        'unchanged_numeric_resource_contract': True, 'initial_gate_samples': 3,
        'initial_gate_interval_seconds': 10, 'initial_ram_headroom_bytes': 1879048192,
        'initial_disk_headroom_bytes': 2415919104,
        'stage_barrier': 'Completed child exit and original seal, stable archive bytes, actual external upload/readback, then exact ACK.',
        'unknown_upload_outcome_retry': False, 'automatic_scientific_retry': False,
        'old_episode03_observation': desc(OWN / 'evidence/EXECUTION03_CONTINUITY_OBSERVATION.json'),
        'historical_cost_mode': 'preregistered_public_summary_projection',
        'historical_preflight_originals_missing': True,
        'preflight_public_summary_lower_bound_microsteps': 864,
        'historical_summary_is_not_completed_receipt_evidence': True,
        'public_engineering_summary_was_seen_during_cost_recovery': True,
        'no_current_episode_outcomes_exist_at_registration': True,
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
        'scope': 'Exact original science with explicit serial scheduling, cwd isolation, durable backups and historical cost disclosure.'}
    if parent is not None:
        value['scientific_parent'] = parent
    return value


def initial_queue(a, c, amend):
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
    return {'schema': 'hepta.fullstudy.queue.2', 'attempt_id': 'attempt02', 'execution_episode': EPISODE,
        'jobs': jobs, 'finalize': False}


def registration_config(commit, amend, a, c, controller, queue):
    evidence = STUDY / 'evidence'
    old = read(evidence / 'REPORT_INPUTS_BLOCKED.json')
    return {'schema': 'hepta.fullstudy.durable-registration-config.1', 'execution_episode': EPISODE,
        'source_root': str(SOURCE), 'source_git_root': str(SOURCE), 'source_commit': commit,
        'raw_root': str(RAW), 'registrations_root': str(OPS / 'registrations'),
        'assets': str(BASE / 'assets_original'), 'analysis_id': 'analysis04durable',
        'amendment': amend, 'a_freeze': a, 'c_freeze': c, 'controller_freeze': controller, 'initial_queue': queue,
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
        'additional_failed_episodes': [{'key': key, 'native_fact_receipt': desc(OWN / 'evidence' / filename)}
            for key, filename in (('episode02', 'EPISODE02_COST_FACTS.json'), ('episode03', 'EPISODE03_COST_FACTS.json'))]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-commit', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-amendment', action='store_true')
    mode.add_argument('--build', action='store_true')
    args = parser.parse_args()
    closure, original_count = committed_closure(args.source_commit)
    require(PYTHON.is_file() and (PYTHON.parent.parent / 'pyvenv.cfg').is_file(), 'Exact venv is absent')
    runtime = desc(BASE / 'runtime_recovery_20261030/RUNTIME_IMPORT_RECEIPT.json')
    assets = desc(BASE / 'assets_original/RESTORATION.json')
    for name in ('cwd_runner.py', 'registration.py', 'historical_costs.py', 'supervisor.py', 'durable_archive.py', 'wait4_launcher.py', 'import_probe.py'):
        require((OWN / name).relative_to(SOURCE).as_posix() in closure, 'Required operational source missing')
    amendment_path = OWN / 'registrations/OPS_EXECUTION04_DURABLE.json'
    if args.prepare_amendment:
        amendment_path.parent.mkdir(parents=True, exist_ok=True)
        item = write(amendment_path, amendment(args.source_commit, runtime, assets))
        print(json.dumps({'status': 'AMENDMENT_PREPARED_REQUIRES_ITS_OWN_COMMIT',
            'amendment': item, 'operational_code_commit': args.source_commit, 'workers_started': 0}))
        return
    if not args.build:
        print(json.dumps({'status': 'COMMITTED_INPUTS_VERIFIED_ONLY', 'source_commit': args.source_commit,
            'source_files': len(closure), 'original_source_files': original_count, 'workers_started': 0}))
        return
    initial = OPS / 'registrations/initial'
    amend = desc(amendment_path)
    relative_amendment = amendment_path.relative_to(SOURCE).as_posix()
    require(hashlib.sha256(git('show', args.source_commit + ':' + relative_amendment)).hexdigest() == amend['sha256'],
            'The original followup helper requires the amendment inside the actual committed source tree')
    registered_amendment = read(amendment_path)
    require(registered_amendment['execution_episode'] == EPISODE
            and registered_amendment['durable_execution']['runtime'] == runtime
            and registered_amendment['durable_execution']['asset_restoration'] == assets,
            'Prepared amendment does not bind the actual runtime/assets')
    code_commit = registered_amendment['operational_code_commit']
    for name, digest in closure.items():
        require(hashlib.sha256(git('show', code_commit + ':' + name)).hexdigest() == digest,
                'Executable code changed after amendment preparation: ' + name)
    require(not initial.exists(), 'Initial registration exists; preserve it and do not silently overwrite')
    for directory in (RAW, CAS):
        require(not directory.exists() or not any(directory.iterdir()), 'New episode must begin with empty RAW/CAS')
    initial.mkdir(parents=True)
    for directory in (RAW, CAS, OPS / 'empty_cwd'):
        directory.mkdir(exist_ok=True)
        require(not any(directory.iterdir()), 'Nonempty new execution directory')
    policy = write(initial / 'CWD_POLICY.json', {
        'schema': 'hepta.fullstudy.cwd-policy.4', 'execution_episode': EPISODE,
        'source_root': str(SOURCE), 'python': str(PYTHON), 'raw_root': str(RAW), 'ops_root': str(OPS),
        'empty_cwd': str(OPS / 'empty_cwd'), 'amendment': amend, 'source_files': closure,
        'worker_modules': [PACKAGE + name for name in ('run_v2', 'architecture_run_v2', 'endpoint_v2')],
        'analysis_module': PACKAGE + 'analysis_launch_v2'})
    artifacts = [amend, runtime, assets, policy]
    a = write(initial / 'A_SOURCE_FREEZE.json', freeze(args.source_commit, closure, amend, artifacts, 'A', original_parent('A')))
    c = write(initial / 'C_SOURCE_FREEZE.json', freeze(args.source_commit, closure, amend, artifacts, 'C', original_parent('C')))
    core = write(initial / 'OPS_CORE_SOURCE_FREEZE.json', freeze(args.source_commit, closure, amend, artifacts, 'OPS'))
    envelope = freeze(args.source_commit, closure, amend, [*artifacts, core], 'OPS')
    envelope.update(controller_envelope_schema='hepta.fullstudy.controller-envelope.1', controller_parent=core)
    controller = write(initial / 'OPS_ENVELOPE_SOURCE_FREEZE.json', envelope)
    queue = write(initial / 'QUEUE_INITIAL.json', initial_queue(a, c, amend))
    reg = write(initial / 'REGISTRATION_CONFIG.json', registration_config(args.source_commit, amend, a, c, controller, queue))
    pins = {'amendment': amend, 'initial_queue': queue, 'controller_freeze': controller,
        'cwd_runner': desc(OWN / 'cwd_runner.py'), 'cwd_policy': policy,
        'registration_driver': desc(OWN / 'registration.py'), 'registration_config': reg,
        'runtime_receipt': runtime, 'own_supervisor': desc(OWN / 'supervisor.py'),
        'durable_archive': desc(OWN / 'durable_archive.py'),
        'wait4_launcher': desc(OWN / 'wait4_launcher.py')}
    config = write(initial / 'PIPELINE_CONFIG.json', {
        'schema': 'hepta.fullstudy.execution04.configuration.1', 'execution_episode': EPISODE,
        'source_root': str(SOURCE), 'source_commit': args.source_commit, 'python': str(PYTHON),
        'ops_root': str(OPS), 'raw_root': str(RAW), 'cas_root': str(CAS),
        'empty_cwd': str(OPS / 'empty_cwd'), 'active_queue': str(OPS / 'ACTIVE_QUEUE.json'),
        'job_order': ORDER, 'descriptors': pins,
        'initial_metadata': [a, c, core, assets, desc(OWN / 'evidence/EXECUTION03_CONTINUITY_OBSERVATION.json'),
            desc(SOURCE / 'supplements/parameter_field_fullstudy_20261030/PRE_ENDPOINT_PLAN.json')]})
    write(initial / 'INITIALIZATION.json', {'schema': 'hepta.fullstudy.initialization.4',
        'source_commit': args.source_commit, 'pipeline_config': config, 'original_source_files': original_count,
        'source_files': len(closure), 'workers_started': 0, 'endpoint_data_opened': False,
        'actual_import_closure_probe_and_remote_publication_still_required': True})
    print(json.dumps({'status': 'INITIAL_REGISTRATION_CREATED_ONLY', 'pipeline_config': config,
        'registration_config': reg, 'workers_started': 0}, sort_keys=True))


if __name__ == '__main__':
    main()
