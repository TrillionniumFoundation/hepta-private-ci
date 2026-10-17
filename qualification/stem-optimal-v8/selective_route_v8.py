"""Counterfactual *reuse* of already-paid original Stem predictions.

The route sees no heldout labels. No pretrained Encoder is executed or saved
by this script, and the experiment cannot attest a physical compute saving.
Research only: an 8/32 top-uncertainty budget selected on a retrospective panel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'stem-optimal-v5'))
import paired_review_v5 as v5

SCHEMA = 'hepta.stem.selective-counterfactual.v8'
SOURCE_SHA = '3e79b3449f3b63d1f261ae4ad9632ae4cff07262a82c5259a17d040e61929900'
CHEAP_ARM = 'char_345_tfidf_centroid'
NEURAL_ARM = 'learned'
CANDIDATES = ('granite47', 'granite97', 'mmbert140')
ROUTE_K = 8


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _scores(receipt, cases, arm, *, cheap=False):
    expected = {row['case_id']: row['source_sha256'] for row in cases}
    require(type(receipt) is dict and type(receipt.get('rows')) is list
            and len(receipt['rows']) == len(expected) == 32,
            'missing unlabelled historical case set')
    result = {}
    for row in receipt['rows']:
        require(type(row) is dict and set(row) == {'case_id', 'source_sha256', 'scores'}
                and row['case_id'] in expected and row['case_id'] not in result
                and row['source_sha256'] == expected[row['case_id']],
                'substituted, duplicated or source-shifted original case')
        scores = row['scores']
        require(type(scores) is dict and arm in scores and
                (set(scores) == {'word_12_tfidf_centroid', CHEAP_ARM} if cheap
                 else set(scores) == {'frozen_init', 'centroid', 'learned'}),
                'incomplete or label-bearing original scores')
        p = scores[arm]
        require(type(p) is list and len(p) == 4 and
                all(type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 1
                    for x in p) and abs(sum(p)-1) < 1e-5,
                'untrusted original probability array')
        result[row['case_id']] = p
    require(set(result) == set(expected), 'case coverage drift')
    return result


def select_unlabelled(cheap_probs, budget=ROUTE_K):
    """Select the lowest cheap top-two margin; tie by case digest, not gold."""
    require(type(budget) is int and budget == ROUTE_K and
            type(cheap_probs) is dict and len(cheap_probs) == 32,
            'nonfrozen selection budget/universe')
    ranked = []
    for cid, p in cheap_probs.items():
        require(type(cid) is str and cid.startswith('heldout:')
                and type(p) is list and len(p) == 4 and
                all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1
                    for v in p) and abs(sum(p)-1) < 1e-5,
                'invalid prelabel cheap probability')
        first, second = sorted(p, reverse=True)[:2]
        ranked.append((first-second, cid))
    ranked.sort()
    selected = [cid for _,cid in ranked[:budget]]
    require(len(selected) == len(set(selected)) == budget,
            'duplicated or unbounded selected IDs')
    return selected


def produce(source_v3, source_v4, original_runs, cheap):
    """The caller must first verify the six archived ZIP byte/sidecar locks."""
    require(source_v3 == source_v4 and
            source_v3.get('source_plan_sha256') == SOURCE_SHA and
            source_v3.get('heldout_labels_excluded') is True and
            len(source_v3.get('heldout', [])) == 32,
            'source/heldout labels or cohort drift')
    v5.original_nogold(source_v3, original_runs)
    require(type(cheap) is dict and
            cheap.get('schema') == 'hepta.stem.hard-charge.lexical-control.v4' and
            cheap.get('authority') == 'DENY_ALL' and
            cheap.get('production_authorized') is False and
            cheap.get('future_windows') == 0 and
            cheap.get('source_plan_sha256') == SOURCE_SHA and
            cheap.get('cost', {}).get('neural_encoder_forward_count') == 0,
            'not original label-blind cheap control')
    cases = source_v3['heldout']
    cheap_lookup = _scores(cheap, cases, CHEAP_ARM, cheap=True)
    originals = {name: _scores(original_runs[name], cases, NEURAL_ARM)
                 for name in CANDIDATES}
    selected = select_unlabelled(cheap_lookup)
    selected_set = set(selected)
    rows=[]
    for case in cases:
        cid = case['case_id']
        rows.append({'case_id':cid, 'source_sha256':case['source_sha256'],
                     'selected_for_hypothetical_escalation':cid in selected_set,
                     'scores': {name: (originals[name][cid] if cid in selected_set else cheap_lookup[cid])
                                for name in CANDIDATES}})
    return {'schema':SCHEMA, 'source_plan_sha256':SOURCE_SHA,
            'cohort':'hard-charge-four-intents-v3',
            'policy':'rank_lowest_top2_margin_then_case_id',
            'predeclared_selected_count':ROUTE_K, 'selected_case_ids':selected,
            'source_original_v3_sha':v5.V3_SOURCE_SHA,
            'source_original_v4_sha':v5.V4_SOURCE_SHA,
            'nonselective_cheap_arm':CHEAP_ARM,
            'hypothetical_escalation_arm':NEURAL_ARM,
            'candidates':list(CANDIDATES), 'rows':rows,
            'evidence':{
                'actual_new_encoder_sequence_forwards':0,
                'historical_original_encoder_forwards_reused':True,
                'hypothetical_heldout_encoder_requests_per_candidate':ROUTE_K,
                'measured_heldout_encoder_savings':False,
                'training_and_load_cost_eliminated':False,
                'matched_device_cpu_rss_p99_energy':False,
                'real_4096_cell_execution':False,
            },
            'source_independent_families':1,'future_windows':0,
            'prior_heldout_labels_previously_exposed':True,
            'stem_winner_verified':False,'ndu_benefit_verified':False,
            'production_authorized':False,'cell_split_authorized':False,
            'disposition':'HOLD_NO_GO','authority':'DENY_ALL'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--zip-dir',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    registry=json.loads(Path(args.manifest).read_text())
    require(registry['schema']=='hepta.stem.original-hard-charge.lock.v5',
            'wrong original zip registry')
    root=Path(args.zip_dir)
    receipts={name:v5.locked_json(root/(name+'.zip'),registry['artifacts'],name)
              for name in v5.ROLES}
    result=produce(receipts['source_v3'],receipts['source_v4'],
                   {name:receipts[name] for name in CANDIDATES},receipts['cheap_v4'])
    target=Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as stream:
        stream.write(canonical(result)+b'\n')
        stream.flush()
    print(json.dumps({'sha256':sha(target.read_bytes()),'authority':'DENY_ALL',
                      'new_encoder_forwards':0,'disposition':'HOLD_NO_GO'},sort_keys=True))

if __name__=='__main__':
    main()
