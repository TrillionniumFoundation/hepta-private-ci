"""Read-only C2 original-state audit; no optimization or original artifact writes."""
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import random
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


def identity(path):
    raw = Path(path).read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def demand(condition, detail):
    if not condition:
        raise ValueError(detail)


def plateau(rows, delta, minimum, patience):
    best = anchor = -1.0
    stale = 0
    best_epoch = first_stop = None
    for number, row in enumerate(rows, 1):
        demand(row['epoch'] == number and row['complete'] is True, 'noncontiguous epochs')
        score = row['development']['macro_f1_11_classes']
        demand(math.isfinite(score) and 0 <= score <= 1, 'nonfinite or invalid score')
        if score > best:
            best, best_epoch = score, number
        if score > anchor + delta:
            anchor, stale = score, 0
        else:
            stale += 1
        if first_stop is None and number >= minimum and stale >= patience:
            first_stop = number
    return {'best': best, 'best_epoch': best_epoch, 'plateau_anchor': anchor,
            'stale_epochs': stale}, first_stop


def metric_audit(path, reported):
    payload = torch.load(path, weights_only=True, map_location='cpu')
    z, y = payload['logits'], payload['labels']
    demand(z.ndim == 2 and z.shape == (len(y), 11), 'invalid logits shape')
    demand(bool(torch.isfinite(z).all()) and bool(((y >= 0) & (y < 11)).all()), 'invalid logits/labels')
    prediction = z.argmax(-1)
    matrix = torch.bincount(y * 11 + prediction, minlength=121).reshape(11, 11)
    m = matrix.double()
    denominator = m.sum(0) + m.sum(1)
    f1 = torch.where(denominator > 0, 2 * m.diag() / denominator, 0).mean().item()
    probability = z.softmax(-1)
    onehot = torch.nn.functional.one_hot(y, 11).to(z.dtype)
    values = {'macro_f1_11_classes': f1, 'accuracy': (prediction == y).double().mean().item(),
              'nll': torch.nn.functional.cross_entropy(z, y).item(),
              'brier_half_sum': ((probability - onehot).square().sum(-1) / 2).mean().item()}
    demand(matrix.tolist() == reported['confusion_matrix'], 'saved-logit confusion matrix differs')
    error = {key: abs(value - reported[key]) for key, value in values.items()}
    demand(all(value <= 1e-12 for value in error.values()), 'saved-logit metric differs')
    demand(len(y) == reported['events'], 'saved-logit event count differs')
    return {'identity': identity(path), 'events': len(y), 'episode_ids': payload['episode_ids'],
            'metrics': values, 'absolute_errors': error, 'confusion_matrix_equal': True,
            'model_forward_performed': False}


torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)
report = {'schema': 'hcsn-c2-independent-readonly-checkpoint-audit-v1',
          'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'original_training_job': '1a1c74f3308-be2a-75', 'new_training_started': False,
          'original_artifacts_modified': False, 'model_forward_performed': False,
          'root': str(ROOT), 'fits': [], 'runtime': {'python': sys.version,
          'torch': torch.__version__, 'torch_git_version': torch.version.git_version,
          'cuda_build': torch.version.cuda, 'cpu_count': os.cpu_count(),
          'load_average': os.getloadavg(), 'meminfo': {
              line.split(':')[0]: line.split(':')[1].strip()
              for line in Path('/proc/meminfo').read_text().splitlines()
              if line.split(':')[0] in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree')}}}
admissions = {fit.name: json.loads((fit / 'ADMISSION.json').read_bytes())
              for fit in sorted(FITS.iterdir()) if fit.is_dir()}
inputs = {}
for admission in admissions.values():
    for key in ('inputs', 'program_inputs'):
        for name, expected in admission[key].items():
            demand(name not in inputs or inputs[name] == expected, 'conflicting original identity')
            inputs[name] = expected
verified_bytes = 0
for name, expected in inputs.items():
    demand(identity(name) == expected, 'original bound input changed: ' + name)
    verified_bytes += expected['bytes']
report['bound_original_inputs'] = {'verified_files': len(inputs), 'verified_bytes': verified_bytes,
                                  'all_match': True}
sys.path.insert(0, str(PROGRAM))
from c2_io import bind_study, runtime_identity
from c2_boundary import validate_checkpoint
study = bind_study(SOURCE)
runtime_path = PROGRAM / 'CONTRACT.json'
contract = json.loads(runtime_path.read_bytes())
report['original_runtime_identity_equal'] = runtime_identity() == json.loads(Path(contract['runtime_identity_path']).read_bytes())
demand(report['original_runtime_identity_equal'], 'original runtime identity changed')

for name, admission in admissions.items():
    fit = FITS / name
    parent = ROOT / 'campaign-v2' / name
    plan = json.loads((parent / 'plan.json').read_bytes())
    prior = json.loads((parent / 'result.json').read_bytes())
    initial = torch.load(parent / 'initial.pt', weights_only=True, map_location='cpu')
    rows = list(admission['boundary']['logical_epochs'])
    previous = None
    commits = sorted((fit / 'commits').glob('epoch-*.json'))
    for path in commits:
        commit = json.loads(path.read_bytes())
        demand(commit['previous_commit'] == previous, 'broken immutable commit chain')
        demand(identity(commit['checkpoint_path']) == commit['checkpoint'], 'epoch checkpoint changed')
        demand(identity(commit['best_path']) == commit['best_checkpoint'], 'strict best checkpoint changed')
        demand(commit['epoch']['epoch'] == len(rows) + 1, 'noncontiguous epoch commit')
        rows.append(commit['epoch'])
        previous = {'path': str(path), **identity(path)}
    demand(bool(commits), 'no immutable C2 epoch commits')
    stopping, first_stop = plateau(rows, plan['plateau_delta'], plan['min_epochs'], plan['patience'])
    demand(commit['stopping'] == stopping, 'last commit stopping state differs from independent calculation')
    states = {}
    for slot, expected in [('last', commit['checkpoint']), ('best', commit['best_checkpoint'])]:
        path = fit / (slot + '.pt')
        demand(identity(path) == expected, slot + ' alias differs from immutable commit')
        state = torch.load(path, weights_only=True, map_location='cpu')
        expected_epoch = len(rows) if slot == 'last' else stopping['best_epoch']
        expected_updates = expected_epoch * admission['boundary']['work']['steps_per_epoch']
        validate_checkpoint(state, prior['model_configuration'], expected_updates, expected_epoch,
                            initial, study.CoreStudyModel, study.adamw, plan['learning_rate'])
        order = random.Random(plan['seed'])
        for _ in range(expected_epoch):
            indices = list(range(prior['episodes_train']))
            order.shuffle(indices)
        demand(order.getstate() == state['order_rng'], 'checkpoint order RNG differs from epoch schedule')
        states[slot] = {'identity': expected, 'epoch': state['epochs_completed'],
                        'main_updates': state['main_updates'], 'optimizer_model_rng_valid': True}
    events = []
    journal_errors = []
    raw_lines = (fit / 'events.jsonl').read_bytes().splitlines()
    for line_number, line in enumerate(raw_lines, 1):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as error:
            demand(line_number == len(raw_lines), 'non-final journal corruption')
            journal_errors.append({'line': line_number, 'error': str(error)})
    complete_rows = [row for row in events if row['kind'] == 'epoch_completed']
    demand(len(complete_rows) == len(commits), 'complete-epoch journal/commit counts differ')
    for journal_row, path in zip(complete_rows, commits):
        demand({key: value for key, value in journal_row.items() if key not in ('kind', 'commit')}
               == json.loads(path.read_bytes())['epoch'], 'epoch journal and immutable commit differ')
        demand(journal_row['commit'] == {'path': str(path), **identity(path)}, 'journal commit identity differs')
    result_path = fit / 'result.json'
    outcome = {'name': name, 'checkpoint_validation': states,
               'commit_chain_count': len(commits), 'complete_epoch_journal_matches': True,
               'stopping_policy': {key: plan[key] for key in ('min_epochs', 'patience', 'plateau_delta')},
               'recomputed_stopping': stopping, 'first_plateau_epoch': first_stop,
               'last_event_kind': events[-1]['kind'], 'result_present': result_path.exists(),
               'journal_errors': journal_errors, 'journal_identity': identity(fit / 'events.jsonl'),
               'scientific_admission': 'HOLD', 'whole_trajectory_numerical_admission': 'HOLD'}
    if result_path.exists():
        demand(not journal_errors, 'producer result exists with corrupted terminal journal')
        result = json.loads(result_path.read_bytes())
        demand(result['stopping'] == stopping and result['cumulative_epochs_completed'] == len(rows),
               'producer result differs from independent commit reconstruction')
        demand(first_stop == len(rows), 'producer did not stop at first prescribed plateau')
        demand(result['inherited_memorization'] == prior['memorization'], 'memorization diagnostic differs')
        demand(result['training_adequacy_established'] is True and prior['memorization']['passed'] is True,
               'producer adequacy has no prescribed diagnostic/plateau support')
        demand(events[-1]['kind'] == 'finished' and events[-1]['status'] == result['status'],
               'producer terminal journal differs')
        outcome['producer_terminal_reconciled'] = True
        outcome['stored_full_D_logit_metrics'] = metric_audit(fit / 'development_logits.pt', result['selected_development'])
    else:
        outcome['producer_terminal_reconciled'] = False
        outcome['no_resume_admission'] = 'Original terminal, cause and full exit cost remain unknown.'
        outcome['zero_byte_files'] = [path.name for path in fit.iterdir() if path.is_file() and path.stat().st_size == 0]
    report['fits'].append(outcome)
    print(json.dumps({'progress': name, 'checkpoint_checked': True}), flush=True)

for name, expected in inputs.items():
    demand(identity(name) == expected, 'original bound input changed during observation: ' + name)
report['bound_original_inputs']['unchanged_after_audit'] = True
report['cost'] = {'full_process_wall_seconds_lower_bound': time.monotonic() - STARTED,
                  'process_cpu_seconds_lower_bound': time.process_time(),
                  'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                  'energy_joules': None, 'energy_measured': False,
                  'scope': 'Audit only, separate from original training; no cost refund.'}
report['all_six_training_terminal_established'] = False
report['all_six_independent_model_forward_replay'] = False
report['qualification'] = 'HOLD_NO_GO'
print(json.dumps(report, sort_keys=True), flush=True)
