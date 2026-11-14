#!/usr/bin/env python3
"""Read-only independent NumPy parity check on P0 V13 original two extant archives.

No pretrained model download, checkpoint loading, source labels, fake study arm
or production selection. NOT a publication origin attestation. The original
human-label source/replay V5/V6/V7 still gates all four model qualification.
"""
from __future__ import annotations
import hashlib, json, math, zipfile
from pathlib import Path
import numpy as np
from safetensors.numpy import load

ROOT=Path('/mnt/data')
ORIGINAL_RUN=38744510538
ARM_PATHS={
    'granite_97m_r2':ROOT/'github-actions-artifact-12024752241.zip',
    'embeddinggemma_2_text':ROOT/'github-actions-artifact-12024478947.zip',
}


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,
                      allow_nan=False).encode()


def sha(x):return hashlib.sha256(x).hexdigest()


def check(actual,expected,name):
    if actual!=expected:raise ValueError(f'mismatch in {name}: {actual} vs {expected}')


def head_checksum(ww,prefix):
    h=hashlib.sha256(b'hepta.p0-reader-head-f32.v1')
    for field in ('bias','weight'):
        x=ww[prefix+'.'+field]
        if x.dtype!=np.dtype('float32'):raise ValueError('head dtype')
        h.update(field.encode()+b'\0'+x.tobytes(order='C'))
    return h.hexdigest()


def softmax_numpy(row,heads,prefix,temp):
    if type(temp) not in (int,float) or not math.isfinite(temp) or temp<=0:
        raise ValueError('temperature missing')
    w=heads[prefix+'.weight'];b=heads[prefix+'.bias']
    logit=(w@row.astype(np.float32)+b).astype(np.float64)/temp
    logit-=logit.max();e=np.exp(logit);return float(e[1]/sum(e))


