"""Independent v4 provenance, neural/native execution and statistical audit.

Exit zero means evidence integrity passed. Mechanism and performance gates are
separate reported booleans; an honestly negative experiment can pass integrity.
No producer, controller, metric or production reporting module is imported.
"""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import resource
import subprocess
import time
import traceback

import numpy as np
import torch

from audit_bridge_fixture import audit_bridge_fixture
from audit_native import NativeAudit
from audit_runtime import audit_runtime_seed
from audit_statistics import audit_statistics
from audit_tables import MODALITIES, PROTOCOL_SHA256, audit_tables, compare, load_renderer, require


PREREGISTRATION = 'f10589f3df5d2da88b2b5d92e3686441ce982461'
BASE = 'experiments/multimodal_output_portfolio/'
V4 = BASE + 'v4/'
BUILD = V4 + 'evidence/native_build_final.json'


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def relative_path(value):
    path = PurePosixPath(value)
    require(isinstance(value, str) and str(path) == value and not path.is_absolute()
            and value and '..' not in path.parts, ('safe relative artifact path', value))
    return path


def git(repo, *arguments):
    return subprocess.check_output(['git', *arguments], cwd=repo,
        env={**os.environ, 'GIT_NO_LAZY_FETCH': '1'}, stderr=subprocess.PIPE, timeout=30)


def commit_tree(repo, commit, paths):
    require(re.fullmatch('[0-9a-f]{40}', commit) is not None, 'full SHA1 source commit')
    result = {}
    for entry in git(repo, 'ls-tree', '-r', '-z', commit, '--', *paths).split(b'\0'):
        if entry:
            header, name = entry.split(b'\t', 1)
            mode, kind, blob = header.decode().split()
            require(kind == 'blob' and mode in ('100644', '100755'), 'regular committed source file')
            result[name.decode()] = blob
    return result


def verify_source_bytes(repo, run, manifest, development):
    require(manifest['git_object_format'] == 'sha1'
            and git(repo, 'rev-parse', '--show-object-format').strip() == b'sha1', 'Git object format')
    paths = sorted(manifest['source_sha256'])
    require(paths and set(paths) == set(manifest['local_blob_sha1']), 'source hash inventory')
    for name in paths:
        relative_path(name)
    committed = commit_tree(repo, manifest['implementation_commit'], paths)
    require(committed == manifest['committed_blob_sha1'], 'actual committed blob inventory')
    dirty = [name for name in paths if committed.get(name) != manifest['local_blob_sha1'][name]]
    require(dirty == manifest['development_dirty_files']
            and manifest['all_source_bytes_committed'] is (not dirty), 'truthful source commit binding')
    require(development or not dirty, 'confirmation source bytes must be committed')
    current_drift, bound = [], {}
    for name in paths:
        path = Path(repo) / name
        require(not path.is_symlink(), ('source symlink', name))
        data = path.read_bytes() if path.is_file() else b''
        if hashlib.sha256(data).hexdigest() != manifest['source_sha256'][name]:
            require(development, ('current frozen confirmation source differs', name))
            current_drift.append(name)
            snapshot = Path(run) / 'development-source-snapshot' / name
            data = snapshot.read_bytes() if snapshot.is_file() else git(
                repo, 'show', manifest['implementation_commit'] + ':' + name)
        require(hashlib.sha256(data).hexdigest() == manifest['source_sha256'][name], ('source SHA256', name))
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        require(blob == manifest['local_blob_sha1'][name], ('source Git blob bytes', name))
        bound[name] = data
    return {'source_files_verified': len(paths), 'implementation_commit': manifest['implementation_commit'],
            'all_source_bytes_committed': not dirty, 'current_development_source_drift': current_drift}, bound


