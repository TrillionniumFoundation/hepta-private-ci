"""Independent read-only public V14 cost/negative receipt audit.

Pure stdlib, no access to raw questions, publisher gold or weights. This
validates reported limitations and historical aggregates, NOT neural ability.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import re
from hashlib import sha256

SCHEMA='hepta.stem.v14.original-primary-single-cost-public.no-go.v1'
REQUIRED_DIGEST={
 'original_dataset_sha256':'79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4',
 'original_v13_public_file_sha256':'7d605aa9184a6df0524b47d71d78d1f3cab5cc478b0e15e3bd41aa978b6dcd1d',
 'original_source_sha256':'9d707c297dc743cffe00d94ead04198b7039f72027743dc6d6e02c826a623a8c',
 'original_frozen_plan_sha256':'8f6efdb78a173d64123209753ebf2dac06b03367637084a4098866cdbfe4df53',
}
KNOWN_FAMILIES={
 'conv-47':(190,1,76,79,3,0),
 'conv-48':(239,0,124,123,1,2),
 'conv-49':(196,3,91,93,3,1),
 'conv-50':(204,3,81,88,7,0),
}
EXPECTED_KEYS={'schema','experiment_date','original_dataset_sha256','original_v13_public_file_sha256',
 'original_source_sha256','original_frozen_plan_sha256','registered_primary','original_heldout_roots',
 'original_heldout_questions','publisher_unknown','complete_source_questions','source_passages',
 'route_parity','physical_cost','original_heldout_weak_evidence_proxy','measured_equal_host_two_runs',
 'optimized_index_cache_includes_full_primary_preprocessing', 'publisher_gold_read_only_after_rank_sealed',
 'v11_trained_head_equal_full_lifecycle_cost','reader_generated_new_outputs','independent_human_semantic_correctness',
 'number_of_new_prospective_calendar_windows','original_v6_seed41_retention_qualified','production_authorized',
 'model_selected','scientific_status'}


def verify(doc, reference):
    if type(doc)!=dict or set(doc)!=EXPECTED_KEYS or doc['schema']!=SCHEMA:
        raise ValueError('invalid V14 public schema')
    for key,value in REQUIRED_DIGEST.items():
        if doc[key]!=value:
            raise ValueError('original material or V13 source pin changed: '+key)
    if sha256(reference).hexdigest()!=REQUIRED_DIGEST['original_v13_public_file_sha256']:
        raise ValueError('original frozen V13 public reference modified')
    v13=json.loads(reference)
    if (v13['per_arm']['bm25']['heldout_any_hit3']!=372 or
        v13['per_arm']['phrase_char']['heldout_any_hit3']!=383 or
        v13['per_arm']['phrase_char']['family_delta_vs_bm25']!={'conv-47':3,'conv-48':-1,'conv-49':2,'conv-50':7}):
        raise ValueError('V13 pre-registered weak baseline changed')
    if (doc['registered_primary']!='phrase_char' or doc['experiment_date']!='2026-10-16'
        or (doc['original_heldout_roots'],doc['original_heldout_questions'],doc['publisher_unknown'],
            doc['complete_source_questions'],doc['source_passages'])!=(4,829,7,1986,5882)):
        raise ValueError('wrong family/selection/denominator')
    correct={'checked_original_source_and_gold_free':True,'exact_original_bm25_top32':1986,
             'exact_original_primary_top32':1986,'duplicate_sealed_replays_match':True,
             'private_full_raw_rank_and_gold_not_uploaded':True}
    if doc['route_parity']!=correct:raise ValueError('original source-first parity incomplete')
    h=doc['original_heldout_weak_evidence_proxy']
    if type(h)!=dict or set(h)!={'bm25_any_hit3','primary_any_hit3','net_primary_hit3',
        'annotated_questions','bm25_any_hit16','primary_any_hit16','bm25_any_hit32','primary_any_hit32',
        'bm25_all_hit3','primary_all_hit3','per_family'}:
        raise ValueError('weak evidence fields changed')
    vals=(h['bm25_any_hit3'],h['primary_any_hit3'],h['net_primary_hit3'],h['annotated_questions'],
          h['bm25_any_hit16'],h['primary_any_hit16'],h['bm25_any_hit32'],h['primary_any_hit32'],
          h['bm25_all_hit3'],h['primary_all_hit3'])
    if vals!=(372,383,11,822,515,528,575,587,317,326) or any(type(v)!=int for v in vals):
        raise ValueError('historical weak support counts mutated')
    fams=h['per_family']
    if type(fams)!=dict or set(fams)!=set(KNOWN_FAMILIES):raise ValueError('source families changed')
    for fam,(n,unknown,baseline,candidate,gain,loss) in KNOWN_FAMILIES.items():
        row=fams[fam]
        if type(row)!=dict or set(row)!={'original_questions','publisher_unknown','bm25_hit3',
                'primary_hit3','gain','loss','net'}:
            raise ValueError('bad family record')
        if (row['original_questions'],row['publisher_unknown'],row['bm25_hit3'],
            row['primary_hit3'],row['gain'],row['loss'],row['net'])!=(n,unknown,baseline,candidate,gain,loss,gain-loss):
            raise ValueError('family gain/loss changed')
    costs=doc['physical_cost']
    if type(costs)!=dict or set(costs)!={'bm25_only','primary_only'}:
        raise ValueError('unregistered profile')
    for arm,record in costs.items():
        if set(record)!={'experiments','repeat_exact_rank_digest','matched_source_cases','source_turns'}:
            raise ValueError('partial cost receipt')
        if (record['matched_source_cases'],record['source_turns'])!=(1986,5882):
            raise ValueError('incomplete measured source census')
        if not (type(record['repeat_exact_rank_digest'])==str and re.fullmatch('[0-9a-f]{64}',record['repeat_exact_rank_digest'])):
            raise ValueError('missing actual route digest')
        if type(record['experiments'])!=list or len(record['experiments'])!=2:
            raise ValueError('missing physical repeat')
        for sample in record['experiments']:
            if type(sample)!=dict or set(sample)!={'cpu_ns','wall_ns','index_cpu_ns','query_cpu_ns','peak_rss_kib'}:
                raise ValueError('incomplete cost sample')
            if any(type(v)!=int or v<=0 for v in sample.values()) or sample['query_cpu_ns']+sample['index_cpu_ns']>sample['cpu_ns']*1.02:
                raise ValueError('implausible physical resource accounting')
    negative={'measured_equal_host_two_runs':True,
      'optimized_index_cache_includes_full_primary_preprocessing':True,
      'publisher_gold_read_only_after_rank_sealed':True,
      'v11_trained_head_equal_full_lifecycle_cost':False,
      'reader_generated_new_outputs':0,
      'independent_human_semantic_correctness':None,
      'number_of_new_prospective_calendar_windows':0,
      'original_v6_seed41_retention_qualified':False,
      'production_authorized':False,
      'model_selected':False,
      'scientific_status':'HOLD_NO_GO_NOT_A_PROSPECTIVE_CAUSAL_BENEFIT'}
    for key,value in negative.items():
        if doc[key] is not value and doc[key]!=value:raise ValueError('false science or authority: '+key)
    cpu={arm:sum(s['cpu_ns'] for s in costs[arm]['experiments'])/2 for arm in costs}
    if cpu['primary_only']<=cpu['bm25_only']:
        raise ValueError('historical CPU delta falsified')
    return {'status':'NO_GO','heldout_questions':829,'source_families':4,
            'weak_delta':11, 'physical_cost_samples_per_arm':2,
            'cpu_primary_to_bm25_ratio':cpu['primary_only']/cpu['bm25_only'],
            'production_authorized':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('--public',required=True);p.add_argument('--v13',required=True)
    a=p.parse_args()
    print(json.dumps(verify(json.loads(Path(a.public).read_bytes()),Path(a.v13).read_bytes()),sort_keys=True))
if __name__=='__main__':main()
