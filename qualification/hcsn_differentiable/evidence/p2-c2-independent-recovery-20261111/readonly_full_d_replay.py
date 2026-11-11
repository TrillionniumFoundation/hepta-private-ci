"""Replay four retained C2 best checkpoints on the original full development set."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

STARTED = time.monotonic()
sys.dont_write_bytecode = True
import torch

ROOT = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
FITS = ROOT / 'c2-native-execution-20261110-c385-v1/fits'
PROGRAM = ROOT / 'c2-execution-source-v4-20261110-c385'
SOURCE = ROOT / 'run-source-v8'
NAMES = ['hcsn-s101-lr0.001', 'hcsn-s101-lr0.003', 'hcsn-s211-lr0.003', 'hcsn-s307-lr0.003']


def demand(value, message):
    if not value:
        raise ValueError(message)


def identity(path):
    raw = Path(path).read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)
original_active = []
tokens = {str(PROGRAM / name).encode() for name in ('c2_runner.py', 'c2_controller.py')}
for process in Path('/proc').iterdir():
    if process.name.isdigit():
        try:
            argv = (process / 'cmdline').read_bytes().split(b'\0')
        except (OSError, PermissionError):
            continue
        if any(value in tokens for value in argv):
            original_active.append(int(process.name))
demand(not original_active, 'original C2 process is still running; no concurrent replay')
inputs = {}
for name in NAMES:
    admission = json.loads((FITS / name / 'ADMISSION.json').read_bytes())
    for category in ('inputs', 'program_inputs'):
        for path, expected in admission[category].items():
            demand(path not in inputs or inputs[path] == expected, 'conflicting original identity')
            inputs[path] = expected
    for file in ('best.pt', 'result.json', 'development_logits.pt'):
        path = FITS / name / file
        inputs[str(path)] = identity(path)
for path, expected in inputs.items():
    demand(identity(path) == expected, 'bound input changed before replay: ' + path)
sys.path.insert(0, str(PROGRAM))
from c2_io import bind_study, runtime_identity
study = bind_study(SOURCE)
contract = json.loads((PROGRAM / 'CONTRACT.json').read_bytes())
demand(runtime_identity() == json.loads(Path(contract['runtime_identity_path']).read_bytes()),
       'replay runtime differs from original')
report = {'schema': 'hcsn-c2-four-terminal-full-development-replay-v1',
          'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'original_job': '1a1c74f3308-be2a-75', 'original_live_process_count': len(original_active),
          'new_training_started': False, 'optimizer_steps': 0,
          'confirmation_E_access': False, 'original_artifacts_modified': False,
          'runtime_matches_original': True, 'threads': 1, 'device': 'cpu',
          'fits': [], 'bound_files_count': len(inputs),
          'whole_trajectory_numerical_admission': 'HOLD', 'scientific_admission': 'HOLD'}

for name in NAMES:
    start, cpu = time.monotonic(), time.process_time()
    fit = FITS / name
    plan = json.loads((ROOT / 'campaign-v2' / name / 'plan.json').read_bytes())
    result = json.loads((fit / 'result.json').read_bytes())
    demand(result['status'] == 'completed_development' and result['training_adequacy_established'] is True,
           'candidate is not a reported adequate terminal')
    data, _, manifest = study.read_episodes(plan['prepared'], plan['manifest_sha256'])
    demand(manifest['mode'] == 'all-development' and manifest.get('confirmation_access') is False,
           'prepared data scope changed')
    saved = torch.load(fit / 'development_logits.pt', weights_only=True, map_location='cpu')
    state = torch.load(fit / 'best.pt', weights_only=True, map_location='cpu')
    demand(identity(fit / 'best.pt')['sha256'] == result['best_checkpoint_sha256'], 'best checkpoint hash differs')
    demand(identity(fit / 'development_logits.pt') == result['selected_development_logits'], 'saved logits hash differs')
    model = study.CoreStudyModel(**state['model_configuration'])
    model.load_state_dict(state['model'], strict=True)
    demand(study.sources(model) == result['source_before'], 'actual model source identity differs')
    model.eval()
    values, labels = [], []
    batches = 0
    with torch.no_grad():
        for _, x, dt, y in study.batches(data['dev'], list(range(len(data['dev']))), plan['batch_size']):
            demand(time.monotonic() - STARTED < 840, 'replay time allowance exhausted')
            logits = model(x, dt)
            values.append(logits[y >= 0])
            labels.append(y[y >= 0])
            batches += 1
    actual, y = torch.cat(values), torch.cat(labels)
    demand(saved['episode_ids'] == [row['id'] for row in data['dev']], 'full-D episode identity differs')
    demand(torch.equal(y, saved['labels']), 'full-D labels differ')
    demand(bool(torch.isfinite(actual).all()), 'replay generated nonfinite logits')
    exact = torch.equal(actual, saved['logits'])
    maximum_error = (actual - saved['logits']).abs().max().item()
    demand(exact, 'full-D replay logits are not bitwise equal')
    metrics = study.metrics(actual, y)
    demand(metrics['confusion_matrix'] == result['selected_development']['confusion_matrix'], 'full-D matrix differs')
    demand(metrics['macro_f1_11_classes'] == result['selected_development']['macro_f1_11_classes'], 'full-D macro-F1 differs')
    entry = {'name': name, 'best_checkpoint': identity(fit / 'best.pt'),
             'best_epoch': state['epochs_completed'], 'development_episode_count': len(data['dev']),
             'development_event_count': len(y), 'batches': batches, 'logits_bitwise_equal': exact,
             'maximum_absolute_logit_error': maximum_error, 'labels_and_episode_ids_equal': True,
             'macro_f1_11_classes': metrics['macro_f1_11_classes'], 'accuracy': metrics['accuracy'],
             'wall_seconds': time.monotonic() - start, 'cpu_seconds': time.process_time() - cpu}
    report['fits'].append(entry)
    print(json.dumps({'progress': entry}), flush=True)
    del model, data, values, labels, state, saved, actual, y

for path, expected in inputs.items():
    demand(identity(path) == expected, 'bound input changed during replay: ' + path)
report['bound_inputs_unchanged'] = True
report['all_four_full_D_replay_passed'] = True
report['all_six_original_training_terminal_established'] = False
report['cost'] = {'full_process_wall_seconds_lower_bound': time.monotonic() - STARTED,
                  'process_cpu_seconds_lower_bound': time.process_time(),
                  'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                  'energy_joules': None, 'energy_measured': False,
                  'scope': 'Independent verification overhead; no refund from original training.'}
report['qualification'] = 'HOLD_NO_GO'
print(json.dumps(report, sort_keys=True), flush=True)
