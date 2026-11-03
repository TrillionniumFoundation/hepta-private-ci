#!/usr/bin/env python3
"""Source-bound, read-only 3-of-4 original P0 research artifact census.

No held labels, no model loads, no physical-source signatures, no FinalUse.
Granite and Gemma independently replayed by separate NumPy evaluators.
Laya has ONLY a native prediction census (not model-weight replay).
"""
from __future__ import annotations
import hashlib, json, math, sys
from pathlib import Path
import zipfile

RUN=38868208650
HEAD='09e5d4806c166586ba18b2ac87f75034fecd6687'
REVISIONS={'granite_97m_r2':'835ad14087e140460703cf0fae09f97d469d65c2',
'embeddinggemma_2_text':'914f7f89142e33e77833254d9c9b90c3cef7303b',
'laya421_nochange':'c5d78730f3493e4fe16d61507ef4b78eef7318cf'}

class Invalid(ValueError):pass

def canonical(obj):return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def unique_pairs(pairs):
    out={}
    for k,v in pairs:
        if k in out:raise Invalid('duplicate original report JSON key')
        out[k]=v
    return out

def source_file(path,name):
    with zipfile.ZipFile(path) as archive:
        items=archive.infolist()
        if len(items)>32 or len({x.filename for x in items})!=len(items):raise Invalid('unsafe archived source census')
        x=archive.getinfo(name)
        if not 10 < x.file_size < 8*1024*1024:raise Invalid('missing/oversized original source')
        return json.loads(archive.read(name), object_pairs_hook=unique_pairs)

def native_laya_census(fit,blind,model):
    if (type(fit) is not dict or type(blind) is not dict or fit.get('metadata')!=blind.get('metadata')
      or type(blind.get('cases')) is not list or not blind['cases'] or
      any('label' in r for r in blind['cases'])):
        raise Invalid('label leakage/source mismatch')
    cases=blind['cases']
    expected={r['case_id']:r['view_sha256'] for r in cases}
    if len(expected)!=len(cases):raise Invalid('duplicate original case')
    if (type(model) is not dict or model.get('model')!='laya421_nochange' or
       model.get('model_revision')!=REVISIONS['laya421_nochange'] or
       model.get('schema')!='hepta.p0.multirc-original-semantic-physical.v1' or
       model.get('panel_id')!=fit['metadata'].get('panel_id') or
       model.get('fit_material_sha256')!=sha(canonical(fit)) or
       model.get('blind_material_sha256')!=sha(canonical(blind)) or
       model.get('actual_pretrained_local_weights_claimed') is not True or
       model.get('head_mode')!='pretrained_checkpoint_native_noul_nochange_not_equal_head' or
       model.get('training') is not None or model.get('feature_width') is not None or
       model.get('production_promotion_permitted') is not False or
       model.get('model_selection_permitted') is not False or
       model.get('physical_model_origin_independently_signed') is not False or
       model.get('authority')!='DENY_ALL'):
        raise Invalid('invalid native Laya execution/authority source')
    ctrl=model.get('control')
    if type(ctrl) is not dict or set(ctrl)!={'laya_native_nochange'}:
        raise Invalid('not a unique original native no-change control')
    p=ctrl['laya_native_nochange'].get('predictions')
    if type(p) is not list or len(p)!=len(cases):raise Invalid('incomplete Laya forecast census')
    seen=set(); summed=0.0
    for item in p:
        if (type(item) is not dict or set(item)!={'case_id','view_sha256','positive_probability','full_request_ms'}):
            raise Invalid('unexpected native prediction fields')
        c=item['case_id']
        prob=item['positive_probability'];t=item['full_request_ms']
        if (c in seen or c not in expected or item['view_sha256']!=expected[c] or
           type(prob) not in (float,int) or not math.isfinite(prob) or not 0<=prob<=1 or
           type(t) not in (float,int) or not math.isfinite(t) or t<=0):
            raise Invalid('invalid authentic source native prediction')
        seen.add(c);summed+=t
    if seen!=set(expected):raise Invalid('missing native source-paired forecast')
    for k in ('local_process_wall_ms','local_process_cpu_ms','local_peak_rss_bytes','model_load_ms'):
        v=model.get(k)
        if type(v) not in (float,int) or not math.isfinite(v) or v<=0:raise Invalid('native physical cost missing')
    if summed>model['local_process_wall_ms']+5 or model['model_load_ms']>model['local_process_wall_ms']+5:
        raise Invalid('native CPU timing impossible')
    return {'original_native_prediction_cases':len(seen),'native_nochange_Head_replay_possible':False,
            'independently_reexecuted_native_model':False,
            'numeric_task_quality_opened':False,
            'original_model_report_sha256':sha(canonical(model))}

