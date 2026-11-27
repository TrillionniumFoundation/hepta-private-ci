"""Freeze six real C2 epoch states, run bounded fresh-process replay and audit it."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from checkpoint_replay import digest, require, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-root', required=True)
    parser.add_argument('--study-source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--selection', required=True)
    parser.add_argument('--selection-sha256', required=True)
    args = parser.parse_args()
    started = time.monotonic()
    output = Path(args.output)
    output.mkdir(exist_ok=False)
    (output / 'inputs').mkdir()
    source_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(source_root / 'c2_successor_v1'))
    import torch
    from c2_io import state_equal, semantic_digest
    original_root = Path(args.original_root)
    original_training = original_root.parent
    worker = Path(__file__).with_name('checkpoint_replay.py')
    program_paths = [worker, Path(__file__).resolve(),
        source_root / 'c2_successor_v1/c2_io.py', source_root / 'c2_successor_v1/c2_boundary.py',
        source_root / 'recovery_v1/c2_durable.py']
    selection_path = Path(args.selection)
    require(digest(selection_path)['sha256'] == args.selection_sha256, 'selection bytes differ')
    selection = json.loads(selection_path.read_bytes())
    require(selection['schema'] == 'hcsn-real-checkpoint-replay-selection-v1'
            and len(selection['fits']) == 6
            and len({row['fit'] for row in selection['fits']}) == 6, 'six fixed source selections required')
    program_paths.append(selection_path)
    plan = {'schema': 'hcsn-real-checkpoint-replay-plan-v1', 'steps': 2,
        'confirmation_access': False, 'scientific_admission': 'HOLD_NO_GO',
        'worker_wall_seconds': 300, 'workers': 2, 'threads_per_worker': 1,
        'torch_version': torch.__version__, 'torch_build': torch.version.git_version,
        'study_source': args.study_source,
        'python': sys.executable, 'program_inputs': {str(path): digest(path) for path in program_paths},
        'original_c2_job_id': '1a1c74f3308-be2a-75', 'original_c2_restarted': False,
        'independent_complete_training_replays_added': 0, 'fits': []}
    for selected in selection['fits']:
        fit = original_root / 'fits' / selected['fit']
        checkpoint = Path(selected['path'])
        require(checkpoint.parent == fit / 'checkpoints', 'selected checkpoint escaped original fit')
        expected = digest(checkpoint)
        require(expected == selected['identity'], 'selected checkpoint differs from preflight commitment')
        commit_path = fit / 'commits' / (checkpoint.stem + '.json')
        commit = json.loads(commit_path.read_bytes())
        require(expected['bytes'] > 0 and commit['checkpoint'] == expected,
                'selected complete checkpoint has no matching commit')
        frozen = output / 'inputs' / (fit.name + '.pt')
        with frozen.open('xb') as target, checkpoint.open('rb') as original:
            target.write(original.read())
            target.flush()
            os.fsync(target.fileno())
        require(digest(checkpoint) == digest(frozen) == expected, 'checkpoint changed while freezing')
        parent = original_training / 'campaign-v2' / fit.name
        prior_path, training_plan_path = parent / 'result.json', parent / 'plan.json'
        prior = json.loads(prior_path.read_bytes())
        require(digest(training_plan_path)['sha256'] == prior['plan_sha256'], 'original plan differs')
        training_plan = json.loads(training_plan_path.read_bytes())
        prepared = Path(training_plan['prepared'])
        manifest_path = prepared / 'data-manifest.json'
        require(digest(manifest_path)['sha256'] == training_plan['manifest_sha256'], 'data manifest differs')
        manifest = json.loads(manifest_path.read_bytes())
        inputs = {str(frozen): expected, str(commit_path): digest(commit_path),
            str(prior_path): digest(prior_path), str(training_plan_path): digest(training_plan_path),
            str(manifest_path): digest(manifest_path)}
        for path, expected_sha in prior['source_before'].items():
            observed = digest(path)
            require(observed['sha256'] == expected_sha, 'original model source has changed: ' + path)
            inputs[path] = observed
        for name, field in [('selection.json', 'selection_sha256'), ('frontend.json', 'frontend_sha256')]:
            observed = digest(prepared / name)
            require(observed['sha256'] == manifest[field], 'prepared auxiliary bytes differ')
            inputs[str(prepared / name)] = observed
        for episode in manifest['episodes']:
            require(episode['partition'] in ('train', 'dev'), 'confirmation episodes forbidden')
            path = (prepared / episode['path']).resolve()
            require(path.is_relative_to(prepared.resolve()), 'prepared episode escapes root')
            observed = digest(path)
            require(observed['sha256'] == episode['sha256'], 'prepared episode differs')
            inputs[str(path)] = observed
        plan['fits'].append({'fit': fit.name, 'checkpoint': str(frozen),
            'checkpoint_identity': expected, 'original_checkpoint': str(checkpoint),
            'expected_epoch': selected['epoch'], 'expected_main_updates': selected['logical_main_updates'],
            'training_plan': str(training_plan_path), 'inputs': inputs,
            'model_sources': prior['source_before']})
    require(len(plan['fits']) == 6, 'must freeze all six C2 fit states')
    plan_path = output / 'PREEXECUTION.json'
    write_json(plan_path, plan)
    plan_sha = digest(plan_path)['sha256']
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
        PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0', CUDA_VISIBLE_DEVICES='')

    def launch(index, mode, label=None, resume=None, omit_optimizer=False):
        name = plan['fits'][index]['fit']
        destination = output / name / (label or mode)
        destination.parent.mkdir(exist_ok=True)
        command = [sys.executable, '-B', str(worker), '--plan', str(plan_path),
            '--plan-sha256', plan_sha, '--fit-index', str(index), '--mode', mode,
            '--output', str(destination)]
        if resume:
            command += ['--resume-checkpoint', str(resume), '--resume-sha256', digest(resume)['sha256']]
        if omit_optimizer:
            command += ['--omit-optimizer-state']
        before = time.monotonic()
        with (destination.parent / ((label or mode) + '.stdout')).open('xb') as stdout, \
                (destination.parent / ((label or mode) + '.stderr')).open('xb') as stderr:
            process = subprocess.run(command, stdout=stdout, stderr=stderr, env=env, timeout=330)
        receipt = {'command': command, 'returncode': process.returncode,
            'outer_wall_seconds': time.monotonic() - before, 'mode': mode, 'fit': name}
        write_json(destination.parent / ((label or mode) + '.EXIT.json'), receipt)
        require(process.returncode == (73 if mode == 'crash' else 0), 'replay child failed: ' + str(destination))
        return destination

    def run_fit(index):
        reference = launch(index, 'reference')
        producer = launch(index, 'producer')
        resumed = launch(index, 'resume', resume=producer / 'state.pt')
        reference_state = torch.load(reference / 'state.pt', map_location='cpu', weights_only=True)
        resumed_state = torch.load(resumed / 'state.pt', map_location='cpu', weights_only=True)
        require(state_equal(reference_state, resumed_state), 'real model/Adam/RNG/cursor continuation differs')
        reports = {name: json.loads((path / 'RESULT.json').read_bytes())
            for name, path in [('reference', reference), ('producer', producer), ('resume', resumed)]}
        require(reports['reference']['steps'] == reports['producer']['steps'] + reports['resume']['steps'],
                'actual loss/gradient/batch receipts differ')
        return {'fit': plan['fits'][index]['fit'], 'full_state_equal': True,
            'model_equal': state_equal(reference_state['state']['model'], resumed_state['state']['model']),
            'optimizer_equal': state_equal(reference_state['state']['optimizer'], resumed_state['state']['optimizer']),
            'rng_and_cursor_equal': state_equal(reference_state['cursor'], resumed_state['cursor'])
                and state_equal(reference_state['state']['torch_rng'], resumed_state['state']['torch_rng'])
                and state_equal(reference_state['state']['order_rng'], resumed_state['state']['order_rng']),
            'semantic_sha256': semantic_digest(reference_state), 'worker_reports': reports,
            'actual_optimizer_steps': 4, 'independent_complete_training_replay': False}

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(run_fit, range(6)))
    producer = output / plan['fits'][0]['fit'] / 'producer' / 'state.pt'
    negative = launch(0, 'resume', label='negative-omit-adam', resume=producer, omit_optimizer=True)
    negative_state = torch.load(negative / 'state.pt', map_location='cpu', weights_only=True)
    reference_state = torch.load(output / plan['fits'][0]['fit'] / 'reference/state.pt', map_location='cpu', weights_only=True)
    require(not state_equal(negative_state['state']['optimizer'], reference_state['state']['optimizer'])
            and not state_equal(negative_state['state']['model'], reference_state['state']['model']),
            'missing-Adam-state negative control failed to differ')
    crash = launch(0, 'crash')
    require(not (crash / 'state.pt').exists(), 'prepublication crash exposed a canonical checkpoint')
    orphans = list(crash.glob('.c2-pending-*'))
    require(len(orphans) == 1 and digest(orphans[0])['bytes'] > 0, 'actual serialized crash artifact missing')
    orphan = torch.load(orphans[0], map_location='cpu', weights_only=True)
    require(state_equal(orphan, torch.load(producer, map_location='cpu', weights_only=True)),
            'crash temporary did not retain the real one-step state')
    for name, expected in plan['program_inputs'].items():
        require(digest(name) == expected, 'replay program mutated')
    summary = {'schema': 'hcsn-real-checkpoint-replay-summary-v1', 'plan_sha256': plan_sha,
        'completed_recovery_diagnostics': len(rows), 'rows': rows,
        'negative_omit_adam_detected': True, 'crash_before_publication_rejected': True,
        'actual_optimizer_steps_total': 26, 'new_independent_complete_training_replays': 0,
        'original_c2_completion_claimed': False, 'scientific_admission': 'HOLD_NO_GO',
        'whole_orchestrator_wall_seconds': time.monotonic() - started,
        'timing_scope': 'worker outer intervals overlap; do not sum as elapsed wall'}
    write_json(output / 'SUMMARY.json', summary)
    print(json.dumps({'completed': 6, 'steps': 26, 'summary': str(output / 'SUMMARY.json')}, sort_keys=True))


if __name__ == '__main__':
    main()
