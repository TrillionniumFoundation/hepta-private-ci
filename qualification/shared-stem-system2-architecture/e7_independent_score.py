"""Independent original-label scoring of sealed paired REAL model routing.

Scores an archived, cross-sectional 128-case experiment. Candidate routing
never sees labels; this scorer imports neither the routing policy nor a model.
Each simulated conditional second invocation has recorded single-model wall
meter proxy, NOT an actual physically executed on-demand model call.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

from e7_archive import (ARMS, HISTORICAL_SHA, PHYSICAL_SHA, PANEL_SHA, THRESHOLDS,
                        canonical, decode, digest, physical_rows, read_zip, require)

_CASE_FIELDS={'case_id','group_id','joint_input_digest','granite_prob','mmbert_prob',
             'granite_encoder_forward_ns','mmbert_encoder_forward_ns',
             'granite_head_ns','mmbert_head_ns','routing'}
_PROPOSAL_FIELDS={'schema','authority','physical_archive_sha256',
                  'source_labels_read_by_proposer','real_new_model_forwards',
                  'original_recorded_encoder_forwards_per_model','policy_thresholds',
                  'no_posthoc_policy_selection','probabilities_from_archive_not_live_model',
                  'actual_matched_online_routing_measured','future_time_task_success_established',
                  'production_accepted','arms','cases'}


def _expected(arm,g,m):
    """Separate evaluator recomputation, never trust presealed decision claims."""
    if arm=='granite_only':
        return g,False
    if arm=='mmbert_only':
        return m,True
    require(arm in THRESHOLDS, 'unregistered route in reviewer')
    invoke=max(g,1-g)<THRESHOLDS[arm]
    return (m if invoke else g),invoke


def score(proposal, labels, physical):
    require(type(proposal) is dict and set(proposal)==_PROPOSAL_FIELDS,
            'incomplete or augmented proposal schema')
    require(proposal['schema']=='hepta.e7.paired-real-physical-route-seal.v1'
            and proposal['authority']=='DENY_ALL'
            and proposal['physical_archive_sha256']==PHYSICAL_SHA
            and proposal['source_labels_read_by_proposer'] is False
            and proposal['real_new_model_forwards']==0
            and proposal['original_recorded_encoder_forwards_per_model']==352
            and proposal['policy_thresholds']==THRESHOLDS
            and proposal['no_posthoc_policy_selection'] is True
            and proposal['probabilities_from_archive_not_live_model'] is True
            and proposal['actual_matched_online_routing_measured'] is False
            and proposal['future_time_task_success_established'] is False
            and proposal['production_accepted'] is False
            and proposal['arms']==list(ARMS), 'forged inference/authority/research roster')
    require(type(labels) is dict and type(physical) is dict
            and set(physical)=={'granite97','mmbert_small'}
            and type(proposal['cases']) is list and len(proposal['cases'])==128,
            'missing paired 128-case rows')
    cohort={x['case_id']:x for x in proposal['cases'] if type(x) is dict and 'case_id' in x}
    require(len(cohort)==128 and set(cohort)==set(labels)==set(physical['granite97'])==set(physical['mmbert_small']),
            'duplicate/extra/unmatched source identities')
    counts={arm:Counter() for arm in ARMS}
    sums={arm:0 for arm in ARMS}
    briers={arm:0. for arm in ARMS}
    costs={arm:0 for arm in ARMS}
    case_right={arm:{} for arm in ARMS}
    groups=set()
    for cid,row in cohort.items():
        require(set(row)==_CASE_FIELDS,'unknown proposed outcome/label field')
        a=physical['granite97'][cid];b=physical['mmbert_small'][cid]
        gold=labels[cid]
        require(type(gold) is dict and type(gold.get('label')) is int and gold['label'] in (0,1),
                'independent binary ground truth required')
        require((row['group_id'],row['joint_input_digest'])==
                (gold['group_id'],gold['joint_input_digest'])==
                (a['group_id'],a['joint_input_digest'])==
                (b['group_id'],b['joint_input_digest']),
                'original historical source vs physical model / proposed source mismatch')
        require(row['group_id'] not in groups,'duplicate original source group')
        groups.add(row['group_id'])
        g=a['probs']['learned_gate'];m=b['probs']['learned_gate']
        require((row['granite_prob'],row['mmbert_prob'])==(g,m)
                and (row['granite_encoder_forward_ns'],row['mmbert_encoder_forward_ns'])==
                (a['encoder_forward_ns'],b['encoder_forward_ns'])
                and (row['granite_head_ns'],row['mmbert_head_ns'])==
                (a['head_ns']['learned_gate'],b['head_ns']['learned_gate']),
                'candidate changed physical archive prediction or meter')
        require(type(row['routing']) is dict and set(row['routing'])==set(ARMS),
                'incomplete route decisions')
        for arm in ARMS:
            predicted,use_m=_expected(arm,g,m)
            entry=row['routing'][arm]
            require(type(entry) is dict and set(entry)=={'probability','secondary_used'}
                    and type(entry['secondary_used']) is bool
                    and type(entry['probability']) in (float,int)
                    and math.isfinite(entry['probability'])
                    and entry['probability']==predicted
                    and entry['secondary_used'] is use_m,
                    'tampered or posthoc routing rule')
            correct=int((predicted>=.5)==bool(gold['label']))
            counts[arm]['correct']+=correct
            counts[arm]['secondary_calls']+=int(use_m)
            sums[arm]+=1
            briers[arm]+=(predicted-gold['label'])**2
            # It is an INFERRED single-model wall proxy from two independently
            # generated archived model runs, not an observed routed workload.
            cost=(a['encoder_forward_ns']+a['head_ns']['learned_gate'])
            if arm=='mmbert_only':
                cost=b['encoder_forward_ns']+b['head_ns']['learned_gate']
            elif use_m:
                cost+=b['encoder_forward_ns']+b['head_ns']['learned_gate']
            costs[arm]+=cost
            case_right[arm][cid]=correct
    base=case_right['granite_only']
    stats={}
    for arm in ARMS:
        recovered=sum(case_right[arm][c]>base[c] for c in base)
        lost=sum(case_right[arm][c]<base[c] for c in base)
        stats[arm]={'n':sums[arm],'correct':counts[arm]['correct'],
                    'accuracy':counts[arm]['correct']/sums[arm],
                    'brier':briers[arm]/sums[arm],
                    'hypothetical_secondary_model_calls':counts[arm]['secondary_calls'] if arm!='mmbert_only' else 0,
                    'hypothetical_total_model_calls':sums[arm]+(counts[arm]['secondary_calls'] if arm not in ('mmbert_only','granite_only') else 0),
                    'archived_per_case_wall_proxy_ns_sum':costs[arm],
                    'paired_recovered_from_granite':recovered,
                    'paired_lost_from_granite':lost}
    require(stats['granite_only']['correct']==sum(base.values()),'baseline missing')
    return {'schema':'hepta.e7.real-two-stem-routed-retrospective-score.v1',
            'source_archive_sha256':HISTORICAL_SHA,
            'physical_archive_sha256':PHYSICAL_SHA,
            'original_panel_sha256':PANEL_SHA,
            'observed_distinct_original_groups':len(groups),
            'arms':stats,'authority':'DENY_ALL','independent_historical_labels_scored':True,
            'independently_authenticated_label_origin':False,
            'same_family_cross_sectional_not_future':True,
            'actual_on_demand_encoder_calls_executed':0,
            'costs_are_archived_single_model_proxies_not_full_serving':True,
            'actual_future_time_outcomes_scored':False,
            'equal_lifecycle_cost_established':False,
            'model_selection_allowed':False,'online_system2_win_established':False,
            'production_accepted':False}


def actual_labels(historical_path):
    raw=read_zip(historical_path,HISTORICAL_SHA)
    require('stem-agnews-new-source-panel.json' in raw,'original source truth missing')
    # Independent original-signer-naive validator, not imported into proposer.
    original_root=Path(__file__).resolve().parents[1]/'p0-four-stem-replay'
    if not (original_root/'independent_replay.py').is_file():
        raise ValueError('mandatory existing #2065 independent label auditor unavailable')
    sys.path.insert(0,str(original_root))
    from independent_replay import validate_panel  # pylint: disable=import-outside-toplevel
    return validate_panel(decode(raw['stem-agnews-new-source-panel.json']))


def run_real(historical,physical,sealfile,sealhash,output):
    raw=Path(sealfile).read_bytes()
    require(type(sealhash) is str and digest(raw)==sealhash,
            'proposer seal not pinned before outcome reveal')
    # This is the FIRST place in E7 allowed to inspect historical labels.
    truth=actual_labels(historical)
    result=score(decode(raw),truth,physical_rows(read_zip(physical,PHYSICAL_SHA)))
    with Path(output).open('xb') as f:
        f.write(canonical(result))
    return {'score_sha256':digest(Path(output).read_bytes()),
            'granite_correct':result['arms']['granite_only']['correct'],
            'mmbert_correct':result['arms']['mmbert_only']['correct'],
            'production_accepted':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--historical',required=True)
    parser.add_argument('--physical',required=True)
    parser.add_argument('--seal-file',required=True)
    parser.add_argument('--seal-sha256',required=True)
    parser.add_argument('--output',required=True)
    opts=parser.parse_args()
    print(json.dumps(run_real(opts.historical,opts.physical,opts.seal_file,opts.seal_sha256,opts.output),sort_keys=True))


if __name__=='__main__':
    main()
