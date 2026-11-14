#!/usr/bin/env python3
"""Independent read-only P0 Granite97 *partial* numeric replay on unscored original inputs.

No owner-only held labels are opened. Proof is limited to consistency of
archived feature/Head tensors and the original producer forecast; NOT fresh
model inference, checkpoint publisher authentication, independent human score
or permission to choose a Stem. Research only; always DENY_ALL.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile
import numpy as np
from safetensors.numpy import load as safetensors_load

MODEL = 'granite_97m_r2'
REVISION = '835ad14087e140460703cf0fae09f97d469d65c2'
SCHEMA = 'hepta.p0.partial-original-granite-local-independent-numeric-replay.v1'
TOLERANCE = 3e-5
HEADS = ('evidence_frozen','evidence_trained','question_frozen','question_trained')

class Invalid(ValueError):
    pass


def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode('utf-8')

def sha_bytes(x):
    return hashlib.sha256(x).hexdigest()

def sha_doc(x):
    return sha_bytes(canonical(x))

def get_zip_blob(path,name,max_bytes=2_000_000):
    with zipfile.ZipFile(path,'r') as arc:
        entries=arc.infolist()
        if len(entries)>32 or len({f.filename for f in entries})!=len(entries):
            raise Invalid('unbounded or duplicate artifact entries')
        member=arc.getinfo(name)
        if member.file_size>max_bytes or member.file_size<=0:
            raise Invalid('unbounded original artifact')
        return arc.read(member)

def strict_pairs(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise Invalid('duplicate artifact JSON key')
        result[k]=v
    return result

def read_json(bytes_):
    return json.loads(bytes_,object_pairs_hook=strict_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(Invalid('nonfinite JSON')))

def load_arm_weights(raw):
    archive=safetensors_load(raw)
    required={f'{head}.{param}' for head in HEADS for param in ('weight','bias')}
    if set(archive)!=required:raise Invalid('missing/extra head tensor')
    for h in HEADS:
        for param,shape in [('weight',(2,384)),('bias',(2,))]:
            a=archive[f'{h}.{param}']
            if a.dtype!=np.float32 or a.shape!=shape or not np.isfinite(a).all():
                raise Invalid('invalid head tensor geometry')
    return archive

def head_sha(weights,head):
    h=hashlib.sha256(b'hepta.p0-reader-head-f32.v1')
    for k in ('bias','weight'):
        h.update(k.encode()+b'\x00'+weights[f'{head}.{k}'].tobytes(order='C'))
    return h.hexdigest()

def probability(x,weights,head,tau):
    if type(tau) not in (int,float) or not math.isfinite(tau) or tau<=0:
        raise Invalid('unregistered calibration temperature')
    w,b=weights[f'{head}.weight'],weights[f'{head}.bias']
    logits=(w@x.astype(np.float32)+b).astype(np.float64)/tau
    logits-=logits.max()
    values=np.exp(logits)
    return float(values[1]/values.sum())

def evaluate(fit,blind,report,manifest,feature_bytes,weight_bytes):
    if (fit.get('metadata')!=blind.get('metadata') or
            type(fit.get('cases')) is not list or type(blind.get('cases')) is not list or
            any('label' in row for row in blind['cases'])):
        raise Invalid('original fit/blind identity or label leakage')
    if (manifest.get('schema')!='hepta.p0.multirc-original-feature-head-numeric-replay.v1' or
            manifest.get('model')!=MODEL or manifest.get('revision')!=REVISION or
            manifest.get('width')!=384 or manifest.get('authority')!='DENY_ALL' or
            manifest.get('production_promotion_permitted') is not False or
            manifest.get('physical_origin_independently_signed') is not False or
            manifest.get('original_human_held_labels_included') is not False or
            manifest.get('actual_pretrained_encoder_recomputed_by_reviewer') is not False):
        raise Invalid('invalid original physical weight manifest boundaries')
    if (report.get('model')!=MODEL or report.get('model_revision')!=REVISION or
            report.get('feature_width')!=384 or
            report.get('panel_id')!=fit['metadata'].get('panel_id') or
            report.get('fit_material_sha256')!=sha_doc(fit) or
            report.get('blind_material_sha256')!=sha_doc(blind) or
            report.get('schema')!='hepta.p0.multirc-original-semantic-physical.v1' or
            report.get('actual_pretrained_local_weights_claimed') is not True or
            report.get('authority')!='DENY_ALL' or
            report.get('production_promotion_permitted') is not False or
            report.get('physical_model_origin_independently_signed') is not False):
        raise Invalid('invalid original model execution report')
    ids=[x['case_id'] for x in fit['cases']+blind['cases']]
    if (len(ids)!=len(set(ids)) or ids!=manifest.get('case_ids_in_original_fit_then_blind_order') or
            len(blind['cases'])!=report.get('eval_blind_rows')):
        raise Invalid('original FIT/BLIND identity census mismatch')
    identities={k:sha_doc(v) for k,v in [('fit',fit),('blind',blind),('report',report)]}
    for key,expected in [('fit_sha256',identities['fit']),('blind_sha256',identities['blind']),
                         ('physical_prediction_report_sha256',identities['report']),
                         ('features_safetensors_sha256',sha_bytes(feature_bytes)),
                         ('head_weights_safetensors_sha256',sha_bytes(weight_bytes))]:
        if manifest.get(key)!=expected:raise Invalid('original committed byte identity mismatch '+key)
    feats=safetensors_load(feature_bytes)
    if set(feats)!={'features_q24_fp32'}:raise Invalid('not original registered feature tensor')
    matrix=feats['features_q24_fp32']
    if (matrix.dtype!=np.float32 or matrix.shape!=(len(ids),384)
            or not np.isfinite(matrix).all() or (np.abs(matrix)>8).any()):
        raise Invalid('invalid pretrained feature tensor bank')
    matrix_byid=dict(zip(ids,matrix))
    weights=load_arm_weights(weight_bytes)
    for h in HEADS:
        if manifest.get('four_head_tensor_sha256',{}).get(h)!=head_sha(weights,h):
            raise Invalid('mismatch between actual FP32 Head and committed lineage')
    if manifest['four_head_tensor_sha256']['evidence_frozen']!=manifest['four_head_tensor_sha256']['question_frozen']:
        raise Invalid('different original Head initialization')
    if manifest['four_head_tensor_sha256']['evidence_frozen']==manifest['four_head_tensor_sha256']['evidence_trained']:
        raise Invalid('original evidence Head lacks physical training update')
    if manifest['four_head_tensor_sha256']['question_frozen']==manifest['four_head_tensor_sha256']['question_trained']:
        raise Invalid('original question-only Head lacks physical training update')
    byid={x['case_id']:x for x in blind['cases']}
    bytask={}
    for r in blind['cases']:
        key=(r['source_group'],r['question_id'],r['answer_id'])
        d=bytask.setdefault(key,{})
        if r['condition'] in d:raise Invalid('duplicate original/no-evidence condition')
        d[r['condition']]=r
    if any(set(d)!={'original','no_evidence'} for d in bytask.values()):
        raise Invalid('original and no-evidence control pairing incomplete')
    prior_original={d['no_evidence']['case_id']:d['original']['case_id'] for d in bytask.values()}
    frozen=report['control'];prior=report['matched_question_only_control']['complete_prior_controls']
    all_result={}
    for h,entry,ids_expected,paired in [
        ('evidence_frozen',frozen['frozen_head'],set(byid),None),
        ('evidence_trained',frozen['trained_head'],set(byid),None),
        ('question_frozen',prior['question_frozen_head'],set(prior_original),prior_original),
        ('question_trained',prior['question_trained_head'],set(prior_original),prior_original)]:
        if (entry.get('head_sha256')!=manifest['four_head_tensor_sha256'][h]
                or type(entry.get('temperature')) not in (int,float)):
            raise Invalid('bad physical Head/temperature lineage')
        else: expected_pair=None
        max_error=0.0;seen=set();field=('no_evidence_case_id' if paired is not None else 'case_id')
        predictions=entry.get('predictions')
        if type(predictions) is not list or len(predictions)!=len(ids_expected):raise Invalid('missing original predictions')
        for item in predictions:
            cid=item.get(field)
            if cid in seen or cid not in ids_expected:raise Invalid('duplicate/missing record')
            seen.add(cid)
            if paired is None:
                if item.get('view_sha256')!=byid[cid]['view_sha256']:raise Invalid('wrong original view')
            else:
                if (item.get('no_evidence_view_sha256')!=byid[cid]['view_sha256']
                        or item.get('original_case_id')!=paired[cid]):raise Invalid('wrong paired human target identity')
            observed=item.get('positive_probability')
            if type(observed) not in (int,float) or not math.isfinite(observed) or not 0<=observed<=1:
                raise Invalid('invalid original probability')
            expected=probability(matrix_byid[cid],weights,h,entry['temperature'])
            error=abs(expected-observed)
            if error>TOLERANCE:raise Invalid('original forecast fails independent NumPy replay')
            max_error=max(max_error,error)
        if seen!=ids_expected:raise Invalid('incomplete original Head prediction census')
        all_result[h]={'checked':len(predictions),'maximum_absolute_probability_error':max_error}
    return {'schema':SCHEMA,'source_github_run_id':38868208650,
            'source_head_sha':'09e5d4806c166586ba18b2ac87f75034fecd6687',
            'source_model':MODEL,'model_revision':REVISION,
            'source_case_count':len(ids),'held_unlabeled_view_count':len(blind['cases']),
            'numeric_replay':all_result,'total_predictions_replayed':sum(v['checked'] for v in all_result.values()),
            'original_fit_sha256':identities['fit'],'original_blind_sha256':identities['blind'],
            'original_physical_report_sha256':identities['report'],
            'features_safetensors_sha256':sha_bytes(feature_bytes),
            'head_weights_safetensors_sha256':sha_bytes(weight_bytes),
            'tolerance':TOLERANCE,
            'original_checkpoint_freshly_reforwarded':False,
            'independently_authenticated_pretrained_origin':False,
            'original_human_held_labels_opened':False,
            'future_time_windows_or_negative_transfer_verified':False,
            'complete_four_model_comparison_passed':False,
            'physical_prod_final_use_allowed':False,
            'stem_selected':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fit',type=Path,required=True)
    ap.add_argument('--blind',type=Path,required=True)
    ap.add_argument('--model-artifact',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    fit=read_json(get_zip_blob(args.fit,'fit.json'))
    blind=read_json(get_zip_blob(args.blind,'blind.json'))
    z=args.model_artifact
    report=read_json(get_zip_blob(z,'granite_97m_r2.json'))
    manifest=read_json(get_zip_blob(z,'granite_97m_r2.replay/COMMITTED.json'))
    f_bytes=get_zip_blob(z,'granite_97m_r2.replay/features.safetensors',max_bytes=20_000_000)
    w_bytes=get_zip_blob(z,'granite_97m_r2.replay/heads.safetensors')
    outcome=evaluate(fit,blind,report,manifest,f_bytes,w_bytes)
    if args.output.exists():raise FileExistsError('write-once independent original replay')
    with args.output.open('xb') as fd:
        fd.write(canonical(outcome)+b'\n')
    print(json.dumps({'total_predictions_replayed':outcome['total_predictions_replayed'],
                      'maximum_probability_error':max(v['maximum_absolute_probability_error'] for v in outcome['numeric_replay'].values()),
                      'production_promotion_permitted':False,'authority':'DENY_ALL'},sort_keys=True))

if __name__=='__main__':main()
