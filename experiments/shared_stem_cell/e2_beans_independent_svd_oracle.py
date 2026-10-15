"""Numerically independent TRAIN-only SVD audit of a sealed Beans visual Ridge.

Unlike the Ridge producer's dual normal-equation solve, this auditor uses a
thin singular value decomposition. It neither imports the producer's optimizer
nor trains from future labels. This is research-only, not publisher attestation.
"""
from __future__ import annotations
import math
import numpy as np
from e2_beans_original_zip_review import (CLASSES, Reject, require, member,
                                           json_lines, original_zip, canon, digest)

WIDTH = 384
RIDGE_ALPHA = 0.1
CLASSES = tuple(CLASSES)


def independently_fit(source_zip, producer_zip):
    """No future ZIP or future labels are accepted by this function."""
    class_rows = json_lines(member(source_zip, 'source/train_class.jsonl'))
    vision_rows = json_lines(member(producer_zip, 'vision_train/features.jsonl'))
    labels = {}
    for row in class_rows:
        require(type(row) is dict and set(row) == {'case_id', 'class_label'}
                and row['case_id'] not in labels and row['class_label'] in CLASSES,
                'invalid original TRAIN labels')
        labels[row['case_id']] = row['class_label']
    features = {}
    for row in vision_rows:
        case = row['case_id']
        require(case not in features and row.get('split') == 'train',
                'unknown or duplicate TRAIN source')
        v = np.asarray(row['source']['values'], dtype=np.float64)
        require(v.shape == (WIDTH,) and bool(np.all(np.isfinite(v))) and
                0.999 <= float(np.linalg.norm(v)) <= 1.001,
                'invalid frozen 384D TRAIN feature')
        features[case] = v
    require(len(labels) == len(features) == 36 and set(labels) == set(features),
            'TRAIN case-feature mismatch')
    require({name:sum(v == name for v in labels.values()) for name in CLASSES}
            == {name:12 for name in CLASSES}, 'TRAIN balance mismatch')
    cases = sorted(labels)
    X = np.stack([features[c] for c in cases], axis=0)
    Y = np.asarray([[float(labels[c] == name) for name in CLASSES]
                    for c in cases], dtype=np.float64)
    xm, ym = np.mean(X, axis=0), np.mean(Y, axis=0)
    xc, yc = X-xm, Y-ym
    # Thin SVD is mathematically equivalent to ridge with an unpenalized bias,
    # and algorithmically independent of the producer's 36x36 dual solver.
    u, singular, vh = np.linalg.svd(xc, full_matrices=False)
    weights = vh.T @ ((singular / (singular**2 + RIDGE_ALPHA))[:,None] * (u.T @ yc))
    bias = ym - xm @ weights
    require(weights.shape == (WIDTH, len(CLASSES)) and
            bias.shape == (len(CLASSES),) and
            np.all(np.isfinite(weights)) and np.all(np.isfinite(bias)),
            'independent oracle numerics invalid')
    return weights, bias


def independent_svd_parity(source_path, source_sha, producer_path, producer_sha,
                           sealed_model, sealed_predictions):
    """Reproduce the saved model and every future inference, with no scorer import."""
    source = original_zip(source_path, source_sha)
    producer = original_zip(producer_path, producer_sha)
    for container in (source,producer):
        require(not any(key.endswith(suffix) for key in container for suffix in (
            'future_class_targets.jsonl', 'future_caption_targets.jsonl', 'target-manifest.json')),
            'future labels reached a fit-only oracle')
    weights,bias=independently_fit(source,producer)
    observed_w=np.asarray(sealed_model.get('weights'),dtype=np.float64)
    observed_b=np.asarray(sealed_model.get('bias'),dtype=np.float64)
    require(observed_w.shape==weights.shape and observed_b.shape==bias.shape and
            np.all(np.isfinite(observed_w)) and np.all(np.isfinite(observed_b)) and
            np.allclose(observed_w,weights,rtol=1e-7,atol=1e-7) and
            np.allclose(observed_b,bias,rtol=1e-7,atol=1e-7),
            'SVD and claimed Ridge weights diverge')
    future_rows=json_lines(member(producer,'vision_future/features.jsonl'))
    source_rows=json_lines(member(source,'source/future_images.jsonl'))
    by_source={r['case_id']:r for r in source_rows}
    by_prediction={}
    for row in sealed_predictions.get('rows',[]):
        require(row['case_id'] not in by_prediction,'duplicate sealed case')
        by_prediction[row['case_id']]=row
    require(len(by_source)==len(by_prediction)==len(future_rows)==24,
            'SVD future case coverage not complete')
    seen=set()
    for row in future_rows:
        case=row['case_id']
        require(case not in seen and case in by_source and case in by_prediction,
                'unexpected future frozen feature')
        seen.add(case)
        src=by_source[case];p=by_prediction[case]
        require(all(p[k]==src[k] for k in ('case_id','group_id','scope','observed_at')) and
                p['source_input_sha256']==src['image_sha256'] and
                row['source']['input_sha256']==src['image_sha256'],
                'future model output/source mismatch')
        vec=np.asarray(row['source']['values'],dtype=np.float64)
        require(vec.shape==(WIDTH,) and bool(np.all(np.isfinite(vec))) and
                0.999<=float(np.linalg.norm(vec))<=1.001,'invalid future vector')
        scores=vec@weights+bias
        expected=CLASSES[int(np.argmax(scores))]
        require(p['predicted_label']==expected,'SVD independent prediction disagreement')
    require(seen==set(by_source)==set(by_prediction),'future case identities drifted')
    return {
        'schema':'hepta.e2.beans-independent-svd-ridge-parity.v1',
        'train_cases':36,'future_cases':24,
        'independent_numerical_method':'thin-svd-centered-unpenalized-bias',
        'linear_probe_parameters':WIDTH*len(CLASSES)+len(CLASSES),
        'original_model_digest':digest(canon(sealed_model)),
        'original_prediction_digest':digest(canon(sealed_predictions)),
        'original_train_source_sha256':source_sha,
        'original_producer_sha256':producer_sha,
        'max_absolute_weight_difference':float(np.max(np.abs(observed_w-weights))),
        'max_absolute_bias_difference':float(np.max(np.abs(observed_b-bias))),
        'independently_replayed_all_predictions':True,
        'new_pretrained_forwards':0,
        'natural_future_windows_verified':False,
        'model_publisher_or_target_host_attested':False,
        'production_accepted':False,'stem_selected':False,'authority':'DENY_ALL',
    }
