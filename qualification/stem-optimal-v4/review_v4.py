"""Independent original-publisher postseal scorer; no model loading or training.

The v3 three-arm original scorer remains authoritative for its own inputs.
This extension checks a fourth, distinct model receipt. Always HOLD_NO_GO.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

import stem_v4 as core

sys.path.insert(0,str(core.ROOT / 'stem-optimal-v3'))
sys.path.insert(0,str(core.ROOT / 'stem-optimal-v1'))

ARMS = ('centroid','frozen_init','learned')
FIELDS = {
    'schema','cohort','candidate','source_plan_sha256','model_repo','model_revision',
    'actual_weight_sha256','model_precision','actual_loaded_parameters','native_width','projected_width',
    'projection','prompt_name','initial_head_sha256','trained_head_sha256',
    'head_parameters','optimizer_steps','rows','cost','fleet','future_windows',
    'human_verified_new_sources','ndu_task_utility_qualified',
    'cell_split_authorized','production_authorized','authority','disposition'
}
COST = {'physical_encoder_sequences','physical_encoder_forward_batches',
        'model_load_seconds','embedding_seconds','head_train_seconds',
        'complete_wall_seconds','complete_cpu_seconds','maxrss_bytes_linux_unattested',
        'energy_joules','complete_request_p99_ms'}
FLEET = {'fleet_cell_count','active_heads_per_call','head_parameter_count',
         'head_weight_bytes_fp32','timed_batched_calls','head_batch_p95_ms',
         'head_batch_p99_ms','last_logit_sha256','real_pretrained_input_feature',
         'complete_request_p99','energy_joules','target_host_attested'}


def safe_float(x, lo=0.0, hi=1e12):
    return type(x) in (float,int) and math.isfinite(x) and lo <= x <= hi


def check_fourth(source, receipt, gold):
    """Presealed receipt + independent heldout label mapping; no raw targets in run."""
    core.require(type(source) is dict and type(receipt) is dict and set(receipt) == FIELDS,
                 'unknown or label-bearing receipt keys')
    core.require(receipt['schema'] == core.SCHEMA and receipt['cohort'] == core.COHORT
                 and receipt['candidate'] == core.ARM
                 and receipt['source_plan_sha256'] == source['source_plan_sha256'],
                 'wrong cohort or source digest')
    core.require((receipt['model_repo'],receipt['model_revision'],receipt['actual_weight_sha256'])
                 == (core.REPO, core.REVISION, core.WEIGHT_SHA), 'unpinned fourth model')
    core.require(type(receipt['actual_loaded_parameters']) is int and
                 200_000_000 <= receipt['actual_loaded_parameters'] <= 350_000_000,
                 'unqualified text-only loaded parameter census')
    core.require(receipt['model_precision'] == 'fp32_cpu' and
                 receipt['native_width'] == 768 and receipt['projected_width'] == 384 and
                 receipt['projection'] == core.PROJECTION and
                 receipt['prompt_name'] == 'Classification', 'unmatched projection/input profile')
    core.require(receipt['head_parameters'] == 27656 and
                 receipt['optimizer_steps'] == 100, 'head parameter/update count')
    for fld in ('initial_head_sha256','trained_head_sha256'):
        value=receipt[fld]
        core.require(type(value) is str and len(value)==64 and
                     all(c in '0123456789abcdef' for c in value), 'head digest invalid')
    core.require(receipt['initial_head_sha256'] != receipt['trained_head_sha256'],
                 'no trained head state')
    core.require(receipt['authority'] == 'DENY_ALL' and
                 receipt['disposition'] == 'HOLD_NO_GO' and
                 receipt['future_windows'] == 0 and receipt['human_verified_new_sources'] == 0 and
                 receipt['ndu_task_utility_qualified'] is False and
                 receipt['cell_split_authorized'] is False and
                 receipt['production_authorized'] is False, 'unauthorized scientific promotion')
    cost=receipt['cost']
    core.require(type(cost) is dict and set(cost)==COST, 'incomplete real cost receipt')
    core.require(type(cost['physical_encoder_sequences']) is int and
                 cost['physical_encoder_sequences']==96 and
                 type(cost['physical_encoder_forward_batches']) is int and
                 cost['physical_encoder_forward_batches']==6, 'no complete real forwards')
    for field in COST - {'physical_encoder_sequences','physical_encoder_forward_batches',
                         'energy_joules','complete_request_p99_ms'}:
        core.require(safe_float(cost[field]), 'invalid meter')
    core.require(cost['energy_joules'] is None and
                 cost['complete_request_p99_ms'] is None, 'unattested energy or p99')
    fleet=receipt['fleet']
    core.require(type(fleet) is dict and set(fleet)==FLEET,'malformed fleet')
    core.require(fleet['fleet_cell_count']==4096 and fleet['active_heads_per_call']==32
                 and fleet['head_parameter_count']==4096*6914 and
                 fleet['head_weight_bytes_fp32']==4096*6914*4 and
                 fleet['timed_batched_calls']==64, 'invented fleet inventory')
    core.require(fleet['real_pretrained_input_feature'] is True and
                 fleet['target_host_attested'] is False and
                 fleet['complete_request_p99'] is None and fleet['energy_joules'] is None,
                 'false target host or lifecycle receipt')
    core.require(safe_float(fleet['head_batch_p95_ms']) and
                 safe_float(fleet['head_batch_p99_ms']) and
                 fleet['head_batch_p95_ms'] <= fleet['head_batch_p99_ms'],
                 'invalid head timings')
    core.require(type(fleet['last_logit_sha256']) is str and
                 len(fleet['last_logit_sha256'])==64 and
                 all(ch in '0123456789abcdef' for ch in fleet['last_logit_sha256']),
                 'unbound real head output')
    expected = source['heldout']
    rows = receipt['rows']
    core.require(type(rows) is list and len(rows)==len(expected)==32
                 and type(gold) is dict and set(gold)=={r['case_id'] for r in expected},
                 'missing independent original case/gold')
    result={}
    for arm in ARMS:
        result[arm]={'correct':0,'brier_sum':0.0}
    for row, registered in zip(rows,expected):
        core.require(type(row) is dict and set(row)=={'case_id','source_sha256','scores'}
                     and row['case_id']==registered['case_id'] and
                     row['source_sha256']==registered['source_sha256'],
                     'case source/order substitution')
        core.require(type(row['scores']) is dict and set(row['scores'])==set(ARMS),
                     'missing score arm')
        y=gold[row['case_id']]
        core.require(type(y) is int and 0 <= y < 4, 'original human label invalid')
        for arm in ARMS:
            prob=row['scores'][arm]
            core.require(type(prob) is list and len(prob)==4 and
                         all(safe_float(p,0,1) for p in prob) and
                         abs(sum(prob)-1)<1e-5, 'invalid probability distribution')
            result[arm]['correct'] += int(max(range(4),key=lambda i: prob[i])==y)
            result[arm]['brier_sum'] += sum((p-int(i==y))**2 for i,p in enumerate(prob))
    return {arm:{'correct':values['correct'],'n':32,
                 'brier':values['brier_sum']/32} for arm,values in result.items()}


def ensure_matched_initial_heads(old_runs, fourth):
    core.require(type(old_runs) is list and len(old_runs) == 3 and
                 all(type(r) is dict and 'initial_head_sha256' in r for r in old_runs),
                 'missing incumbent initializer receipts')
    digests={r['initial_head_sha256'] for r in old_runs}
    core.require(len(digests) == 1 and fourth['initial_head_sha256'] in digests,
                 'cross-version initial Head tensor mismatch; not equal Head baseline')


def review_original(train_raw, test_raw, source, old_runs, fourth, materials):
    import stem_hard_charge_review_v3 as v3_review
    import stem_candidate_v1 as v1
    # Independently reconstruct the complete roster, both truth files and v3 controls.
    incumbent = v3_review._review(train_raw,test_raw,source,old_runs,materials)
    _,gold=v3_review.reconstruct(train_raw,test_raw,v1.ORIGINAL_SHA)
    core.check_source(source)
    fourth_result=check_fourth(source,fourth,gold)
    ensure_matched_initial_heads(old_runs, fourth)
    return {'schema':'hepta.stem.original-four-model-postseal.v4',
            'cohort':core.COHORT,'source_sha256':source['source_plan_sha256'],
            'existing_original_three_model_scoring':incumbent,
            'fourth_model':{'id':core.ARM,'source':'original_pretrained_embeddinggemma2',
                            'descriptive_scores':fourth_result,
                            'matched_training_budget_only':True,
                            'matched_end_to_end_compute':False},
            'future_windows':0,'new_source_families':0,'stem_winner_verified':False,
            'system2_net_utility_verified':False,'production_authorized':False,
            'authority':'DENY_ALL','disposition':'HOLD_NO_GO'}


def main():
    p=argparse.ArgumentParser()
    for key in ('train','test','source','old_granite47','old_granite97',
                'old_mmbert140','fourth','materials','output'):
        p.add_argument('--'+key.replace('_','-'),type=Path,required=True)
    args=p.parse_args()
    def file_bytes(path):
        core.require(path.is_file() and not path.is_symlink() and
                     path.stat().st_size<=2_000_000,'publisher material size')
        return path.read_bytes()
    result=review_original(file_bytes(args.train),file_bytes(args.test),
                           core.read_json(args.source),
                           [core.read_json(getattr(args,'old_'+name))
                            for name in ('granite47','granite97','mmbert140')],
                           core.read_json(args.fourth),core.read_json(args.materials))
    core.write_private(args.output,result)

if __name__=='__main__':
    main()
