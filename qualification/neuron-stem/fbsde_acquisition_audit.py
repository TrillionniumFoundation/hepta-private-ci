"""Independent original-file arithmetic recheck; imports no policy or neural model."""
from collections import Counter
from functools import lru_cache
from itertools import product
import hashlib
import math
from pathlib import Path

from four_gate_common import digest, require, strict_loads
from fbsde_acquisition_data import INTENTS, text_view, cohort_spec


def audit(directory, original_splits):
    root = Path(directory)
    def read(name):
        p = root/name
        require(p.is_file() and not p.is_symlink() and p.stat().st_size <= 32*1024*1024,
                'bounded regular audit source')
        return strict_loads(p.read_bytes())
    plan, result, stored, selection = (read(n) for n in ('plan.json', 'results.json', 'kernel.json', 'selection.json'))
    intents, _ = cohort_spec(plan.get('cohort', 'banking_v1'))
    guarded = plan.get('cohort') == 'travel_guard_v1'
    require(tuple(plan['intents']) == intents, 'cohort intent mapping drift')
    require(plan['backend'] == result['backend'], 'backend identity changed')
    count = stored['counts']; classes = stored['classes']; symbols = stored['symbols']
    require(stored['identity'] == digest({'counts': count, 'classes': classes, 'symbols': symbols,
            'binding': digest(stored['binding'])}), 'kernel original bytes differ')
    require(stored['binding']['head'] == selection['head_sha256'], 'kernel uses another Head')
    worlds = [(w, count[i]) for i, w in enumerate(product(range(classes), range(symbols), range(symbols), range(symbols)))]
    @lru_cache(maxsize=1024)
    def conditional(h):
        rows = [(y, (a, b, c), w) for (y, a, b, c), w in worlds if all((a, b, c)[v] == s for v, s in h)]
        mass = sum(w for _, _, w in rows)
        label = [sum(w for y, _, w in rows if y == j)/mass for j in range(classes)]
        laws = [[sum(w for _, ss, w in rows if ss[v] == j)/mass for j in range(symbols)] for v in range(3)]
        return label, laws
    def ce(values, law, rho):
        if rho == 0: return sum(v*p for v, p in zip(values, law))
        m = min(values)
        return m-math.log(sum(p*math.exp(-rho*(v-m)) for v, p in zip(values, law)))/rho
    @lru_cache(maxsize=4096)
    def optimum(h, rho, myopic=False):
        obj = plan['objective']; labels, laws = conditional(h)
        terms = [('abstain', obj['abstain'])]+[(f'answer:{j}', ce([obj['correct'], obj['wrong']], [p, 1-p], rho))
                                                    for j, p in enumerate(labels)]
        action, value = max(terms, key=lambda x: x[1])
        for v in (1, 2):
            if v in dict(h): continue
            if myopic:
                children = []
                for symbol in range(symbols):
                    child = tuple(sorted(h+((v, symbol),))); lab, _ = conditional(child)
                    children.append(max([obj['abstain']]+[ce([obj['correct'], obj['wrong']], [p, 1-p], rho) for p in lab]))
            else:
                children = [optimum(tuple(sorted(h+((v, symbol),))), rho)[1] for symbol in range(symbols)]
            candidate = ce(children, laws[v], rho)-obj['costs'][v-1]
            if candidate > value+1e-12: action, value = f'read:{v}', candidate
        return action, value
    originals = {s: {r['id']: r for r in rows} for s, rows in original_splits.items()}
    observed = read('kernel-fit-observations.json')
    require(len(observed) == len(originals['kernel']) and {r['id'] for r in observed} == set(originals['kernel']), 'kernel fit source coverage')
    rebuilt = [float(plan['kernel_alpha'])]*len(count)
    raw_kernel_rows = []
    for item in observed:
        src = originals['kernel'][item['id']]
        require(item['text_sha256'] == src['text_sha256'] and item['head_sha256'] == selection['head_sha256'], 'kernel observation identity')
        require(len(item['probabilities']) == len(item['symbols']) == 3, 'kernel view inventory')
        for p, symbol in zip(item['probabilities'], item['symbols']):
            require(len(p) == classes and all(type(x) in (float, int) and math.isfinite(x) and 0 <= x <= 1 for x in p) and abs(sum(p)-1) < 1e-5, 'kernel probability')
            require(symbol == max(range(classes), key=lambda j: p[j]), 'kernel symbol/probability mismatch')
        index = src['label']
        for symbol in item['symbols']: index = index*symbols+symbol
        rebuilt[index] += 1
        raw_kernel_rows.append((src['label'], *item['symbols']))
    kernel_profile = plan.get('kernel_model_profile', 'uniform_joint_v1')
    require(kernel_profile in ('uniform_joint_v1', 'joint_backoff_cv_v2'), 'unknown kernel profile')
    expected_arms = ('initial_only', 'full_only', 'all_views', 'best_fixed', 'confidence',
                     'myopic', 'ndu_bsde', 'compiled_same_model', 'risk_ndu')
    if kernel_profile == 'joint_backoff_cv_v2':
        from fbsde_acquisition_kernel_audit import verified_counts
        choice = read('kernel-selection.json')
        hashes = [originals['kernel'][item['id']]['text_sha256'] for item in observed]
        require(stored['binding']['smoothing_selection_sha256'] == digest(choice), 'kernel selection identity')
        rebuilt = verified_counts(raw_kernel_rows, hashes, classes, choice)
        expected_arms += ('full_symbol',)
    if guarded: expected_arms += ('ndu_backoff_5', 'ndu_backoff_20', 'risk_selected')
    require(tuple(plan['arms']) == expected_arms, 'missing or extra control arm')
    require(len(rebuilt) == len(count) and all(abs(a-b) < 1e-11 for a, b in zip(rebuilt, count)),
            'kernel counts not fitted from original training observations')
    outcomes = read('outcomes.json')
    require(outcomes == {s: {i: r['label'] for i, r in rows.items()} for s, rows in originals.items()},
            'outcome labels differ from original publisher')
    physical = read('physical.json'); require(physical['backend'] == plan['backend'], 'physical backend drift')
    tensor = root/'candidate-head.pt'
    require(tensor.is_file() and not tensor.is_symlink() and tensor.stat().st_size < 4*1024*1024 and
            hashlib.sha256(tensor.read_bytes()).hexdigest() == physical['candidate_head_file_sha256'], 'Head artifact mismatch')
    calibration_records = {}
    calibration = read('risk-calibration.json') if guarded else None
    cpu = {s: {} for s in ('validation', 'test')}; metrics = {}; root_decisions = {}; total_events = 0
    for split in ('validation', 'test'):
        attempted = None
        if plan.get('view_attempt_profile') == 'measured_attempts_v1':
            path = root/f'{split}-view-attempts.jsonl'
            require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 64*1024*1024,
                    'missing/bounded attempt journal')
            attempted = {}; previous = None
            for number, line in enumerate(path.read_bytes().splitlines()):
                item = strict_loads(line); identity = item.pop('attempt_sha256')
                require(identity == digest(item) and identity not in attempted and
                        item['previous_sha256'] == previous and item['sequence'] == number,
                        'attempt chain mismatch')
                require(item['status'] == 'returned' and item['prediction_returned'] is True and
                        item['split'] == split and item['limit_ns'] == plan['prediction_cpu_limit_ns'] and
                        type(item['cpu_ns']) is int and 0 <= item['cpu_ns'] <= item['limit_ns'],
                        'failed/overbudget attempt cannot certify a completed trial')
                require(all(type(v) is int and v >= 0 for v in item['phase_cpu_ns'].values()) and
                        sum(item['phase_cpu_ns'].values()) == item['cpu_ns'], 'view phase CPU mismatch')
                attempted[identity] = item; previous = identity
        for arm in plan['arms']:
            if guarded and split == 'validation' and arm == 'risk_selected':
                cpu[split][arm] = 0
                require(not (root/f'{split}-{arm}.jsonl').exists(), 'selected policy used before calibration')
                continue
            path = root/f'{split}-{arm}.jsonl'
            require(path.is_file() and not path.is_symlink() and path.stat().st_size < 32*1024*1024, 'trace file')
            records = [strict_loads(line) for line in path.read_bytes().splitlines()]
            require(len(records) == len(originals[split]) and {r['id'] for r in records} == set(originals[split]),
                    'incomplete/unpaired terminal inventory')
            if guarded and split == 'validation': calibration_records[arm] = records
            correct = answered = 0; rewards = []; counts = Counter(); events_count = 0; summed_cpu = 0
            support_bins = {'zero': [], 'one_to_four': [], 'five_plus': []}
            for record in records:
                r = originals[split][record['id']]; history = (); costs = 0.
                require(record['source_input_sha256'] == digest(r['text']) and record['head_sha256'] == selection['head_sha256']
                        and record['kernel_sha256'] == stored['identity'], 'input/model binding mismatch')
                require(len(record['events']) == len(record['decisions']), 'unmatched action/evidence sequence')
                for index, (event, decision) in enumerate(zip(record['events'], record['decisions'])):
                    v = event['view']; require(type(v) is int and v in range(3) and v not in dict(history), 'repeated view')
                    require((v == 0) if index == 0 else record['decisions'][index-1]['action'] == f'read:{v}',
                            'unrequested future evidence delivered')
                    receipt = event['receipt']; p = receipt['probabilities']
                    if attempted is not None:
                        identity = receipt.get('attempt_sha256')
                        require(identity in attempted, 'missing/reused view attempt')
                        attempt = attempted.pop(identity)
                        payload = {k: v for k, v in receipt.items() if k != 'attempt_sha256'}
                        require(attempt['computed_receipt_sha256'] == digest(payload) and
                                (attempt['arm'], attempt['id'], attempt['view'], attempt['head_sha256']) ==
                                (arm, record['id'], v, selection['head_sha256']), 'attempt/terminal mismatch')
                    require(len(p) == classes and all(type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 1 for x in p)
                            and abs(sum(p)-1) < 1e-5, 'invalid actual Head probabilities')
                    require(event['symbol'] == max(range(classes), key=lambda j: p[j]) and receipt['text_sha256'] == digest(text_view(r['text'], v)),
                            'view content/symbol mismatch')
                    history = tuple(sorted(history+((v, event['symbol']),)))
                    require(history == tuple(map(tuple, decision['history'])), 'history included unrevealed state')
                    key = (arm, history)
                    require(root_decisions.setdefault(key, decision['action']) == decision['action'],
                            'same information prefix changed its decision')
                    effective_arm = calibration['selected'] if arm == 'risk_selected' else arm
                    if arm == 'risk_selected' and effective_arm == 'abstain':
                        require(decision['action'] == 'abstain', 'uncertified policy returned an answer')
                    if effective_arm in ('ndu_backoff_5', 'ndu_backoff_20'):
                        raw = sum(all(rr[v+1] == sym for v, sym in history) for rr in raw_kernel_rows)
                        expected = optimum(history, 0.)[0]
                        if raw < int(effective_arm.rsplit('_', 1)[1]):
                            expected = f'answer:{dict(history)[2]}' if 2 in dict(history) else 'read:2'
                        require(decision['action'] == expected, 'raw-support fallback drift')
                    if effective_arm == 'full_symbol':
                        expected = f'answer:{dict(history)[2]}' if 2 in dict(history) else 'read:2'
                        require(decision['action'] == expected, 'full-symbol control drift')
                    if effective_arm in ('ndu_bsde', 'compiled_same_model', 'risk_ndu', 'myopic'):
                        expected, value = optimum(history, .5 if effective_arm == 'risk_ndu' else 0., effective_arm == 'myopic')
                        require(decision['action'] == expected, 'policy disagrees with independently reconstructed law')
                        if decision['bsde'] is not None:
                            require(abs(decision['bsde']['root_value']-value) < 1e-9, 'original-law value mismatch')
                    costs += plan['objective']['costs'][v-1] if v else 0.
                if split == 'test' and kernel_profile == 'joint_backoff_cv_v2':
                    support = sum(all(rr[v+1] == symbol for v, symbol in history) for rr in raw_kernel_rows)
                    belief = conditional(history)[0]
                    loss = -math.log(belief[r['label']])
                    brier = sum((q-(j == r['label']))**2 for j, q in enumerate(belief))/classes
                    group = 'zero' if support == 0 else 'one_to_four' if support < 5 else 'five_plus'
                    support_bins[group].append((support, loss, brier))
                answer = record['action']; require(answer == record['decisions'][-1]['action'], 'final decision drift')
                if answer == 'abstain':
                    require(record['text'] == 'Insufficient evidence; abstain.', 'decoder altered abstention')
                    reward = plan['objective']['abstain']
                else:
                    require(answer.startswith('answer:'), 'unterminated action')
                    label = int(answer.split(':')[1]); require(0 <= label < classes, 'answer class')
                    require(record['text'] == f'The request is classified as {intents[label]}.', 'decoder altered answer')
                    answered += 1; correct += label == r['label']
                    reward = plan['objective']['correct'] if label == r['label'] else plan['objective']['wrong']
                require(abs(costs-record['modeled_cost']) < 1e-12, 'unpaid/duplicated modeled cost')
                require(type(record['cpu_ns']) is int and record['cpu_ns'] >= 0, 'invalid CPU record')
                rewards.append(reward-costs); counts[len(history)-1] += 1; summed_cpu += record['cpu_ns']; events_count += len(history)
            cpu[split][arm] = summed_cpu; total_events += events_count
            if split == 'test':
                if kernel_profile == 'joint_backoff_cv_v2':
                    for name, values in support_bins.items():
                        saved = result['posterior_support'][arm][name]
                        require(saved['cases'] == len(values) and
                                saved['minimum_raw_support'] == min((r[0] for r in values), default=None),
                                'raw support count mismatch')
                        for key, i in (('mean_log_loss', 1), ('mean_brier', 2)):
                            expected = sum(r[i] for r in values)/len(values) if values else None
                            require(saved[key] is None if expected is None else
                                    abs(saved[key]-expected) < 1e-10, 'support calibration mismatch')
                m = result['metrics'][arm]
                require(m['correct'] == correct and m['answered'] == answered and abs(m['mean_external_score_minus_cost']-sum(rewards)/len(rewards)) < 1e-12,
                        'reported answer/utility metrics mismatch')
                require(result['actual_test_forwards'][arm] == events_count, 'forward-count mismatch')
                metrics[arm] = {'correct': correct, 'answered': answered, 'mean_score': sum(rewards)/len(rewards)}
        require(attempted is None or not attempted, 'unaccounted attempted work')
        if guarded and split == 'validation':
            verify_calibration(calibration, calibration_records, original_splits[split],
                digest([stored['identity'], selection['head_sha256'], plan['objective']]))
            require(calibration == result['conditional_risk_selection'], 'risk report drift')
    require(cpu['test'] == result['actual_test_cpu_ns'] and cpu['validation'] == result['actual_validation_cpu_ns'], 'CPU sums mismatch')
    classified = sum(j['cpu_ns'] for j in result['jobs_once'])+sum(sum(v.values()) for v in cpu.values())
    require(len({j['id'] for j in result['jobs_once']}) == len(result['jobs_once']), 'physical job repeated')
    require(classified == result['classified_cpu_ns'] and classified+result['unallocated_preparation_recording_ns'] == result['measured_experiment_cpu_ns'],
            'CPU envelope mismatch')
    return {'original_arithmetic_recomputed': True, 'metrics': metrics, 'actual_requested_views': total_events,
            'nonanticipative_information_sets_checked': len(root_decisions),
            'physical_execution_authenticated': False, 'semantic_law_truth_authenticated': False,
            'test_label_independence_authenticated': False, 'production_promotion_permitted': False}