def verify_artifacts(run, receipt):
    run = Path(run)
    manifest_path = run / 'artifacts.json'
    require(digest(manifest_path) == receipt['artifact_manifest_sha256'], 'artifact manifest binding')
    manifest, actual = read(manifest_path), set()
    for path in run.rglob('*'):
        require(not path.is_symlink(), ('artifact symlink', str(path)))
        if path.is_file() and str(path.relative_to(run)) not in ('artifacts.json', 'run-receipt.json'):
            actual.add(str(path.relative_to(run)))
    require(actual == set(manifest), 'complete artifact inventory without omitted or extra files')
    for name, item in manifest.items():
        relative_path(name)
        path = run / name
        require(type(item['bytes']) is int and path.stat().st_size == item['bytes']
                and digest(path) == item['sha256'], ('actual artifact bytes', name))
    require(sum(item['bytes'] for item in manifest.values()) == receipt['artifact_payload_bytes'], 'total artifact payload bytes')
    return {'files_verified': len(manifest), 'payload_bytes': receipt['artifact_payload_bytes'],
            'manifest_sha256': digest(manifest_path)}


def verify_storage(record, protocol, development):
    """Check the retained preflight observations, not today's free disk space."""
    seeds = 1 if development else len(protocol['seeds'])
    worlds = 32 * protocol['development' if development else 'confirmation']['worlds_per_condition_initial_mode']
    nodes, modalities, width, output_width = 32 * (1 + 12 + 12 ** 2), 4, 64, 4904
    latent_bytes, output_bytes = nodes * modalities * width * 4, nodes * output_width * 4
    require(protocol['planning']['joint_latent_float32_bytes_if_all_retained'] == latent_bytes
            and protocol['planning']['four_output_float32_bytes_if_all_retained'] == output_bytes,
            'registered retained-tree byte estimate')
    per_world = output_width * 4 + 3 * modalities * width * 4 + 16384
    payload = seeds * (latent_bytes + output_bytes + 4 * worlds * per_world + 4 * 1024 ** 2)
    total = 2 * payload + 128 * 1024 ** 2
    require(record['uncompressed_payload_estimate_bytes'] == payload
            and record['required_free_bytes_with_archive_headroom'] == total
            and record['total_required_unique_filesystem_bytes'] == total, 'unchanged complete payload and archive reservation')
    output, archive = record['output'], record['archive']
    for item in (output, archive):
        require(Path(item['directory']).is_absolute()
                and all(type(item[key]) is int and item[key] >= 0
                        for key in ('st_dev', 'free_bytes', 'required_free_bytes')), 'recorded start filesystem observations')
    shared = output['st_dev'] == archive['st_dev']
    required = total if shared else payload + 64 * 1024 ** 2
    require(record['strategy'] == ('shared-filesystem' if shared else 'split-filesystems')
            and record['distinct_filesystems'] is (not shared)
            and archive['required_is_shared_with_output'] is shared
            and type(record['archive_headroom_requested']) is bool, 'actual recorded device allocation strategy')
    require(record['archive_headroom_requested'] or output['directory'] == archive['directory'], 'default archive uses output directory')
    require(output['directory'] != archive['directory'] or shared, 'one directory cannot name distinct devices')
    require(record['free_bytes_at_start'] == output['free_bytes']
            and all(item['required_free_bytes'] == required and item['free_bytes'] >= required
                    for item in (output, archive)) and record['passed'] is True, 'both reservations passed at start without double counting')
    return {'strategy': record['strategy'], 'payload_estimate_bytes': payload,
            'total_required_unique_filesystem_bytes': total, 'passed_at_recorded_start': True,
            'scope': 'Arithmetic and retained start observations verified; current free capacity is not a replay requirement.'}


