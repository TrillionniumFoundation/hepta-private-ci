"""Observed partial-text decisions and bounded finite NDU acquisition control.

Called by the existing fbsde_study entrypoint. Labels are original public labels;
view acquisition is a designed offline protocol, not real user clarification.
"""
from collections import Counter
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import random
import time

from four_gate_common import canonical, digest, require, write_once
from four_gate_capture import tensor_digest
from fbsde_acquisition_observe import AttemptJournal, observe_view
from fbsde_acquisition_support import (LEGACY_KERNEL, SUPPORTED_KERNEL, KERNEL_PROFILES,
                                       select_counts, support_summary)
from fbsde_acquisition import (JointKernel, Objective, ViewPort, certainty_equivalent,
                               exhaustive_reference, history_key, solve, terminal)
from fbsde_acquisition_data import (DATA_REV, DATA_PINS, INTENTS, PARTITIONS,
                                    load_publisher, partition, text_view, hashed_reference, cohort_spec)
from fbsde_acquisition_guard import CANDIDATES, RULE, compile_guard, guarded_action, calibrate

ARMS = ('initial_only', 'full_only', 'all_views', 'best_fixed', 'confidence',
        'myopic', 'ndu_bsde', 'compiled_same_model', 'risk_ndu')
FIXED = ((), (1,), (2,), (1, 2))
THRESHOLDS = (.5, .65, .8, .95)
SEED = 179424673


def scored(records, labels, objective, intents=INTENTS):
    require(len(records) == len(labels) and len({r['id'] for r in records}) == len(labels),
            'complete terminal evaluation inventory')
    correct = accepted = 0; rewards = []; costs = []; reads = []; errors = Counter(); classes = Counter()
    for row in records:
        require(row['id'] in labels, 'unregistered answer')
        gold = labels[row['id']]; classes[gold] += 1
        answer = row['action']
        if answer == 'abstain':
            reward = objective.abstain
            require(row['text'] == 'Insufficient evidence; abstain.', 'abstention decoding drift')
        else:
            require(answer.startswith('answer:'), 'unfinished decision')
            label = int(answer.split(':')[1]); require(0 <= label < len(intents), 'invalid label')
            require(row['text'] == f'The request is classified as {intents[label]}.', 'decoded answer drift')
            right = label == gold; correct += right; accepted += 1
            errors[gold] += not right
            reward = objective.correct if right else objective.wrong
        viewed = [event['view'] for event in row['events']]
        require(viewed[0] == 0 and len(viewed) == len(set(viewed)) <= 3, 'invalid acquisition trace')
        cost = sum(objective.costs[v-1] for v in viewed if v)
        require(abs(cost-row['modeled_cost']) < 1e-12, 'cost/trace mismatch')
        rewards.append(reward-cost); costs.append(cost); reads.append(len(viewed)-1)
    return {'count': len(records), 'correct': correct, 'answered': accepted,
            'answer_coverage': accepted/len(records), 'correct_coverage': correct/len(records),
            'accepted_error': (accepted-correct)/accepted if accepted else None,
            'mean_external_score_minus_cost': sum(rewards)/len(rewards),
            'empirical_entropic_score_rho_half': certainty_equivalent(rewards, [1/len(rewards)]*len(rewards), .5),
            'mean_additional_views': sum(reads)/len(reads), 'modeled_cost_total': sum(costs),
            'wrong_answers_by_class': dict(sorted(errors.items())),
            'class_counts': dict(sorted(classes.items())), 'read_count_histogram': dict(Counter(reads)),
            'iid_independence_authenticated': False, 'confidence_intervals_claimed': False}


