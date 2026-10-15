#!/usr/bin/env python3
"""Read-only scrutiny of claimed SIGKILL phase observations (never host attestation)."""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
from e5_crash_atomic_store import FAILPOINTS,Invalid,parse

SCHEMA='hepta.e5.actual-sigkill-atomic-checkpoint.v1'

def _sha(v):
    if type(v) is not str or len(v)!=64 or v=='0'*64 or any(c not in '0123456789abcdef' for c in v):
        raise Invalid('malformed SHA')
    return v

def _observed(record,logical,active,expected):
    if type(record) is not dict or record.get('schema')!=SCHEMA or record.get('authority')!='DENY_ALL' or record.get('production_promotion_permitted') is not False:
        raise Invalid('unsupported physical report')
    if record.get('logical_cells')!=logical or record.get('active_cells')!=active or record.get('real_child_sigkill_count')!=len(expected):
        raise Invalid('reported cohort or SIGKILL count disagrees')
    if record.get('cut_points_checked')!=list(expected) or type(record.get('stage_observations')) is not list or len(record['stage_observations'])!=len(expected):
        raise Invalid('missing or reordered crash-cut evidence')
    if record.get('same_seed_four_step_reference_momentum_and_weights_bit_exact') is not True:
        raise Invalid('no exact optimizer replay')
    for field in ('power_loss_durability_verified','production_WAL_CAS_or_FinalUse_verified','independent_model_origin_verified','real_pretrained_encoder_forward_executed','real_future_ndu_verified'):
        if record.get(field) is not False:raise Invalid('unsupported production/security/model claim')
    for field in ('process_wall_ms','process_peak_rss_bytes'):
        value=record.get(field)
        if type(value) not in (float,int) or not math.isfinite(value) or value<=0:
            raise Invalid('missing process measurement')
    _sha(record.get('reference_training_loss_sequence_sha256'))
    for stage,name in zip(record['stage_observations'],expected):
        if type(stage) is not dict or stage.get('failpoint')!=name or stage.get('child_exit_signal')!='SIGKILL' or stage.get('child_returncode')!=-9:
            raise Invalid('false child termination claim')
        if stage.get('final_step')!=4 or stage.get('replay_bit_exact') is not True or stage.get('prelabel_or_production_outcome_authenticated') is not False:
            raise Invalid('missing final optimizer match')
        before=name not in ('head_replaced','head_dirsynced')
        if stage.get('observed_step_after_crash')!=(2 if before else 4):
            raise Invalid('torn/stale publication or guessed durability')
        _sha(stage.get('stage_manifest_sha256'))
    return {'logical_cells':logical,'active_cells':active,'verified_stage_reports':len(expected),
            'pre_pointer_crashes_keep_prior_state':sum(name not in ('head_replaced','head_dirsynced') for name in expected),
            'post_pointer_crashes_show_new_state':sum(name in ('head_replaced','head_dirsynced') for name in expected)}

def review(a,b):
    if not isinstance(a,dict) or not isinstance(b,dict):raise Invalid('two separate physical panels required')
    return {'schema':'hepta.e5.crash-sigkill-descriptive-review.v1',
            'cohorts':{'64':_observed(a,64,8,FAILPOINTS),
                       '256':_observed(b,256,25,('blob_partial','manifest_published','head_replaced','head_dirsynced'))},
            'claimed_total_separate_sigkill_children':14,
            'independently_verified_OS_process_exits':False,
            'verified_original_pretrained_encoder':False,
            'signed_worker_or_source_provenance':False,
            'real_power_cut_or_native_WAL_qualified':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--small',type=Path,required=True)
    p.add_argument('--medium',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    x=p.parse_args()
    if x.output.exists():raise FileExistsError('create-only audit')
    source=[];records=[]
    for path in (x.small,x.medium):
        data=path.read_bytes()
        if not 2<len(data)<32768:raise Invalid('unbounded JSON report')
        records.append(parse(data));source.append(hashlib.sha256(data).hexdigest())
    result=review(*records);result['untrusted_source_file_sha256s']=source
    with x.output.open('x',encoding='utf8') as out:
        json.dump(result,out,sort_keys=True,indent=2,allow_nan=False);out.write('\n')
if __name__=='__main__':main()
