"""Independent trajectory enumeration and central differences on synthetic DAGs."""
from pathlib import Path
import itertools
import json
import hashlib
import math
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
from data_contract import exact_radius, save
from soft_value import Forest, optimize


def tiny(p, scale):
    masks = np.array([[1, 1, 1, 0, 1, 1], [1, 0, 1, 0, 1, 1], [1, 0, 0, 0, 1, 1],
                      [1, 0, 0, 0, 1, 1]], dtype=bool)
    posterior = np.array([p, .2, .85, .4])
    terminal = np.zeros((4, 6))
    terminal[:, 4], terminal[:, 5] = 1 - 2 * posterior, 2 * posterior - 1
    graph = dict(masks=masks, posterior=posterior, terminal=terminal,
        states=[dict(tick=t) for t in (0, 1, 2, 2)], initial=0,
        edges=[[[[1., 1, .02]], [[1., 1, .15]], []], [[], [[.3, 2, .07], [.7, 3, .07]], []],
               [[], [], []], [[], [], []]])
    generator = np.random.Generator(np.random.PCG64(20261122))
    hidden = generator.uniform(-scale, scale, (4, 49))
    hidden[:, -1] = 1
    return dict(graph=graph, H=hidden)


def enumerated(item, rows, temperature):
    graph, H = item['graph'], item['H']
    count = 0
    def walk(index, probability, accumulated):
        nonlocal count
        logits = [sum(float(h) * float(w) for h, w in zip(H[index], row)) for row in rows]
        posterior = 1 / (1 + math.exp(-logits[3]))
        scores = [0, *logits[:3], 1 - 2 * posterior, 2 * posterior - 1]
        legal = [a for a, x in enumerate(graph['masks'][index]) if x]
        largest = max(scores[a] / temperature for a in legal)
        weights = {a: math.exp(scores[a] / temperature - largest) for a in legal}
        denominator = sum(weights.values())
        total = 0.
        for action in legal:
            mass = probability * weights[action] / denominator
            if action in (0, 4, 5):
                count += 1
                total += mass * (accumulated + float(graph['terminal'][index, action]))
            else:
                for branch_mass, after, fee in graph['edges'][index][action - 1]:
                    total += walk(after, mass * branch_mass, accumulated - fee)
        return total
    return walk(graph['initial'], 1., 0.), count


def main():
    destination = Path(sys.argv[1])
    destination.mkdir(parents=True, exist_ok=False)
    started, wall = time.process_time(), time.monotonic()
    generator = np.random.Generator(np.random.PCG64(17))
    anchor = generator.normal(0, .06, (4, 49))
    rows = anchor + generator.normal(0, .003, (4, 49))
    radius = exact_radius(anchor)['numeric_radius']
    cases, max_fd, max_value = [], 0., 0.
    for tau in (.1, .3):
        items = [tiny(.37, .25), tiny(.68, .5)]
        forest = Forest(items)
        actual = forest.evaluate(rows, anchor, radius, tau, .001, True)
        witnesses = [enumerated(item, rows, tau) for item in items]
        expected = sum(x[0] for x in witnesses) / len(items)
        error = abs(actual['utility'] - expected)
        assert error <= 2e-13, error
        max_value = max(max_value, error)
        maximum = 0.
        for r, c in itertools.product(range(4), range(49)):
            plus, minus = rows.copy(), rows.copy()
            plus[r, c] += 1e-6
            minus[r, c] -= 1e-6
            upper = forest.evaluate(plus, anchor, radius, tau, .001)['objective']
            lower = forest.evaluate(minus, anchor, radius, tau, .001)['objective']
            difference = (upper - lower) / 2e-6
            error = abs(float(actual['gradient'][r, c]) - difference)
            maximum = max(maximum, error)
            assert error <= 3e-8 + 5e-6 * abs(difference), (r, c, error)
        max_fd = max(max_fd, maximum)
        cases.append(dict(temperature=tau, enumerated_terminal_paths=sum(x[1] for x in witnesses),
                          absolute_value_error=abs(actual['utility'] - expected), maximum_gradient_error=maximum))
    settings = dict(radius=radius, temperature=.1, penalty=.001, family_cpu_seconds=5,
                    direct_rounds=1, states_per_round=2, proposal_doses=[.5, 1.],
                    bp_steps=4, bp_relative_step=.25, proposal_slots=4)
    reports = {}
    def legal(a, b):
        assert exact_radius(a, b)['within_shared_ball']
    for family in ('DIRECT', 'BP'):
        forest = Forest([tiny(.37, .25), tiny(.68, .5)])
        candidate, report = optimize(forest, anchor, family, settings, legal, lambda: None)
        assert report['status'] == 'COMPLETED', report
        assert report['counters']['objective_calls'] == 5
        assert report['counters']['gradient_calls'] == (5 if family == 'BP' else 0)
        assert report['counters']['complete_policy_DPs'] == 10
        legal(anchor, candidate)
        reports[family] = report
    limited = dict(settings, family_cpu_seconds=-1)
    candidate, report = optimize(Forest([tiny(.4, .2)]), anchor, 'DIRECT', limited, legal, lambda: None)
    assert candidate is None and report['status'] == 'FAILED_KEEP'
    result = dict(status='PASS', scope='synthetic-only independent enumeration and derivative/ledger controls',
                  cases=cases, maximum_absolute_value_error=max_value, maximum_absolute_gradient_error=max_fd,
                  optimizer_controls=reports, budget_refusal=report,
                  CPU_seconds=time.process_time() - started, wall_seconds=time.monotonic() - wall,
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    save(destination / 'RESULTS.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('optimizer_controls', 'budget_refusal')}))


if __name__ == '__main__':
    main()
