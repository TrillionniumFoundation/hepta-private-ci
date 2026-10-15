"""Label-separated, independently recomputed post-seal Beans vision-only probe readout.

Requires all four original archive ZIPs, their operator-frozen SHA-256 identities,
and two separately SHA-pinned seal files. A successful archive read is not
publisher/hardware attestation or real source-independent future evidence.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import numpy as np

from e2_beans_original_zip_review import (
    CLASSES, Reject, require, canon, digest, original_zip, member, json_lines,
    review_archives, _validate_source_images,
)
from e2_beans_frozen_vision_linear_probe import (
    PROBE, PARAMETER_COUNT, ALPHA, INPUT_WIDTH,
    _features, _solve, _decision,
)


def read_pinned(path,sha):
    path=Path(path)
    require(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<130_000,
            'unsafe sealed model or predictions')
    raw=path.read_bytes()
    require(digest(raw)==sha,'sealed model/predictions SHA mismatch')
    from e2_beans_original_zip_review import json_object
    return json_object(raw)


def paired(a,b):
    out={'rescued':0,'harmed':0,'both_correct':0,'both_wrong':0}
    for ca,cb in zip(a,b):
        label='rescued' if ca and not cb else 'harmed' if cb and not ca else 'both_correct' if ca else 'both_wrong'
        out[label]+=1
    return out


def exact_mcnemar(r,h):
    n=r+h
    if n==0:return 1.0
    return min(1.0,2.0*math.fsum(math.comb(n,k) for k in range(min(r,h)+1))/2**n)


def independent_score(paths, pins, model, model_sha, predictions):
    original=review_archives(paths,pins)
    src=original_zip(paths['source'],pins['source'])
    prod=original_zip(paths['producer'],pins['producer'])
    withheld=original_zip(paths['withheld'],pins['withheld'])
    source_manifest_sha=digest(member(src,'source-manifest.json'))
    require(model.get('schema')==PROBE+'.model' and
            model.get('source_zip_sha256')==pins['source'] and
            model.get('producer_zip_sha256')==pins['producer'] and
            model.get('source_manifest_sha256')==source_manifest_sha and
            model.get('train_classes_sha256')==digest(member(src,'source/train_class.jsonl')) and
            model.get('train_cases')==36 and model.get('feature_width')==INPUT_WIDTH and
            model.get('parameter_count')==PARAMETER_COUNT and
            type(model.get('alpha')) is float and model['alpha']==ALPHA and
            model.get('trained_on_future_labels') is False and
            model.get('model_origin_independently_attested') is False and
            model.get('production_accepted') is False and model.get('stem_selected') is False and
            model.get('authority')=='DENY_ALL', 'unapproved linear probe model')
    require(digest(canon(model))==model_sha,'not an original sealed parameter checkpoint')
    require(predictions.get('schema')==PROBE+'.sealed-predictions' and
            predictions.get('model_sha256')==model_sha and
            predictions.get('source_zip_sha256')==pins['source'] and
            predictions.get('producer_zip_sha256')==pins['producer'] and
            predictions.get('source_manifest_sha256')==source_manifest_sha and
            predictions.get('future_labels_seen') is False and
            predictions.get('stem_selected') is False and
            predictions.get('production_accepted') is False and
            predictions.get('authority')=='DENY_ALL' and
            predictions.get('target_host_attested') is False and
            predictions.get('natural_original_images_not_verified_by_probe') is True and
            predictions.get('training_energy_joules') is None,
            'invalid sealed predictions identity/authority')
    w=np.asarray(model.get('weights'),dtype=np.float64)
    b=np.asarray(model.get('bias'),dtype=np.float64)
    require(w.shape==(INPUT_WIDTH,3) and b.shape==(3,) and np.isfinite(w).all() and
            np.isfinite(b).all(), 'incorrect model geometry')
    # Independently fit from *TRAIN-only* vision and labels, not using future targets.
    expected_w,expected_b,_=_solve(src,prod)
    require(np.allclose(w,expected_w,atol=1e-7,rtol=1e-7) and
            np.allclose(b,expected_b,atol=1e-7,rtol=1e-7),
            'linear Head weights are not independently reproducible from TRAIN')
    future=_features(prod,'future')
    prediction_by={}
    for row in predictions.get('rows',[]):
        require(type(row) is dict and set(row)=={'case_id','group_id','scope','observed_at',
                'source_input_sha256','predicted_label'} and
                row['predicted_label'] in CLASSES, 'unexpected inference row')
        key=row['case_id']
        require(key not in prediction_by,'duplicate probe prediction')
        prediction_by[key]=row
    require(set(prediction_by)==set(future) and len(future)==24,
            'incomplete or extra frozen vision probe predictions')
    expected_src={r['case_id']:r for r in json_lines(member(src,'source/future_images.jsonl'))}
    original_predictions={r['case_id']:r['predicted_labels'] for r in
        json.loads(member(prod,'sealed_class_predictions.json'))['rows']}
    targets=json_lines(member(withheld,'future_class_targets.jsonl'))
    actual={r['case_id']:r for r in targets}
    require(set(actual)==set(future)==set(original_predictions), 'wrong comparison cohort')
    correct_probe=[]; correct_fitted=[];correct_frozen=[]
    for cid in sorted(future):
        row=prediction_by[cid];feat,vector=future[cid]
        srcrow=expected_src[cid];truth=actual[cid]
        require(all(row[k]==srcrow[k] for k in ('case_id','group_id','scope','observed_at')) and
                row['source_input_sha256']==srcrow['image_sha256'] and
                feat['source']['input_sha256']==srcrow['image_sha256'],
                'source case/feature mismatch')
        require(row['predicted_label']==_decision(vector@w+b),
                'original label-blind prediction does not reproduce checkpoint')
        label=truth['class_label']
        correct_probe.append(row['predicted_label']==label)
        correct_fitted.append(original_predictions[cid]['fitted']==label)
        correct_frozen.append(original_predictions[cid]['vision_prototype']==label)
    paired_controls={'fitted_bridge':paired(correct_fitted,correct_probe),
                     'vision_prototype':paired(correct_frozen,correct_probe)}
    ps={k:exact_mcnemar(v['rescued'],v['harmed']) for k,v in paired_controls.items()}
    ordered=sorted(ps,key=lambda k:(ps[k],k))
    holm={};prev=0.
    for i,k in enumerate(ordered):
        prev=min(1.,max(prev,(len(ordered)-i)*ps[k]))
        holm[k]=prev
    return {'schema':PROBE+'.independent-comparison',
            'probe_model_sha256':model_sha,'cases':24,
            'frozen_vision_ridge_correct':sum(correct_probe),
            'original_fitted_bridge_correct':sum(correct_fitted),
            'original_vision_prototype_correct':sum(correct_frozen),
            'paired_vs_vision_ridge':{k:{**v,'exact_mcnemar_p':ps[k],
                'holm_adjusted_p_two_comparisons':holm[k]}
                for k,v in paired_controls.items()},
            'all_four_original_archives_independently_validated':True,
            'original_four_archive_audit':original,
            'probe_was_train_only_and_replayed_from_original_features':True,
            'matched_parameter_and_total_compute_budget':False,
            'original_source_independent_future_windows':False,
            'independent_ground_truth_owner_attested':False,
            'no_new_pretrained_encoder_forwards':True,
            'stem_selected':False,'production_accepted':False,'authority':'DENY_ALL'}


def cli():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','withheld','producer','independent'):
        p.add_argument('--'+key+'-zip',required=True,type=Path)
        p.add_argument('--'+key+'-sha256',required=True)
    p.add_argument('--model',required=True,type=Path)
    p.add_argument('--model-sha256',required=True)
    p.add_argument('--predictions',required=True,type=Path)
    p.add_argument('--predictions-sha256',required=True)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    paths={k:getattr(a,k+'_zip') for k in ('source','withheld','producer','independent')}
    pins={k:getattr(a,k+'_sha256') for k in paths}
    model=read_pinned(a.model,a.model_sha256)
    predictions=read_pinned(a.predictions,a.predictions_sha256)
    out=independent_score(paths,pins,model,a.model_sha256,predictions)
    require(not a.output.exists() and a.output.parent.is_dir(), 'write-once readout required')
    a.output.write_bytes(canon(out))
    print(json.dumps({k:out[k] for k in ('frozen_vision_ridge_correct','original_fitted_bridge_correct',
         'original_vision_prototype_correct','authority')},sort_keys=True))

if __name__=='__main__':cli()
