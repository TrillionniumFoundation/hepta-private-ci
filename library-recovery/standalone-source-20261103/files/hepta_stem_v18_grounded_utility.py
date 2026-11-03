"""V18 evidence-linked System2 utility: source-bound, non-authorizing research.

Requires *external* original Reader outputs and an externally sealed citation
inventory. Does not run or authenticate an LLM, evidence owner or evaluator.
A raw correct answer without supported citations earns no grounded task reward.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path

import v14_reader_sufficiency_gate as v14
import v15_system2_split_shadow as v15
import v16_reader_system2_bridge as v16

SCHEMA = 'hepta.stem.v18.grounded-ndu-utility.v1'
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_IDS = 64


def require(predicate, message):
    if not predicate:
        raise ValueError(message)


def exact(value, fields, label):
    require(type(value) is dict and set(value) == set(fields), label + ' shape')


def safe_id(value):
    return type(value) is str and 1 <= len(value) <= 128 and all(
        ord(c) >= 32 and ord(c) != 127 for c in value)


def load_json(path):
    p = Path(path)
    require(p.is_file() and not p.is_symlink() and
            0 < p.stat().st_size <= MAX_JSON_BYTES, 'missing/unsafe file')
    def unique(pairs):
        row = {}
        for key, value in pairs:
            require(key not in row, 'duplicate JSON property')
            row[key] = value
        return row
    def finite(value):
        raise ValueError('nonfinite JSON constant: ' + value)
    return json.loads(p.read_bytes(), object_pairs_hook=unique,
                      parse_constant=finite)


def _source_catalog(case, node, source_id):
    catalog = case['sources']
    require(source_id in catalog and v15.hex_sha(catalog[source_id]),
            'source ID not in immutable admitted catalog')
    require(source_id in node['delivered_evidence_ids'],
            'cited source not in actual terminal delivered evidence')


def source_first_seal(v14_plan, v15_study, sources):
    """Prelabel: require one immutable scope/source/evidence roster for every node."""
    parent = v16.source_first_bridge(v14_plan, v15_study)
    exact(sources, ('schema', 'source_only','frozen_before_predictions',
                    'production_authorized','v14_plan_sha256',
                    'v15_study_sha256','cases'), 'source roster')
    require(sources['schema'] == SCHEMA+'.source-roster'
            and sources['source_only'] is True
            and sources['frozen_before_predictions'] is True
            and sources['production_authorized'] is False
            and sources['v14_plan_sha256'] == v15.sha_obj(v14_plan)
            and sources['v15_study_sha256'] == v15.sha_obj(v15_study),
            'unfrozen or incorrectly bound source roster')
    require(type(sources['cases']) is list and
            len(sources['cases']) == len(v15_study['cases']),
            'source roster census')
    original = {c['id']:c for c in v14_plan['cases']}
    studies = {c['id']:c for c in v15_study['cases']}
    seen_cases = set()
    for case in sources['cases']:
        exact(case, ('case_id','sources','nodes'), 'case source roster')
        cid = case['case_id']
        require(safe_id(cid) and cid in original and cid not in seen_cases,
                'source roster missing/duplicated case')
        seen_cases.add(cid)
        require(type(case['sources']) is dict and 1 <= len(case['sources']) <= MAX_EVIDENCE_IDS,
                'no/too many sources')
        for eid, digest in case['sources'].items():
            require(safe_id(eid) and v15.hex_sha(digest), 'malformed source identity')
        study = studies[cid]
        require(type(case['nodes']) is list and
                len(case['nodes']) == len(study['nodes']), 'node source census')
        nodes = {n['id']:n for n in study['nodes']}
        seen_nodes = set()
        for item in case['nodes']:
            exact(item, ('node_id','request_sha256','delivered_evidence_ids'),
                  'node evidence binding')
            node_id = item['node_id']
            require(safe_id(node_id) and node_id in nodes and
                    node_id not in seen_nodes and
                    item['request_sha256'] == nodes[node_id]['request_sha256'],
                    'unbound/repeated state node')
            seen_nodes.add(node_id)
            ids = item['delivered_evidence_ids']
            require(type(ids) is list and len(ids) <= MAX_EVIDENCE_IDS and
                    len(ids) == len(set(ids)) and
                    all(type(x) is str and x in case['sources'] for x in ids),
                    'unregistered/duplicated delivered evidence')
        root = next(n for n in case['nodes'] if n['node_id']==study['root'])
        require(root['delivered_evidence_ids'] ==
                original[cid]['arms']['sufficient']['evidence_ids'],
                'root evidence differs from frozen V14 sufficient evidence')
    return {
        'schema':SCHEMA+'.source-first-seal',
        'v16_source_first_sha256':v15.sha_obj(parent),
        'v18_source_roster_sha256':v15.sha_obj(sources),
        'case_count':len(sources['cases']),
        'source_only':True,'labels_seen':False,
        'source_identity_authenticated':False,
        'pretraining_or_generation_verified':False,
        'production_authorized':False,
        'decision':'HOLD_NO_GO'
    }


def review_grounded(v14_plan, v14_predictions, v14_adjudication,
                    v15_study, v15_policy, v15_execution, v15_adjudication,
                    v16_prelabel, sources, v18_prelabel, citations):
    require(v18_prelabel == source_first_seal(v14_plan,v15_study,sources),
            'source-first evidence seal mismatch')
    # Validate the complete V14 -> V15 -> V16 experiment with unchanged
    # original source, model, output and postseal judgment bindings first.
    parent = v16.review_bridge(v14_plan,v14_predictions,v14_adjudication,
                              v15_study,v15_policy,v15_execution,
                              v15_adjudication,v16_prelabel)
    v14_report = v14.report(v14_plan,v14_predictions,v14_adjudication)
    source_cases = {c['case_id']:c for c in sources['cases']}
    observed = {(r['case_id'],r['arm']):r for r in v15_execution['records']}
    judged = {(r['case_id'],r['arm']):r for r in v15_adjudication['results']}
    original = {(r['case_id'],r['reader'],r['arm']):r
                for r in v14_predictions['records']}
    exact(citations, ('schema','v18_prelabel_sha256','v15_execution_sha256',
                      'model_output_source','sealed_before_adjudication',
                      'reviewer_independence_unverified','production_authorized',
                      'records'), 'citation inventory')
    require(citations['schema']==SCHEMA+'.citation-inventory'
            and citations['v18_prelabel_sha256']==v15.sha_obj(v18_prelabel)
            and citations['v15_execution_sha256']==v15.sha_obj(v15_execution)
            and citations['model_output_source']=='external_original_required'
            and citations['sealed_before_adjudication'] is True
            and citations['reviewer_independence_unverified'] is True
            and citations['production_authorized'] is False,
            'citation inventory is not sealed/bound')
    require(type(citations['records']) is list and
            len(citations['records']) == len(observed),
            'incomplete four-arm citation census')
    seen = {}
    terminal_views = {}
    for record in citations['records']:
        exact(record, ('case_id','arm','terminal_request_sha256',
                       'answer_sha256','cited_evidence_ids','abstained'),
              'citation row')
        key = record['case_id'],record['arm']
        require(key in observed and key not in seen,'foreign/duplicate citation row')
        source = source_cases[record['case_id']]
        issued = observed[key]
        require(record['terminal_request_sha256']==issued['terminal_request_sha256']
                and record['answer_sha256']==issued['answer_sha256'],
                'citation row altered original model request or answer')
        terminal = next(n for n in source['nodes']
            if n['request_sha256']==issued['terminal_request_sha256'])
        cited = record['cited_evidence_ids']
        require(type(cited) is list and len(cited) <= MAX_EVIDENCE_IDS
                and len(cited) == len(set(cited))
                and all(type(x) is str for x in cited)
                and type(record['abstained']) is bool,
                'malformed citation and abstention metadata')
        for eid in cited:
            _source_catalog(source,terminal,eid)
        if judged[key]['citations_entailed']:
            require(bool(cited) and not record['abstained'],
                    'unanchored V15 citation entailment cannot earn utility')
        claim_key = record['case_id'],issued['terminal_request_sha256']
        claim = tuple(cited),record['abstained']
        if claim_key in terminal_views:
            require(terminal_views[claim_key]==claim,
                    'identical frozen Reader terminal claimed different citations')
        terminal_views[claim_key] = claim
        if record['arm']=='stop':
            old = original[record['case_id'],'candidate','sufficient']
            require(cited==old['cited_evidence_ids']
                    and record['abstained']==old['abstained'],
                    'V15 STOP evidence differs from V14 original Reader')
        seen[key]=record
    rewards = v15_study['prices']
    tally = {arm:{'cases':0,'raw_correct':0,'grounded_correct':0,
                  'unsupported_raw_correct':0,'abstained':0,
                  'cpu_ms':0,'tokens':0,'raw_net_micro':0,'grounded_net_micro':0}
             for arm in v15.ARMS}
    groups = {ref:defaultdict(lambda:dict(cases=0,raw_correct_delta=0,
               grounded_correct_delta=0,grounded_net_micro_delta=0))
              for ref in v15.ARMS if ref!='ndu_shadow'}
    for case in v15_study['cases']:
        cid=case['id']
        for arm in v15.ARMS:
            row=observed[cid,arm]
            decision=judged[cid,arm]
            note=seen[cid,arm]
            raw=bool(decision['correct'])
            grounded=bool(raw and decision['citations_entailed']
                and note['cited_evidence_ids'] and not note['abstained'])
            t=tally[arm]
            t['cases']+=1;t['raw_correct']+=int(raw)
            t['grounded_correct']+=int(grounded)
            t['unsupported_raw_correct']+=int(raw and not grounded)
            t['abstained']+=int(note['abstained'])
            t['cpu_ms']+=row['cpu_ms'];t['tokens']+=row['tokens']
            charge=row['cpu_ms']*rewards['cpu_ms_price_micro']+\
                   row['tokens']*rewards['token_price_micro']
            t['raw_net_micro']+=int(raw)*rewards['correct_reward_micro']-charge
            t['grounded_net_micro']+=int(grounded)*rewards['correct_reward_micro']-charge
        def net(arm):
            row=observed[cid,arm]; note=seen[cid,arm];score=judged[cid,arm]
            grounded=(score['correct'] and score['citations_entailed']
                and note['cited_evidence_ids'] and not note['abstained'])
            raw=score['correct']
            cost=row['cpu_ms']*rewards['cpu_ms_price_micro']+\
                 row['tokens']*rewards['token_price_micro']
            return int(raw),int(grounded),int(grounded)*rewards['correct_reward_micro']-cost
        nd_raw,nd_gr,nd_net=net('ndu_shadow')
        for ref in groups:
            ref_raw,ref_gr,ref_net=net(ref)
            group=groups[ref][case['family']]
            group['cases']+=1
            group['raw_correct_delta']+=nd_raw-ref_raw
            group['grounded_correct_delta']+=nd_gr-ref_gr
            group['grounded_net_micro_delta']+=nd_net-ref_net
    # The V14.1 source-evidence metric must exactly agree with the V15 STOP
    # evidence ledger before System 2 receives even a descriptive comparison.
    v14_grounded = v14_report['per_reader_arm']['candidate']['sufficient']['grounded_correct']
    require(tally['stop']['grounded_correct']==v14_grounded,
            'V14 grounded Reader and V15 STOP have different score semantics')
    contrasts={}
    for ref,by_group in sorted(groups.items()):
        total=sum(x['grounded_net_micro_delta'] for x in by_group.values())
        contrasts[ref]={
            'paired_cases':sum(x['cases'] for x in by_group.values()),
            'claimed_source_families_not_authenticated':len(by_group),
            'raw_correct_delta':sum(x['raw_correct_delta'] for x in by_group.values()),
            'grounded_correct_delta':sum(x['grounded_correct_delta'] for x in by_group.values()),
            'grounded_net_micro_delta':total,
            'per_claimed_family':dict(sorted(by_group.items())),
            'changed_terminal_cases':parent['system2_vs_baselines_descriptive'][ref]
                                     ['changed_terminal_cases'],
        }
    return {
        'schema':SCHEMA+'.research-report',
        'v18_prelabel_sha256':v15.sha_obj(v18_prelabel),
        'citation_inventory_sha256':v15.sha_obj(citations),
        'v16_review_sha256':v15.sha_obj(parent),
        'v14_grounded_reader_count':v14_grounded,
        'per_arm_descriptive':tally,
        'grounded_system2_vs_baselines_descriptive':contrasts,
        'original_reader_execution_authenticated':False,
        'model_host_authentication_verified':False,
        'source_authority_authenticated':False,
        'independent_citation_evaluator_authenticated':False,
        'real_world_expected_utility_qualified':False,
        'system2_activation_authorized':False,
        'cell_split_authorized':False,
        'model_promotion_authorized':False,
        'production_authorized':False,
        'decision':'HOLD_NO_GO',
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='cmd',required=True)
    freeze=sub.add_parser('freeze')
    freeze.add_argument('--v14-plan',required=True)
    freeze.add_argument('--v15-study',required=True)
    freeze.add_argument('--source-roster',required=True)
    audit=sub.add_parser('audit')
    for name in ('v14-plan','v14-predictions','v14-adjudication',
                 'v15-study','v15-policy','v15-execution','v15-adjudication',
                 'v16-prelabel','source-roster','v18-prelabel','citations'):
        audit.add_argument('--'+name,required=True)
    args=p.parse_args()
    if args.cmd=='freeze':
        value=source_first_seal(*[load_json(getattr(args,k.replace('-','_')))
             for k in ('v14-plan','v15-study','source-roster')])
    else:
        value=review_grounded(*[load_json(getattr(args,k.replace('-','_')))
             for k in ('v14-plan','v14-predictions','v14-adjudication',
                 'v15-study','v15-policy','v15-execution','v15-adjudication',
                 'v16-prelabel','source-roster','v18-prelabel','citations')])
    print(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__':main()