def verify_model_work(run, seeds, runtime_audits, table_audits, protocol, receipt):
    work = read(Path(run) / 'model-work.json')
    expected_order = [(seed, phase) for seed in seeds for phase in
                      ('encoder_contract', 'planning', *('arm:' + arm for arm in protocol['policies']['arms']))]
    require([(row['seed'], row['phase']) for row in work] == expected_order, 'complete ordered model-work phases')
    total, encoder_total = 0, 0
    for row in work:
        seed, phase = row['seed'], row['phase']
        folder = Path(run) / f'seed-{seed}'
        if phase == 'encoder_contract':
            saved = read(folder / 'encoder-contract.json')
            expected = {'linear_macs': 16 * 3072,
                        'linear_layer_examples': {'base.encoders.text.0': 16, 'base.encoders.text.2': 16}}
            require(saved['inputs'] == saved['correct'] == 16 and saved['actual_linear_macs'] == 16 * 3072
                    and saved['predictions'] == saved['expected_conditions'] == list(range(8)) * 2,
                    'executed exhaustive clean encoder contract')
            encoder_total += expected['linear_macs']
        elif phase == 'planning':
            saved = read(folder / 'planning.json')
            layers = {'base.initial_latent': 8}
            for suffix in (0, 2):
                layers[f'refinement.{suffix}'] = 4992
                for modality in MODALITIES:
                    layers[f'base.decoders.{modality}.{suffix}'] = 5032
            expected = {'linear_macs': 1705222144, 'linear_layer_examples': layers}
            require(saved['tree_and_clean_forward_linear_macs'] == expected['linear_macs']
                    and saved['nodes'] == 5024 and saved['checkpoint_sha256'] == table_audits[seed]['checkpoint_sha256'],
                    'all full-tree and clean-reference forwards accounted')
            for arm, value in table_audits[seed]['J'].items():
                compare([saved['root_J'][arm]], [value], 'independent exact policy J', 1e-10)
        else:
            arm = phase.removeprefix('arm:')
            saved = read(folder / arm / 'summary.json')
            expected = saved['actual_model_work']
            require(expected['linear_macs'] == runtime_audits[seed]['arms'][arm]['actual_linear_macs'], 'audited online work')
        require(saved['actual_model_work'] == expected and {key: row[key] for key in expected} == expected,
                ('phase and actual invocation receipts', seed, phase))
        require(all(np.isfinite(row[key]) and row[key] >= 0 for key in ('wall_seconds', 'python_process_cpu_seconds')),
                'finite measured phase costs')
        total += expected['linear_macs']
    require(receipt['full_actual_linear_macs'] == total and receipt['full_actual_model_work_phases'] == len(work)
            and receipt['separately_metered_encoder_contract_linear_macs'] == encoder_total
            and receipt['planning_and_online_linear_macs_subtotal'] == total - encoder_total, 'full actual model-work accounting')
    return {'actual_forward_linear_macs': total, 'encoder_contract_linear_macs': encoder_total,
            'planning_and_online_linear_macs': total - encoder_total, 'complete_phases': len(work)}


