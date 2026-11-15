"""Run the real checkpoint diagnostic under an explicit independent CPU profile."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from checkpoint_replay import digest, require, write_json
from cpu_migration import (ARCHIVE_BYTES, ARCHIVE_SHA256, NATIVE_PREEXECUTION_SHA256,
                           assemble_parts, derive_cpu_plan, extract_verified, object_json)

FROZEN_EXECUTABLES = {
    'checkpoint_replay.py': '9fc8d5cc1541643ea46c3c9ef159a56e70ce1f2be20329ed2fd31185c86b7d9a',
    'c2_io.py': '355712a5b5c1fd9d3413988fa52832aaa97e2da3b417d8961f0ae19b2324fddb',
    'c2_boundary.py': '177a23a3d0502a79912efdd2a14a365bc716961698a6949bb45d380ba147e6dd',
    'c2_durable.py': 'c02d45119837c1b25a4b6ee0788b0c638718486c0301a8e90c5aa6d1f6252157',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parts-manifest', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    require(sys.version_info[:3] == (3, 12, 3), 'CPU profile requires the declared Python 3.12.3')
    started = time.monotonic()
    out = Path(args.output).resolve()
    out.mkdir(exist_ok=False)
    archive = assemble_parts(args.parts_manifest, out / 'original-export.zip',
        {'bytes': ARCHIVE_BYTES, 'sha256': ARCHIVE_SHA256})
    index = extract_verified(archive, out / 'original', {'bytes': ARCHIVE_BYTES, 'sha256': ARCHIVE_SHA256})
    candidates = [item for item in index['files'] if item['sha256'] == NATIVE_PREEXECUTION_SHA256
                  and item['original_path'].endswith('/PREEXECUTION.json')]
    require(len(candidates) == 1, 'exact original native plan not found')
    native_path = out / 'original' / candidates[0]['member']
    native = object_json(native_path.read_bytes())
    source = Path(__file__).resolve().parent
    domain = source.parent
    programs = [source / 'checkpoint_replay.py', Path(__file__).resolve(), source / 'cpu_migration.py',
        domain / 'c2_successor_v1/c2_io.py', domain / 'c2_successor_v1/c2_boundary.py',
        domain / 'recovery_v1/c2_durable.py', source / 'SELECTION.json', native_path]
    for path in programs:
        if path.name in FROZEN_EXECUTABLES:
            require(digest(path)['sha256'] == FROZEN_EXECUTABLES[path.name], 'frozen native executable differs')
    import torch
    torch.set_num_threads(1)
    runtime = {'executable': sys.executable, 'python': sys.version, 'platform': platform.platform(),
        'torch_version': torch.__version__, 'torch_build': torch.version.git_version,
        'cuda_build': torch.version.cuda}
    selection = object_json((source / 'SELECTION.json').read_bytes())
    plan = derive_cpu_plan(native, index, out / 'original', out / 'derived-training-plans',
        programs, Path(torch.__file__).resolve().parent, runtime, selection)
    plan.update(worker_wall_seconds=600, workers=2, threads_per_worker=1)
    plan['profile_amendment']['resource_amendment'] = {
        'native_worker_wall_seconds': native['worker_wall_seconds'], 'cpu_worker_wall_seconds': 600,
        'outer_worker_timeout_seconds': 660, 'workers': 2, 'threads_per_worker': 1,
        'claim': 'new CPU recovery profile, no original CUDA budget or performance qualification inherited'}
    plan_path = out / 'CPU-PREEXECUTION.json'
    write_json(plan_path, plan)
    plan_sha = digest(plan_path)['sha256']
    sys.path.insert(0, str(domain / 'c2_successor_v1'))
    from c2_io import state_equal, semantic_digest
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
        PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0', CUDA_VISIBLE_DEVICES='')

    def launch(index, mode, label=None, resume=None, omit=False):
        destination = out / plan['fits'][index]['fit'] / (label or mode)
        destination.parent.mkdir(exist_ok=True)
        command = [sys.executable, '-B', str(source / 'checkpoint_replay.py'), '--plan', str(plan_path),
            '--plan-sha256', plan_sha, '--fit-index', str(index), '--mode', mode, '--output', str(destination)]
        if resume:
            command += ['--resume-checkpoint', str(resume), '--resume-sha256', digest(resume)['sha256']]
        if omit:
            command += ['--omit-optimizer-state']
        before = time.monotonic()
        receipt = {'command': command, 'mode': mode, 'returncode': None, 'timed_out': False}
        try:
            with destination.with_suffix('.stdout').open('xb') as stdout, destination.with_suffix('.stderr').open('xb') as stderr:
                process = subprocess.run(command, env=env, stdout=stdout, stderr=stderr, timeout=660)
            receipt['returncode'] = process.returncode
        except subprocess.TimeoutExpired:
            receipt['timed_out'] = True
        finally:
            receipt['outer_wall_seconds'] = time.monotonic() - before
            receipt['optimizer_steps_if_no_worker_result'] = 'UNKNOWN'
            write_json(destination.with_suffix('.EXIT.json'), receipt)
        require(receipt['returncode'] == (73 if mode == 'crash' else 0), 'CPU worker failed: ' + str(destination))
        return destination

    def run_fit(index):
        try:
            reference = launch(index, 'reference')
            producer = launch(index, 'producer')
            resumed = launch(index, 'resume', resume=producer / 'state.pt')
            expected = torch.load(reference / 'state.pt', map_location='cpu', weights_only=True)
            actual = torch.load(resumed / 'state.pt', map_location='cpu', weights_only=True)
            require(state_equal(expected, actual), 'CPU full decoded continuation differs')
            reports = [object_json((path / 'RESULT.json').read_bytes()) for path in (reference, producer, resumed)]
            require(reports[0]['steps'] == reports[1]['steps'] + reports[2]['steps'], 'CPU loss/gradient/batch receipts differ')
            return {'fit': plan['fits'][index]['fit'], 'complete': True, 'full_state_equal': True,
                'semantic_sha256': semantic_digest(expected), 'current_attempt_verified_optimizer_calls': 4,
                'worker_reports': reports}
        except Exception as error:
            return {'fit': plan['fits'][index]['fit'], 'complete': False, 'error': repr(error),
                    'actual_optimizer_calls': 'UNKNOWN'}

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(run_fit, range(6)))
    write_json(out / 'FIT-RESULTS.json', {'rows': rows})
    require(all(row['complete'] for row in rows), 'six CPU continuations did not all complete')
    first = out / plan['fits'][0]['fit']
    producer = first / 'producer/state.pt'
    expected = torch.load(first / 'reference/state.pt', map_location='cpu', weights_only=True)
    negative = launch(0, 'resume', label='negative-omit-adam', resume=producer, omit=True)
    negative_state = torch.load(negative / 'state.pt', map_location='cpu', weights_only=True)
    require(not state_equal(expected['state']['model'], negative_state['state']['model'])
            and not state_equal(expected['state']['optimizer'], negative_state['state']['optimizer']),
            'omit-Adam negative control did not differ')
    crash = launch(0, 'crash')
    require(not (crash / 'state.pt').exists(), 'crash exposed a canonical checkpoint')
    orphans = list(crash.glob('.c2-pending-*'))
    require(len(orphans) == 1 and state_equal(torch.load(orphans[0], map_location='cpu', weights_only=True),
        torch.load(producer, map_location='cpu', weights_only=True)), 'actual crash temporary differs')
    for path, expected_identity in plan['program_inputs'].items():
        require(digest(path) == expected_identity, 'CPU source changed')
    summary = {'schema': 'hcsn-cpu-checkpoint-replay-summary-v1', 'plan_sha256': plan_sha,
        'complete_checkpoint_continuities': 6, 'current_attempt_verified_optimizer_calls': 26,
        'lifetime_total_optimizer_calls': 'UNKNOWN', 'original_native_attempt_optimizer_calls': 'UNKNOWN',
        'new_independent_complete_training_replays': 0, 'scientific_admission': 'HOLD_NO_GO',
        'omit_adam_control_detected': True, 'crash_before_publication_rejected': True,
        'whole_wall_seconds': time.monotonic() - started, 'rows': rows,
        'timing_scope': 'overlapping worker wall times are not additive elapsed wall'}
    write_json(out / 'SUMMARY.json', summary)
    print(json.dumps({key: value for key, value in summary.items() if key != 'rows'}, sort_keys=True))


if __name__ == '__main__':
    main()
