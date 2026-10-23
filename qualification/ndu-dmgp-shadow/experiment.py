"""A0-A5 reproducible *synthetic* shadow ablation; no neural inference claims.

Run `python3 experiment.py`; programmatic output is JSON. Every input, reward,
latency and decoder operation below is explicitly simulated. Controller CPU
bookkeeping is measured but cannot be compared to real GPU decode latency.
"""
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from math import cos, sin
from statistics import mean
from time import perf_counter_ns
import json

from reference import (Action, Freeze, GenerationState, JointSample, Outcome,
                       allocate, joint_covariance, paired_future_evaluation,
                       recursive_stop_choice, require)

FREEZE = Freeze('synthetic-objective-v1', 1, 'shadow-generator', 'shadow-critic',
                'synthetic-independent-evaluator', 'critic-freeze-v1',
                'feature-freeze-v1')
ARMS = ('A0', 'A1', 'A2', 'A3', 'A4', 'A5')
COST = {'text': 1000, 'image': 1400}


@dataclass(frozen=True)
class Prompt:
    episode: int
    context: str
    split: str


def prompts(split: str, count: int = 40) -> tuple[Prompt, ...]:
    require(split in {'train', 'future'}, 'invalid split')
    offset = 0 if split == 'train' else 10000
    return tuple(Prompt(offset + i, 'complex' if i % 2 else 'simple', split)
                 for i in range(count))


def gains(prompt: Prompt) -> dict[str, float]:
    # Fixed synthetic oracle, never fitted on the future split.
    return ({'text': .06, 'image': .20} if prompt.context == 'complex'
            else {'text': .23, 'image': .05})


def independent_synthetic_score(prompt: Prompt, chosen: tuple[str, ...]) -> float:
    """Explicit simulator oracle, NOT evidence of external model output truth."""
    g = gains(prompt)
    quality = .45 + sum(g[a] for a in chosen)
    if set(chosen) == {'text', 'image'}:
        quality += .07 if prompt.context == 'complex' else .01
    quality += .01 * sin(prompt.episode * .8)
    # Action-specific realized variation lives in the outcome oracle itself.
    # The train-only risk estimator below uses these *observed simulated*
    # returns, not a second fabricated variance bolted onto forecasts.
    quality += (.015 * sin(prompt.episode * .7) if 'text' in chosen else 0.0)
    quality += (.02 * cos(prompt.episode * .5) if 'image' in chosen else 0.0)
    return min(1.0, quality)


@dataclass(frozen=True)
class TrainingSignals:
    context: str
    text_advantage: float
    image_advantage: float
    pair_synergy: float
    train_episodes: tuple[int, ...]


@lru_cache(maxsize=1)
def frozen_training_signals() -> tuple[TrainingSignals, ...]:
    """Fit A2/A3/A5 on TRAIN ONLY; never inspect a future scenario's oracle.

    Full factorial labels are synthetic training outcomes, not a real task
    observer, causal intervention or evidence of independent NDU utility.
    """
    result = []
    for context in ('simple', 'complex'):
        data = tuple(p for p in prompts('train', 80) if p.context == context)
        require(len(data) >= 20 and len({p.episode for p in data}) == len(data),
                'unpaired or unsupported training labels')
        labels = tuple((independent_synthetic_score(p, ()),
                        independent_synthetic_score(p, ('text',)),
                        independent_synthetic_score(p, ('image',)),
                        independent_synthetic_score(p, ('text', 'image')))
                       for p in data)
        result.append(TrainingSignals(
            context,
            mean(t - b for b, t, _, _ in labels),
            mean(i - b for b, _, i, _ in labels),
            mean(ti - t - i + b for b, t, i, ti in labels),
            tuple(p.episode for p in data)))
    return tuple(result)


@lru_cache(maxsize=1)
def training_risk() -> dict[str, object]:
    result = {}
    for context in ('simple', 'complex'):
        samples = tuple(JointSample(
            str(p.episode), context, FREEZE.objective, FREEZE.observer,
            tuple(independent_synthetic_score(p, (a,)) -
                  independent_synthetic_score(p, ())
                  for a in ('text', 'image')))
            for p in prompts('train', 80) if p.context == context)
        result[context] = joint_covariance(samples, FREEZE, context)
    return result


