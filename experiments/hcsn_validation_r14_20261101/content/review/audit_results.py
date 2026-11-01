"""Independent accounting audit of completed R14 content evidence.

This script performs no training or model forwards. It reconstructs factorial
effects from individual NPZ outcomes, inspects checkpoint tensors directly, and
checks data interventions. Run only after the serialized timing window and the
complete study have finished. Its output must use a new path.
"""

import argparse
import hashlib
import json
import math
import resource
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[4]
SCALAR_ATOL = 2e-6
SELECTION_ATOL = 2e-12


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def serializable(value):
    if isinstance(value, dict):
        return {k: serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return dict(nonfinite_value=str(value))
    return value


class Audit:
    def __init__(self):
        self.checks = []

    def check(self, name, condition, **details):
        self.checks.append(dict(check=name, passed=bool(condition), **details))

    def close(self, name, observed, expected, tolerance=SCALAR_ATOL):
        delta = abs(float(observed)-float(expected))
        self.check(name, delta <= tolerance, observed=float(observed),
                   expected=float(expected), absolute_error=delta, tolerance=tolerance)


def tensor_identity(state):
    result = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        value = tensor.detach().cpu().contiguous().numpy()
        result.update(name.encode())
        result.update(str((value.shape, value.dtype.str)).encode())
        result.update(value.tobytes())
    return result.hexdigest()


def array_identity(np, *arrays):
    result = hashlib.sha256()
    for value in arrays:
        value = np.ascontiguousarray(value)
        result.update(str((value.shape, value.dtype.str)).encode())
        result.update(value.tobytes())
    return result.hexdigest()


def receipt(audit, output, phase, task, seed, mode):
    name = f'{phase}_{task}_s{seed}_{mode}'
    row = read(output/'receipts'/(name+'.json'))
    command = row['command']
    valid = row['exit_code'] == 0
    for flag, expected in (('--task', task), ('--seed', str(seed)), ('--mode', mode)):
        valid &= flag in command and command[command.index(flag)+1] == expected
    audit.check('receipt/'+name, valid, cpu_seconds=row['cpu_seconds'])
    return row


def data_checks(audit, np, protocol):
    # Import only the frozen data generator, not study/evaluate/engine metrics.
    from experiments.hcsn_validation_r14_20261101.content.data import dataset
    values, descriptions = {}, []
    for task in protocol['tasks']:
        for split in ('train', 'val', 'test'):
            value = dataset(task, split)
            key = (task, split, 'iid')
            values[key] = value
            count = protocol['splits'][split][0]
            audit.check('data/shape/'+task+'/'+split,
                        len(value['y']) == count and value['x'].shape[2] == protocol['tasks'][task][0])
        base = values[task, 'test', 'iid']
        x, y, groups = base['x'], base['y'], base['group']
        for domain in protocol['domains'][task]:
            value = values.setdefault((task, 'test', domain), dataset(task, 'test', domain))
            a, dt, target = value['x'], value['dt'], value['y']
            prefix = 'data/'+task+'/'+domain
            audit.check(prefix+'/digest', array_identity(np, a, dt, target, value['group']) == value['sha256'])
            audit.check(prefix+'/identities', np.array_equal(value['ids'], np.arange(len(y)))
                        and np.array_equal(value['group'], groups))
            if domain != 'query_swap':
                audit.check(prefix+'/labels_preserved', np.array_equal(target, y))
            if domain in ('iid', 'irregular_dt', 'clock4x'):
                audit.check(prefix+'/payload_preserved', np.array_equal(a, x))
            if domain == 'irregular_dt':
                audit.check(prefix+'/public_intervals', np.all(dt[:, ::2] == .25) and np.all(dt[:, 1::2] == 1.75))
            elif domain == 'clock4x':
                audit.check(prefix+'/public_intervals', np.all(dt == 4))
            else:
                audit.check(prefix+'/public_intervals', np.all(dt == 1))
            if domain == 'blank_retention':
                audit.check(prefix+'/blank_suffix', a.shape[1] == x.shape[1]+8
                            and np.array_equal(a[:, :x.shape[1]], x) and np.all(a[:, x.shape[1]:] == 0))
            if domain == 'long_distractors':
                tail = 2 if task == 'recall' else 1
                inserted = a[:, x.shape[1]-tail:x.shape[1]-tail+12]
                preserved = a.shape[1] == x.shape[1]+12 and np.array_equal(a[:, :x.shape[1]-tail], x[:, :-tail]) and np.array_equal(a[:, -tail:], x[:, -tail:])
                if task == 'recall':
                    noise_ok = np.all(inserted[..., :7] == 0) and np.all(inserted[..., 7:].sum(-1) == 1)
                else:
                    noise_ok = np.all(inserted[..., :16] == 0) and np.all(inserted[..., 16] == 1)
                audit.check(prefix+'/insertion', preserved and noise_ok)
            if domain == 'missing_payload':
                expected = x.copy(); expected[:, 1:6:2] = 0
                audit.check(prefix+'/exact_removal', np.array_equal(a, expected))
            if domain in ('missing_a', 'missing_b'):
                expected = x.copy(); expected[x[..., 10 if domain == 'missing_a' else 11] > 0] = 0
                audit.check(prefix+'/exact_removal', np.array_equal(a, expected))
                buckets = {}
                for raw, intervals, label in zip(a, dt, target):
                    buckets.setdefault(array_identity(np, raw, intervals), []).append(int(label))
                audit.check(prefix+'/identical_observation_balance', all(sum(v)*2 == len(v) for v in buckets.values()), buckets=len(buckets))
            if domain == 'query_swap':
                audit.check(prefix+'/earlier_frames_preserved', np.array_equal(a[:, :-1], x[:, :-1]))
                old_query = x[:, -1, :3].argmax(-1) if task == 'recall' else x[:, -1, 12:14].argmax(-1)
                new_query = a[:, -1, :3].argmax(-1) if task == 'recall' else a[:, -1, 12:14].argmax(-1)
                audit.check(prefix+'/changed_query', np.array_equal(new_query, (old_query+1) % (3 if task == 'recall' else 2)))
            if domain in ('iid', 'query_swap'):
                if task == 'recall':
                    query = a[:, -1].argmax(-1)
                    keys = a[:, :6:2].argmax(-1)
                    labels = a[:, 1:6:2].argmax(-1)-3
                    expected_y = labels[np.arange(len(y)), (keys == query[:, None]).argmax(-1)]
                else:
                    expected_y = []
                    template = np.array([1, 1, -1, -1, 1, 1, -1, -1])
                    for row in a:
                        query = int(row[-1, 12:14].argmax())
                        signs = {}
                        for event in row[:4]:
                            if int(event[12:14].argmax()) != query:
                                continue
                            if event[10] > 0:
                                signs['a'] = event[1] > 0
                            if event[11] > 0:
                                signs['b'] = event[2:10] @ template > 0
                        expected_y.append(int(signs['a'] == signs['b']))
                    expected_y = np.array(expected_y)
                audit.check(prefix+'/raw_label_rule', np.array_equal(target, expected_y))
            descriptions.append(dict(task=task, domain=domain, sha256=value['sha256'],
                                     shape=list(a.shape), label_counts=np.bincount(target).tolist()))
    return values, descriptions


def inspect_fit(audit, np, torch, output, protocol, candidates, values, task, seed, mode):
    name = f'{task}_s{seed}_{mode}'
    prefix = 'fit/'+name
    folder = output/'fits'/name
    audit.check(prefix+'/no_failure', not (folder/'FAILED.json').exists())
    summary, trace = read(folder/'SUMMARY.json'), read(folder/'TRACE.json')
    selected, final = (torch.load(folder/file, map_location='cpu', weights_only=True) for file in ('selected.pt', 'final.pt'))
    entry = candidates['candidates']['fits/'+name]
    audit.check(prefix+'/selected_file_identity', sha(folder/'selected.pt') == summary['selected_checkpoint_sha256'] == entry['sha256'])
    audit.check(prefix+'/final_file_identity', sha(folder/'final.pt') == summary['final_checkpoint_sha256'])
    audit.check(prefix+'/steps', selected['step'] == summary['selected_step'] and final['step'] == protocol['updates'])
    audit.check(prefix+'/payload_identity', all(payload['task'] == task and payload['seed'] == seed and payload['mode'] == mode and payload['protocol_sha256'] == sha(output/'PROTOCOL.json') for payload in (selected, final)))
    families = protocol['families']
    audit.check(prefix+'/all_backends', set(selected['models']) == set(final['models']) == set(families))
    validations = summary['validations']
    expected_steps = [0]+[s for s in range(1, protocol['updates']+1) if s % protocol['validate_every'] == 0 or s == protocol['updates']]
    audit.check(prefix+'/validation_steps', [v['step'] for v in validations] == expected_steps)
    best_score, best_step, best_metrics = -float('inf'), None, None
    for row in validations:
        score = float(np.mean([row['cores'][f]['value_utility'] for f in families]))
        audit.close(prefix+'/validation_score/'+str(row['step']), row['score'], score, SELECTION_ATOL)
        if score > best_score+1e-12:
            best_score, best_step, best_metrics = score, row['step'], row['cores']
    ordinary = max((f for f in families if f != 'analytic'), key=lambda f: best_metrics[f]['value_utility'])
    audit.check(prefix+'/validation_only_selection', best_step == selected['step'] and ordinary == summary['ordinary_selected'] == entry['ordinary'])
    audit.close(prefix+'/selected_score', summary['selection_score'], best_score, SELECTION_ATOL)
    audit.check(prefix+'/alignment', all(not any(row.values()) for row in read(folder/'ONLINE_VALIDATION_ALIGNMENT.json').values()))
    data_record = read(folder/'DATA.json')
    audit.check(prefix+'/data_identity', all(data_record[s] == values[task, s, 'iid']['sha256'] for s in ('train', 'val')))
    rng = np.random.default_rng(seed+141000)
    audit.check(prefix+'/trace_steps', [row['step'] for row in trace] == list(range(1, protocol['updates']+1)))
    trace_valid = True
    for row in trace:
        expected = rng.integers(len(values[task, 'train', 'iid']['y']), size=protocol['batch_size'])
        trace_valid &= np.array_equal(row['ids'], expected) and set(row['cores']) == set(families)
        loss = np.mean([row['cores'][f]['ce']+row['cores'][f]['value_mse'] for f in families])
        trace_valid &= np.isfinite(row['loss']) and abs(row['loss']-loss) <= SCALAR_ATOL
    audit.check(prefix+'/fixed_batches_and_loss', trace_valid)
    controller_hash = tensor_identity(selected['controller'])
    backend_hashes, details = {}, []
    for family in families:
        label = prefix+'/'+family
        inherited = protocol['inputs'][f'{task}_s{seed}_joint_{family}']
        old = torch.load(REPO/inherited['path'], map_location='cpu', weights_only=True)
        initial = old['model_state']
        current, last = selected['models'][family]['state'], final['models'][family]['state']
        initial_hash, selected_hash, final_hash = map(tensor_identity, (initial, current, last))
        backend_hashes[family] = selected_hash
        audit.check(label+'/initial_identity', initial_hash == summary['initial_hashes'][family] == selected['initial_hashes'][family] == final['initial_hashes'][family])
        audit.check(label+'/config', selected['models'][family]['config'] == final['models'][family]['config'] == old['config'])
        audit.check(label+'/selected_change_flag', summary['backend_changed'][family] == (selected_hash != initial_hash))
        if mode == 'frozen_backend':
            audit.check(label+'/complete_backend_frozen', initial_hash == selected_hash == final_hash)
        changes = {}
        for component in ('encoder', 'core', 'readout'):
            subset = lambda state: {k: v for k, v in state.items() if k.startswith(component+'.')}
            old_hash, current_hash, last_hash = map(tensor_identity, (subset(initial), subset(current), subset(last)))
            count = summary['nonzero_gradient_steps'][family][component]
            changes[component] = dict(nonzero_gradient_steps=count, selected_changed=current_hash != old_hash, final_changed=last_hash != old_hash)
            if mode == 'frozen_backend':
                audit.check(label+'/'+component+'/fully_frozen', count == 0 and old_hash == current_hash == last_hash)
            else:
                audit.check(label+'/'+component+'/joint_updated', 0 < count <= protocol['updates'] and last_hash != old_hash)
            if selected['step'] == 0:
                audit.check(label+'/'+component+'/step_zero_unchanged', current_hash == old_hash)
        details.append(dict(family=family, initial_sha256=initial_hash, selected_sha256=selected_hash, final_sha256=final_hash, components=changes))
    return dict(task=task, seed=seed, mode=mode, selected_step=selected['step'], ordinary=ordinary,
                controller_sha256=controller_hash, final_controller_sha256=tensor_identity(final['controller']),
                backends=details, backend_hashes=backend_hashes, selected=selected)


def inspect_outcomes(audit, np, output, protocol, fit, values, source_sha, candidate_sha):
    task, seed, mode = (fit[k] for k in ('task', 'seed', 'mode'))
    name = f'{task}_s{seed}_{mode}'
    folder = output/'heldout'/name
    result = read(folder/'SUMMARY.json')
    audit.check('heldout/'+name+'/no_failure', not (folder/'FAILED.json').exists())
    audit.check('heldout/'+name+'/identity', result['source_freeze_sha256'] == source_sha and result['candidate_freeze_sha256'] == candidate_sha and result['controller_sha256'] == fit['controller_sha256'])
    expected = {(f, d) for f in protocol['families'] for d in protocol['domains'][task]}
    observed = {(r['family'], r['domain']) for r in result['rows']}
    audit.check('heldout/'+name+'/inventory', observed == expected and len(result['rows']) == len(expected))
    outcomes = {}
    for row in result['rows']:
        family, domain = row['family'], row['domain']
        tag = 'raw/'+name+'/'+family+'/'+domain
        data = values[task, 'test', domain]
        count, length = data['dt'].shape
        path = folder/row['raw']
        audit.check(tag+'/raw_sha', sha(path) == row['raw_sha256'])
        with np.load(path, allow_pickle=False) as archive:
            raw = {key: archive[key].copy() for key in archive.files}
        audit.check(tag+'/row_identity', row['task'] == task and row['seed'] == seed and row['mode'] == mode)
        audit.check(tag+'/data_identity', row['data_sha256'] == str(raw['input_sha256']) == data['sha256'] and np.array_equal(raw['ids'], data['ids']) and np.array_equal(raw['labels'], data['y']) and np.array_equal(raw['group'], data['group']))
        audit.check(tag+'/common_weights', row['controller_sha256'] == fit['controller_sha256'] and row['backend_sha256'] == fit['backend_hashes'][family])
        audit.check(tag+'/alignment', row['offline_online_read_mismatches'] == row['offline_online_prediction_mismatches'] == 0)
        vectors = ('value_utility','light_utility','value_accuracy','light_accuracy','reads','fees','initial_stop')
        audit.check(tag+'/shapes', all(raw[k].shape == (count,) for k in vectors) and all(raw[k].shape == (count, length+1) for k in ('score_margin','realized_margin','occupied')))
        audit.check(tag+'/finite', all(np.isfinite(raw[k]).all() for k in vectors+('score_margin','realized_margin')))
        reads = raw['reads']
        audit.check(tag+'/legal_reads', np.issubdtype(reads.dtype, np.integer) and np.all((reads >= 0) & (reads <= length)))
        elapsed = np.concatenate((np.zeros((count, 1)), np.cumsum(data['dt'].astype(float), axis=1)), axis=1)
        fee = protocol['read_fee']*reads+protocol['time_fee']*elapsed[np.arange(count), reads]
        full_fee = protocol['read_fee']*length+protocol['time_fee']*elapsed[:, -1]
        for key, expected_vector in (('fees', fee), ('value_utility', raw['value_accuracy']-fee), ('light_utility', raw['light_accuracy']-full_fee)):
            audit.close(tag+'/'+key+'_identity', np.max(np.abs(raw[key]-expected_vector)), 0.)
        audit.check(tag+'/binary_accuracy', all(np.isin(raw[k], [0, 1]).all() for k in ('value_accuracy','light_accuracy','initial_stop')))
        choose_read = raw['score_margin'] > 0
        choose_read[:, -1] = False
        stops = (~choose_read).argmax(1)
        occupied = np.arange(length+1)[None, :] <= reads[:, None]
        audit.check(tag+'/first_stop_and_occupancy', np.array_equal(stops, reads) and np.array_equal(raw['occupied'], occupied))
        audit.check(tag+'/terminal_target_margin', np.all(raw['realized_margin'][:, -1] == 0))
        bias = fit['selected']['models'][family]['state']['readout.bias'].detach().cpu().numpy()
        initial_correct = (data['y'] == int(bias.argmax())).astype(float)
        audit.check(tag+'/initial_stop_accuracy', np.array_equal(raw['initial_stop'], initial_correct)
                    and np.array_equal(raw['value_accuracy'][reads == 0], initial_correct[reads == 0]))
        audit.check(tag+'/same_terminal_prediction', np.array_equal(raw['value_accuracy'][reads == length], raw['light_accuracy'][reads == length]))
        audit.check(tag+'/actual_prefix_work', row['actor_model_calls'] == int(reads.max()) and row['processed_prefix_tokens'] == int(np.sum(reads*(reads+1)//2)))
        hindsight = np.where(choose_read, np.maximum(-raw['realized_margin'], 0), np.maximum(raw['realized_margin'], 0))
        audit.close(tag+'/sample_hindsight_gap', row['occupied_sample_hindsight_gap'], hindsight[occupied].mean())
        audit.check(tag+'/no_conditional_regret_claim', row['conditional_expected_regret'] is None)
        for key in ('value_utility','light_utility','value_accuracy','light_accuracy','initial_stop'):
            audit.close(tag+'/mean_'+key, row[key], raw[key].astype(float).mean())
        for key, expected_value in (('initial_selected', np.mean(reads == 0)), ('read_count', reads.mean()), ('actual_fee', fee.mean())):
            audit.close(tag+'/'+key, row[key], expected_value)
        outcomes[family, domain] = dict(raw=raw, row=row)
    return outcomes


def factorial(audit, np, protocol, fits, outcomes, official):
    official_rows = {(r['task'], r['mode'], r['seed'], r['domain'], r['comparison']): r for r in official['contrasts']}
    computed, samples = [], []
    for fit in fits:
        task, seed, mode = (fit[k] for k in ('task','seed','mode'))
        raw = outcomes[task, seed, mode]
        for domain in protocol['domains'][task]:
            analytic = raw['analytic', domain]
            for comparison, family in (('matched','ordinary_dual'), ('strong_selected',fit['ordinary'])):
                ordinary = raw[family, domain]
                b, d = ordinary['raw'], analytic['raw']
                a, B, c, D = [v.astype(float) for v in (b['light_utility'], b['value_utility'], d['light_utility'], d['value_utility'])]
                vectors = dict(A=a, B=B, C=c, D=D, B_A=B-a, D_C=D-c, C_A=c-a, D_B=D-B, interaction=(D-c)-(B-a), D_B_quality=d['value_accuracy'].astype(float)-b['value_accuracy'].astype(float))
                key = (task, mode, seed, domain, comparison)
                row = dict(task=task, mode=mode, seed=seed, domain=domain, comparison=comparison, ordinary=family,
                           **{name: float(v.mean()) for name, v in vectors.items()},
                           online_cpu_ratio=analytic['row']['value_cpu_seconds']/ordinary['row']['value_cpu_seconds'])
                audit.check('factorial/'+str(key)+'/paired_rows', np.array_equal(b['ids'], d['ids']) and np.array_equal(b['labels'], d['labels']) and np.array_equal(b['group'], d['group']))
                published = official_rows[key]
                audit.check('factorial/'+str(key)+'/ordinary', published['ordinary'] == family)
                for metric in vectors.keys() | {'online_cpu_ratio'}:
                    audit.close('factorial/'+str(key)+'/'+metric, published[metric], row[metric])
                computed.append(row)
                samples.append(dict(task=task, mode=mode, seed=seed, domain=domain, comparison=comparison,
                    units=len(D), groups=int(len(np.unique(d['group']))), sample_D_B_min=float((D-B).min()), sample_D_B_max=float((D-B).max()),
                    mean_D_B=float((D-B).mean()), mean_D_B_group_means=float(np.mean([np.mean((D-B)[d['group'] == group]) for group in np.unique(d['group'])]))))
    audit.check('factorial/inventory', len(computed) == len(official_rows) == len(official['contrasts']))
    means = []
    expected_means = {tuple(r[k] for k in ('task','mode','domain','comparison')) for r in computed}
    audit.check('means/inventory', len(official['means']) == len(expected_means)
                and {tuple(r[k] for k in ('task','mode','domain','comparison')) for r in official['means']} == expected_means)
    for published in official['means']:
        key = tuple(published[k] for k in ('task','mode','domain','comparison'))
        subset = [r for r in computed if tuple(r[k] for k in ('task','mode','domain','comparison')) == key]
        audit.check('means/'+str(key)+'/fit_units', len(subset) == published['n_fit_seeds'] == len(protocol['seeds'])
                    and {r['seed'] for r in subset} == set(protocol['seeds']))
        row = dict(zip(('task','mode','domain','comparison'), key))
        for metric in ('A','B','C','D','B_A','D_C','C_A','D_B','interaction','D_B_quality','online_cpu_ratio'):
            row[metric] = float(np.mean([r[metric] for r in subset]))
            audit.close('means/'+str(key)+'/'+metric, published[metric], row[metric])
        audit.check('means/'+str(key)+'/ordinary_choices', published['ordinary'] == [r['ordinary'] for r in subset])
        audit.close('means/'+str(key)+'/paired_D_B', np.max(np.abs(np.array(published['paired_seed_D_B'])-[r['D_B'] for r in subset])), 0.)
        means.append(row)
    return computed, means, samples


def run(output, audit):
    import numpy as np
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    sys.path.insert(0, str(REPO))
    protocol, source = read(output/'PROTOCOL.json'), read(output/'SOURCE_FREEZE.json')
    candidates, official = read(output/'CANDIDATE_FREEZE.json'), read(output/'RESULTS.json')
    protocol_sha, source_sha, candidate_sha = map(sha, (output/'PROTOCOL.json', output/'SOURCE_FREEZE.json', output/'CANDIDATE_FREEZE.json'))
    audit.check('source/protocol', source['protocol_sha256'] == candidates['protocol_sha256'] == protocol_sha)
    audit.check('source/results', official['source_freeze_sha256'] == source_sha and official['candidate_freeze_sha256'] == candidate_sha)
    audit.check('source/estimand', 'execution-control effects' in protocol.get('estimand','') and 'not total effects' in protocol.get('estimand',''))
    for name, digest in source['files'].items():
        audit.check('source/'+name, sha(REPO/name) == digest == sha(output/'source'/name))
    for name, digest in protocol['inherited_manifests'].items():
        audit.check('inherited_manifest/'+name, sha(REPO/name) == digest)
    for name, row in protocol['inputs'].items():
        audit.check('inherited_input/'+name, sha(REPO/row['path']) == row['sha256'])
    values, descriptions = data_checks(audit, np, protocol)
    fits, outcomes, receipts = [], {}, {'train': [], 'evaluate': []}
    expected_candidates = set()
    for task in protocol['tasks']:
        for mode in protocol['modes']:
            for seed in protocol['seeds']:
                expected_candidates.add(f'fits/{task}_s{seed}_{mode}')
                for phase in receipts:
                    receipts[phase].append(receipt(audit, output, phase, task, seed, mode))
                fit = inspect_fit(audit, np, torch, output, protocol, candidates, values, task, seed, mode)
                outcomes[task, seed, mode] = inspect_outcomes(audit, np, output, protocol, fit, values, source_sha, candidate_sha)
                fits.append(fit)
    audit.check('candidates/inventory', set(candidates['candidates']) == expected_candidates)
    expected_rows = {(t, s, m, f, d) for t in protocol['tasks'] for s in protocol['seeds'] for m in protocol['modes'] for f in protocol['families'] for d in protocol['domains'][t]}
    audit.check('results/rows_inventory', len(official['rows']) == len(expected_rows) and
                {(r['task'],r['seed'],r['mode'],r['family'],r['domain']) for r in official['rows']} == expected_rows)
    for row in official['rows']:
        actual = outcomes[row['task'],row['seed'],row['mode']][row['family'],row['domain']]['row']
        audit.check('results/row_copy/'+str((row['task'],row['seed'],row['mode'],row['family'],row['domain'])), row == actual)
    contrasts, means, sample_ranges = factorial(audit, np, protocol, fits, outcomes, official)
    costs = {}
    for phase, rows in receipts.items():
        total = read(output/'receipts'/(phase+'_TOTAL.json'))
        cpu = sum(r['cpu_seconds'] for r in rows)
        audit.check('cost/'+phase+'/jobs', len(rows) == total['jobs'])
        audit.close('cost/'+phase+'/whole_children', total['full_child_cpu_seconds'], cpu, 1e-9)
        costs[phase] = dict(full_child_cpu_seconds=cpu, jobs=len(rows), max_child_rss_bytes=max(r['max_rss_bytes'] for r in rows), energy_joules=None)
    for fit in fits:
        fit.pop('selected')
    return dict(protocol_sha256=protocol_sha, source_freeze_sha256=source_sha,
                candidate_freeze_sha256=candidate_sha, results_sha256=sha(output/'RESULTS.json'),
                data_domains=descriptions, fits=fits, recomputed_contrasts=contrasts,
                recomputed_means=means, paired_sample_ranges=sample_ranges, full_process_cost=costs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Completed content study directory')
    parser.add_argument('--report', type=Path, required=True, help='New review JSON path; existing reports are never replaced')
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError('Preserve previous audit report: '+str(args.report))
    begin_cpu, begin_wall = time.process_time(), time.perf_counter()
    audit, payload = Audit(), {}
    try:
        payload = run(args.output.resolve(), audit)
    except Exception as error:
        audit.check('fatal_exception', False, type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
    failures = [row for row in audit.checks if not row['passed']]
    record = dict(schema='hcsn.r14.content.independent-results-audit.v1',
        audit_script_sha256=sha(SCRIPT), reviewed_at_utc=datetime.now(timezone.utc).isoformat(),
        input_directory=str(args.output.resolve()), status='pass' if not failures else 'fail',
        checks=audit.checks, failed_checks=failures, result=payload,
        thresholds=dict(absolute_scalar=SCALAR_ATOL, validation_selection=SELECTION_ATOL),
        cost=dict(audit_body_cpu_seconds=time.process_time()-begin_cpu, wall_seconds=time.perf_counter()-begin_wall,
                  max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform == 'darwin' else 1024), energy_joules=None),
        scope=[
            'Independent saved-outcome accounting and direct checkpoint-byte/gradient-log audit; no model forward, backpropagation, optimizer or training is executed.',
            'Nonzero-gradient evidence is the frozen execution log, supported by final component tensor changes; this does not independently replay every optimizer update.',
            'Raw NPZ stores action margins and outcomes, not absolute Q targets or every prediction. This audit reconstructs first STOP, occupancy, fees, sample hindsight gap and all factorial effects; it does not reconstruct absolute Q MSE or conditional expected regret.',
            'Joint A/C are read-all execution ablations of the same value-trained weights used in B/D. Their control contrasts are conditional execution effects, not separate light-versus-value training total effects.',
            'The three inherited fit seeds are the descriptive fitting units. Rows, binding twins, domains, families and prefixes are not additional independent fits.',
            'Whole child receipts contain nested phase timers; this audit does not add those timers again or divide shared eight-backend training cost by eight.',
            'Source-level controller causality and original online/offline prediction gates are independently reviewed separately; outcome accounting alone cannot certify all unobserved counterfactual trajectories.',
            'The analytic network remains the inherited fixed renewal gate. No full-distribution integration, arbitrary moving boundary, device-energy or foundation-core superiority is established.'
        ])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x') as stream:
        json.dump(serializable(record), stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(status=record['status'], checks=len(audit.checks), failures=len(failures), report=str(args.report), sha256=sha(args.report))))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
