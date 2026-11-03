"""Frozen-control first-hit composition by integrating the killed density.

No task metric, neural parameter, trained checkpoint, or production state is
changed. This is a scalar distribution-retention check, not a new network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from scipy.integrate import quad

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from rrsnn_experiments.runtime.event_runtime import first_hit_cdf


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def killed_density(y, distance, duration, mu, sigma):
    variance = sigma * sigma * duration
    gaussian = math.exp(-(y - distance - mu * duration) ** 2 / (2 * variance))
    gaussian /= math.sqrt(2 * math.pi * variance)
    return gaussian * (-math.expm1(-2 * distance * y / variance))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controls', type=Path,
                        default=Path(__file__).with_name('proxy_exact_gap.json'))
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).with_name('semigroup_repair_probe.json'))
    args = parser.parse_args()
    source = json.loads(args.controls.read_text())
    sigma = source['sigma']
    records = []
    begun = time.perf_counter()
    for old in source['records']:
        horizon = old['horizon']
        if horizon not in (.5, 1., 2.):
            continue
        distance, mu, half = old['distance'], -old['drift'], horizon / 2
        start = time.perf_counter()
        integral, estimated_error, info = quad(
            lambda y: killed_density(y, distance, half, mu, sigma)
            * first_hit_cdf(y, half, mu, sigma),
            0., np.inf, epsabs=1e-11, epsrel=1e-10, limit=200, full_output=True,
        )
        elapsed = time.perf_counter() - start
        first = first_hit_cdf(distance, half, mu, sigma)
        composed = first + integral
        unsplit = first_hit_cdf(distance, horizon, mu, sigma)
        records.append({
            'profile': old['profile'], 'unit': old['unit'], 'horizon': horizon,
            'distance': distance, 'drift': old['drift'],
            'directFirstHitProbability': unsplit,
            'killedDensityComposedProbability': composed,
            'absoluteCompositionError': abs(composed - unsplit),
            'quadratureEstimatedAbsoluteError': estimated_error,
            'integralUnconditionalSurvivalContribution': integral,
            'quadratureEvaluations': info['neval'],
            'quadratureWallSeconds': elapsed,
            'oldMeanClosureAbsoluteProbabilityError': old['survivalMeanClosure']['absoluteProbabilityDifference'],
        })
    summaries = []
    for horizon in (.5, 1., 2.):
        rows = [r for r in records if r['horizon'] == horizon]
        summaries.append({
            'horizon': horizon, 'controls': len(rows),
            'maximumAbsoluteCompositionError': max(r['absoluteCompositionError'] for r in rows),
            'meanAbsoluteCompositionError': float(np.mean([r['absoluteCompositionError'] for r in rows])),
            'maximumQuadratureEstimatedAbsoluteError': max(r['quadratureEstimatedAbsoluteError'] for r in rows),
            'meanOldMeanClosureAbsoluteProbabilityError': float(np.mean([r['oldMeanClosureAbsoluteProbabilityError'] for r in rows])),
            'totalQuadratureWallSeconds': sum(r['quadratureWallSeconds'] for r in rows),
        })
    maximum_error = max(r['absoluteCompositionError'] for r in records)
    if maximum_error > 1e-8:
        raise AssertionError('Killed-density composition did not meet the scalar tolerance')
    report = {
        'schema': 'rrsnn.killed-density-composition-probe.v1',
        'checkpointSha256': source['checkpointSha256'],
        'controlSourceSha256': sha256(args.controls),
        'probeSourceSha256': sha256(__file__),
        'runtimeSourceSha256': sha256(ROOT / 'runtime/event_runtime.py'),
        'formula': 'F(x,h) + integral_0^infinity K(y,h|x) F(y,h) dy = F(x,2h)',
        'kernelForm': 'normal_density(y; x+mu*h, sigma^2*h) * (-expm1(-2*x*y/(sigma^2*h)))',
        'quadrature': {'implementation': 'scipy.integrate.quad', 'epsabs': 1e-11,
                       'epsrel': 1e-10, 'interval': '[0, infinity)', 'subintervalLimit': 200},
        'checks': len(records), 'maximumAbsoluteCompositionError': maximum_error,
        'absoluteTolerance': 1e-8, 'allWithinTolerance': maximum_error <= 1e-8,
        'summaryByHorizon': summaries, 'records': records,
        'totalWallSeconds': time.perf_counter() - begun,
        'timingScope': 'Scalar adaptive quadrature in a concurrently used scratch executor; not deployment latency.',
        'neuralWeightsChanged': False, 'taskMetricsOpened': False,
        'completeNetworkRepaired': False, 'productionHeptaExecuted': False,
        'interpretation': 'Retaining the complete unnormalised surviving density restores constant-control first-hit partition consistency; this does not repair or retrain the full policy.',
    }
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'checks': len(records),
                      'maximumAbsoluteCompositionError': maximum_error,
                      'totalWallSeconds': report['totalWallSeconds'],
                      'summaryByHorizon': summaries}, indent=2))


if __name__ == '__main__':
    main()
