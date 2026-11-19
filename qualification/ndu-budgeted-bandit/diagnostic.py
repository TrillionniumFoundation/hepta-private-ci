"""Synthetic one-step routing controls. Not a Hepta scientific gate runner."""
import hashlib
import json
import math
import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

N_TRAIN = 4096
N_EVAL = 4096
SEEDS = range(32)
COSTS = (1, 3)
FULL = ((.6, .9), (.6, .8), (.6, .55), (.6, .95))
HIGH = ((.6, .9), (.6, .8), (.6, .95), (.6, .95))
LOW = ((.6, .9), (.6, .8), (.6, 0.), (.6, 0.))
SHIFT = ((.6, .05), (.6, .05), (.6, .55), (.6, .05))
POLICIES = ('baseline', 'empirical_extrapolation', 'support_lcb')


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


@dataclass(frozen=True)
class LoggedEvent:
    context: int
    action: int
    reward: int
    propensity: float
    cost: int


def generate_train(seed, *, deficient=False, means=FULL, n=N_TRAIN):
    # Only the chosen reward is drawn; the hidden reward law cannot change logs.
    rng = random.Random(100000 + seed)
    rows = []
    for _ in range(n):
        x = rng.randrange(4)
        restricted = deficient and x in (2, 3)
        action = 0 if restricted else rng.randrange(2)
        propensity = 1. if restricted else .5
        reward = int(rng.random() < means[x][action])
        rows.append(LoggedEvent(x, action, reward, propensity, COSTS[action]))
    return rows


def fit(rows):
    if not rows:
        raise ValueError('training log is empty')
    counts = [[0, 0] for _ in range(4)]
    sums = [[0, 0] for _ in range(4)]
    for row in rows:
        if (row.context not in range(4) or row.action not in range(2)
                or row.reward not in (0, 1) or not 0 < row.propensity <= 1
                or row.cost != COSTS[row.action]):
            raise ValueError('invalid logged event')
        counts[row.context][row.action] += 1
        sums[row.context][row.action] += row.reward
    pooled = []
    for a in range(2):
        n = sum(counts[x][a] for x in range(4))
        pooled.append(sum(sums[x][a] for x in range(4)) / n if n else 0.)
    estimates = [[sums[x][a] / counts[x][a] if counts[x][a] else pooled[a]
                  for a in range(2)] for x in range(4)]
    naive, conservative = [], []
    for x in range(4):
        naive.append(int(estimates[x][1] > estimates[x][0]))
        supported = min(counts[x]) >= 32
        radii = [math.sqrt(math.log(16 / .05) / (2 * n)) if n else None
                 for n in counts[x]]
        safe = supported and estimates[x][1] - radii[1] > estimates[x][0] + radii[0]
        conservative.append(int(safe))
    return {'counts': counts, 'estimates': estimates,
            'maps': {'baseline': [0] * 4, 'empirical_extrapolation': naive,
                     'support_lcb': conservative}}


def admitted_action(requested, spent, index, horizon, cap):
    if (requested not in (0, 1) or not 0 <= index < horizon
            or spent < 0 or cap < horizon):
        raise ValueError('invalid or infeasible budget state')
    remaining = horizon - index - 1
    action = requested if spent + COSTS[requested] + remaining <= cap else 0
    if spent + COSTS[action] + remaining > cap:
        raise ValueError('baseline reserve was already violated')
    return action


def evaluation_stream(seed, n=N_EVAL):
    rng = random.Random(200000 + seed)
    return [(rng.randrange(4), (rng.random(), rng.random())) for _ in range(n)]


def rollout(policy, stream, means, counts, cap):
    horizon = len(stream)
    spent = reward = blocks = unsupported = expensive = 0
    expected = 0.
    actions = []
    max_reserve_excess = 0
    for i, (context, draws) in enumerate(stream):
        requested = policy[context]
        action = admitted_action(requested, spent, i, horizon, cap)
        blocks += int(action != requested)
        spent += COSTS[action]
        expensive += action
        unsupported += int(counts[context][action] == 0)
        reward += int(draws[action] < means[context][action])
        expected += means[context][action]
        actions.append(action)
        max_reserve_excess = max(max_reserve_excess, spent + horizon - i - 1 - cap)
    return {'mean_reward': reward / horizon, 'expected_mean_reward': expected / horizon,
            'spend': spent, 'cap': cap, 'budget_interventions': blocks,
            'unsupported_choices': unsupported, 'expensive_choices': expensive,
            'max_reserve_excess': max_reserve_excess, 'actions_sha256': digest(actions)}


