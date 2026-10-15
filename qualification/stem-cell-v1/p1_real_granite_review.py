"""Independent stdlib original-source, prediction and complete-cost P1 reviewer.

Not a publisher signer, pretrained-forward attestor or model/Cell selector.
No PyTorch, model loader, training or producer import is allowed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat

SCHEMA='hepta.stem.p1-real-granite-physical-cohort.v1'
SCORE='hepta.stem.p1-real-granite-independent-score.v1'
MATERIAL='hepta.stem.p1-real-granite-material.v1'
PANEL_SHA='2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4'
REVISION='835ad14087e140460703cf0fae09f97d469d65c2'
MODEL='ibm-granite/granite-embedding-97m-multilingual-r2'
SIZES=(64,256,1024,4096)
MODES=('repeated4','test_panel','two_scopes')
COST_PHASES=('encoding_material_ms','head_quality_training_ms','baseline_requests_ms',
             'shared_requests_ms','physical_cell_training_ms','scoring_forward_ms')


def require(c,m):
    if not c:raise ValueError(m)


def canonical(v):
    return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,
                      allow_nan=False).encode('utf8')


def digest(x):return hashlib.sha256(canonical(x)).hexdigest()


def read_strict(path,limit=16*1024*1024):
    p=Path(path)
    fd=os.open(p,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    try:
        a=os.fstat(fd)
        require(stat.S_ISREG(a.st_mode) and 0<a.st_size<=limit,'bounded regular evidence required')
        with os.fdopen(fd,'rb',closefd=False) as f:raw=f.read(limit+1)
        b=os.fstat(fd)
        require(len(raw)==a.st_size and (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns)==
                (b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns),'evidence bytes changed during read')
    finally:os.close(fd)
    def pairs(items):
        out={}
        for k,v in items:
            require(k not in out,'duplicate source JSON key')
            out[k]=v
        return out
    try:
        return json.loads(raw,object_pairs_hook=pairs,
                  parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite number')))
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise ValueError('malformed source evidence') from exc


def validate_original(panel,training,blind,owner):
    require(isinstance(panel,dict) and digest(panel)==PANEL_SHA,
            'real public AG News panel original 224-case bytes must match pinned digest')
    rows=panel.get('cases')
    require(type(rows) is list and len(rows)==224,'original source panel census')
    expected_train=[];expected_eval=[];expected_labels=[]
    seen=set();counts={'train':0,'calibration':0,'test':0}
    for c in rows:
        require(type(c) is dict and all(k in c for k in
                ('case_id','group_id','split','joint_input','joint_input_digest','label')),
                'source publisher row fields incomplete')
        part=c['split'];require(part in counts,'source split unknown')
        counts[part]+=1
        state=c['joint_input'].get('state')
        require(type(state) is str and state and
              hashlib.sha256(state.encode('utf8')).hexdigest()==c['group_id']
              and c['case_id']==c['group_id'][:24]
              and digest(c['joint_input'])==c['joint_input_digest']
              and c['group_id'] not in seen
              and type(c['label']) is int and c['label'] in (0,1),
              'invalid real source/label identity or duplicate group')
        seen.add(c['group_id'])
        item={k:c[k] for k in ('case_id','group_id','split','joint_input','joint_input_digest')}
        if part=='train':item['label']=c['label'];expected_train.append(item)
        else:
            expected_eval.append(item)
            expected_labels.append(dict(case_id=c['case_id'],split=part,label=c['label']))
    require(counts=={'train':128,'calibration':32,'test':64},'original source partition size drift')
    for doc,role,expected in ((training,'train_labels_only',expected_train),
                               (blind,'blind_calibration_and_test',expected_eval)):
        require(type(doc) is dict and doc.get('schema')==MATERIAL
                and doc.get('panel_sha256')==PANEL_SHA
                and doc.get('source_is_cross_sectional_not_future') is True
                and doc.get('source_origin_independently_signed') is False
                and doc.get('model_revision')==REVISION
                and doc.get('role')==role
                and doc.get('rows')==expected
                and doc.get('seal_id')==digest({k:v for k,v in doc.items() if k!='seal_id'}),
                'training/eval material differs from pinned real original publisher source')
    require(type(owner) is dict and owner.get('schema')==MATERIAL+'.labels'
            and owner.get('panel_sha256')==PANEL_SHA
            and owner.get('independent_observer_authenticated') is False
            and owner.get('rows')==expected_labels
            and owner.get('seal_id')==digest({k:v for k,v in owner.items() if k!='seal_id'}),
            'original publicly labeled eval source was changed after predictions')
    return expected_labels


def _metrics(rows,labels):
    require(len(rows)==len(labels)==96,'complete original heldout census')
    correct=0;brier=0.0;paired=[]
    for item,label in zip(rows,labels,strict=True):
        require(type(item) is dict and set(item)=={
            'case_id','group_id','split','joint_input_digest','positive_probability'},
            'exact frozen/learned numeric prediction schema required')
        require(item['case_id']==label['case_id'] and item['split']==label['split']
                and type(item['positive_probability']) is float
                and math.isfinite(item['positive_probability'])
                and 0<=item['positive_probability']<=1,
                'missing/altered original label or bad probability')
        p=item['positive_probability'];y=label['label']
        correct+=int((p>=0.5)==bool(y));brier+=(p-y)**2
        paired.append(int((p>=0.5)==bool(y)))
    return dict(correct=correct,total=len(rows),accuracy=correct/len(rows),
                binary_brier=brier/len(rows)),paired


def review_public(panel,training,blind,owner,observations):
    gold=validate_original(panel,training,blind,owner)
    require(type(observations) is list and 1<=len(observations)<=14,
            'nonempty bounded cohort comparison')
    census=set();summaries={}
    blind_rows=blind['rows']
    for r in observations:
        require(type(r) is dict and r.get('schema')==SCHEMA
                and r.get('report_sha256')==digest({k:v for k,v in r.items() if k!='report_sha256'})
                and r.get('panel_sha256')==PANEL_SHA and r.get('model')==MODEL
                and r.get('model_revision')==REVISION and r.get('authority')=='DENY_ALL'
                and r.get('production_promotion_permitted') is False,
                'incorrect exact frozen source/unsupported admission')
        for k in ('model_origin_independently_authenticated',
                  'source_origin_independently_authenticated',
                  'pretrained_forward_count_independently_attested',
                  'true_prospective_future_evaluation',
                  'independent_reader_evidence_sufficiency',
                  'complete_worker_signed_final_use','quality_superiority_established'):
            require(r.get(k) is False,f'unsupported {k} claim')
        require(r.get('no_claim_of_general_reasoning') is True and
                type(r.get('pretrained_weight_execution_claimed')) is bool,
                'no general reasoning or unsupported model mode')
        n=r.get('cohort_logical_cells');k=r.get('active_cells');mode=r.get('mode')
        require(type(n) is int and n in SIZES and type(k) is int and k==max(8,n//10)
                and mode in MODES and r.get('head_per_cell_parameters')==9744
                and r.get('head_parameter_count')==n*9744
                and r.get('resident_head_tensor_bytes')==n*9744*4,
                'real sparse physically-resident Cell capacity mismatch')
        slot=(n,mode,r.get('cache_budget_bytes'))
        require(slot not in census,'duplicate experimental cohort')
        census.add(slot)
        expected_src=min(k,4 if mode!='test_panel' else 64)
        scoped=(8 if mode=='two_scopes' else expected_src)
        require(r.get('complete_actual_pretrained_api_calls')==224+r['baseline']['physical_model_api_calls']+r['shared']['physical_model_api_calls']
                and r.get('matched_baseline_total_api_calls')==224+r['baseline']['physical_model_api_calls']
                and r.get('matched_shared_total_api_calls')==224+r['shared']['physical_model_api_calls']
                and r.get('process_wall_excludes_model_load') is True
                and r.get('decoder_generation_executed') is False
                and r.get('real_421m_copy_control_executed') is False
                and r.get('model_cpu_runtime_order_control_matched') is False,
                'unaccounted model materialization or false all-lifecycle/production equivalence')
        require(r.get('source_group_count')==expected_src
                and r.get('unique_scoped_source_count')==scoped
                and r.get('complete_real_source_material_calls')==224
                and r.get('per_use_research_access_hook_count')==2*k,
                'incorrect real source diversity or per-use access count')
        require(type(r.get('model_parameter_count')) is int and r['model_parameter_count']>0
                and type(r.get('frozen_model_tensor_sha256')) is str
                and len(r['frozen_model_tensor_sha256'])==64
                and r.get('model_unchanged_after_cell_fit') is True,
                'selected actual frozen pretrained weights were not retained')
        if r['pretrained_weight_execution_claimed']:
            require(r['model_parameter_count']>=90_000_000,'fabricated real 97M model size')
        for kind in ('baseline','shared'):
            met=r.get(kind)
            require(type(met) is dict and met.get('logical_head_uses')==k
                    and type(met.get('physical_model_api_calls')) is int
                    and type(met.get('cache_hits')) is int
                    and met['physical_model_api_calls']>=0 and met['cache_hits']>=0
                    and met['physical_model_api_calls']+met['cache_hits']==k
                    and type(met.get('request_batch_wall_ns')) is int
                    and met['request_batch_wall_ns']>0,
                    'measured physical pretrained Encoder request census invalid')
        require(r['baseline']['physical_model_api_calls']==k
                and r['baseline']['cache_hits']==0
                and r['shared']['unique_scoped_input_keys']==scoped
                and r['shared']['physical_cache_payload_peak_bytes']<=r['cache_budget_bytes'],
                'falsified unshared/cached original request control')
        if r['cache_budget_bytes']==0:
            require(r['shared']['physical_model_api_calls']==k
                    and r['shared']['cache_hits']==0,'no-cache negative control must be admitted')
        if r['cache_budget_bytes']>=scoped*384*4:
            require(r['shared']['physical_model_api_calls']==scoped
                    and r['shared']['cache_hits']==k-scoped,
                    'full feature residency must reuse the exact scoped input keys')
        for k2 in ('frozen_head_max_unpacked_abs_error','learned_head_max_unpacked_abs_error'):
            require(type(r.get(k2)) is float and 0<=r[k2]<=1e-5,
                    'separately unpacked native FP32 Head numeric replay invalid')
        stage=r.get('local_cell_train')
        require(type(stage) is dict and stage.get('dormant_weights_byte_identical') is True
                and stage.get('training_steps') in range(2,9)
                and stage.get('trainable_active_parameters')==k*9744
                and stage.get('training_examples')==k*stage['training_steps']
                and type(stage.get('physically_changed_active_scalars')) is int
                and 0<stage['physically_changed_active_scalars']<=k*9744,
                'inactive trained Cell or fake sparse local SGD')
        phases=r.get('cost_phases_ms')
        require(type(phases) is dict and set(phases)==set(COST_PHASES)
                and all(type(v) is float and math.isfinite(v) and v>0 for v in phases.values())
                and type(r.get('entire_process_wall_ms')) is float
                and r['entire_process_wall_ms']>0
                and sum(phases.values())<=r['entire_process_wall_ms']+5,
                'incomplete/double-counted physical source and Cell cost phase')
        require(type(r.get('lifetime_peak_process_rss_bytes')) is int
                and r['lifetime_peak_process_rss_bytes']>=r['resident_head_tensor_bytes'],
                'full population memory cannot be below actual resident FP32 Head payload')
        probes=r.get('quality_probes')
        require(type(probes) is dict and set(probes)=={'no_change','trained'},
                'matched frozen and real-label Head comparator missing')
        result={}
        for arm in ('no_change','trained'):
            control=probes[arm]
            require(type(control) is dict and control.get('parameter_count')==770
                    and type(control.get('weights_sha256')) is str
                    and len(control['weights_sha256'])==64,
                    'unmatched or altered genuine binary Head parameter budget')
            preds=control.get('rows')
            require(type(preds) is list and len(preds)==96,
                    'incomplete original calibration/test reader predictions')
            for p,source in zip(preds,blind_rows,strict=True):
                require(p['case_id']==source['case_id'] and
                        p['group_id']==source['group_id'] and
                        p['joint_input_digest']==source['joint_input_digest'],
                        'original source attribution differs from recorded prediction')
            res,correctness=_metrics(preds,gold)
            result[arm]=dict(**res,calibration_count=32,test_count=64)
            result['_'+arm]=correctness
        a=result.pop('_trained');b=result.pop('_no_change')
        result['paired_recovered']=sum(x and not y for x,y in zip(a,b))
        result['paired_lost']=sum(y and not x for x,y in zip(a,b))
        result['accuracy_delta_descriptive']=(result['paired_recovered']-result['paired_lost'])/96
        summaries[f'{n}:{mode}:{r["cache_budget_bytes"]}']=dict(
            cases_scored=96,unique_source_groups=96,models={'source_pretrained_claimed':r['pretrained_weight_execution_claimed'],
            'parameters':r['model_parameter_count'],'tensor_digest':r['frozen_model_tensor_sha256']},
            quality=result,cost_phases_ms=phases,
            measured_no_cache_model_calls=r['baseline']['physical_model_api_calls'],
            measured_cache_model_calls=r['shared']['physical_model_api_calls'],
            full_lifecycle_cost_independently_authenticated=False)
    return dict(schema=SCORE,models=summaries,studies=len(summaries),
       actual_independent_observed_future_task_groups=0,
       retrospective_public_calibration_and_test=True,
       independent_source_label_publisher_signature_verified=False,
       independent_pretrained_model_origin_verified=False,
       independent_hardware_forward_counter_verified=False,
       complete_native_worker_cost_verified=False,
       statistical_model_winner_selected=False,capacity_compression_10t_or_100t_established=False,
       real_text_to_image_video_audio_generation_verified=False,
       production_promotion_permitted=False,authority='DENY_ALL')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original-panel',required=True)
    p.add_argument('--train-material',required=True)
    p.add_argument('--blind-material',required=True)
    p.add_argument('--owner-labels',required=True)
    p.add_argument('--report',required=True,nargs='+')
    p.add_argument('--output',required=True)
    a=p.parse_args()
    report=review_public(read_strict(a.original_panel),read_strict(a.train_material),
                         read_strict(a.blind_material),read_strict(a.owner_labels),
                         [read_strict(path) for path in a.report])
    with Path(a.output).open('x',encoding='utf8') as f:
        json.dump(report,f,allow_nan=False,sort_keys=True,indent=2);f.write('\n')

if __name__=='__main__':main()