def verify_calibration(saved, records, originals, binding):
    """Rebuild the frozen finite-family certificate without importing its fitter."""
    candidates = ('full_symbol', 'ndu_bsde', 'ndu_backoff_5', 'ndu_backoff_20')
    rule = {'alpha': .05, 'max_accepted_error': .10, 'min_coverage': .50, 'min_sources': 200}
    require(saved['binding'] == binding and saved['rule'] == rule, 'risk calibration binding/rule drift')
    labelled = [(r['id'], r['text_sha256'], r['label']) for r in originals]
    require(saved['source_inventory_sha256'] == digest(labelled) and
            saved['candidate_predictions_sha256'] == digest({a: records[a] for a in candidates}),
            'risk calibration source/prediction drift')
    require(len({r['text_sha256'] for r in originals}) == len(originals), 'duplicate risk source')
    n = len(originals); label = {r['id']: r['label'] for r in originals}
    def tail(k, upper):
        p = k/n; lo, hi = (p, 1.) if upper else (0., p)
        target = math.log(2*len(candidates)/rule['alpha'])/n
        for _ in range(70):
            q = (lo+hi)/2
            if q == 0 or q == 1: break
            divergence = (p*math.log(p/q) if p else 0)+((1-p)*math.log((1-p)/(1-q)) if p < 1 else 0)
            if (divergence > target) == upper: hi = q
            else: lo = q
        return hi if upper else lo
    passed = []
    for arm in candidates:
        rows = records[arm]; accepted = sum(r['action'] != 'abstain' for r in rows)
        errors = sum(r['action'] not in ('abstain', f"answer:{label[r['id']]}") for r in rows)
        coverage, error = tail(accepted, False), tail(errors, True)
        risk = min(1., error/coverage) if coverage else 1.
        profile = saved['profiles'][arm]
        require((profile['sources'], profile['accepted'], profile['wrong']) == (n, accepted, errors),
                'risk observed counts drift')
        require(all(abs(profile[k]-v) < 1e-11 for k,v in
                (('coverage_lcb', coverage), ('joint_error_ucb', error), ('accepted_error_ucb', risk))),
                'risk confidence bound drift')
        score = sum((0 if r['action'] == 'abstain' else 1 if r['action'] == f"answer:{label[r['id']]}" else -1)
                    - r['modeled_cost'] for r in rows)/n
        require(abs(profile['empirical_score']-score) < 1e-12, 'calibration objective drift')
        valid = n >= rule['min_sources'] and accepted > 0 and coverage >= .5 and risk <= .1
        require(profile['conditional_certificate'] == valid, 'unsupported risk certificate')
        if valid: passed.append(arm)
    selected = max(passed, key=lambda a: (saved['profiles'][a]['accepted'],
                   saved['profiles'][a]['empirical_score'], -candidates.index(a))) if passed else 'abstain'
    require(saved['selected'] == selected and saved['no_candidate_passes'] == (not passed),
            'calibration winner or abstention drift')
