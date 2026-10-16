"""Finite research-only ambiguity control and post-hoc transfer stress checks.

Not an NDU FBSDE, learned posterior, confidence bound or runtime authority.
No heldout labels or retrospective observations enter an online control rule.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from dataclasses import asdict, dataclass
from fractions import Fraction as F
from pathlib import Path

SCHEMA = 'hepta.ndu-merton-ambiguity.v1'


def q(value):
    if type(value) is bool or not isinstance(value, (int, str, F)):
        raise ValueError('exact rational values required; float and boolean forbidden')
    return F(value)


def law(prior, outcomes, radius):
    probabilities, returns = tuple(q(p) for p in prior), tuple(q(v) for v in outcomes)
    e = q(radius)
    if not 1 <= len(probabilities) <= 16 or len(probabilities) != len(returns):
        raise ValueError('bounded aligned scenario support required')
    if sum(probabilities, F(0)) != 1 or any(p < 0 for p in probabilities):
        raise ValueError('probability simplex violated')
    if not 0 <= e <= 1:
        raise ValueError('total-variation ambiguity radius invalid')
    return probabilities, returns, e


def total_variation(a, b):
    if len(a) != len(b):
        raise ValueError('distribution dimension mismatch')
    return sum((abs(x-y) for x,y in zip(a,b)),F(0))/2


def exact_worst(prior, outcomes, radius):
    """Worst supported expectation in a full-simplex TV ball; no empirical coverage claim.

    Mass can always be relocated from the largest reward to one minimum-reward
    coordinate. This rearrangement is optimal for linear expectation on the
    unrestricted probability simplex under a total-variation constraint.
    """
    probabilities, returns, e = law(prior, outcomes, radius)
    order = sorted(range(len(returns)), key=lambda i: (returns[i], i))
    minimum = order[0]
    weights = list(probabilities)
    moves = []
    remaining = min(e, 1-weights[minimum])
    for donor in reversed(order[1:]):
        if not remaining or returns[donor] == returns[minimum]:
            break
        moved = min(remaining, weights[donor])
        if moved:
            weights[donor] -= moved
            weights[minimum] += moved
            remaining -= moved
            moves.append((donor, minimum, moved))
    weights = tuple(weights)
    if sum(weights,F(0)) != 1 or total_variation(probabilities,weights) > e:
        raise RuntimeError('impossible optimal TV transport')
    return sum((p*v for p,v in zip(weights,returns)),F(0)), weights, tuple(moves)


@dataclass(frozen=True)
class Verdict:
    decision: str
    stop: str
    nominal_continuation: str
    robust_continuation: str
    radius: str
    risk_weight: str
    adversarial_probabilities: tuple[str, ...]
    unsupported_source: bool = True
    source_new_model_calls: int = 0
    production_permission: bool = False


def choose(prior, returns, stop, radius='0', risk_weight='0'):
    """Robust preference-sensitive special-case decision; never online by default."""
    s, alpha = q(stop), q(risk_weight)
    if not 0 <= alpha <= F(1,2):
        raise ValueError('unregistered preference weight')
    probabilities, rewards, radius = law(prior, returns, radius)
    mean = sum((p*v for p,v in zip(probabilities,rewards)),F(0))
    minimum = min(rewards)
    adverse,weights,_ = exact_worst(probabilities,rewards,radius)
    nominal = (1-alpha)*mean + alpha*minimum
    robust = (1-alpha)*adverse + alpha*minimum
    action = 'continue' if robust > s else 'stop'
    return Verdict(action,str(s),str(nominal),str(robust),str(radius),str(alpha),tuple(map(str,weights)))


def gate_prior_before_fitting(horizon, base_floor, prior_charge):
    """Necessary potential-to-pay condition, not a promise of positive ROI.

    Task utility is in [0,H]. A no-op fallback is feasible and guarantees the
    declared nonnegative floor. A prior fit costing >= H-floor cannot possibly
    increase net value relative to that floor for this one-shot horizon.
    """
    h, f, c = q(horizon), q(base_floor), q(prior_charge)
    if h <= 0 or not 0 <= f <= h or c < 0:
        raise ValueError('invalid registered objective or nonnegative cost')
    return {'admit': bool(h-c>f), 'best_possible_net':str(h-c),
            'fallback_floor':str(f),'reason':'upper_bound_only' if h-c>f else 'no_possible_repayment'}


def delayed_gain_counterexample():
    """Two worlds have exactly the same initial information and contrary investments."""
    prior=(F(7,10),F(3,10))
    delayed=(F(19,20),F(9,20))
    baseline=F(3,4)
    nominal=choose(prior,delayed,baseline)
    robust=choose(prior,delayed,baseline,F(3,20))
    if nominal.decision != 'continue' or robust.decision != 'stop':
        raise RuntimeError('constructed ambiguity witness drift')
    return {'observed_history':'identical pre-decision history in both worlds',
            'good_world_continue_net':'19/20','bad_world_continue_net':'9/20',
            'common_stop_net':'3/4','nominal':asdict(nominal),
            'robust':asdict(robust),
            'interpretation':'no history-measurable policy simultaneously chooses both world-optimal actions'}


def descriptive_nested_audit(filename):
    """Examine source-locked historical summaries only AFTER their completed seal."""
    source=Path(filename).read_bytes()
    report=json.loads(source)
    required={'schema','transfer_qualified','new_sources','source_family_independence_verified',
              'mean_absolute_forecast_error','signed_forecast_bias','summaries',
              'original32_holdout_used_for_new_training_or_scoring','unique_outer_evaluation_records'}
    if not required <= set(report) or report['schema'] != 'hepta.nested-transfer.local-observation.v1':
        raise ValueError('unregistered nested source')
    if report['transfer_qualified'] is not False or report['new_sources'] != 0:
        raise ValueError('not a documented no-transfer source')
    if report['source_family_independence_verified'] is not False or report['original32_holdout_used_for_new_training_or_scoring'] is not False:
        raise ValueError('incorrect source family / HOLDOUT status')
    summary=report['summaries']
    if type(summary) is not dict or set(summary) != {'normal','optimized'}:
        raise ValueError('missing completed interpreter modes')
    rows={x['arm']:x for x in summary['normal']}
    optimized={x['arm']:x for x in summary['optimized']}
    for arm in ('fixed8','belief_neutral','belief_ndu'):
        if (arm not in rows or arm not in optimized or rows[arm]['denominator'] != 64
                or optimized[arm]['denominator'] != 64
                or rows[arm]['correct'] != optimized[arm]['correct']):
            raise ValueError('missing or inconsistent original real comparator')
    return {'source_sha256':hashlib.sha256(source).hexdigest(),
            'unique_historical_records':report['unique_outer_evaluation_records'],
            'forecast_mae':report['mean_absolute_forecast_error'],
            'forecast_bias':report['signed_forecast_bias'],
            'fixed8_correct':rows['fixed8']['correct'],
            'neutral_correct':rows['belief_neutral']['correct'],
            'ndu_correct':rows['belief_ndu']['correct'],
            'empirical_source_family_independence':False,
            'radius_calibrated_from_future_groups':False,
            'qualifies_transfer':False}


def report(nested_path):
    case=delayed_gain_counterexample()
    p=(F(7,10),F(3,10));payoff=(F(19,20),F(9,20))
    stress=[]
    for e,alpha in itertools.product((F(0),F(1,20),F(1,10),F(3,20),F(1,5)),(F(0),F(1,4))):
        stress.append({'epsilon':str(e),'alpha':str(alpha),**asdict(choose(p,payoff,F(3,4),e,alpha))})
    return {'schema':SCHEMA,'posture':'RESEARCH_ONLY_DENY_ALL',
            'toy_shift':case,'registered_sensitivity':stress,
            'cold_admission':{str(c):gate_prior_before_fitting(1,0,c)
                              for c in (F(0),F(1,2),F(1),F(3,2))},
            'retrospective_nested':descriptive_nested_audit(nested_path),
            'new_independent_source_groups':0,'neural_training':False,
            'real_task_superiority_established':False,'production_accepted':False}


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--nested',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    value=report(a.nested)
    with a.output.open('x') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({'schema':value['schema'],'nominal':value['toy_shift']['nominal']['decision'],
                      'robust':value['toy_shift']['robust']['decision'],
                      'historical_nested_correct':value['retrospective_nested']['ndu_correct']}))