def verify(model,archive,fit,blind):
    with zipfile.ZipFile(archive) as z:
        names=set(z.namelist())
        required={model+'.json',model+'.replay/COMMITTED.json',
                  model+'.replay/features.safetensors',model+'.replay/heads.safetensors',
                  'attempt-'+model+'.json'}
        if not required.issubset(names):raise ValueError('partial original artifact inventory')
        result=json.loads(z.read(model+'.json'))
        meta=json.loads(z.read(model+'.replay/COMMITTED.json'))
        att=json.loads(z.read('attempt-'+model+'.json'))
        if att['outcome']!='model_report_written' or att['authority']!='DENY_ALL':
            raise ValueError('not an original accepted model report')
        feat_bytes=z.read(model+'.replay/features.safetensors')
        head_bytes=z.read(model+'.replay/heads.safetensors')
        check(sha(feat_bytes),meta['features_safetensors_sha256'],'feature archive')
        check(sha(head_bytes),meta['head_weights_safetensors_sha256'],'head archive')
        check(sha(canonical(result)),meta['physical_prediction_report_sha256'],'producer')
        check(sha(canonical(fit)),meta['fit_sha256'],'fit')
        check(sha(canonical(blind)),meta['blind_sha256'],'blind')
        check(result['model'],model,'model')
        check(result['authority'],'DENY_ALL','result authority')
        if result['production_promotion_permitted'] is not False:
            raise ValueError('false original success authority')
        ordered=fit['cases']+blind['cases']
        ids=[r['case_id'] for r in ordered]
        check(ids,meta['case_ids_in_original_fit_then_blind_order'],'ordered case identities')
        x=load(feat_bytes)['features_q24_fp32'];h=load(head_bytes)
        width=meta['width']
        if x.shape!=(len(ids),width) or x.dtype!=np.float32 or not np.isfinite(x).all():
            raise ValueError('invalid feature tensor shape')
        prefixes=['evidence_frozen','evidence_trained','question_frozen','question_trained']
        for prefix in prefixes:
            check(head_checksum(h,prefix),meta['four_head_tensor_sha256'][prefix],prefix+' actual Head tensor digest')
        view={cid:feature for cid,feature in zip(ids,x)}
        blind_cases={r['case_id']:r for r in blind['cases']}
        original_rows={r['case_id']:r for r in blind['cases'] if r['condition']=='original'}
        paired={r['case_id']:r for r in blind['cases'] if r['condition']=='no_evidence'}
        try:
            from p0_question_only_head import matched_pairs
        except ImportError:
            # Validate original/no-evidence task ancestry without importing
            # the model producer/trainer: match split, question and answer.
            by_key={}
            for r in blind['cases']:
                k=(r['split'],r['source_group'],r['question_id'],r['answer_id'])
                by_key.setdefault(k,{})[r['condition']]=r
            for k,d in by_key.items():
                if set(d)!={'original','no_evidence'}:raise ValueError('not a task pair')
            no_evidence_to_original={d['no_evidence']['case_id']:d['original']['case_id'] for d in by_key.values()}
        else:
            # Optional if full original source modules are installed.
            no_evidence_to_original={p['case_id']:o['case_id'] for o,p in matched_pairs(fit,blind)['test']}
        controls={
            'evidence_frozen':result['control']['frozen_head'],
            'evidence_trained':result['control']['trained_head'],
            'question_frozen':result['matched_question_only_control']['complete_prior_controls']['question_frozen_head'],
            'question_trained':result['matched_question_only_control']['complete_prior_controls']['question_trained_head']
        }
        output={};overall=0.0
        for prefix,arm in controls.items():
            predictions=arm['predictions'];errs=[];seen=set()
            for p in predictions:
                cid=p['case_id'] if prefix.startswith('evidence_') else p['no_evidence_case_id']
                if cid in seen:raise ValueError('duplicate prediction')
                seen.add(cid)
                if cid not in blind_cases: raise ValueError('foreign model input')
                source=blind_cases[cid]
                if prefix.startswith('evidence_'):
                    check(p['view_sha256'],source['view_sha256'],'same evidence task view')
                else:
                    check(p['original_case_id'],no_evidence_to_original[cid],'question-only parent')
                    check(p['no_evidence_view_sha256'],source['view_sha256'],'same no-evidence view')
                expected=softmax_numpy(view[cid],h,prefix,arm['temperature'])
                err=abs(expected-p['positive_probability'])
                if err>3e-5:raise ValueError('original prediction exceeds independent FP32 replay tolerance')
                errs.append(err)
            check(seen,set(blind_cases if prefix.startswith('evidence_') else paired),'complete prediction case census')
            output[prefix]={'replayed_blind_predictions':len(predictions),
                            'maximum_absolute_probability_difference':max(errs),
                            'mean_absolute_probability_difference':sum(errs)/len(errs),
                            'head_bytes_sha256_verified':True}
            overall=max(overall,max(errs))
        return {'model':model,'run_id':ORIGINAL_RUN,'candidate_source_sha':'89a3f1606bd0fa4d7dd8214bd4eb3c64b43c7b97',
                'all_four_arms_checked':True,'original_fit_cases':len(fit['cases']),
                'original_blind_cases':len(blind['cases']),
                'evidence_types':output,
                'maximum_absolute_prediction_error':overall,
                'original_HF_publisher_signature_independently_verified':False,
                'actual_pretrained_reencoded_by_independent_host':False,
                'training_gradient_history_independently_replayed':False,
                'original_held_human_labels_accessed':False,
                'four_model_full_qualification':False,
                'model_selected':False,'production_promotion_permitted':False,
                'authority':'DENY_ALL'}


def main():
    with zipfile.ZipFile(ROOT/'github-actions-artifact-12016706648.zip') as z:
        fit=json.loads(z.read('fit.json'))
    with zipfile.ZipFile(ROOT/'github-actions-artifact-12016552240.zip') as z:
        blind=json.loads(z.read('blind.json'))
    d={'schema':'hepta.p0.v13.partial-prelabel-numeric-replay-untrusted-publisher.v1',
       'source_run_id':ORIGINAL_RUN,
       'model_results':{m:verify(m,p,fit,blind) for m,p in ARM_PATHS.items()},
       'other_two_models_failed':['mmbert_small','laya421_nochange'],
       'independent_human_scoring':False,
       'full_four_model_qualification':False,
       'production_promotion_permitted':False,'authority':'DENY_ALL'}
    target=ROOT/'hepta_p0_v13_two_model_numeric_replay_20261016.json'
    target.write_bytes(canonical(d)+b'\n')
    print(json.dumps({m:{'cases':r['original_blind_cases'],'max_err':r['maximum_absolute_prediction_error']} for m,r in d['model_results'].items()},indent=2))
    print(target)

if __name__=='__main__':main()