def choose(arm, kernel, history, objective, fixed, threshold, tables, guard=None):
    if arm == "risk_selected":
        require(guard is not None and guard["selected"] is not None, "calibration not sealed")
        require(guard["binding"] == digest([kernel.identity, asdict(objective)]), "stale calibrated policy")
        arm = guard["selected"]
        if arm == "abstain": return "abstain", None
    if arm in CANDIDATES[2:]:
        return guarded_action(arm, kernel, history, objective, guard), None
    if arm in ('initial_only', 'full_only', 'all_views', 'best_fixed', 'full_symbol'):
        order = {'initial_only': (), 'full_only': (2,), 'all_views': (1, 2), 'best_fixed': fixed, 'full_symbol': (2,)}[arm]
        for view in order:
            if view not in dict(history): return f'read:{view}', None
    elif arm == 'confidence':
        belief = kernel.distribution(history)[1]
        if max(belief) < threshold:
            for view in (1, 2):
                if view not in dict(history): return f'read:{view}', None
    elif arm == 'compiled_same_model':
        identity, actions = tables
        require(identity == digest([kernel.identity, asdict(objective)]), 'stale kernel/objective table')
        return actions[history_key(history, kernel.symbols)], None
    elif arm in ('myopic', 'ndu_bsde', 'risk_ndu'):
        value = solve(kernel, history, objective, one_step=arm == 'myopic')
        return value['action'], {'root_value': value['value'], 'edges': value['edges'],
                                 'kernel_sha256': value['kernel_sha256']}
    if arm == 'full_symbol': return f'answer:{dict(history)[2]}', None
    return terminal(kernel, history, objective)[0], None


def execute(row, arm, kernel, objective, provider, fixed, threshold, tables, head_identity,
            intents=INTENTS, guard=None):
    """The chooser has no row text, ID, hidden future symbol, or label argument."""
    started_cpu, started_wall = time.process_time_ns(), time.perf_counter_ns()
    port = ViewPort(provider, kernel.symbols); history = port.read(0); decisions = []
    for _ in range(3):
        begin = time.process_time_ns()
        action, trace = choose(arm, kernel, history, objective, fixed, threshold, tables, guard)
        decisions.append({'history': history, 'action': action, 'bsde': trace,
                          'cpu_ns': time.process_time_ns()-begin})
        if action.startswith('read:'):
            history = port.read(int(action.split(':')[1]))
        else:
            text = ('Insufficient evidence; abstain.' if action == 'abstain' else
                    f'The request is classified as {intents[int(action.split(":")[1])]}.')
            return {'id': row['id'], 'source_input_sha256': row['text_sha256'], 'arm': arm,
                    'action': action, 'text': text, 'head_sha256': head_identity,
                    'kernel_sha256': kernel.identity, 'objective_sha256': digest(asdict(objective)),
                    'events': port.events, 'decisions': decisions,
                    'modeled_cost': sum(objective.costs[e['view']-1] for e in port.events if e['view']),
                    'cpu_ns': time.process_time_ns()-started_cpu, 'wall_ns': time.perf_counter_ns()-started_wall}
    raise ValueError('acquisition policy exceeded horizon')


def make_head(torch):
    """Shared exact acquisition Head for fitting and source-bound CPU replay."""
    nn = torch.nn
    class Head(nn.Module):
        def __init__(self):
            super().__init__(); self.value = nn.Linear(384, 16); self.gate = nn.Linear(384, 16); self.out = nn.Linear(16, 8)
        def forward(self, x): return self.out(self.value(x).tanh()*self.gate(x).sigmoid())
    return Head()


