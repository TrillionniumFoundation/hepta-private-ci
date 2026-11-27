"""P0.9 post-hoc, immutable shadow decision portfolio on genuine P0.6 mmBERT features.

A deliberately simple, label-blind, fixed *heuristic*, not a learned NDU/FBSDE
solver or a production decision owner. It consumes the original P0.6 sealed
producer predictions and does not invoke any GUI, JIT, network, or side effect.

The actual original publisher gold was historically exposed. The separation
between proposer/reviewer processes only enforces a testable local data boundary.
"""
from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
import math
import os
import stat
from pathlib import Path

from agnews_crossfamily import read_original
import matched_router_p06 as original

SCHEMA = 'hepta.cell-fabric.p09.budgeted-shadow.v1'
POLICY = {
    'schema': SCHEMA,
    'name': 'fixed-posthoc-confidence-portfolio',
    'centroid_fast_floor': 0.65,
    'split_absolute_floor': 0.55,
    'shared_absolute_floor': 0.55,
    'split_advantage_min': 0.08,
    'shared_advantage_min': 0.10,
    'centroid_stop_floor': 0.38,
    'available_arms': ['centroid_train_loo', 'split', 'shared_one', 'stop'],
    'budget_unit': 'hypothetical per-request extra head forward, NOT actual GPU/CPU work',
    'historically_exposed_panel': True,
    'prospective_policy': False,
    'authority': 'DENY_ALL',
}
POLICY_SHA = hashlib.sha256(b'hepta.p09.policy.v1\0'+original.canonical(POLICY)).hexdigest()


def assert_registered_policy() -> None:
    # Keep an in-memory mutation from silently changing the admitted action
    # threshold while still advertising the frozen original policy digest.
    if hashlib.sha256(b'hepta.p09.policy.v1\0'+original.canonical(POLICY)).hexdigest() != POLICY_SHA:
        raise original.Denied('registered policy mutated after source selection')


def require(cond: bool, why: str) -> None:
    if not cond:
        raise original.Denied(why)


def confidence(p: list[float]) -> float:
    require(type(p) is list and len(p) == 4 and
            all(type(v) in (int, float) and math.isfinite(v) and 0. <= v <= 1. for v in p) and
            abs(math.fsum(p)-1) <= 1e-10, 'invalid original posterior')
    return float(max(p))


def decide(arms: dict[str, list[float]]) -> tuple[str, str]:
    assert_registered_policy()
    require(type(arms) is dict and set(arms)==set(original.ALL_ARMS), 'wrong original candidate arms')
    # Validate every arm, including those not used by the fixed portfolio.
    for p in arms.values():confidence(p)
    c=confidence(arms['centroid_train_loo'])
    s=confidence(arms['split'])
    h=confidence(arms['shared_one'])
    if c >= POLICY['centroid_fast_floor']:
        return 'centroid_fast','centroid_train_loo'
    if s >= POLICY['split_absolute_floor'] and s > c + POLICY['split_advantage_min']:
        return 'split_shadow','split'
    if h >= POLICY['shared_absolute_floor'] and h > c + POLICY['shared_advantage_min']:
        return 'shared_shadow','shared_one'
    if c < POLICY['centroid_stop_floor']:
        return 'stop_shadow','stop'
    return 'centroid_uncertain','centroid_train_loo'


def proposed(bundle: dict, prelabel: dict) -> dict:
    assert_registered_policy()
    original.verify_bundle(bundle)
    require(prelabel.get('schema') == original.SCHEMA and
            prelabel.get('bundle_sha256') == original.digest(original.canonical(bundle)) and
            prelabel.get('producer_observed_heldout_labels') is False and
            prelabel.get('same_pretrained_encoder_and_frozen_features') is True and
            prelabel.get('original_encoder_new_forward_calls') == 0 and
            prelabel.get('authority') == 'DENY_ALL' and
            prelabel.get('disposition') == 'HOLD_NO_GO', 'unqualified original producer')
    actual={r['id']:r['cell'] for r in bundle['holdout']}
    require(len(actual)==32, 'original heldout census drift')
    require(type(prelabel.get('trials')) is list and len(prelabel['trials']) == 3,
            'incomplete seeds')
    choices=[]
    for row,seed in zip(prelabel['trials'],original.SEEDS,strict=True):
        require(row.get('seed') == seed and type(row.get('predictions')) is list and
                len(row['predictions'])==32*len(original.ALL_ARMS), 'seed/arm count drift')
        cases={}
        for r in row['predictions']:
            require(type(r) is dict and set(r)=={'id','cell','seed','arm','probabilities'},
                    'wrong original prediction row')
            ident,arm=r['id'],r['arm']
            require(type(ident) is str and ident in actual and r['cell'] == actual[ident] and
                    type(r['seed']) is int and r['seed']==seed and arm in original.ALL_ARMS,
                    'source/route drift')
            v=cases.setdefault(ident,{})
            require(arm not in v, 'duplicate original arm')
            confidence(r['probabilities'])
            v[arm]=r['probabilities']
        require(set(cases)==set(actual), 'missing heldout original identities')
        for ident in sorted(cases):
            action, selected=decide(cases[ident])
            p=None if selected=='stop' else cases[ident][selected]
            choices.append({'id':ident,'seed':seed,'action':action,'chosen_arm':selected,
                            'probabilities':p})
    require(len(choices)==3*32, 'missing shadow choices')
    return {'schema':SCHEMA, 'original_bundle_digest':original.digest(original.canonical(bundle)),
            'original_prelabel_sha256':hashlib.sha256(original.canonical(prelabel)+b'\n').hexdigest(),
            'registered_policy_sha256':POLICY_SHA, 'registered_policy':POLICY,
            'population':{'cases':32,'seeds':list(original.SEEDS),'new_pretrained_forwards':0},
            'choices':choices,
            'claims':{'observations_are_historical':True,'original_gold_previously_exposed':True,
                      'resource_savings_physically_measured':False,
                      'learned_ndu_or_fbsde':False,'signed_issuer_gold':False,
                      'prospective_window':False,'production_authorized':False,
                      'model_promotion_authorized':False,'effect_authorized':False,
                      'authority':'DENY_ALL','disposition':'HOLD_NO_GO'}}