def audit(args):
    started, cpu = time.perf_counter(), time.process_time()
    repo, run = args.repo.resolve(), args.run.resolve()
    receipt = read(run / 'run-receipt.json')
    require(type(receipt['development']) is bool and receipt['status'] == 'completed'
            and receipt['source_unchanged'] is True and 'traceback' not in receipt, 'completed unchanged-source attempt')
    development = receipt['development']
    require(not development or args.allow_development, 'development evidence requires explicit --allow-development')
    require(receipt['attempt_kind'] == ('development' if development else 'confirmation')
            and receipt['protocol_sha256'] == digest(run / 'protocol.json') == PROTOCOL_SHA256
            and receipt['preregistration_commit'] == PREREGISTRATION, 'registered scientific protocol and attempt kind')
    require(datetime.fromisoformat(receipt['completed_at_utc']) >= datetime.fromisoformat(receipt['started_at_utc']), 'execution timestamp order')
    receipt_hash, artifacts = digest(run / 'run-receipt.json'), verify_artifacts(run, receipt)
    protocol, source = read(run / 'protocol.json'), read(run / 'source-manifest.json')
    storage_record = read(run / 'storage.json')
    storage = verify_storage(storage_record, protocol, development)
    require(storage_record['output']['directory'] == receipt['output'], 'preflight observed the actual original output directory')
    require(read(run / 'source-end.json') == source and source['protocol_sha256'] == PROTOCOL_SHA256
            and source['preregistration_commit'] == PREREGISTRATION and source['preregistration_is_ancestor'], 'source freeze before and after execution')
    git(repo, 'merge-base', '--is-ancestor', PREREGISTRATION, source['implementation_commit'])
    provenance, bound = verify_source_bytes(repo, run, source, development)
    build = json.loads(bound[BUILD])
    required = {V4 + name for name in ('run.py', 'protocol.json', 'THEORY.md', 'allocation_model.py',
        'allocation_control.py', 'allocation_evaluation.py', 'allocation_bridge.py', 'allocation_reporting.py')}
    required.update(BASE + name for name in ('model.py', 'world.py', 'metrics.py', 'controlled_model.py', 'v3/feedback_model.py', 'v3/risk.py'))
    required.update((*build['source_sha256'], *build['dependency_source_sha256'], BUILD))
    required.update(str(path.relative_to(repo)) for path in (repo / (V4 + 'evidence')).glob('*.py'))
    require(required <= set(bound), 'complete executed, audit and native source coverage')
    for name, expected in {**build['source_sha256'], **build['dependency_source_sha256']}.items():
        require(hashlib.sha256(bound[name]).hexdigest() == expected, ('native built source bytes', name))
    runtime, native_receipt = read(run / 'runtime-start.json'), read(run / 'native-receipt.json')
    binary_hash = digest(args.native_binary)
    require(binary_hash == build['binary']['sha256'] == runtime['native_binary_sha256'] == native_receipt['binary_sha256']
            and args.native_binary.stat().st_size == build['binary']['bytes']
            and runtime['native_build_receipt_sha256'] == hashlib.sha256(bound[BUILD]).hexdigest(), 'original run binary and committed build receipt')
    require(runtime['implementation_commit'] == source['implementation_commit'] and runtime['development'] is development
            and runtime['attempt_kind'] == receipt['attempt_kind'] and runtime['tier'] == 'local-cpu'
            and runtime['dedicated_runner_verified'] is False and runtime['device'] == 'cpu'
            and runtime['python'].split('.')[:2] == ['3', '12'] and runtime['numpy'] == np.__version__ == '1.26.4'
            and runtime['torch'] == torch.__version__ == '2.5.1+cpu' and torch.version.cuda is None
            and platform.python_version_tuple()[:2] == ('3', '12') and runtime['threads'] == 4, 'truthful registered CPU execution tier')
    require(native_receipt['exit_code'] == 0 and native_receipt['stderr'] == ''
            and not native_receipt['terminated_after_timeout'] and native_receipt['caller_failure'] is None
            and native_receipt['sessions'] == native_receipt['completed_sessions'], 'native process completed all sessions')
    legacy_paths = [BASE.rstrip('/'), 'codex-rs/hepta-ndu']
    before, after = commit_tree(repo, PREREGISTRATION, legacy_paths), commit_tree(repo, source['implementation_commit'], legacy_paths)
    legacy = {name: value for name, value in before.items() if not name.startswith(V4)}
    require(all(after.get(name) == value for name, value in legacy.items()), 'pre-v4 scientific sources and evidence preserved')
    torch.set_num_threads(4)
    renderer = load_renderer(repo, protocol)
    fixture = audit_bridge_fixture(repo, args.bridge_fixture, args.source_run / protocol['source_checkpoints']['17']['path'],
                                   protocol, renderer, binary_hash)
    seeds = [protocol['development']['study_seed']] if development else protocol['seeds']
    replicates = protocol['development' if development else 'confirmation']['worlds_per_condition_initial_mode']
    require(receipt['completed_seeds'] == seeds, 'all registered seeds complete')
    require({path.name for path in run.glob('seed-*')} == {f'seed-{seed}' for seed in seeds}, 'registered seed directory inventory')
    native, table_audits, runtime_audits, seed_directories = NativeAudit(run / 'native-transcript.tsv.gz'), {}, {}, {}
    for seed in seeds:
        directory = run / f'seed-{seed}'
        source_seed = protocol['development']['source_checkpoint_seed'] if development else seed
        frozen = protocol['source_checkpoints'][str(source_seed)]
        checkpoint = args.source_run / frozen['path']
        identity = read(directory / 'checkpoint.json')
        require(identity['study_seed'] == seed and identity['source_seed'] == source_seed and identity['bytes'] == checkpoint.stat().st_size == frozen['bytes']
                and identity['sha256'] == digest(checkpoint) == frozen['sha256'], 'actual inherited source checkpoint')
        table_audits[seed] = audit_tables(repo, protocol, checkpoint, seed, directory / 'tree.npz', directory / 'policy.npz')
        runtime_audits[seed] = audit_runtime_seed(directory, checkpoint, seed, protocol, renderer, native, replicates)
        seed_directories[seed] = directory
        print(json.dumps({'audit_seed_complete': seed, 'worlds_all_arms': 4 * 32 * replicates}), flush=True)
    native_result = native.finish(native_receipt)
    require(native_result['sessions'] == len(seeds) * 4 * 32 * replicates, 'every actual world executed natively')
    work = verify_model_work(run, seeds, runtime_audits, table_audits, protocol, receipt)
    statistics = audit_statistics(seed_directories, table_audits, protocol, read(run / 'report.json'), development)
    artifact_after = verify_artifacts(run, receipt)
    require(artifact_after == artifacts and digest(run / 'run-receipt.json') == receipt_hash
            and digest(args.native_binary) == binary_hash, 'evidence and executable unchanged by audit')
    for name, value in bound.items():
        if not development or name not in provenance['current_development_source_drift']:
            require(digest(repo / name) == hashlib.sha256(value).hexdigest(), ('source changed during independent audit', name))
    strong = {str(seed): runtime_audits[seed]['sibling_evidence']['strong_modality_reallocation_passed'] for seed in seeds}
    return {'schema': 'hepta.modality-allocation.independent-confirmation-audit.v4', 'integrity_passed': True,
        'development': development, 'confirmatory': not development, 'protocol_sha256': PROTOCOL_SHA256,
        'run_receipt_sha256': receipt_hash, 'provenance': provenance, 'artifacts': artifacts,
        'legacy_committed_blobs_preserved': len(legacy), 'native_binary_sha256': binary_hash,
        'four_action_fixture': fixture, 'tables': table_audits, 'runtime': runtime_audits, 'native': native_result,
        'model_work': work, 'statistics': statistics, 'storage_preflight': storage, 'strong_sibling_gate_by_seed': strong,
        'mechanism_gate_passed': bool(not development and fixture['four_actions_physically_executed'] and all(strong.values())),
        'primary_superiority_passed': statistics['independent_estimates']['primary_superiority_passed'],
        'production_runtime_or_attestation_claim': False, 'new_training_claim': False,
        'audit_source_sha256': {path.name: digest(path) for path in Path(__file__).parent.glob('*.py')},
        'audit_work': {'linear_macs': fixture['audit_linear_macs'] + sum(a['audit_forward_linear_macs'] for a in table_audits.values())
                      + sum(a['audit_neural_linear_macs'] for a in runtime_audits.values()),
                      'wall_seconds': time.perf_counter() - started, 'python_process_cpu_seconds': time.process_time() - cpu,
                      'peak_process_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      'scope': 'Independent audit work is additional to all reported experimental costs.'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('repo', 'run', 'source-run', 'native-binary', 'bridge-fixture', 'output'):
        parser.add_argument('--' + option, type=Path, required=True)
    parser.add_argument('--allow-development', action='store_true')
    args = parser.parse_args()
    require(not args.output.exists() and not args.output.resolve().is_relative_to(args.run.resolve())
            and not args.output.resolve().is_relative_to(args.bridge_fixture.resolve()), 'new audit output must be outside immutable evidence inputs')
    failed = False
    try:
        result = audit(args)
    except Exception:
        failed = True
        result = {'schema': 'hepta.modality-allocation.independent-confirmation-audit.v4',
                  'integrity_passed': False, 'mechanism_gate_passed': False, 'primary_superiority_passed': False,
                  'traceback': traceback.format_exc(), 'auditor_sha256': digest(__file__)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        json.dump(result, output, indent=2, allow_nan=False)
        output.write('\n')
    print(json.dumps({key: result[key] for key in ('integrity_passed', 'mechanism_gate_passed', 'primary_superiority_passed')}))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
