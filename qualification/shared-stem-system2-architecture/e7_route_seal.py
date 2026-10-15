"""Read only REAL prelabel physical predictions, seal FIXED conditional routing.

Critically no independent historical label ZIP argument, input, or import exists
in this process. Routing is retroactive to an archived physical cohort and NOT
new Encoder inference, production selection or a prospective model trial.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from e7_archive import (ARMS, PHYSICAL_SHA, THRESHOLDS, canonical, digest,
                        physical_rows, read_zip, require)


def routing_prob(arm,pgranite,pmmbert):
    require(arm in ARMS,'undeclared route arm')
    for p in (pgranite,pmmbert):
        require(type(p) in (float,int) and 0<=p<=1,'invalid scored probability')
    if arm=='granite_only':
        return pgranite,False
    if arm=='mmbert_only':
        return pmmbert,True
    invoked=max(pgranite,1-pgranite)<THRESHOLDS[arm]
    return (pmmbert if invoked else pgranite),invoked


def seal(rows):
    """No ground-truth information ever consumed by this function."""
    require(type(rows) is dict and set(rows)=={'granite97','mmbert_small'},
            'complete model roster required')
    gr,mm=rows['granite97'],rows['mmbert_small']
    require(type(gr) is dict and type(mm) is dict and len(gr)==128 and set(gr)==set(mm),
            'complete paired original 128-case cohort required')
    outcomes=[]
    for cid in sorted(gr):
        a,b=gr[cid],mm[cid]
        require(type(a) is dict and type(b) is dict and set(a)==set(b)
                and a['case_id']==cid==b['case_id']
                and a['group_id']==b['group_id']
                and a['joint_input_digest']==b['joint_input_digest'],
                'tampered case/schema/model source')
        p=a['probs']['learned_gate'];q=b['probs']['learned_gate']
        arm_policy={}
        for name in ARMS:
            selected,invoked=routing_prob(name,p,q)
            arm_policy[name]={'probability':selected,'secondary_used':invoked}
        outcomes.append({'case_id':cid,'group_id':a['group_id'],
                         'joint_input_digest':a['joint_input_digest'],
                         'granite_prob':p,'mmbert_prob':q,
                         'granite_encoder_forward_ns':a['encoder_forward_ns'],
                         'mmbert_encoder_forward_ns':b['encoder_forward_ns'],
                         'granite_head_ns':a['head_ns']['learned_gate'],
                         'mmbert_head_ns':b['head_ns']['learned_gate'],
                         'routing':arm_policy})
    require(len({x['group_id'] for x in outcomes})==128,
            'source group reuse cannot be mistaken for independent cases')
    return {'schema':'hepta.e7.paired-real-physical-route-seal.v1',
            'authority':'DENY_ALL',
            'physical_archive_sha256':PHYSICAL_SHA,
            'source_labels_read_by_proposer':False,
            'real_new_model_forwards':0,
            'original_recorded_encoder_forwards_per_model':352,
            'policy_thresholds':THRESHOLDS,
            'no_posthoc_policy_selection':True,
            'probabilities_from_archive_not_live_model':True,
            'actual_matched_online_routing_measured':False,
            'future_time_task_success_established':False,
            'production_accepted':False,'arms':list(ARMS),'cases':outcomes}


def run_real(physical,output):
    data=read_zip(physical,PHYSICAL_SHA)
    result=seal(physical_rows(data))
    # Exclusive write before any independent outcome file is available.
    target=Path(output)
    with target.open('xb') as f:
        f.write(canonical(result))
    return {'schema':result['schema'],'seal_sha256':digest(target.read_bytes()),
            'sealed_cases':len(result['cases']),
            'historical_ground_truth_accessed':False,'production_accepted':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--physical',required=True)
    p.add_argument('--output',required=True)
    opts=p.parse_args()
    print(json.dumps(run_real(opts.physical,opts.output),sort_keys=True))


if __name__=='__main__':
    main()
