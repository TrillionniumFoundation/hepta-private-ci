"""Measure local proxy/exact gaps using a trained RR checkpoint's first controls.

This freezes drift, threshold and resource availability after the first controller
calculation. It is not a transfer of the complete trained recurrent policy to the
exact engine. It isolates the one-event cap and conditional-mean closure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from rrsnn_experiments.resource_env import Scenario, state_features
from rrsnn_experiments.train_compare import Policy
from rrsnn_experiments.models.sequence_models import surviving_distance_mean
from rrsnn_experiments.runtime.event_runtime import Neuron, first_hit_cdf, simulate


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def count_law(distance, drift, sigma, refractory, horizon):
    """Exact renewal count law with constant controls and reset to zero.

    P(N(H)>=n) = F_{n*distance}(H-(n-1)*refractory; mu=-drift).
    This uses the strong Markov property and first-passage convolution for
    identical Brownian reset segments. Both drift signs are allowed.
    """
    tails = []
    for count in range(1, math.ceil(horizon / refractory) + 1):
        active_time = horizon - (count - 1) * refractory
        tails.append(first_hit_cdf(count * distance, active_time, -drift, sigma))
    pmf = np.r_[1.0, tails] - np.r_[tails, 0.0]
    if pmf.min() < -1e-12 or abs(pmf.sum() - 1.0) > 1e-12:
        raise AssertionError('Invalid renewal-count distribution')
    return {
        'firstHitProbability': tails[0],
        'probabilityAtLeastTwoEvents': tails[1] if len(tails) > 1 else 0.0,
        'exactMeanCount': float(sum(tails)),
        'singleIntervalProxyMeanCount': tails[0],
        'missedCountFromOneEventCap': float(sum(tails[1:])),
        'countPmf': pmf.tolist(),
    }


def closure_gap(distance, drift, sigma, horizon):
    half = horizon / 2.0
    p_first = first_hit_cdf(distance, half, -drift, sigma)
    x = torch.tensor([distance], dtype=torch.float64)
    t = torch.tensor([half], dtype=torch.float64)
    mu = torch.tensor([-drift], dtype=torch.float64)
    conditional_mean = float(surviving_distance_mean(x, t, mu, sigma)[0])
    p_next_at_mean = first_hit_cdf(conditional_mean, half, -drift, sigma)
    approximation = p_first + (1.0 - p_first) * p_next_at_mean
    exact = first_hit_cdf(distance, horizon, -drift, sigma)
    return {
        'exactUnsplitFirstHitProbability': exact,
        'twoHalfIntervalsMeanClosureFirstHitProbability': approximation,
        'signedProbabilityDifference': approximation - exact,
        'absoluteProbabilityDifference': abs(approximation - exact),
        'conditionalDistanceMeanAtHalf': conditional_mean,
        'tailClampReached': conditional_mean <= 1e-5 or conditional_mean >= 50.0,
    }


def controls(checkpoint):
    saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
    if saved['variant'] != 'rr_full':
        raise ValueError('Use an rr_full checkpoint for this probe')
    hidden = int(saved['state_dict']['encoder.input_layer.weight'].shape[0])
    model = Policy('rr_full', hidden=hidden, mode='expected').eval()
    model.load_state_dict(saved['state_dict'])
    common = dict(values=(1.4, 1.2, .7, .5), budget=4,
                  shock_amount=2, refill_amount=1)
    scenarios = [Scenario(deadlines=(1., 1., 3., 3.), profile='A', **common),
                 Scenario(deadlines=(2., 2., 2., 2.), profile='B', **common)]
    feature = np.stack([state_features(s, 0., 15, s.budget) for s in scenarios])
    inputs = torch.from_numpy(feature[:, None, :])
    with torch.no_grad():
        output = model(inputs, torch.full((2, 1), .1))
        # At the first update recurrent events and retained state are zero.
        pre = model.encoder.input_layer(inputs[:, 0])
        drift = (.45 + .8 * torch.tanh(pre)).clamp(min=-.6, max=1.5)
    thresholds = output['thresholds'][:, 0].numpy()
    values = []
    for row, scenario in enumerate(scenarios):
        for unit in range(hidden):
            values.append({'profile': scenario.profile, 'unit': unit,
                           'distance': float(thresholds[row, unit]),
                           'drift': float(drift[row, unit])})
    return values, model.encoder.constants, saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path,
                        default=ROOT / 'results/rr_full/seed_101/model.pt')
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).with_name('proxy_exact_gap.json'))
    parser.add_argument('--samples', type=int, default=1500)
    args = parser.parse_args()
    torch.set_num_threads(1)
    values, constants, saved = controls(args.checkpoint)
    horizons = [.1, .25, .5, 1., 2., 4.]
    records = []
    for item in values:
        for horizon in horizons:
            count = count_law(item['distance'], item['drift'], constants.sigma,
                              constants.refractory, horizon)
            closure = closure_gap(item['distance'], item['drift'], constants.sigma, horizon)
            records.append({**item, 'horizon': horizon,
                            'repeatCount': count, 'survivalMeanClosure': closure})
    summaries = []
    for horizon in horizons:
        selected = [r for r in records if r['horizon'] == horizon]
        missed = [r['repeatCount']['missedCountFromOneEventCap'] for r in selected]
        closure = [r['survivalMeanClosure']['absoluteProbabilityDifference'] for r in selected]
        multi = [r['repeatCount']['probabilityAtLeastTwoEvents'] for r in selected]
        summaries.append({
            'horizon': horizon, 'unitContextPairs': len(selected),
            'meanMissedCount': float(np.mean(missed)), 'maximumMissedCount': max(missed),
            'meanProbabilityAtLeastTwoEvents': float(np.mean(multi)),
            'maximumProbabilityAtLeastTwoEvents': max(multi),
            'meanAbsoluteMeanClosureProbabilityGap': float(np.mean(closure)),
            'maximumAbsoluteMeanClosureProbabilityGap': max(closure),
            'tailClampCount': sum(r['survivalMeanClosure']['tailClampReached'] for r in selected),
        })

    # Select the largest analytic cap gap at one observed-interval-scale horizon
    # and one explicitly longer stress horizon. This is a diagnostic selection,
    # not a randomly sampled performance estimate or a hypothesis test.
    sampled = []
    for case_index, horizon in enumerate((1., 4.)):
        selected = max((r for r in records if r['horizon'] == horizon),
                       key=lambda r: r['repeatCount']['missedCountFromOneEventCap'])
        neuron = Neuron(drift=selected['drift'], sigma=constants.sigma,
                        threshold=selected['distance'], reset=0.,
                        refractory=constants.refractory, initial=0.)
        counts = np.asarray([
            len(simulate([neuron], horizon, seed=840_000 + case_index * 100_000 + sample,
                         record_trace=False)['spikes'])
            for sample in range(args.samples)
        ])
        sampled.append({
            'profile': selected['profile'], 'unit': selected['unit'], 'horizon': horizon,
            'n': args.samples, 'selection': 'largest analytic one-event cap gap at this horizon',
            'analyticMeanCount': selected['repeatCount']['exactMeanCount'],
            'sampleMeanCount': float(counts.mean()),
            'sampleMeanStandardError': float(counts.std(ddof=1) / math.sqrt(args.samples)),
            'analyticProbabilityAtLeastTwoEvents': selected['repeatCount']['probabilityAtLeastTwoEvents'],
            'sampleProbabilityAtLeastTwoEvents': float((counts >= 2).mean()),
            'maximumObservedCount': int(counts.max()),
        })
    training = np.load(ROOT / 'data/train.npz')
    durations = np.concatenate([training['dt'][i, :n] for i, n in enumerate(training['lengths'])])
    report = {
        'schema': 'rrsnn.trained-local-proxy-exact-gap.v1',
        'checkpoint': str(args.checkpoint), 'checkpointSha256': sha256(args.checkpoint),
        'trainingSeed': saved['seed'], 'trainingEpochBudget': saved['plan']['epochs'],
        'sigma': constants.sigma, 'refractory': constants.refractory,
        'trainingObservedIntervalRange': [float(durations.min()), float(durations.max())],
        'controllerExtraction': 'Actual trained first-update thresholds; drift reconstructed with zero recurrent/retained initial state.',
        'controlsHeldFixed': ['drift', 'threshold', 'resource availability', 'sigma', 'reset', 'refractory'],
        'summaryByHorizon': summaries, 'exactRuntimeSampling': sampled, 'records': records,
        'sourceSha256': {name: sha256(ROOT / name) for name in (
            'models/sequence_models.py', 'train_compare.py', 'runtime/event_runtime.py', 'resource_env.py')},
        'probeSourceSha256': sha256(__file__),
        'completeTrainedNetworkTransferred': False,
        'productionHeptaExecuted': False,
        'limits': [
            'Only two initial observed contexts and one trained seed are probed.',
            'Unit-context summaries are descriptive, not independent statistical replications.',
            'Resource/controller feedback and recurrent coupling are held fixed, not integrated into R1.',
            'Mean-closure test concerns first-hit probabilities before the first reset, separate from repeated counts.',
            'One-interval Bernoulli count and multi-interval first-hit closure are local reductions, not the complete surrogate network.',
            'Horizons above the maximum training interval are explicitly stress probes.',
            'A finite difference or small local gap does not certify task-level transfer or gradient equivalence.',
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'summaryByHorizon': summaries,
                      'exactRuntimeSampling': sampled}, indent=2))


if __name__ == '__main__':
    main()