def combined(fit,blind,laya,granite,gemma,mmbert_attempt):
    l=native_laya_census(fit,blind,laya)
    if (type(mmbert_attempt) is not dict or mmbert_attempt.get('model')!='mmbert_small' or
        mmbert_attempt.get('schema')!='hepta.p0.single-original-model-attempt.v10' or
        mmbert_attempt.get('outcome')!='failed_or_incomplete' or
        mmbert_attempt.get('authority')!='DENY_ALL' or
        mmbert_attempt.get('production_promotion_permitted') is not False):
        raise Invalid('original fourth arm must remain an explicit failure')
    base={'granite_97m_r2':granite,'embeddinggemma_2_text':gemma}
    for m,r in base.items():
        if (type(r) is not dict or r.get('source_github_run_id')!=RUN or
            r.get('source_head_sha')!=HEAD or r.get('source_model')!=m or
            r.get('model_revision')!=REVISIONS[m] or
            r.get('original_fit_sha256')!=sha(canonical(fit)) or
            r.get('original_blind_sha256')!=sha(canonical(blind)) or
            r.get('source_case_count')!=len(fit['cases'])+len(blind['cases']) or
            r.get('held_unlabeled_view_count')!=len(blind['cases']) or
            r.get('total_predictions_replayed')!=348 or
            r.get('original_human_held_labels_opened') is not False or
            r.get('original_checkpoint_freshly_reforwarded') is not False or
            r.get('production_promotion_permitted') is not False or
            r.get('complete_four_model_comparison_passed') is not False or
            r.get('authority')!='DENY_ALL'):
            raise Invalid('unqualified partial source/NumPy receipt')
    return {'schema':'hepta.p0.source-bound-three-of-four-partial-numeric-census.v1',
            'source_run_id':RUN,'source_head_sha':HEAD,
            'source_fit_sha256':sha(canonical(fit)),
            'source_blind_sha256':sha(canonical(blind)),
            'original_blind_case_count':len(blind['cases']),
            'observed':{'granite_97m_r2':{'status':'independent_archived_head_numeric_replay_consistent',
                            'replay_prediction_count':348,'max_abs_probability_error':max(x['maximum_absolute_probability_error'] for x in granite['numeric_replay'].values()),'independent_cold_pretrained_forward_verified':False},
                        'embeddinggemma_2_text':{'status':'independent_archived_head_numeric_replay_consistent',
                            'replay_prediction_count':348,'max_abs_probability_error':max(x['maximum_absolute_probability_error'] for x in gemma['numeric_replay'].values()),'independent_cold_pretrained_forward_verified':False},
                        'laya421_nochange':dict(status='native_prediction_census_only',**l),
                        'mmbert_small':{'status':'producer_failed_or_incomplete','has_original_prediction_report':False}},
            'original_held_human_labels_read':False,
            'full_original_four_model_population_admitted':False,
            'independent_original_human_semantic_score_run':False,
            'frozen_native_laya_equal_parameter_head_comparator':False,
            'independent_original_weight_publisher_signature_verified':False,
            'model_selected':False,'physical_cell_split_allowed':False,
            'final_use_authorized':False,'production_promotion_permitted':False,'authority':'DENY_ALL'}

def main():
    home=Path('/mnt/data')
    fit=source_file(home/'p0_multirc_fit_38868208650.zip','fit.json')
    blind=source_file(home/'p0_multirc_blind_38868208650.zip','blind.json')
    laya=source_file(home/'p0_laya_38868208650.zip','laya421_nochange.json')
    failure=source_file(home/'p0_mmbert_failed_38868208650.zip','attempt-mmbert_small.json')
    granite=json.loads((home/'hepta_p0_granite97_numeric_replay_38868208650.json').read_text())
    gemma=json.loads((home/'hepta_p0_gemma_independent_numeric_replay_38868208650.json').read_text())
    result=combined(fit,blind,laya,granite,gemma,failure)
    with (home/'hepta_p0_three_of_four_partial_replay_census_38868208650.json').open('xb') as f:
        f.write(canonical(result)+b'\n')
    print(json.dumps({'status':'partial', 'source_run_id':RUN,'models':{k:v['status'] for k,v in result['observed'].items()},'authority':'DENY_ALL'}))

if __name__=='__main__':main()