def decide_detail(arm: str, prompt: Prompt,
                  risk: object) -> tuple[tuple[str, ...], float]:
    """Chosen generation actions and exact executed behavior propensity."""
    require(prompt.context in ('simple', 'complex')
            and prompt.split in ('train', 'future'), 'invalid evaluation context')
    signal = next(item for item in frozen_training_signals()
                  if item.context == prompt.context)
    g = {'text': signal.text_advantage, 'image': signal.image_advantage}
    if arm == 'A0':
        return ('text',), 1.0
    if arm == 'A1':
        return ('text', 'image'), 1.0
    if arm == 'A2':
        return (max(('text', 'image'), key=lambda a: (g[a], a)),), 1.0
    if arm == 'A3':
        return (max(('text','image'),
                    key=lambda a: (g[a] - COST[a]*1e-5, a)),), 1.0
    if arm == 'A4':
        actions = (Action('text', 'text', COST['text']),
                   Action('image', 'image', COST['image']))
        weights = allocate(actions, risk, 2600, 1.5, .08, (.5,.5))
        # Deterministic counter-based draw, independent of outcome labels.
        # The receipt stores the ACTUAL categorical behavior propensity, not
        # the model's raw output probability or its highest-weight route.
        seed = sha256(f'{FREEZE.objective}:{prompt.episode}:A4:policy-v1'.encode()).digest()
        u = int.from_bytes(seed[:8], 'big') / 2**64
        cumulative = 0.0
        for i, w in enumerate(weights.weights):
            cumulative += w
            if u < cumulative or i == len(weights.weights) - 1:
                require(w > 0, 'zero-propensity route forbidden')
                return (actions[i].name,), w
        raise AssertionError('unreachable portfolio simplex')
    if arm == 'A5':
        actions = tuple(Action(a, a, COST[a]) for a in ('text','image'))
        state = GenerationState(1, 2600, 2, .45)
        pair = {frozenset({'text','image'}): signal.pair_synergy}
        first, _ = recursive_stop_choice(state, actions, g, cost_per_us=1e-5,
                                         pair_gain=pair)
        if first == 'stop':
            return (), 1.0
        state2 = GenerationState(1, 2600-COST[first], 1, .45+g[first])
        next_actions = tuple(a for a in actions if a.name != first)
        # Already-earned synergy enters the one-step successor estimate.
        next_gains = {a.name: g[a.name] + pair[frozenset({a.name,first})]
                      for a in next_actions}
        second, _ = recursive_stop_choice(state2, next_actions, next_gains,
                                          cost_per_us=1e-5)
        return ((first,) if second == 'stop' else (first, second)), 1.0
    raise ValueError('unknown arm')


def decide(arm: str, prompt: Prompt, risk: object) -> tuple[str, ...]:
    return decide_detail(arm, prompt, risk)[0]


def run() -> dict:
    risk = training_risk()
    results = {arm: [] for arm in ARMS}
    for prompt in prompts('future', 40):
        for arm in ARMS:
            t0 = perf_counter_ns()
            chosen, propensity = decide_detail(arm, prompt, risk[prompt.context])
            controller_us = max(0, (perf_counter_ns() - t0 + 999) // 1000)
            results[arm].append(Outcome(
                str(prompt.episode), arm, FREEZE.objective, FREEZE.generation,
                FREEZE.observer, FREEZE.actor, FREEZE.critic_digest,
                f'simulated-prompt-{prompt.episode}', 'future',
                independent_synthetic_score(prompt, chosen),
                500 + sum(COST[a] for a in chosen), controller_us, 50,
                f'simulation:{prompt.episode}:{arm}', propensity))
    output = {'kind': 'synthetic-shadow-only', 'model_training': False,
              'neural_decoding': False, 'gpu_benchmark': False,
              'objective': FREEZE.objective, 'episodes': 40, 'arms': {}}
    for arm in ARMS:
        rows = results[arm]
        output['arms'][arm] = {
            'mean_synthetic_quality': round(sum(r.observed_utility for r in rows)/len(rows), 6),
            'mean_simulated_decoder_us': round(sum(r.decoder_us for r in rows)/len(rows), 3),
            'mean_local_controller_us': round(sum(r.controller_us for r in rows)/len(rows), 3),
            'mean_realized_route_propensity': round(
                sum(r.behavior_propensity for r in rows)/len(rows), 6)}
        if arm != 'A0':
            gain, lcb, count = paired_future_evaluation(
                tuple(results['A0'] + rows), FREEZE, 'A0', arm, 1e-5)
            output['arms'][arm]['paired_net_gain'] = round(gain, 6)
            output['arms'][arm]['paired_exploratory_lcb'] = round(lcb, 6)
            output['arms'][arm]['paired_cases'] = count
    return output


if __name__ == '__main__':
    print(json.dumps(run(), indent=2, sort_keys=True))
