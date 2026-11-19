"""Complete OS envelope for one exact frozen resource-analysis launcher; disabled without root authorization."""
import time
START = time.monotonic()
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import resource
import stat
import sys
import traceback
import zipfile

import os_processes

PROGRAM_SHA = 'f2d1ce683591a9b8575aab2d0981bf67b9e465bf9686a8da2e87a2246a0ea70e'
PLAN_SHA = '4ccfa7cc21ec37312e48d095e8f4b7373c765dd6d33fa9314ce724d161e8b06b'
LIMITS = {'whole_wall_seconds': 120, 'peak_RSS_bytes': 536870912, 'workers': 1, 'threads': 1, 'automatic_retry': False}
RUNTIME = ('complete_os_envelope.py', 'os_processes.py')
MEMBERS = {'MANIFEST.json', 'RESULT.json', 'LONGER-CURVES.json',
           'frozen-original-budget/RESULT.json', 'frozen-original-budget/POINTS.json'}
MAX_BYTES = 64 * 2**20


def require(value, message):
    if not value:
        raise ValueError(message)


def number(value, cap=math.inf):
    require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= cap, 'scalar outside fixed envelope')
    return value


def strict(raw):
    def pairs(rows):
        out = {}
        for key, value in rows:
            require(key not in out, 'duplicate JSON key')
            out[key] = value
        return out
    def invalid(value):
        raise ValueError('nonfinite JSON: ' + value)
    def real(value):
        parsed = float(value)
        require(math.isfinite(parsed), 'nonfinite JSON number')
        return parsed
    require(len(raw) <= MAX_BYTES, 'oversize JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_float=real, parse_constant=invalid)


def raw_id(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def identity(path, budget=lambda: None):
    path = Path(path)
    require(stat.S_ISREG(path.lstat().st_mode), 'regular nonsymlink artifact required: ' + str(path))
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(2**20), b''):
            budget()
            size += len(chunk)
            digest.update(chunk)
    return {'bytes': size, 'sha256': digest.hexdigest()}


def load(path, tracked, budget=lambda: None):
    path = Path(path)
    require(stat.S_ISREG(path.lstat().st_mode), 'regular nonsymlink input required')
    path = path.resolve()
    item = identity(path, budget)
    require(item['bytes'] <= MAX_BYTES, 'metadata file too large')
    raw = path.read_bytes()
    require(raw_id(raw) == item, 'file changed while reading')
    if str(path) in tracked:
        require(tracked[str(path)] == item, 'input changed')
    tracked[str(path)] = item
    return strict(raw), item


def source_manifest(program, tracked, budget):
    manifest, item = load(program / 'MANIFEST.json', tracked, budget)
    require(item['sha256'] == PROGRAM_SHA, 'frozen analysis manifest differs')
    names = {str(p.relative_to(program)) for p in program.rglob('*') if p.is_file()
             and p.name not in ('MANIFEST.json', 'FREEZE.json') and '__pycache__' not in p.parts}
    require(set(manifest['files']) == names, 'frozen program roster differs')
    for name, expected in manifest['files'].items():
        require(not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts, 'unsafe member')
        path = program / name
        require(identity(path, budget) == expected, 'frozen source changed: ' + name)
        tracked[str(path.resolve())] = expected


def authorize(args, tracked, budget):
    auth, auth_id = load(args.authorization, tracked, budget)
    binding, binding_id = load(args.binding, tracked, budget)
    require(auth_id['sha256'] == args.authorization_sha and binding_id['sha256'] == args.binding_sha,
            'exact authorization/binding SHA required')
    require(auth['execution_authorized'] is True and auth['scope'] == 'c2-terminal-resource-metadata-only'
            and auth['confirmation_E_access'] is False and auth['program_manifest_sha256'] == PROGRAM_SHA
            and auth['plan_sha256'] == PLAN_SHA and auth['binding_sha256'] == args.binding_sha, 'analysis authorization differs')
    require(auth['resources'] == {'whole_hard_wall_seconds': 120, 'peak_RSS_bytes': 536870912,
            'workers': 1, 'threads': 1, 'automatic_retry': False}, 'core limits changed')
    require(binding['schema'] == 'c2-resource-input-binding-v1' and binding['all_six_terminal'] is True
            and binding['confirmation_E_access'] is False, 'terminal-only input binding required')
    extra = auth['complete_os_supervisor']
    require(extra['schema'] == 'c2-resource-complete-os-authorization-v1' and extra['execution_authorized'] is True
            and extra['limits'] == LIMITS and extra['metadata_finalization_seconds'] == 30
            and extra['native_whole_seconds'] == 155 and extra['startup_allowance_seconds'] == 5,
            'complete OS authorization or bounds differ')
    require(Path(extra['output_directory']).resolve() == Path(args.output).resolve()
            and Path(extra['core_program_directory']).resolve() == Path(args.program).resolve(), 'authorized path differs')
    directory = Path(__file__).resolve().parent
    require(Path(os_processes.__file__).resolve() == directory / 'os_processes.py', 'loaded process module differs')
    require(set(extra['runtime_sources']) == set(RUNTIME), 'supervisor runtime source roster differs')
    for name in RUNTIME:
        item = identity(directory / name, budget)
        require(item == extra['runtime_sources'][name], 'supervisor source SHA differs: ' + name)
        tracked[str(directory / name)] = item
    require(extra['source_sha256'] == extra['runtime_sources'][RUNTIME[0]]['sha256'], 'supervisor entry pin differs')
    source_manifest(Path(args.program).resolve(), tracked, budget)
    return auth, auth_id, binding_id


def verify_artifacts(output, auth_id, binding_id, tracked, budget):
    paths = {'core_receipt': output / 'core-launch' / 'RECEIPT.json',
             'RESULT': output / 'core-output' / 'RESULT.json', 'ZIP': output / 'core-output.zip'}
    core, core_id = load(paths['core_receipt'], tracked, budget)
    result, result_id = load(paths['RESULT'], tracked, budget)
    archive_id = identity(paths['ZIP'], budget)
    tracked[str(paths['ZIP'].resolve())] = archive_id
    require(archive_id['bytes'] <= MAX_BYTES, 'oversize metadata archive')
    with zipfile.ZipFile(paths['ZIP']) as archive:
        infos = archive.infolist()
        require(len(infos) == len(MEMBERS) and {i.filename for i in infos} == MEMBERS
                and sum(i.file_size for i in infos) <= MAX_BYTES, 'archive roster or size differs')
        require(all(not i.is_dir() and stat.S_IFMT(i.external_attr >> 16) in (0, stat.S_IFREG)
                    for i in infos), 'nonregular archive member')
        members = {}
        for name in sorted(MEMBERS):
            budget()
            raw = archive.read(name)  # Full member read verifies CRC, bounded by aggregate MAX_BYTES.
            members[name] = raw_id(raw)
            if name == 'MANIFEST.json':
                manifest = strict(raw)['files']
        require(manifest == {k: v for k, v in members.items() if k != 'MANIFEST.json'}, 'member manifest mismatch')
    require(members['RESULT.json'] == result_id, 'standalone RESULT differs from archive')
    require(core['schema'] == 'c2-resource-analysis-launch-v1' and core['status'] == 'completed'
            and core['process_started'] is True and core['spawn_attempted'] is True and core['returncode'] == 0
            and core['archive_finalized'] is True and core['child_CPU_complete'] is True
            and core['CPU_unknown_or_lower_bound'] is False and core.get('child_terminal_unknown', False) is False,
            'core terminal or CPU incomplete')
    require(core['whole_hard_wall_seconds'] == 120 and core['peak_RSS_limit_bytes'] == LIMITS['peak_RSS_bytes']
            and core['workers'] == core['threads'] == 1, 'core declared envelope differs')
    number(core['whole_wall_seconds'], 120)
    number(core['exact_waited_child_CPU_seconds'])
    for key in ('sampled_child_peak_RSS_bytes', 'exact_waited_child_peak_RSS_bytes', 'own_peak_RSS_bytes'):
        number(core[key], LIMITS['peak_RSS_bytes'])
    require(core['archive'] == archive_id and core['RESULT'] == result_id and core['members'] == len(MEMBERS)
            and core['CRC_all_members_manifest_verified'] is True, 'core artifact bindings differ')
    require(result['schema'] == 'c2-longer-resource-metadata-analysis-v1'
            and result['execution_status'] in ('completed_metadata', 'completed_metadata_with_explicit_holds')
            and result['inputs_unchanged'] is True and result['program_manifest_before'] ==
            result['program_manifest_after'] == PROGRAM_SHA, 'result source/input status differs')
    require(core['authorization'] == result['authorization_identity'] == auth_id
            and core['binding'] == result['binding_identity'] == binding_id
            and core['result_status'] == result['execution_status'], 'input/terminal bindings differ')
    require(result['confirmation_E_access'] is False and all(type(result[k]) is int and result[k] == 0
            for k in ('training_steps', 'forward_calls', 'backward_calls', 'numerical_oracle_calls')), 'execution scope differs')
    require(len(result['candidates']) == 42 and len({r['name'] for r in result['candidates']}) == 42, 'candidate roster incomplete')
    number(result['worker_self_peak_RSS_bytes'], LIMITS['peak_RSS_bytes'])
    for path, expected in result['input_identities'].items():
        require(identity(path, budget) == expected, 'worker input changed: ' + path)
        require(path not in tracked or tracked[path] == expected, 'cross-record input mismatch')
        tracked[path] = expected
    return ({'core_receipt': core_id, 'RESULT': result_id, 'ZIP': archive_id},
            {key: str(path.resolve()) for key, path in paths.items()}, core)


def run(args):
    output, tracked, tree, reaped_at = Path(args.output), {}, None, None
    output.mkdir(parents=True, exist_ok=False)
    row = {'schema': 'c2-resource-analysis-complete-os-envelope-v1', 'status': 'not_completed',
           'limits': LIMITS, 'process_started': False, 'returncode': None, 'timed_out': False,
           'child_terminal_unknown': False, 'unreaped_descendants': False, 'source_inputs_unchanged': False,
           'whole_child_wall_seconds': None, 'wait4_child_CPU_seconds': None,
           'wait4_peak_RSS_bytes': None, 'sampled_peak_RSS_bytes': None, 'artifacts': {},
           'program_manifest_sha256': PROGRAM_SHA, 'started_utc': datetime.now(timezone.utc).isoformat(),
           'scientific_admission': 'HOLD', 'whole_training_numerical_admission': 'HOLD'}
    entry = Path(__file__).resolve()
    row['supervisor_source_sha256'] = row['supervisor_source_sha256_before'] = identity(entry)['sha256']
    deadline = START + 5
    def budget():
        require(time.monotonic() <= deadline, 'supervisor startup/finalization budget exceeded')
        require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024 <= LIMITS['peak_RSS_bytes'], 'supervisor RSS exceeded')
    try:
        auth, auth_id, binding_id = authorize(args, tracked, budget)
        argv = [sys.executable, '-B', str(Path(args.program).resolve() / 'launch_analysis.py'),
                '--authorization', str(Path(args.authorization).resolve()), '--authorization-sha', args.authorization_sha,
                '--binding', str(Path(args.binding).resolve()), '--binding-sha', args.binding_sha,
                '--output', str(output.resolve() / 'core-output'), '--launch-directory', str(output.resolve() / 'core-launch')]
        env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                   NUMEXPR_NUM_THREADS='1', CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1')
        (output / 'INTENT.json').write_text(json.dumps({'argv': argv, 'authorization': auth_id, 'binding': binding_id,
            'limits': LIMITS, 'source_before': tracked}, indent=2, sort_keys=True) + '\n')
        budget()
        observed, tree = os_processes.observe(argv, output, env, 120, LIMITS['peak_RSS_bytes'], launch_deadline=START+5)
        reaped_at = observed['wait4_completed_monotonic'] or time.monotonic()
        deadline = min(START + 155, reaped_at + 30)
        row.update(observed)
        require(row['process_gate_passed'] and row['direct_child_CPU_complete'] is True
                and row['total_attempt_CPU_unknown_or_lower_bound'] is False and not row['adopted_child_wait4'],
                'complete OS child, descendant, or CPU-completeness gate failed admission')
        artifacts, paths, core = verify_artifacts(output, auth_id, binding_id, tracked, budget)
        require(core['whole_wall_seconds'] <= row['whole_child_wall_seconds'], 'inner prefix exceeds complete child wall')
        row.update(artifacts=artifacts, artifact_paths=paths, authorization=auth_id, binding=binding_id)
        source_manifest(Path(args.program).resolve(), tracked, budget)
        for path, expected in tracked.items():
            require(identity(path, budget) == expected, 'source/input/artifact changed at finalization: ' + path)
        row['supervisor_source_sha256_after'] = identity(entry, budget)['sha256']
        require(row['supervisor_source_sha256_before'] == row['supervisor_source_sha256_after'], 'supervisor source changed')
        budget()
        row.update(source_inputs_unchanged=True, status='completed')
    except Exception:
        row.update(status='not_admitted', error=traceback.format_exc(), source_inputs_unchanged=False)
    finally:
        if tree is not None:
            try:
                scan = tree.scan()  # Final scan follows all artifact and source verification.
                row['process_observations']['after_cleanup'] = scan
                row['process_observations']['unreadable'] = tree.unreadable
                if tree.unreadable or any(scan[k] for k in
                        ('same_group_pids', 'tracked_live_descendants', 'adopted_children', 'scan_errors')):
                    row.update(status='not_admitted', unreaped_descendants=True, total_attempt_CPU_unknown_or_lower_bound=True)
            except Exception:
                row.update(status='not_admitted', descendant_terminal_unknown=True,
                           total_attempt_CPU_unknown_or_lower_bound=True, process_final_scan_error=traceback.format_exc())
        row.setdefault('supervisor_source_sha256_after', None)
        if not row.get('direct_child_CPU_complete', False) or row.get('total_attempt_CPU_unknown_or_lower_bound', True):
            row['status'] = 'not_admitted'
        row.update(source_and_input_identities=tracked, finished_utc=datetime.now(timezone.utc).isoformat(),
                   supervisor_main_wall_prefix_seconds=time.monotonic()-START,
                   supervisor_CPU_prefix_seconds=time.process_time(),
                   metadata_finalization_wall_prefix_seconds=time.monotonic()-reaped_at if reaped_at else None,
                   supervisor_peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                   supervisor_cost_scope='Self prefix through final checks; receipt serialization and supervisor OS exit excluded. A separate native <=155s terminal receipt is required.',
                   child_cost_scope='Popen-before to actual wait4-after, including core import, verification, receipt writing and OS exit. Core receipt whole_wall_seconds remains its earlier prefix.')
        if row['supervisor_main_wall_prefix_seconds'] > 155 or row['supervisor_peak_RSS_bytes'] > LIMITS['peak_RSS_bytes'] or (
                row['metadata_finalization_wall_prefix_seconds'] is not None
                and row['metadata_finalization_wall_prefix_seconds'] > 30):
            row['status'] = 'not_admitted'
        with (output / 'OS-RECEIPT.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(row, indent=2, sort_keys=True, allow_nan=False) + '\n')
    return row


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('authorization', 'authorization-sha', 'binding', 'binding-sha', 'program', 'output'):
        parser.add_argument('--' + key, required=True)
    receipt = run(parser.parse_args())
    raise SystemExit(0 if receipt['status'] == 'completed' else 2)