def interval(values):
    mean = statistics.mean(values)
    margin = 2.039513 * statistics.stdev(values) / math.sqrt(len(values))
    return {'mean': mean, 'descriptive_95pct_t_interval': [mean - margin, mean + margin],
            'seed_min': min(values), 'seed_max': max(values)}


def run():
    started = time.perf_counter()
    scenarios = {'full_support': (False, FULL, FULL),
                 'deficient_high': (True, HIGH, HIGH),
                 'deficient_low': (True, LOW, LOW),
                 'reward_law_shift': (False, FULL, SHIFT)}
    rows = []
    for seed in SEEDS:
        stream = evaluation_stream(seed)
        for scenario, (deficient, train_means, eval_means) in scenarios.items():
            training = generate_train(seed, deficient=deficient, means=train_means)
            fitted = fit(training)
            result = {p: rollout(fitted['maps'][p], stream, eval_means,
                                 fitted['counts'], N_EVAL * 7 // 4) for p in POLICIES}
            baseline = result['baseline']
            for p in POLICIES:
                result[p]['paired_reward_gain'] = result[p]['mean_reward'] - baseline['mean_reward']
                result[p]['paired_expected_gain'] = result[p]['expected_mean_reward'] - baseline['expected_mean_reward']
            rows.append({'seed': seed, 'scenario': scenario,
                         'training_sha256': digest([r.__dict__ for r in training]),
                         'evaluation_stream_sha256': digest(stream),
                         'fitted': fitted, 'policies': result})
    summary = {}
    for scenario in scenarios:
        subset = [r for r in rows if r['scenario'] == scenario]
        summary[scenario] = {}
        for p in POLICIES:
            outcomes = [r['policies'][p] for r in subset]
            summary[scenario][p] = {
                'paired_reward_gain': interval([r['paired_reward_gain'] for r in outcomes]),
                'paired_expected_gain': interval([r['paired_expected_gain'] for r in outcomes]),
                'mean_spend': statistics.mean(r['spend'] for r in outcomes),
                'max_spend': max(r['spend'] for r in outcomes),
                'budget_violations': sum(r['spend'] > r['cap'] or r['max_reserve_excess'] > 0 for r in outcomes),
                'unsupported_choices': sum(r['unsupported_choices'] for r in outcomes),
                'total_expensive_choices': sum(r['expensive_choices'] for r in outcomes),
                'total_budget_interventions': sum(r['budget_interventions'] for r in outcomes)}
    twins = []
    for seed in SEEDS:
        high = next(r for r in rows if r['seed'] == seed and r['scenario'] == 'deficient_high')
        low = next(r for r in rows if r['seed'] == seed and r['scenario'] == 'deficient_low')
        twins.append(high['training_sha256'] == low['training_sha256']
                     and high['fitted'] == low['fitted']
                     and all(high['policies'][p]['actions_sha256'] == low['policies'][p]['actions_sha256'] for p in POLICIES))
    checks = {
        'all_32_twins_identical_observed_logs_fits_and_decisions': all(twins),
        'all_policy_runs_within_cap_and_prefix_reserve': all(v['budget_violations'] == 0 for s in summary.values() for v in s.values()),
        'conservative_never_selects_unobserved_cell': all(s['support_lcb']['unsupported_choices'] == 0 for s in summary.values()),
        'full_support_conservative_gain_interval_positive': summary['full_support']['support_lcb']['paired_reward_gain']['descriptive_95pct_t_interval'][0] > 0,
        'shift_conservative_gain_interval_negative': summary['reward_law_shift']['support_lcb']['paired_reward_gain']['descriptive_95pct_t_interval'][1] < 0,
        'empirical_twin_high_gain_interval_positive_low_negative': summary['deficient_high']['empirical_extrapolation']['paired_reward_gain']['descriptive_95pct_t_interval'][0] > 0 and summary['deficient_low']['empirical_extrapolation']['paired_reward_gain']['descriptive_95pct_t_interval'][1] < 0,
    }
    root = Path(__file__).resolve().parent
    report = {'scope': 'synthetic_mechanism_diagnostic_only', 'protocol_version': 1,
              'protocol_sha256': hashlib.sha256((root / 'PROTOCOL.md').read_bytes()).hexdigest(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'all_six_scientific_blockers_remain_open': True,
              'n_seeds': len(SEEDS), 'n_train': N_TRAIN, 'n_eval': N_EVAL,
              'summary': summary, 'checks': checks, 'per_seed': rows,
              'harness_wall_seconds_not_model_cost': time.perf_counter() - started}
    output = root / 'results.json'
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: report[k] for k in ('scope', 'checks', 'summary', 'harness_wall_seconds_not_model_cost')}, indent=2))


if __name__ == '__main__':
    run()
