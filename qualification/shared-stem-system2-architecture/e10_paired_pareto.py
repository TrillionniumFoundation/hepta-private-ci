"""Exact retrospective paired-route dominance review; research-only / DENY_ALL.

No independent future rows, confidence interval on deployment policy value,
physical routed-serving cost, original signer or stochastic FBSDE assertion.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
from math import comb
from pathlib import Path

ARMS=('granite_only','mmbert_only','gate_conf_075','gate_conf_090','gate_conf_098')


def require(ok,why):
    if not ok:
        raise ValueError(why)


def exact_mcnemar(wins,losses):
    """Exact two-sided paired binomial under discordant null, no asymptotics."""
    require(type(wins) is int and type(losses) is int and
            0 <= wins <= 128 and 0 <= losses <= 128 and wins+losses <= 128,
            'impossible paired discordance')
    n=wins+losses
    if n == 0:return Fraction(1)
    smaller=min(wins,losses)
    return min(Fraction(1), Fraction(2*sum(comb(n,k) for k in range(smaller+1)),2**n))


def holm(pairs):
    """Exact familywise step-down adjustment, including monotone correction."""
    require(type(pairs) is dict and set(pairs)==set(ARMS)-{'granite_only'},
            'registered four hypotheses required')
    require(all(type(p) is Fraction and 0<=p<=1 for p in pairs.values()),
            'invalid exact p')
    sorted_items=sorted(pairs.items(),key=lambda item:(item[1],item[0]))
    adjusted={}
    previous=Fraction(0)
    for rank,(arm,p) in enumerate(sorted_items):
        previous=max(previous,min(Fraction(1),(len(pairs)-rank)*p))
        adjusted[arm]=previous
    return adjusted


def review(first,second):
    require(type(first) is dict and first.get('schema')=='hepta.e7.real-two-stem-routed-retrospective-score.v1'
            and first.get('authority')=='DENY_ALL' and first.get('production_accepted') is False
            and first.get('actual_on_demand_encoder_calls_executed')==0
            and first.get('same_family_cross_sectional_not_future') is True
            and first.get('model_selection_allowed') is False,
            'primary source/claim inadmissible')
    require(type(second) is dict and second.get('schema')=='hepta.e7.independent-dual-algorithm-real-retrospective.v1'
            and second.get('authority')=='DENY_ALL' and second.get('production_accepted') is False
            and second.get('actual_online_second_model_invocations_executed')==0
            and second.get('original_source_signer_independently_authenticated') is False
            and second.get('model_winner_selected') is False,
            'second independent source/claim inadmissible')
    arms=first.get('arms'); other=second.get('arms')
    require(type(arms) is dict and type(other) is dict and set(arms)==set(ARMS)
            and set(other)==set(ARMS),'incomplete policy set')
    base=arms['granite_only']
    require(type(base.get('correct')) is int and base['correct']==122
            and type(base.get('n')) is int and base['n']==128
            and type(base.get('archived_per_case_wall_proxy_ns_sum')) is int
            and base['archived_per_case_wall_proxy_ns_sum']>0,
            'Granite historical baseline changed')
    results={};pvals={}
    for arm in ARMS:
        item=arms[arm]; independent=other[arm]
        for field in ('correct','n','hypothetical_secondary_model_calls',
                      'archived_per_case_wall_proxy_ns_sum',
                      'paired_lost_from_granite','paired_recovered_from_granite'):
            require(type(item.get(field)) is int and item[field] == independent.get(field),
                    'independent reviewer count mismatch')
        for field in ('brier','accuracy'):
            require(type(item.get(field)) is float and 0<=item[field]<=1
                    and abs(item[field]-independent.get(field,float('inf')))<1e-14,
                    'independent reviewer metric mismatch')
        wins=item['paired_recovered_from_granite'];losses=item['paired_lost_from_granite']
        require(0<=wins<=128 and 0<=losses<=128 and wins+losses<=128
                and item['n']==128 and item['correct']==base['correct']+wins-losses
                and item['accuracy']==item['correct']/128,
                'impossible paired count arithmetic')
        require(item['archived_per_case_wall_proxy_ns_sum']>0
                and item['hypothetical_secondary_model_calls']>=0,
                'missing paid inference proxy')
        if arm=='granite_only':
            require(wins==losses==0 and item['hypothetical_secondary_model_calls']==0,
                    'baseline must be exact control')
            continue
        value_p=exact_mcnemar(wins,losses)
        pvals[arm]=value_p
        results[arm]={
            'delta_correct':item['correct']-base['correct'],
            'paired_recovered':wins,'paired_lost':losses,
            'extra_archived_time_proxy_ns':item['archived_per_case_wall_proxy_ns_sum']-base['archived_per_case_wall_proxy_ns_sum'],
            'delta_Brier':item['brier']-base['brier'],
            'strictly_dominated_by_granite_in_three_registered_metrics':
                (item['correct']<base['correct'] and
                 item['brier']>base['brier'] and
                 item['archived_per_case_wall_proxy_ns_sum']>base['archived_per_case_wall_proxy_ns_sum']),
            'exact_unadjusted_mcnemar_two_sided':str(value_p),
        }
    adjusted=holm(pvals)
    for arm,p in adjusted.items():results[arm]['holm_four_hypotheses_adjusted_p']=str(p)
    require(second.get('paired_correctness',{}).get('at_least_one_right')==126
            and second['paired_correctness'].get('oracle_extra_correct_over_granite')==4
            and second['paired_correctness'].get('oracle_uses_future_labels_is_not_an_admissible_policy') is True,
            'incorrect same-panel unattainable ceiling')
    return {
        'schema':'hepta.e10.retrospective-three-metric-Pareto-and-exact-paired-review.v1',
        'authority':'DENY_ALL','n':128,
        'all_four_policies_strictly_dominated_in_registered_historical_metrics':all(
            r['strictly_dominated_by_granite_in_three_registered_metrics'] for r in results.values()),
        'original_label_oracle_upper_correct':126,
        'oracle_not_deployable':True,
        'paired_exact_tests_are_exploratory_within_one_AGNews_family':True,
        'archived_meter_proxy_is_not_live_routed_latency':True,
        'real_new_encoder_forwards':0,
        'source_family_future_time_generalization':False,
        'decision':'NO_GO_FOR_PROMOTION',
        'production_accepted':False,'models':results,
    }


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--original',required=True);ap.add_argument('--independent',required=True)
    ap.add_argument('--output',required=True);v=ap.parse_args()
    original=json.loads(Path(v.original).read_text());second=json.loads(Path(v.independent).read_text())
    output=review(original,second)
    with Path(v.output).open('x',encoding='utf-8') as f:
        json.dump(output,f,sort_keys=True,separators=(',',':'),allow_nan=False)
    print(json.dumps(output,sort_keys=True))

if __name__=='__main__':main()