def verify_shadow(bundle: dict,prelabel: dict,shadow: dict) -> None:
    require(original.canonical(shadow)==original.canonical(proposed(bundle,prelabel)),
            'modified shadow action or recorded probabilities')


def record(bundle_file:Path,prelabel_file:Path,original_seal:Path,
           shadow_file:Path,shadow_seal:Path) -> dict:
    # Original producer sealed its predictions before the shadow policy reads them.
    inp=original._check_prelabel(prelabel_file,original_seal)
    bundle=original.json_read(bundle_file)
    shadow=proposed(bundle,inp)
    receipt_sha=original.write_private(shadow_file,shadow)
    seal={'schema':SCHEMA,'original_prelabel_sha256':shadow['original_prelabel_sha256'],
          'original_bundle_digest':shadow['original_bundle_digest'],
          'registered_policy_sha256':POLICY_SHA,'shadow_file_sha256':receipt_sha,
          'historical_original':True,'authority':'DENY_ALL','production_authorized':False}
    original.write_private(shadow_seal,seal)
    return {'shadow_sha256':receipt_sha,'case_seed_pairs':96,'authority':'DENY_ALL'}


def _sealed_shadow(bundle_file:Path,prelabel_file:Path,original_seal:Path,
                   shadow_file:Path,shadow_seal:Path) -> tuple[dict,dict,dict]:
    # Do all local and independently replayable checks BEFORE opening original gold.
    prelabel=original._check_prelabel(prelabel_file,original_seal)
    bundle=original.json_read(bundle_file)
    seal=original.json_read(shadow_seal,25000)
    expected={'schema':SCHEMA,'original_prelabel_sha256':hashlib.sha256(
       original.canonical(prelabel)+b'\n').hexdigest(),
       'original_bundle_digest':original.digest(original.canonical(bundle)),
       'registered_policy_sha256':POLICY_SHA,'historical_original':True,
       'authority':'DENY_ALL','production_authorized':False}
    require(type(seal) is dict and set(seal)==set(expected)|{'shadow_file_sha256'} and
            all(seal[k]==v for k,v in expected.items()),'wrong shadow seal')
    sha=hashlib.sha256()
    fd=os.open(shadow_file,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        require(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and
                st.st_mode & 0o077 == 0,'shadow evidence file not private regular file')
        # Hash exactly the descriptor bytes that will be parsed, never re-open a path.
        raw=f.read(900_001)
    require(len(raw)<=900_000,'oversized shadow record')
    sha.update(raw)
    require(sha.hexdigest()==seal['shadow_file_sha256'],'tampered shadow prelabel seal')
    shadow=original.json.loads(raw,object_pairs_hook=original._strict_pairs,
                              parse_constant=original._reject_constant)
    verify_shadow(bundle,prelabel,shadow)
    return bundle,prelabel,shadow


def score(archive:Path,bundle_file:Path,prelabel_file:Path,original_seal:Path,
          shadow_file:Path,shadow_seal:Path) -> dict:
    bundle,prelabel,shadow=_sealed_shadow(bundle_file,prelabel_file,original_seal,shadow_file,shadow_seal)
    # P0.6 fully authenticates archived feature rows, numerically replays all
    # 512-step training arms and independently checks the FP64 oracle *before*
    # any historical publisher outcome is reopened for this shadow scorer.
    already=original.independent_review(archive,bundle_file,prelabel_file,original_seal)
    require(already['independent_fp64_oracle']['independent_trained_head_prediction_rows_replayed']==672 and
            already['independent_reviewer_reconstructed_source_features'] is True and
            already['production_authorized'] is False,'original physical replay incomplete')
    corpus=read_original(archive)
    rows=[original.json.loads(line,object_pairs_hook=original._strict_pairs,
            parse_constant=original._reject_constant) for line in corpus['dataset.jsonl'].splitlines()]
    gold={r['case_id']:r['label'] for r in rows if r['split']=='holdout'}
    require(len(gold)==32 and set(gold)==set(r['id'] for r in bundle['holdout']),
            'unqualified historical source labels')
    baseline={}
    for trial in prelabel['trials']:
        b={r['id']:r['probabilities'] for r in trial['predictions']
           if r['arm']=='centroid_train_loo'}
        require(len(b)==32,'baseline missing')
        baseline[trial['seed']]=b
    data={s:[] for s in original.SEEDS}
    for r in shadow['choices']:
        ident,seed,arm=r['id'],r['seed'],r['chosen_arm']
        expected=gold[ident]
        guessed=None if arm=='stop' else max(range(4),key=lambda i:r['probabilities'][i])
        ref=max(range(4),key=lambda i:baseline[seed][ident][i])
        data[seed].append({'action':r['action'],'correct':int(guessed==expected) if guessed is not None else 0,
                          'covered':int(guessed is not None),'reference_correct':int(ref==expected),
                          'shadow_only':int(guessed==expected and ref!=expected) if guessed is not None else 0,
                          'baseline_only':int(ref==expected and guessed!=expected)})
    answer={}
    for seed,rows in data.items():
        require(len(rows)==32,'missing source-root population')
        choices=Counter(r['action'] for r in rows)
        covered=sum(r['covered'] for r in rows)
        wins=sum(r['shadow_only'] for r in rows);losses=sum(r['baseline_only'] for r in rows)
        answer[str(seed)]={'cases':32,'answered':covered,'abstained':32-covered,
           'correct_when_abstentions_count_as_incorrect':sum(r['correct'] for r in rows),
           'centroid_reference_correct':sum(r['reference_correct'] for r in rows),
           'shadow_extra_head_requests':choices['split_shadow']+choices['shared_shadow'],
           'shadow_action_counts':dict(sorted(choices.items())),
           'paired_against_centroid':{'shadow_only_correct':wins,'centroid_only_correct':losses,
              'nominal_two_sided_p_descriptive':original.exact_mcnemar(wins,losses)}}
    return {'schema':SCHEMA+'.review.v1','original_source_sha256':original.ARCHIVE_SHA256,
            'original_prelabel_sha256':shadow['original_prelabel_sha256'],
            'shadow_prelabel_sha256':original.json_read(shadow_seal,25000)['shadow_file_sha256'],
            'policy_sha256':POLICY_SHA,'retrospective_seen_source_root_count':32,
            'seed_results_not_independent_populations':True,
            'new_model_forwards':0,'real_original_features':True,'real_original_head_sgd_replayed':True,
            'incremental_execution_latency_or_energy_measured':False,
            'estimated_counterfactual_savings_not_physical':True,
            'original_publisher_gold_previously_exposed':True,
            'prospective_2026_outcome':False,'new_publisher_used':False,
            'numerical_utility_not_ndu_fbsde':True,'results':answer,
            'disposition':'HOLD_NO_GO','model_promotion_authorized':False,
            'cell_split_activation_authorized':False,'native_effect_authorized':False,
            'production_authorized':False,'authority':'DENY_ALL'}


def main() -> None:
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest='operation',required=True)
    a=sub.add_parser('propose')
    a.add_argument('--source',type=Path,required=True)
    a.add_argument('--prelabel',type=Path,required=True)
    a.add_argument('--seal',type=Path,required=True)
    a.add_argument('--shadow',type=Path,required=True)
    a.add_argument('--shadow-seal',type=Path,required=True)
    b=sub.add_parser('review')
    b.add_argument('--archive',type=Path,required=True)
    b.add_argument('--source',type=Path,required=True)
    b.add_argument('--prelabel',type=Path,required=True)
    b.add_argument('--seal',type=Path,required=True)
    b.add_argument('--shadow',type=Path,required=True)
    b.add_argument('--shadow-seal',type=Path,required=True)
    b.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    if args.operation=='propose':
        print(original.json.dumps(record(args.source,args.prelabel,args.seal,
                args.shadow,args.shadow_seal),sort_keys=True))
    else:
        result=score(args.archive,args.source,args.prelabel,args.seal,args.shadow,args.shadow_seal)
        outsha=original.write_private(args.out,result)
        print(original.json.dumps({'report_sha256':outsha,'disposition':'HOLD_NO_GO',
                                   'real_publisher_historical_only':True},sort_keys=True))

if __name__=='__main__':main()
