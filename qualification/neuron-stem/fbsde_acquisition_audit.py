"""Independent original-file arithmetic recheck; imports no policy or neural model."""
from collections import Counter
from functools import lru_cache
from itertools import product
import hashlib
import math
from pathlib import Path

from four_gate_common import digest, require, strict_loads
from fbsde_acquisition_data import INTENTS, text_view


def audit(directory, original_splits):
    root = Path(directory)
    def read(name):
        p = root/name
        require(p.is_file() and not p.is_symlink() and p.stat().st_size <= 32*1024*1024,
                'bounded regular audit source')
        return strict_loads(p.read_bytes())
    plan, result, stored, selection = (read(n) for n in ('plan.json', 'results.json', 'kernel.json', 'selection.json'))
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
    require(rebuilt == count, 'kernel counts not fitted from original training observations')
    outcomes = read('outcomes.json')
    require(outcomes == {s: {i: r['label'] for i, r in rows.items()} for s, rows in originals.items()},
            'outcome labels differ from original publisher')
    physical = read('physical.json'); require(physical['backend'] == plan['backend'], 'physical backend drift')
    tensor = root/'candidate-head.pt'
    require(tensor.is_file() and not tensor.is_symlink() and tensor.stat().st_size < 4*1024*1024 and
            hashlib.sha256(tensor.read_bytes()).hexdigest() == physical['candidate_head_file_sha256'], 'Head artifact mismatch')
    cpu = {s: {} for s in ('validation', 'test')}; metrics = {}; root_decisions = {}; total_events = 0
    for split in ('validation', 'test'):
        for arm in plan['arms']:
            path = root/f'{split}-{arm}.jsonl'
            require(path.is_file() and not path.is_symlink() and path.stat().st_size < 32*1024*1024, 'trace file')
            records = [strict_loads(line) for line in path.read_bytes().splitlines()]
            require(len(records) == len(originals[split]) and {r['id'] for r in records} == set(originals[split]),
                    'incomplete/unpaired terminal inventory')
            correct = answered = 0; rewards = []; counts = Counter(); events_count = 0; summed_cpu = 0
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
                    require(len(p) == classes and all(type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 1 for x in p)
                            and abs(sum(p)-1) < 1e-5, 'invalid actual Head probabilities')
                    require(event['symbol'] == max(range(classes), key=lambda j: p[j]) and receipt['text_sha256'] == digest(text_view(r['text'], v)),
                            'view content/symbol mismatch')
                    history = tuple(sorted(history+((v, event['symbol']),)))
                    require(history == tuple(map(tuple, decision['history'])), 'history included unrevealed state')
                    key = (arm, history)
                    require(root_decisions.setdefault(key, decision['action']) == decision['action'],
                            'same information prefix changed its decision')
                    if arm in ('ndu_bsde', 'compiled_same_model', 'risk_ndu', 'myopic'):
                        expected, value = optimum(history, .5 if arm == 'risk_ndu' else 0., arm == 'myopic')
                        require(decision['action'] == expected, 'policy disagrees with independently reconstructed law')
                        if decision['bsde'] is not None:
                            require(abs(decision['bsde']['root_value']-value) < 1e-9, 'original-law value mismatch')
                    costs += plan['objective']['costs'][v-1] if v else 0.
                answer = record['action']; require(answer == record['decisions'][-1]['action'], 'final decision drift')
                if answer == 'abstain':
                    require(record['text'] == 'Insufficient evidence; abstain.', 'decoder altered abstention')
                    reward = plan['objective']['abstain']
                else:
                    require(answer.startswith('answer:'), 'unterminated action')
                    label = int(answer.split(':')[1]); require(0 <= label < classes, 'answer class')
                    require(record['text'] == f'The request is classified as {INTENTS[label]}.', 'decoder altered answer')
                    answered += 1; correct += label == r['label']
                    reward = plan['objective']['correct'] if label == r['label'] else plan['objective']['wrong']
                require(abs(costs-record['modeled_cost']) < 1e-12, 'unpaid/duplicated modeled cost')
                require(type(record['cpu_ns']) is int and record['cpu_ns'] >= 0, 'invalid CPU record')
                rewards.append(reward-costs); counts[len(history)-1] += 1; summed_cpu += record['cpu_ns']; events_count += len(history)
            cpu[split][arm] = summed_cpu; total_events += events_count
            if split == 'test':
                m = result['metrics'][arm]
                require(m['correct'] == correct and m['answered'] == answered and abs(m['mean_external_score_minus_cost']-sum(rewards)/len(rewards)) < 1e-12,
                        'reported answer/utility metrics mismatch')
                require(result['actual_test_forwards'][arm] == events_count, 'forward-count mismatch')
                metrics[arm] = {'correct': correct, 'answered': answered, 'mean_score': sum(rewards)/len(rewards)}
    require(cpu['test'] == result['actual_test_cpu_ns'] and cpu['validation'] == result['actual_validation_cpu_ns'], 'CPU sums mismatch')
    classified = sum(j['cpu_ns'] for j in result['jobs_once'])+sum(sum(v.values()) for v in cpu.values())
    require(len({j['id'] for j in result['jobs_once']}) == len(result['jobs_once']), 'physical job repeated')
    require(classified == result['classified_cpu_ns'] and classified+result['unallocated_preparation_recording_ns'] == result['measured_experiment_cpu_ns'],
            'CPU envelope mismatch')
    return {'original_arithmetic_recomputed': True, 'metrics': metrics, 'actual_requested_views': total_events,
            'nonanticipative_information_sets_checked': len(root_decisions),
            'physical_execution_authenticated': False, 'semantic_law_truth_authenticated': False,
            'test_label_independence_authenticated': False, 'production_promotion_permitted': False}
