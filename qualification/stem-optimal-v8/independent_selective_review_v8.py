"""Independent no-model scorer for a *historical* selective-compute policy.

Does not import the route producer and refuses to claim measured savings from
previously paid full-Encoder predictions. Publisher gold is opened only after
prelabel route and original material are sealed; earlier studies exposed gold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'stem-optimal-v5'))
sys.path.insert(0,str(ROOT/'stem-optimal-v3'))
import paired_review_v5 as v5
import stem_hard_charge_review_v3 as v3

SCHEMA='hepta.stem.selective-counterfactual.v8'
REVIEW_SCHEMA='hepta.stem.selective-counterfactual-review.v8'
MODELS=('granite47','granite97','mmbert140')
CHEAP='char_345_tfidf_centroid'
BUDGET=8
FIELDS={'schema','source_plan_sha256','cohort','policy','predeclared_selected_count',
        'selected_case_ids','source_original_v3_sha','source_original_v4_sha',
        'nonselective_cheap_arm','hypothetical_escalation_arm','candidates',
        'rows','evidence','source_independent_families','future_windows',
        'prior_heldout_labels_previously_exposed','stem_winner_verified',
        'ndu_benefit_verified','production_authorized','cell_split_authorized',
        'disposition','authority'}
EVIDENCE_FIELDS={'actual_new_encoder_sequence_forwards',
                 'historical_original_encoder_forwards_reused',
                 'hypothetical_heldout_encoder_requests_per_candidate',
                 'measured_heldout_encoder_savings',
                 'training_and_load_cost_eliminated','matched_device_cpu_rss_p99_energy',
                 'real_4096_cell_execution'}


def require(ok,why):
    if not ok:
        raise ValueError(why)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(doc):
    return json.dumps(doc,sort_keys=True,allow_nan=False,ensure_ascii=False,
                      separators=(',',':')).encode('utf-8')


def probability(p):
    require(type(p) is list and len(p)==4 and
            all(type(x) in (int,float) and 0<=x<=1 and math.isfinite(x) for x in p) and
            abs(sum(p)-1)<1e-5,'untrusted original probability array')
    return p


def reference_route(source,cheap):
    """Independently order all 32 label-free original char probabilities."""
    cases=source['heldout']
    expected={row['case_id']:row['source_sha256'] for row in cases}
    require(len(expected)==32 and len(cheap['rows'])==32,
            'original cheap reference universe missing')
    ranking=[]
    cheap_prob={}
    for row in cheap['rows']:
        cid=row['case_id']
        require(cid in expected and cid not in cheap_prob and
                row['source_sha256']==expected[cid] and
                set(row)=={'case_id','source_sha256','scores'} and
                set(row['scores'])=={'word_12_tfidf_centroid',CHEAP},
                'cheap baseline identity or field substitution')
        p=probability(row['scores'][CHEAP]);cheap_prob[cid]=p
        values=sorted(p,reverse=True)
        ranking.append((values[0]-values[1],cid))
    require(set(cheap_prob)==set(expected),'missing original cheap case')
    ranking.sort(key=lambda x:(x[0],x[1]))
    return [case_id for _,case_id in ranking[:BUDGET]],cheap_prob


def audit_prelabel(source,runs,cheap,route):
    require(type(route) is dict and set(route)==FIELDS and
            route['schema']==SCHEMA and
            route['source_plan_sha256']==v5.SOURCE_PLAN_SHA and
            route['source_original_v3_sha']==v5.V3_SOURCE_SHA and
            route['source_original_v4_sha']==v5.V4_SOURCE_SHA and
            route['cohort']=='hard-charge-four-intents-v3' and
            route['policy']=='rank_lowest_top2_margin_then_case_id' and
            type(route['predeclared_selected_count']) is int and
            route['predeclared_selected_count']==BUDGET and
            route['nonselective_cheap_arm']==CHEAP and
            route['hypothetical_escalation_arm']=='learned' and
            route['candidates']==list(MODELS),
            'wrong prelabel routing identity or policy')
    require(route['source_independent_families']==1 and
            route['future_windows']==0 and
            route['prior_heldout_labels_previously_exposed'] is True and
            route['production_authorized'] is False and
            route['cell_split_authorized'] is False and
            route['stem_winner_verified'] is False and
            route['ndu_benefit_verified'] is False and
            route['authority']=='DENY_ALL' and
            route['disposition']=='HOLD_NO_GO',
            'forged outcome or producer authority')
    observed=route['evidence']
    require(type(observed) is dict and set(observed)==EVIDENCE_FIELDS and
            type(observed['actual_new_encoder_sequence_forwards']) is int and
            observed['actual_new_encoder_sequence_forwards']==0 and
            type(observed['hypothetical_heldout_encoder_requests_per_candidate']) is int and
            observed['hypothetical_heldout_encoder_requests_per_candidate']==BUDGET and
            observed['historical_original_encoder_forwards_reused'] is True and
            all(observed[key] is False for key in EVIDENCE_FIELDS if key not in
                {'actual_new_encoder_sequence_forwards',
                 'hypothetical_heldout_encoder_requests_per_candidate',
                 'historical_original_encoder_forwards_reused'}),
            'hypothetical compute incorrectly claimed as physical cost saving')
    v5.original_nogold(source,runs)
    selected, cheap_probs=reference_route(source,cheap)
    require(route['selected_case_ids']==selected and len(set(selected))==BUDGET,
            'prelabel route not independently reproducible')
    expected={row['case_id']:row['source_sha256'] for row in source['heldout']}
    require(type(route['rows']) is list and len(route['rows'])==32,
            'case universe changed after routing')
    original={name:{row['case_id']:probability(row['scores']['learned'])
                    for row in runs[name]['rows']} for name in MODELS}
    rows={}
    for row in route['rows']:
        require(type(row) is dict and set(row)=={'case_id','source_sha256',
                'selected_for_hypothetical_escalation','scores'} and
                row['case_id'] in expected and row['case_id'] not in rows and
                row['source_sha256']==expected[row['case_id']] and
                type(row['selected_for_hypothetical_escalation']) is bool and
                row['selected_for_hypothetical_escalation']==(row['case_id'] in selected) and
                type(row['scores']) is dict and set(row['scores'])==set(MODELS),
                'leaked label, swapped original case or wrong routed mask')
        for name in MODELS:
            ref=original[name][row['case_id']] if row['case_id'] in selected else cheap_probs[row['case_id']]
            require(probability(row['scores'][name])==ref,
                    'original model or cheap prediction illegally replaced')
        rows[row['case_id']]=row
    require(set(rows)==set(expected),'missing original routed predictions')
    return selected,cheap_probs,original,rows


def _paired(scores_a,scores_b,gold):
    ids=set(gold)
    require(set(scores_a)==set(scores_b)==ids and len(ids)==32,
            'original late-label paired case mismatched')
    a=b=only_a=only_b=0
    brier_a=brier_b=0.0
    for cid,y in gold.items():
        pa,pb=probability(scores_a[cid]),probability(scores_b[cid])
        aa=max(range(4),key=lambda k:pa[k])==y
        bb=max(range(4),key=lambda k:pb[k])==y
        a+=aa;b+=bb
        only_a+=aa and not bb
        only_b+=bb and not aa
        brier_a+=sum((p-float(i==y))**2 for i,p in enumerate(pa))/32
        brier_b+=sum((p-float(i==y))**2 for i,p in enumerate(pb))/32
    return {'candidate_correct':a,'comparator_correct':b,
            'candidate_only':only_a,'comparator_only':only_b,
            'candidate_brier':brier_a,'comparator_brier':brier_b,
            'delta_brier_candidate_minus_comparator':brier_a-brier_b,
            'exploratory_exact_mcnemar_p':v5.mcnemar(only_a,only_b)}


def review_original(train_raw,test_raw,source_v3,source_v4,runs,cheap,route,materials):
    require(source_v3==source_v4,'V3/V4 original case source bytes differ')
    selected,cheap_probs,original,rows=audit_prelabel(source_v3,runs,cheap,route)
    verified=v5.run_original(train_raw,test_raw,source_v3,source_v4,runs,cheap,materials)
    require(verified['independent_lexical_numeric_replay'] is True and
            verified['publisher_original_sha_verified'] is True and
            verified['source_independent_families']==1 and
            verified['disposition']=='HOLD_NO_GO',
            'old independent publisher and lexical review not qualified')
    _,gold=v3.reconstruct(train_raw,test_raw,v3.original.FIXED_SHA)
    result={}
    for name in MODELS:
        routed={cid:rows[cid]['scores'][name] for cid in gold}
        result[name]={'vs_cheap':_paired(routed,cheap_probs,gold),
                      'vs_full_paid_model':_paired(routed,original[name],gold)}
    return {'schema':REVIEW_SCHEMA,'original_source_plan_sha256':v5.SOURCE_PLAN_SHA,
            'selected_case_ids':selected,'selected_count':BUDGET,'heldout_n':32,
            'original_neural_candidate_results':result,
            'publisher_original_sha_verified':True,
            'independent_lexical_numeric_replay':True,
            'independent_route_replay':True,
            'reference_full_forward_count_already_paid_per_model':96,
            'new_encoder_sequence_forwards_observed':0,
            'hypothetical_neural_requests_per_32_cases':BUDGET,
            'physical_neural_compute_savings_proven':False,
            'historically_exposed_labels':True,
            'prospective_future_windows':0,'source_independent_families':1,
            'stem_winner_verified':False,'ndu_benefit_verified':False,
            'production_authorized':False,'cell_split_authorized':False,
            'disposition':'HOLD_NO_GO','authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser()
    for arg in ('manifest','zip-dir','route','route-sha256','train','test','materials','output'):
        p.add_argument('--'+arg,required=True)
    a=p.parse_args();root=Path(a.zip_dir)
    lock=json.loads(Path(a.manifest).read_text())
    require(lock['schema']=='hepta.stem.original-hard-charge.lock.v5',
            'unregistered original artifacts')
    path=Path(a.route)
    require(path.is_file() and not path.is_symlink() and
            sha(path.read_bytes())==a.route_sha256,
            'route digest did not match prelabel checkpoint')
    r=json.loads(path.read_text(),parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite route')))
    src={n:v5.locked_json(root/(n+'.zip'),lock['artifacts'],n) for n in v5.ROLES}
    report=review_original(Path(a.train).read_bytes(),Path(a.test).read_bytes(),
        src['source_v3'],src['source_v4'],{n:src[n] for n in MODELS},
        src['cheap_v4'],r,json.loads(Path(a.materials).read_text()))
    out=Path(a.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('xb') as handle:
        handle.write(canonical(report)+b'\n');handle.flush()
    print(json.dumps({'sha256':sha(out.read_bytes()),'authority':'DENY_ALL',
                      'disposition':'HOLD_NO_GO'},sort_keys=True))

if __name__=='__main__':
    main()
