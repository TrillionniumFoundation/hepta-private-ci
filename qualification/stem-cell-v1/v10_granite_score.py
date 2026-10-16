"""Independent postseal source-group review of actual frozen-Granite Reader outputs.

A strong restricted symbolic solver is an honest null, not a neural teacher.
The V9 synthetic task is not original-human MultiRC or a future-time cohort.
"""
from collections import Counter, defaultdict
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path
import time

from v9_typed_graph import digest, solve, verify_proof
from v9_independent_review import reference_semantics
from v10_granite_features import load, save_new, validate_public, MODEL, REVISION
# Independently registered. Never import the TRAINER into the heldout reviewer.
ARMS = ('base', 'bridge', 'endpoint')
SEEDS = (41, 47, 53)


def sha_file(path):
    with Path(path).open('rb') as stream:
        return sha256(stream.read()).hexdigest()
from v10_training_audit import verify_trace


def review(public_path, source_seal_path, held_truth_path, blind_path,
           model_root, feature_receipt_path, output):
    start_cpu,start_wall=time.process_time_ns(),time.perf_counter_ns()
    public=validate_public(load(public_path))
    seal=load(source_seal_path)
    held=load(held_truth_path)
    blind=load(blind_path)
    ids={c['case_id'] for c in public if not c['case_id'].startswith('train/')}
    expected={f'{seed}/{arm}' for seed in SEEDS for arm in ARMS}
    if (seal.get('schema')!='hepta.v10.real-granite-source.v1'
            or seal.get('public_sha256')!=digest(public)
            or seal.get('held_label_sha256')!=digest(held)
            or seal.get('model_id')!=MODEL or seal.get('revision')!=REVISION
            or len(held)!=960 or set(held)!=ids
            or any(type(t) is not int or t not in (0,1) for t in held.values())
            or blind.get('schema')!='hepta.v10.real-granite-blind.v1'
            or blind.get('public_sha256')!=digest(public)
            or blind.get('probabilities_sha256')!=digest(blind.get('probabilities'))
            or blind.get('arms')!=list(ARMS)
            or blind.get('seeds')!=list(SEEDS)
            or set(blind.get('probabilities',{}))!=expected
            or set(blind.get('training_commitments',{}))!=expected
            or blind.get('commitment_sha256')!=digest(blind.get('training_commitments'))
            or blind.get('held_labels_used') is not False
            or blind.get('model_selected') is not False
            or blind.get('authority')!='DENY_ALL'
            or blind.get('production_accepted') is not False):
        raise ValueError('source-frozen hidden truth and matching blind seal required')
    feature=load(feature_receipt_path)
    if (feature.get('schema')!='hepta.v10.real-granite-encoding.v1'
            or feature.get('public_sha256')!=digest(public)
            or feature.get('model_id')!=MODEL or feature.get('model_revision')!=REVISION
            or feature.get('real_pretrained_forward_executed') is not True
            or feature.get('frozen_weight_verified') is not True
            or feature.get('held_labels_accessed') is not False
            or blind.get('feature_receipt_sha256')!=sha_file(feature_receipt_path)):
        raise ValueError('physically recorded real Granite Encoder evidence missing')
    # Independent reviewer re-opens EVERY actual selected source artifact. A
    # textual claim of nine trained models is not sufficient for admission.
    training_trace_audits={}
    for name, recorded in blind['training_commitments'].items():
        seed, arm=name.split('/')
        folder=Path(model_root)/f'{seed}-{arm}'
        actual=load(folder/'training.json')
        if (recorded != dict(seed=int(seed), arm=arm,
                weights_sha256=actual.get('weights_sha256'),
                training_receipt_sha256=sha_file(folder/'training.json'),
                schedule_sha256=actual.get('schedule_sha256'),
                source_public_sha256=actual.get('input_public_sha256'),
                feature_receipt_sha256=actual.get('feature_receipt_sha256'),
                actual_updates=actual.get('actual_updates'),
                experiment_origin=actual.get('experiment_origin'))
                or sha_file(folder/'reader.safetensors')!=recorded['weights_sha256']
                or sha_file(folder/'schedule.json')!=recorded['schedule_sha256']
                or actual.get('actual_updates')!=256
                or actual.get('model_selected') is not False
                or actual.get('production_accepted') is not False
                or actual.get('experiment_origin')!='real_verified_granite'
                or actual.get('frozen_pretrained_features_verified') is not True
                or actual.get('feature_receipt_sha256')!=sha_file(feature_receipt_path)
                or actual.get('held_labels_seen') is not False):
            raise ValueError('original complete Reader weights, physical work or frozen source mismatched')
        training_trace_audits[name]=verify_trace(public, seal, actual,
            load(folder/'schedule.json'), seed=int(seed), arm=arm)
    groups=defaultdict(list)
    for row in public:
        ident=row['case_id'].split('/')
        if len(ident)!=5 or ident[0] not in ('train','held_known','held_novel'):
            raise ValueError('registered world/group/source identity required')
        if row['case_id'] in ids:
            groups[(ident[0],int(ident[1]),row['source_group'])].append(row)
            if reference_semantics(row)!=held[row['case_id']]:
                raise ValueError('independently reconstructed truth conflicts with source owner')
    if len(groups)!=240 or any(len(rows)!=4 for rows in groups.values()):
        raise ValueError('source-disjoint 240 group held evaluation required')
    for rows in groups.values():
        a,b,c,d=rows
        if (a['facts']!=b['facts'] or c['facts']!=d['facts']
                or Counter(' '.join(a['facts']).split()) != Counter(' '.join(c['facts']).split())
                or [held[r['case_id']] for r in rows]!=[1,0,0,1]):
            raise ValueError('counterfactual source or label structure changed')
    observations=[]
    for model in sorted(expected):
        probs=blind['probabilities'][model]
        if (type(probs) is not dict or set(probs)!={c['case_id'] for c in public}
                or any(type(x) not in (float,int) or not math.isfinite(x) or not 0<=x<=1
                       for x in probs.values())):
            raise ValueError('complete finite original sealed numeric outputs required')
        seed,arm=model.split('/')
        counts=defaultdict(lambda:dict(cases=0,correct=0,paired=0,both=0,groups=0,
                                       exact_groups=0,brier_sum=0.,log_loss_sum=0.))
        for (role,depth,group),cases in groups.items():
            item=counts[(role,depth)]
            decisions=[int(probs[c['case_id']]>0.5) for c in cases]
            gold=[held[c['case_id']] for c in cases]
            right=sum(p==g for p,g in zip(decisions,gold))
            both=sum(decisions[i]==gold[i] and decisions[i+2]==gold[i+2] for i in (0,1))
            item['cases']+=4
            item['correct']+=right
            item['paired']+=2
            item['both']+=both
            item['groups']+=1
            item['exact_groups']+=right==4
            item['brier_sum']+=sum((probs[c['case_id']]-g)**2 for c,g in zip(cases,gold))
            item['log_loss_sum']+=sum(-math.log(max(1e-12,probs[c['case_id']] if g else 1-probs[c['case_id']]))
                                      for c,g in zip(cases,gold))
        for (role,depth),item in sorted(counts.items()):
            observations.append(dict(seed=int(seed),arm=arm,role=role,depth=depth,
                                     cases=item['cases'],correct=item['correct'],
                                     paired_candidates=item['paired'],both_correct=item['both'],
                                     groups=item['groups'],exact_group_count=item['exact_groups'],
                                     candidate_accuracy=item['correct']/item['cases'],
                                     paired_accuracy=item['both']/item['paired'],
                                     brier=item['brier_sum']/item['cases'],
                                     cross_entropy=item['log_loss_sum']/item['cases'],
                                     source_groups_repeated_across_seeds=True))
    # Actual independent cheap full-graph calls over same held cohorts, without
    # pretending that a deterministic restricted parser is a general LLM.
    null_groups=defaultdict(lambda:dict(cases=0,correct=0,pairs=0,both=0,proofs=0))
    null_start_cpu=time.process_time_ns()
    for (role,depth,_),cases in groups.items():
        item=null_groups[(role,depth)]
        decisions=[]
        for c in cases:
            proof=solve(c['facts'],c['question'],c['candidate']).receipt()
            if not verify_proof(c['facts'],c['question'],c['candidate'],proof):
                raise ValueError('proof verifier disagrees with admitted graph')
            decisions.append(int(proof['claim']))
            item['proofs']+=1
        target=[held[c['case_id']] for c in cases]
        item['cases']+=4
        item['correct']+=sum(p==g for p,g in zip(decisions,target))
        item['pairs']+=2
        item['both']+=sum(decisions[k]==target[k] and decisions[k+2]==target[k+2] for k in (0,1))
    null_cpu_ns=time.process_time_ns()-null_start_cpu
    symbolic=[dict(role=role,depth=depth,**values) for (role,depth),values in sorted(null_groups.items())]
    admitted={arm:all(row['candidate_accuracy']>=.75 and row['paired_accuracy']>=.50
                       for row in observations if row['arm']==arm) for arm in ARMS}
    # Scientific full-release admission requires entirely separate previous V7
    # natural+retention and non-synthetic human/future task evidence: ALWAYS FALSE.
    result=dict(schema='hepta.v10.real-granite-postseal.v1',
        source_sha256=seal['public_sha256'],held_truth_sha256=seal['held_label_sha256'],
        blind_probability_sha256=blind['probabilities_sha256'],
        held_independent_groups=240, held_distinct_candidates=960,
        repeated_seed_cases_not_independent=True, neural_observations=observations,
        independent_training_trace_audits=training_trace_audits,
        symbolic_observations=symbolic,cheap_symbolic_cpu_ns=null_cpu_ns,
        exploratory_held_gate_three_seed=admitted,
        real_granite_model_calls_credited_only_to_encoder_receipt=True,
        natural_real_human_questions_scored=False,
        future_time_cohort=False,V7_joint_admission_passed=False,
        FBSDE_or_NDU_incremental_gain_established=False,
        production_accepted=False,model_selected=False,authority='DENY_ALL',
        reviewer_cpu_ns=time.process_time_ns()-start_cpu,
        reviewer_wall_ns=time.perf_counter_ns()-start_wall)
    save_new(output,result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('public','source-seal','held-labels','predictions','models','feature-receipt','output'):
        p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args()
    result=review(a.public,a.source_seal,a.held_labels,a.predictions,
                  a.models,a.feature_receipt,a.output)
    print(json.dumps(dict(groups=result['held_independent_groups'],
        candidate_rows=len(result['neural_observations']),
        symbolic=result['symbolic_observations'],authority=result['authority'])))

if __name__=='__main__':main()
