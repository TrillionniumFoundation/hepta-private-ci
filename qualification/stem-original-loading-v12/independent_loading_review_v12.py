"""Model-free negative qualification of pinned pretrained loader diagnostics."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'stem-optimal-v5'))
import paired_review_v5 as archive

SCHEMA='hepta.stem.pretrained-loading-head-parity-diagnostic.v12'
ROLES=('granite47-auto_model','granite97-auto_model',
       'mmbert140-auto_model','mmbert140-full_mlm')


def need(ok,why):
    if not ok:raise ValueError(why)


def audit(report,original):
    name=report.get('candidate')
    profile=report.get('profile')
    need(type(report) is dict and report.get('schema')==SCHEMA and
         name in ('granite47','granite97','mmbert140') and
         name==original.get('candidate') and
         profile in ({'mmbert140':('auto_model','full_mlm')}.get(name,('auto_model',))),
         'not exact original model and profile')
    need(report.get('source_plan_sha256')==original.get('source_plan_sha256') and
         report.get('original_model_revision')==original.get('model_revision') and
         report.get('original_weight_sha256')==original.get('actual_weight_sha256') and
         report.get('original_initial_head_sha256')==original.get('initial_head_sha256') and
         report.get('original_trained_head_sha256')==original.get('trained_head_sha256'),
         'original model/head/source material substituted')
    meta=report.get('load_diagnostics')
    need(type(meta) is dict and
         type(meta.get('missing_key_count')) is int and meta['missing_key_count']>=0 and
         type(meta.get('mismatched_key_count')) is int and meta['mismatched_key_count']>=0 and
         type(meta.get('error_count')) is int and meta['error_count']>=0 and
         type(meta.get('unexpected_key_count')) is int and meta['unexpected_key_count']>=0 and
         type(meta.get('missing_keys')) is list and
         len(meta['missing_keys'])==min(30,meta['missing_key_count']) and
         type(meta.get('mismatched_keys')) is list and
         len(meta['mismatched_keys'])==min(30,meta['mismatched_key_count']) and
         type(meta.get('error_messages')) is list and
         len(meta['error_messages'])==min(10,meta['error_count']),
         'unqualified or truncated loader-missing-key provenance')
    loaded=(meta['missing_key_count']==meta['mismatched_key_count']==meta['error_count']==0)
    need(meta.get('model_base_weights_complete') is loaded and
         type(meta.get('complete_model_resident_parameter_scalars')) is int and
         meta['complete_model_resident_parameter_scalars']>0 and
         type(meta.get('loader_class')) is str and type(meta.get('base_model_class')) is str,
         'unreliable original pretrained weights completeness status')
    for field in ('initial','trained'):
        equal=report.get(field+'_head_byte_equal')
        expected=report.get('original_'+('initial' if field=='initial' else 'trained')+'_head_sha256')
        observed=report.get('observed_'+('initial' if field=='initial' else 'trained')+'_head_sha256')
        need(type(equal) is bool and type(observed) is str and len(observed)==64 and
             equal==(expected==observed),'false original Head reproducibility flag')
    drifts=report.get('historical_original_probability_max_abs_drift')
    need(type(drifts) is dict and set(drifts)=={'learned','centroid','frozen_init'} and
         all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1
             for v in drifts.values()),'nonfinite historical score comparison')
    passes=loaded and report['initial_head_byte_equal'] and report['trained_head_byte_equal'] and all(v<=5e-4 for v in drifts.values())
    need(report.get('scientifically_fully_reproducible_same_head_and_base') is passes and
         report.get('original_encoder_sequences_paid')==72 and
         report.get('original_encoder_batches_paid')==5 and
         report.get('selected_case_count')==8,
         'incorrect physical model qualification/conformance counters')
    for field in ('model_load_wall_seconds','actual_encode_wall_seconds','actual_head_train_wall_seconds',
                  'total_elapsed_wall_seconds','total_elapsed_cpu_seconds','self_reported_peak_rss_bytes'):
        v=report.get(field)
        need(type(v) in (int,float) and math.isfinite(v) and v>0,
             'invalid model stage resource witness '+field)
    need(report['total_elapsed_wall_seconds']+1e-5 >=
         report['model_load_wall_seconds']+report['actual_encode_wall_seconds']+report['actual_head_train_wall_seconds'],
         'bad complete wall stage reconciliation')
    need(report.get('authority')=='DENY_ALL' and report.get('disposition')=='HOLD_NO_GO' and
         report.get('production_authorized') is False and
         report.get('cell_split_authorized') is False and
         report.get('stem_winner_verified') is False and
         report.get('ndu_benefit_verified') is False and
         report.get('same_host_full_lifecycle_cost_verified') is False and
         report.get('retrospective_test_labels_previously_exposed') is True,
         'forged scientific or product authority')
    return {'profile':profile,'candidate':name,'complete_pretrained_base_weights':loaded,
            'missing_parameter_count':meta['missing_key_count'],
            'unloaded_unexpected_checkpoint_keys':meta['unexpected_key_count'],
            'initial_head_byte_match':report['initial_head_byte_equal'],
            'trained_head_byte_match':report['trained_head_byte_equal'],
            'max_selected_probability_drift':drifts,
            'all_original_baseline_replay_checks_pass':passes,
            'score_status':'DIAGNOSTIC_ONLY_NOT_FUTURE_OR_STEM_SELECTION'}


def main():
    p=argparse.ArgumentParser()
    for n in ('manifest','zip-dir','output'):
        p.add_argument('--'+n,required=True)
    p.add_argument('--receipt',action='append',required=True)
    args=p.parse_args()
    lock=json.loads(Path(args.manifest).read_text())
    need(lock['schema']=='hepta.stem.original-hard-charge.lock.v5' and
         lock['authority']=='DENY_ALL','wrong original archive registry')
    need(len(args.receipt)==4,'four exact original model-loading profiles required')
    reports=[json.loads(Path(f).read_text()) for f in args.receipt]
    roles=[r['candidate']+'-'+r['profile'] for r in reports]
    need(set(roles)==set(ROLES),'missing or duplicate model profile')
    originals={n:archive.locked_json(Path(args.zip_dir)/(n+'.zip'),lock['artifacts'],n)
               for n in ('granite47','granite97','mmbert140')}
    scored={role:audit(report,originals[report['candidate']])
            for role,report in zip(roles,reports)}
    data={'schema':'hepta.stem.pretrained-loading-independent-diagnostic.v12',
          'profiles':scored,'original_historical_model_loading_qualification_only':True,
          'future_windows':0,'source_independent_families':1,
          'no_new_model_issuer_signature':True,'target_host_full_lifecycle_savings_verified':False,
          'production_authorized':False,'cell_split_authorized':False,
          'stem_winner_verified':False,'authority':'DENY_ALL','disposition':'HOLD_NO_GO'}
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as f:f.write(json.dumps(data,allow_nan=False,sort_keys=True,separators=(',',':')).encode()+b'\n')
    print(json.dumps({'original_model_diagnostic_profiles':list(scored),
                      'authority':'DENY_ALL'},sort_keys=True))

if __name__=='__main__':main()