def run(output, *, backend='hashing_reference_v1', publisher_root=None, model_dir=None,
        kernel_profile=LEGACY_KERNEL, cohort="banking_v1", clock_diagnostics=False):
    intents, partitions = cohort_spec(cohort)
    guarded = cohort == "travel_guard_v1"
    require(type(clock_diagnostics) is bool, "explicit clock diagnostics mode")
    if clock_diagnostics:
        from fbsde_cpu_replay import PhaseClock
    require(not guarded or kernel_profile == SUPPORTED_KERNEL, "guard requires supported kernel")
    import torch
    from torch import nn
    from four_gate_pretrained import MODEL, REVISION, load_pinned, file_hash

    require(backend in ('hashing_reference_v1', 'mmbert'), 'explicit backend; no silent substitute')
    require(kernel_profile in KERNEL_PROFILES, 'explicit kernel profile')
    arms = ARMS + (('full_symbol',) if kernel_profile == SUPPORTED_KERNEL else ())
    if guarded: arms += CANDIDATES[2:]+('risk_selected',)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2); torch.manual_seed(SEED)
    envelope_cpu = time.process_time_ns(); jobs = []
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('fbsde_acquisition*.py')}
    if clock_diagnostics:
        sources.update({name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                        for name in ('fbsde_cpu_replay.py','fbsde_cpu_replay_audit.py')})
    objective, risk = Objective(), Objective(rho=.5)
    write_once(output/'plan.json', {'schema': 'hepta.fbsde.semantic-acquisition.plan.v1',
        'backend': backend, 'model': MODEL if backend == 'mmbert' else 'deterministic_sha256_lexical_384',
        'revision': REVISION if backend == 'mmbert' else None, 'publisher_revision': DATA_REV,
        'publisher_pins': DATA_PINS, 'sources': sources, 'intents': intents, 'partitions': partitions,
        'cohort': cohort, 'guard_rule': RULE if guarded else None,
        'validation_role': 'policy_risk_calibration' if guarded else 'untouched_validation',
        'seed': SEED, 'steps': 96, 'lr': .003, 'kernel_alpha': .01,
        'normalization_fit_only': True, 'view_protocol': 'first_3_words,last_3_words,full_original',
        'objective': asdict(objective), 'risk_objective': asdict(risk), 'arms': arms,
        'kernel_model_profile': kernel_profile,
        'fixed_grid': FIXED, 'confidence_grid': THRESHOLDS, 'prediction_cpu_limit_ns': 100_000_000,
        'view_attempt_profile': 'measured_attempts_v1',
        'cpu_clock_profile': 'parallel_clocks_v1' if clock_diagnostics else 'process_only_v1',
        'test_labels_not_used_for_selection': True, 'real_future_observations': False,
        'source_author_independence_unknown': True, 'production_promotion_permitted': False})
    begin = time.process_time_ns()
    data = load_publisher(publisher_root or output/'publisher'); splits = partition(data, cohort)
    # Text and gold remain separate at the policy interface, not separate OS trust domains.
    inputs = {s: [{k: v for k, v in r.items() if k != 'label'} for r in rows] for s, rows in splits.items()}
    labels = {s: {r['id']: r['label'] for r in rows} for s, rows in splits.items()}
    write_once(output/'input-inventory.json', inputs)
    jobs.append({'id': 'publisher_and_partition', 'phase': 'load', 'cpu_ns': time.process_time_ns()-begin})
    physical = {'backend': backend, 'real_pretrained_weights_executed': backend == 'mmbert'}
    begin = time.process_time_ns()
    if backend == 'mmbert':
        require(model_dir is not None, 'physical model directory required')
        model, tokenizer, inventory, loading = load_pinned(Path(model_dir))
        physical.update({'model': MODEL, 'revision': REVISION, 'physical_files': inventory, 'loading': loading})
        def encode(texts):
            tokens = tokenizer(texts, padding=True, truncation=False, return_tensors='pt')
            require(tokens['input_ids'].shape[1] <= 256, 'no silent truncation')
            with torch.inference_mode():
                h = model(**tokens).last_hidden_state.float(); mask = tokens['attention_mask'].unsqueeze(-1)
                return (h*mask).sum(1)/mask.sum(1)
    else:
        def encode(texts): return hashed_reference(texts, torch)
    jobs.append({'id': 'encoder_load', 'phase': 'load', 'cpu_ns': time.process_time_ns()-begin})
    begin = time.process_time_ns(); encode(['Please classify this request.'])
    jobs.append({'id': 'encoder_warmup', 'phase': 'warmup', 'cpu_ns': time.process_time_ns()-begin})
    # Preparation never computes test views. Each TEST acquisition below performs its own forward.
    features = {}; forward_records = []
    begin = time.process_time_ns()
    for split in ('fit', 'kernel', 'selection'):
        requests = [(r['id'], v, text_view(r['text'], v)) for r in inputs[split] for v in range(3)]
        for start in range(0, len(requests), 32):
            batch = requests[start:start+32]; t = time.process_time_ns(); x = encode([r[2] for r in batch])
            require(x.shape == (len(batch), 384) and torch.isfinite(x).all().item(), 'encoder feature contract')
            forward_records.append({'split': split, 'inputs': [(u, v, digest(txt)) for u, v, txt in batch],
                'vectors_sha256': tensor_digest(x), 'cpu_ns': time.process_time_ns()-t})
            features.update({(u, v): x[i].clone() for i, (u, v, _) in enumerate(batch)})
    fit_keys = [(r['id'], v) for r in inputs['fit'] for v in range(3)]
    fit_x = torch.stack([features[k] for k in fit_keys]); mean, scale = fit_x.mean(0), fit_x.std(0).clamp_min(.1)
    normalize = lambda x: ((x-mean)/scale).clamp(-8, 8)
    fit_x = normalize(fit_x); features = {k: normalize(v) for k, v in features.items()}
    jobs.append({'id': 'pretest_features_and_normalizer', 'phase': 'training', 'cpu_ns': time.process_time_ns()-begin})
    begin = time.process_time_ns(); head = make_head(torch); optimizer = torch.optim.AdamW(head.parameters(), lr=.003)
    fit_y = torch.tensor([labels['fit'][uid] for uid, _ in fit_keys]); losses = []
    for _ in range(96):
        optimizer.zero_grad(); loss = nn.functional.cross_entropy(head(fit_x), fit_y)
        require(torch.isfinite(loss).item(), 'nonfinite head loss'); loss.backward()
        nn.utils.clip_grad_norm_(head.parameters(), 1.); optimizer.step(); losses.append(float(loss.item()))
    head.eval().requires_grad_(False)
    head_id = digest({k: tensor_digest(v) for k, v in head.state_dict().items()})
    jobs.append({'id': 'shared_head_fit', 'phase': 'training', 'cpu_ns': time.process_time_ns()-begin})
    begin = time.process_time_ns(); observations = {}; kernel_observations = []
    with torch.inference_mode():
        for split in ('kernel', 'selection'):
            for r in inputs[split]:
                x = torch.stack([features[(r['id'], v)] for v in range(3)])
                probabilities = head(x).softmax(-1)
                observations[r['id']] = tuple(int(v) for v in probabilities.argmax(-1).tolist())
                if split == 'kernel':
                    kernel_observations.append({'id': r['id'], 'text_sha256': r['text_sha256'],
                        'symbols': observations[r['id']], 'probabilities': probabilities.tolist(),
                        'head_sha256': head_id})
    kernel_rows = [(labels['kernel'][r['id']], *observations[r['id']]) for r in inputs['kernel']]
    binding = {'head': head_id, 'backend': physical, 'kernel_inputs': digest(inputs['kernel']),
               'normalizer': digest([tensor_digest(mean), tensor_digest(scale)])}
    if kernel_profile == SUPPORTED_KERNEL:
        counts, selected_kernel = select_counts(kernel_rows, [r['text_sha256'] for r in inputs['kernel']], 8)
        binding = {**binding, 'smoothing_selection_sha256': digest(selected_kernel)}
        kernel = JointKernel(counts, 8, 8, binding)
        write_once(output/'kernel-selection.json', selected_kernel)
    else:
        kernel = JointKernel.fit(kernel_rows, 8, binding)
    jobs.append({'id': 'joint_kernel_fit', 'phase': 'training', 'cpu_ns': time.process_time_ns()-begin})
    write_once(output/'kernel-fit-observations.json', kernel_observations)
    write_once(output/'kernel.json', {'counts': kernel.counts, 'binding': binding, 'identity': kernel.identity,
                                    'fit_row_count': len(kernel_rows), 'classes': 8, 'symbols': 8})
    def cached_provider(row):
        def view(v): return observations[row['id']][v], {'kind': 'pretest_cached_symbol', 'view': v}
        return view
    begin = time.process_time_ns(); fixed_scores = []; threshold_scores = []
    for order in FIXED:
        rows = [execute(r, 'best_fixed', kernel, objective, cached_provider(r), order, .8, None, head_id, intents)
                for r in inputs['selection']]
        fixed_scores.append((order, scored(rows, labels['selection'], objective, intents)['mean_external_score_minus_cost']))
    fixed = max(fixed_scores, key=lambda x: x[1])[0]
    for threshold in THRESHOLDS:
        rows = [execute(r, 'confidence', kernel, objective, cached_provider(r), fixed, threshold, None, head_id, intents)
                for r in inputs['selection']]
        threshold_scores.append((threshold, scored(rows, labels['selection'], objective, intents)['mean_external_score_minus_cost']))
    threshold = max(threshold_scores, key=lambda x: x[1])[0]
    jobs.append({'id': 'simple_controller_selection', 'phase': 'search', 'cpu_ns': time.process_time_ns()-begin})
    begin = time.process_time_ns(); table = {}; interfaces = []
    for symbol in range(8):
        solved = solve(kernel, ((0, symbol),), objective); table.update(solved['actions']); interfaces += solved['edges']
    tables = (digest([kernel.identity, asdict(objective)]), table)
    guard = compile_guard(kernel, kernel_rows, table, objective) if guarded else None
    jobs.append({'id': 'compiled_dp_preparation', 'phase': 'search', 'cpu_ns': time.process_time_ns()-begin})
    write_once(output/'selection.json', {'fixed_scores': fixed_scores, 'selected_fixed': fixed,
        'threshold_scores': threshold_scores, 'threshold': threshold, 'head_sha256': head_id,
        'tables_binding': tables[0], 'tables': [{'history': h, 'action': a} for h, a in table.items()],
        'training_losses': losses, 'head_parameters': sum(p.numel() for p in head.parameters()),
        'finite_bsde_edges': interfaces})
    # Preserve completed preparation even when a later requested view fails.
    tensor_file = output/'candidate-head.pt'
    torch.save({'state': head.state_dict(), 'mean': mean, 'scale': scale}, tensor_file)
    write_once(output/'preparation-forwards.json', forward_records)
    write_once(output/'physical.json', {**physical, 'normalizer_fit_ids': [r['id'] for r in inputs['fit']],
        'candidate_head_file_sha256': file_hash(tensor_file), 'candidate_head_identity': head_id})
    write_once(output/'preparation-jobs.json', jobs)
    records = {a: [] for a in arms}; validation_records = {a: [] for a in arms}
    # Model coefficients are frozen. The optional new cohort uses this first
    # evaluation split only for declared whole-policy risk selection before test.
    for split in ('validation', 'test'):
        split_arms = tuple(a for a in arms if not (guarded and split == 'validation' and a == 'risk_selected'))
        streams = {a: (output/f'{split}-{a}.jsonl').open('xb') for a in split_arms}
        attempts = AttemptJournal(output/f'{split}-view-attempts.jsonl')
        clocks = AttemptJournal(output/f'{split}-parallel-clocks.jsonl') if clock_diagnostics else None
        try:
            for ordinal, row in enumerate(inputs[split]):
                order = list(split_arms); random.Random(SEED+ordinal).shuffle(order)
                for arm in order:
                    obj = risk if arm == 'risk_ndu' else objective
                    def provider(view):
                        clock = PhaseClock() if clock_diagnostics else time.process_time_ns
                        status = 'returned'; sequence = attempts.sequence
                        try:
                            return observe_view(view, lambda v: text_view(row['text'], v), encode,
                                normalize, head, torch, head_id, attempts,
                                {'split': split, 'arm': arm, 'id': row['id'],
                                 'source_input_sha256': row['text_sha256']}, cpu_clock=clock)
                        except Exception as error:
                            from fbsde_acquisition_observe import ViewBudgetExceeded
                            status = 'budget_exceeded' if isinstance(error, ViewBudgetExceeded) else 'execution_error'
                            raise
                        finally:
                            if clocks is not None:
                                clocks.append({'split': split, 'id': row['id'], 'arm': arm,
                                    'view': view, 'status': status,
                                    'source_sequence': sequence, 'source_attempt_sha256': attempts.previous,
                                    **clock.report()})
                    rec = execute(row, arm, kernel, obj, provider, fixed, threshold, tables, head_id, intents, guard)
                    streams[arm].write(canonical(rec)+b'\n'); streams[arm].flush()
                    (records if split == 'test' else validation_records)[arm].append(rec)
        except Exception as error:
            write_once(output/'failure.json', {'schema': 'hepta.acquisition.failure.v1',
                'split': split, 'error_type': type(error).__name__,
                'attempts_in_split': attempts.sequence, 'last_attempt_sha256': attempts.previous,
                'run_complete': False, 'scientific_pass': False, 'budget_relaxed': False,
                'measured_experiment_cpu_ns': time.process_time_ns()-envelope_cpu,
                'completed_terminal_counts': {a: len((records if split == 'test' else validation_records)[a]) for a in arms}})
            raise
        finally:
            attempts.close()
            if clocks is not None: clocks.close()
            for stream in streams.values():
                stream.flush(); os.fsync(stream.fileno()); stream.close()
        if guarded and split == 'validation':
            begin = time.process_time_ns()
            calibration = calibrate({a: validation_records[a] for a in CANDIDATES},
                [(r['id'], r['text_sha256'], labels[split][r['id']]) for r in inputs[split]],
                digest([kernel.identity, head_id, asdict(objective)]))
            write_once(output/'risk-calibration.json', calibration)
            guard['selected'] = calibration['selected']
            jobs.append({'id': 'policy_risk_calibration', 'phase': 'evaluation',
                         'cpu_ns': time.process_time_ns()-begin})
    require(head_id == digest({k: tensor_digest(v) for k, v in head.state_dict().items()}), 'selected head mutated')
    # All test predictions exist on disk BEFORE the outcome scorer uses labels.
    begin = time.process_time_ns()
    metrics = {a: scored(records[a], labels['test'], objective, intents) for a in arms}
    jobs.append({'id': 'outcome_scoring', 'phase': 'evaluation', 'cpu_ns': time.process_time_ns()-begin})
    for a, b in zip(records['ndu_bsde'], records['compiled_same_model']):
        require(a['id'] == b['id'] and a['action'] == b['action'] and
                [e['view'] for e in a['events']] == [e['view'] for e in b['events']],
                'compiled policy differs from same-model BSDE')
    write_once(output/'outcomes.json', labels)
    elapsed = time.process_time_ns()-envelope_cpu
    classified = sum(j['cpu_ns'] for j in jobs)+sum(r['cpu_ns'] for grouped in (records, validation_records) for rows in grouped.values() for r in rows)
    require(elapsed >= classified, 'overlapping CPU components')
    report = {'schema': 'hepta.fbsde.semantic-acquisition.results.v1', 'backend': backend,
        'metrics': metrics, 'actual_test_forwards': {a: sum(len(r['events']) for r in rows) for a, rows in records.items()},
        'actual_test_cpu_ns': {a: sum(r['cpu_ns'] for r in rows) for a, rows in records.items()},
        'jobs_once': jobs, 'measured_experiment_cpu_ns': elapsed,
        'actual_validation_cpu_ns': {a: sum(r['cpu_ns'] for r in rows) for a, rows in validation_records.items()},
        'classified_cpu_ns': classified, 'unallocated_preparation_recording_ns': elapsed-classified,
        'test_source_count': len(inputs['test']), 'kernel_source_count': len(inputs['kernel']),
        'compiled_vs_bsde_predictions_equal': True, 'full_lifecycle_costs_allocated': False,
        'native_deployment_evidence': False, 'future_window_evidence': False,
        'general_continuous_fbsde_claimed': False, 'production_promotion_permitted': False,
        'risk_objective_is_preregistered_not_redefined_by_predictions': True,
        'validation_not_used_for_selection': not guarded,
        'cohort': cohort, 'conditional_risk_selection': calibration if guarded else None,
        'interpretation': 'partial historical text views; no new user response or world truth is synthesized'}
    report['kernel_model_profile'] = kernel_profile
    if kernel_profile == SUPPORTED_KERNEL:
        report['posterior_support'] = {a: support_summary(kernel_rows, records[a], labels['test'], kernel)
                                       for a in arms}
        report['kernel_cv_choice'] = selected_kernel['selected']
        report['test_reuse_is_exploratory'] = True
    write_once(output/'results.json', report)
    from fbsde_acquisition_audit import audit
    write_once(output/'arithmetic-audit.json', audit(output, splits))
    if clock_diagnostics:
        from fbsde_cpu_replay_audit import audit_live
        write_once(output/'clock-audit.json', audit_live(output))
    return report
