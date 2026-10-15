#!/usr/bin/env python3
"""Bounded CPU-only independent replay of P0 frozen-Encoder Head predictions.

A source-locked model process writes immutable FP32 feature and four trained/frozen
Head tensors, never original held evaluation labels. A DIFFERENT process checks
byte digests, dimensions, tensor lineage, complete case identity, then recomputes
all held probabilities using NumPy instead of trusting report probabilities.

This is self-consistency, not a signature, independent model origin, certified
training history, semantic accuracy, future generalization or FinalUse authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import resource
import time
from pathlib import Path
import stat

from p0_multirc_semantic_material import Invalid, canonical, read, sha, validate
from p0_multirc_semantic_review import REVISIONS
from p0_question_only_head import matched_pairs

SCHEMA = 'hepta.p0.multirc-original-feature-head-numeric-replay.v1'
MODEL_WIDTHS = {'granite_97m_r2': 384, 'mmbert_small': 384,
                'embeddinggemma_2_text': 256}
HEADS = ('evidence_frozen', 'evidence_trained',
         'question_frozen', 'question_trained')
MAX_CASES = 1024
MAX_BYTES = 16 * 1024 * 1024
TOLERANCE = 3e-5  # CPU BLAS FP32 versus independent NumPy arithmetic, not bit identity


def _hash_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _ensure_hash(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise Invalid('bad fixed-identity hex digest')
    return value


def _safe_tensor_bytes(directory, name):
    path = Path(directory) / name
    if path.is_symlink() or not path.is_file():
        raise Invalid('missing/symlinked untrusted tensor archive')
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or not 64 <= metadata.st_size <= MAX_BYTES:
        raise Invalid('oversized or missing bounded original tensor archive')
    return path.read_bytes()


def _control_sha(weights, name):
    import numpy as np
    h = hashlib.sha256(b'hepta.p0-reader-head-f32.v1')
    for key in ('bias', 'weight'):
        array = weights[f'{name}.{key}']
        if array.dtype != np.dtype('float32') or not array.flags.c_contiguous:
            raise Invalid('invalid original Head FP32 tensor dtype')
        h.update(key.encode() + b'\0' + array.tobytes(order='C'))
    return h.hexdigest()


def _checked_tensors(matrix, heads, ids, width):
    import numpy as np
    if (set(matrix) != {'features_q24_fp32'} or
            matrix['features_q24_fp32'].dtype != np.dtype('float32') or
            matrix['features_q24_fp32'].shape != (len(ids), width) or
            set(heads) != {f'{prefix}.{field}' for prefix in HEADS for field in ('weight', 'bias')}):
        raise Invalid('noncanonical original feature/Head tensor inventory')
    x = matrix['features_q24_fp32']
    if not bool(np.isfinite(x).all()) or bool((np.abs(x)>8).any()):
        raise Invalid('nonfinite/overrange imported shared Encoder features')
    # Initial effective head and trained gradients must be unaliased, finite and physically present.
    for prefix in HEADS:
        for field,shape in (('weight',(2,width)), ('bias',(2,))):
            a=heads[f'{prefix}.{field}']
            if a.dtype != np.dtype('float32') or a.shape != shape or not bool(np.isfinite(a).all()):
                raise Invalid('not an actual correctly-shaped finite FP32 Head')
    return x


def _manifest(fit, blind, report, model, feature_rows, head_tensors, feature_sha, head_sha):
    width = MODEL_WIDTHS[model]
    ordered = fit['cases'] + blind['cases']
    ids = [r['case_id'] for r in ordered]
    if len(ids)!=len(set(ids)) or not 1<=len(ids)<=MAX_CASES or set(feature_rows)!={'__packed_matrix__'}:
        raise Invalid('duplicate, missing or unbounded physical feature rows')
    if not isinstance(head_tensors, dict):
        raise Invalid('no original physical Head weight snapshots')
    _checked_tensors({'features_q24_fp32':feature_rows['__packed_matrix__']},head_tensors,ids,width)
    heads = head_tensors
    # A report may come from a research worker; the independent reviewer still
    # cross-checks original immutable HEAD hashes and no-effect disposition.
    old, matched = report.get('control'),report.get('matched_question_only_control')
    if type(old) is not dict or type(matched) is not dict:
        raise Invalid('missing actual trained-versus-frozen evidence/prior baselines')
    checks = {
        'evidence_frozen': old['frozen_head']['head_sha256'],
        'evidence_trained': old['trained_head']['head_sha256'],
        'question_frozen': matched['complete_prior_controls']['question_frozen_head']['head_sha256'],
        'question_trained': matched['complete_prior_controls']['question_trained_head']['head_sha256']}
    for name in HEADS:
        if _control_sha(heads,name) != _ensure_hash(checks[name]):
            raise Invalid('serialized Head does not equal the original trained tensor digest')
    if checks['evidence_frozen'] != checks['question_frozen']:
        raise Invalid('initially matched Heads differ physically')
    if (checks['evidence_frozen']==checks['evidence_trained'] or
            checks['question_frozen']==checks['question_trained']):
        raise Invalid('claimed learning without changed FP32 parameter tensors')
    return {
        'schema': SCHEMA,
        'model':model,'revision':REVISIONS[model], 'width':width,
        'frozen_model_encoder_loaded_only_once':True,
        'case_ids_in_original_fit_then_blind_order':ids,
        'fit_sha256':sha(canonical(fit)),
        'blind_sha256':sha(canonical(blind)),
        'physical_prediction_report_sha256':sha(canonical(report)),
        'features_safetensors_sha256':feature_sha,
        'head_weights_safetensors_sha256':head_sha,
        'four_head_tensor_sha256':checks,
        'original_human_held_labels_included':False,
        'physical_origin_independently_signed':False,
        'actual_pretrained_encoder_recomputed_by_reviewer':False,
        'independent_reviewer_did_not_retrain_heads':True,
        'production_promotion_permitted':False,'authority':'DENY_ALL'}


def capture_head_tensors(slot, prefix, module):
    """Capture actual Torch state immediately after original fit; no JSON weight fabrication."""
    if type(slot) is not dict or prefix not in HEADS:
        raise Invalid('unregistered original physical Head capture')
    for field in ('weight','bias'):
        key=f'{prefix}.{field}'
        if key in slot:
            raise Invalid('duplicate original physical tensor name')
        value=getattr(module,field).detach().cpu().contiguous().numpy().copy()
        if value.dtype.name != 'float32':
            raise Invalid('unexpected original physical Head precision')
        slot[key]=value


def export_original_replay(directory, fit, blind, report, model, features, head_tensors):
    """Write-once files, commit manifest LAST. A torn export is never complete."""
    import numpy as np
    from safetensors.numpy import save_file

    validate(fit,blind)
    if model not in MODEL_WIDTHS or report.get('model')!=model or report.get('authority')!='DENY_ALL':
        raise Invalid('wrong model or untrusted source authority')
    width=MODEL_WIDTHS[model]
    cases=fit['cases']+blind['cases']
    ids=[r['case_id'] for r in cases]
    if type(features) is not dict or set(features)!=set(ids) or len(ids)!=len(set(ids)):
        raise Invalid('missing original source-aligned physical vectors')
    vectors=np.asarray([features[cid] for cid in ids],dtype=np.float32)
    feature_rows={'__packed_matrix__':vectors}
    if set(head_tensors)!={f'{prefix}.{field}' for prefix in HEADS for field in ('weight','bias')}:
        raise Invalid('missing original physically trained Head')
    # Check tensor-shape/lineage and report identity *before writing* any files.
    _manifest(fit,blind,report,model,feature_rows,head_tensors,'0'*64,'0'*64)
    path=Path(directory)
    if path.exists() or path.is_symlink():
        raise FileExistsError('replay output directory must be new and source isolated')
    path.mkdir(parents=True,exist_ok=False,mode=0o700)
    try:
        features_path=path/'features.safetensors'
        heads_path=path/'heads.safetensors'
        save_file({'features_q24_fp32':vectors},str(features_path))
        save_file(head_tensors,str(heads_path))
        for file in (features_path,heads_path):
            with file.open('rb') as stream:
                os.fsync(stream.fileno())
        feature_sha=_hash_bytes(_safe_tensor_bytes(path,'features.safetensors'))
        head_sha=_hash_bytes(_safe_tensor_bytes(path,'heads.safetensors'))
        meta=_manifest(fit,blind,report,model,feature_rows,head_tensors,feature_sha,head_sha)
        with (path/'COMMITTED.json').open('xb') as stream:
            stream.write(canonical(meta)+b'\n')
            stream.flush();os.fsync(stream.fileno())
        fd=os.open(str(path),os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        return meta
    except Exception:
        # Incomplete files remain explicitly uncommitted for fault triage.
        raise


def _probability_numpy(x, heads, prefix, temperature):
    import numpy as np
    if type(temperature) not in (int,float) or not math.isfinite(temperature) or temperature<=0:
        raise Invalid('invalid recorded calibration temperature')
    w=heads[prefix+'.weight']
    b=heads[prefix+'.bias']
    # Actual Torch applies a binary FP32 linear layer; perform an independent
    # float32 matrix multiplication and numerically stable float64 softmax.
    logits=(w@x.astype(np.float32)+b).astype(np.float64) / temperature
    logits-=logits.max()
    scores=np.exp(logits)
    return float(scores[1]/scores.sum())


def independent_numeric_replay(directory, fit, blind, report, *, model):
    """Independent process: never imports original trainer or loads labels/weights model."""
    import numpy as np
    from safetensors.numpy import load_file

    validate(fit,blind)
    if model not in MODEL_WIDTHS or report.get('model')!=model:
        raise Invalid('not a research matched pretrained-Head replay subject')
    path=Path(directory)
    committed=path/'COMMITTED.json'
    if committed.is_symlink() or not committed.is_file() or committed.stat().st_size>MAX_BYTES:
        raise Invalid('absent original committed replay manifest')
    meta=read(committed)
    feature_bytes=_safe_tensor_bytes(path,'features.safetensors')
    weight_bytes=_safe_tensor_bytes(path,'heads.safetensors')
    if (meta.get('schema')!=SCHEMA or meta.get('model')!=model or
            meta.get('revision')!=REVISIONS[model] or meta.get('width')!=MODEL_WIDTHS[model] or
            meta.get('authority')!='DENY_ALL' or meta.get('production_promotion_permitted') is not False or
            meta.get('original_human_held_labels_included') is not False or
            meta.get('physical_origin_independently_signed') is not False or
            meta.get('actual_pretrained_encoder_recomputed_by_reviewer') is not False or
            meta.get('independent_reviewer_did_not_retrain_heads') is not True):
        raise Invalid('false original physical Head replay authorizer/capability')
    ids=[r['case_id'] for r in fit['cases']+blind['cases']]
    if (meta.get('case_ids_in_original_fit_then_blind_order')!=ids or
            meta.get('fit_sha256')!=sha(canonical(fit)) or
            meta.get('blind_sha256')!=sha(canonical(blind)) or
            meta.get('physical_prediction_report_sha256')!=sha(canonical(report)) or
            meta.get('features_safetensors_sha256')!=_hash_bytes(feature_bytes) or
            meta.get('head_weights_safetensors_sha256')!=_hash_bytes(weight_bytes)):
        raise Invalid('unmatched complete original encoder features or model report SHA')
    features=load_file(str(path/'features.safetensors'))
    heads=load_file(str(path/'heads.safetensors'))
    x=_checked_tensors(features,heads,ids,MODEL_WIDTHS[model])
    verified=_manifest(fit,blind,report,model,
                       {'__packed_matrix__':x},heads,meta['features_safetensors_sha256'],
                       meta['head_weights_safetensors_sha256'])
    if canonical(verified)!=canonical(meta):
        raise Invalid('different physical tensors than published Head lineage')
    view={cid:row for cid,row in zip(ids,x)}
    byid={r['case_id']:r for r in blind['cases']}
    if len(view)!=len(ids) or len(byid)!=len(blind['cases']):
        raise Invalid('missing original source-input case')
    original_controls=report['control']
    candidate=report['matched_question_only_control']['complete_prior_controls']
    checks=(('evidence_frozen',original_controls['frozen_head'],'case_id'),
            ('evidence_trained',original_controls['trained_head'],'case_id'),
            ('question_frozen',candidate['question_frozen_head'],'no_evidence_case_id'),
            ('question_trained',candidate['question_trained_head'],'no_evidence_case_id'))
    count=0;max_error=0.
    pairs=matched_pairs(fit,blind)['test']
    expected_question={prior['case_id']:(orig['case_id'],prior['view_sha256'])
                       for orig,prior in pairs}
    for prefix,arm,id_key in checks:
        source=byid if id_key=='case_id' else expected_question
        predicted=arm.get('predictions')
        if type(predicted) is not list or len(predicted)!=len(source):
            raise Invalid('missing original prediction for numeric replay')
        seen=set()
        for row in predicted:
            cid=row.get(id_key)
            if type(cid) is not str or cid not in source or cid in seen:
                raise Invalid('swapped or duplicated original held evaluation task')
            seen.add(cid)
            if id_key=='case_id':
                if row.get('view_sha256')!=byid[cid]['view_sha256']:
                    raise Invalid('replayed original Head against a different task')
            else:
                if (row.get('original_case_id')!=source[cid][0] or
                        row.get('no_evidence_view_sha256')!=source[cid][1]):
                    raise Invalid('replayed Question-only Head against a different task')
            score=row.get('positive_probability')
            if type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=1:
                raise Invalid('nonfinite/invalid original model probability')
            estimate=_probability_numpy(view[cid],heads,prefix,arm.get('temperature'))
            err=abs(estimate-score)
            if err>TOLERANCE:
                raise Invalid('reported learned prediction disagrees with actual serialized Head and feature')
            max_error=max(max_error,err)
            count+=1
        if seen!=set(source):
            raise Invalid('incomplete original held Head prediction census')
    return {'schema':'hepta.p0.original-stem-head-independent-numeric-replay.v1',
            'model':model,'source_case_count':len(ids),'head_parameter_count_each':2*MODEL_WIDTHS[model]+2,
            'replayed_original_and_question_head_predictions':count,
            'max_probability_disagreement':max_error,
            'tolerance':TOLERANCE,
            'physical_model_origin_independently_authenticated':False,
            'independent_task_quality_proven':False,'production_promotion_permitted':False,
            'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for field in ('fit','blind','output'):
        p.add_argument('--'+field,type=Path,required=True)
    p.add_argument('--granite-97m-r2',type=Path,required=True)
    p.add_argument('--mmbert-small',type=Path,required=True)
    p.add_argument('--embeddinggemma-2-text',type=Path,required=True)
    p.add_argument('--replay-root',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('exact independent-replay outcome must be create only')
    fit,blind=read(a.fit),read(a.blind)
    results={}
    for model in MODEL_WIDTHS:
        begin_wall=time.perf_counter_ns();begin_cpu=time.process_time_ns()
        filename=getattr(a,model)
        results[model]=independent_numeric_replay(a.replay_root/f'{model}.replay',fit,blind,read(filename),model=model)
        results[model]['independent_audit_wall_ms']=(time.perf_counter_ns()-begin_wall)/1e6
        results[model]['independent_audit_cpu_ms']=(time.process_time_ns()-begin_cpu)/1e6
        results[model]['independent_audit_process_peak_rss_bytes']=(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    from p0_multirc_semantic_material import save
    save(a.output,{'schema':'hepta.p0.three-pretrained-head-numeric-replay.v1',
                   'models':results,'laya_noul_policy_numerically_replayed':False,
                   'original_human_labels_accessed_by_replay':False,
                   'production_promotion_permitted':False,'authority':'DENY_ALL'})


if __name__=='__main__':main()
