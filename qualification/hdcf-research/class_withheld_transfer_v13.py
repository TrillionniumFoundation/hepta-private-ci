"""Exact-original-image, TRAIN-class-withheld Organ transfer falsification.

The common DINO/Granite pretrained representations are real historical model outputs.
Fits three bounded float64 low-rank Organ models on 24 labeled TRAIN images per
fold, then seals 24 public TEST-image predictions *without opening TEST labels*.
No new pretrained forwards, novel publisher cohort, semantic grounding, Cell
promotion or production authority is claimed.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import time

import numpy as np

from organ_query_binding_v12 import (
    CLASSES, WIDTH, RANK, SCALE, STEPS, SEED, LR, L2,
    SOURCE_ZIP_SHA, FEATURE_ZIP_SHA, MODEL_SCOPE,
    Denied, need, canonical, sha, load_training_only, sigmoid_scores, write_new,
    fit_rank8, ridge,
)

SCHEMA = "hepta.hdcf.original-class-withheld-transfer.v13"
RESULT_SCHEMA = "hepta.hdcf.original-class-withheld-review.v13"
FOLDS = tuple(CLASSES)


def checked_shape(X, y, T):
    need(X.shape == (36, WIDTH) and y.shape == (36,) and
         T.shape == (3, WIDTH) and y.dtype.kind in ('i','u') and
         set(y.tolist()) == {0,1,2} and
         all(int(np.sum(y == k)) == 12 for k in range(3)) and
         np.all(np.isfinite(X)) and np.all(np.isfinite(T)),
         "original three-class TRAIN feature geometry invalid")


def fit_without_one_class(X: np.ndarray, T: np.ndarray, labels: np.ndarray,
                          withheld: int):
    """Real 160-step 6,144-weight SGD with the excluded class *never in loss*."""
    checked_shape(X, labels, T)
    need(type(withheld) is int and 0 <= withheld < 3, "unregistered held class")
    train_ids = np.flatnonzero(labels != withheld)
    need(train_ids.size == 24 and np.all(labels[train_ids] != withheld),
         "unseen class leaked into fitting")
    seen = [c for c in range(3) if c != withheld]
    x = X[train_ids]
    y = np.asarray([seen.index(int(labels[j])) for j in train_ids], dtype=np.int64)
    # Reuse exact V12 seed and per-scalar parameter profile across folds.
    rng = np.random.default_rng(SEED)
    a = rng.normal(0, 0.05, size=(WIDTH, RANK))
    b = rng.normal(0, 0.05, size=(WIDTH, RANK))
    before = time.process_time_ns()
    wall = time.perf_counter_ns()
    first_loss = None
    for _ in range(STEPS):
        q = T[seen] @ b
        u = x @ a
        scores = SCALE * (u @ q.T)
        probs = sigmoid_scores(scores)
        loss = float(-np.mean(np.log(np.maximum(probs[np.arange(24), y], 1e-300))))
        if first_loss is None:
            first_loss = loss
        e = probs.copy()
        e[np.arange(24), y] -= 1.0
        e /= 24.0
        da = SCALE * x.T @ (e @ q) + L2*a
        db = SCALE * T[seen].T @ (e.T @ u) + L2*b
        a -= LR*da
        b -= LR*db
        need(np.all(np.isfinite(a)) and np.all(np.isfinite(b)),
             "real Organ fit numerical instability")
    finish = SCALE * ((x @ a) @ (T[seen] @ b).T)
    p = sigmoid_scores(finish)
    loss_final = float(-np.mean(np.log(np.maximum(p[np.arange(24), y], 1e-300))))
    digest = hashlib.sha256(b"hepta.hdcf.class-withheld-v13.weights\0" +
                            a.astype('<f8',copy=False).tobytes() +
                            b.astype('<f8',copy=False).tobytes()).hexdigest()
    work = {'steps': STEPS, 'parameter_count': 2*WIDTH*RANK,
            'paid_scalar_updates': STEPS*2*WIDTH*RANK,
            'train_images': len(train_ids),
            'seen_class_indices': seen,
            'withheld_class_index': withheld,
            'withheld_images_fit': 0,
            'first_cross_entropy': first_loss,
            'last_cross_entropy': loss_final,
            'reported_process_cpu_ns': time.process_time_ns()-before,
            'reported_wall_ns': time.perf_counter_ns()-wall,
            'weights_sha256': digest}
    return a, b, work


def score_with_weights(features: np.ndarray, text: np.ndarray,
                       a: np.ndarray, b: np.ndarray) -> np.ndarray:
    need(features.ndim == 2 and features.shape[1] == WIDTH and
         text.shape == (3, WIDTH) and a.shape == b.shape == (WIDTH,RANK),
         "unsupported model/feature dimensions")
    out = SCALE * ((features @ a) @ (text @ b).T)
    need(out.shape == (features.shape[0],3) and np.all(np.isfinite(out)),
         "invalid class-withheld original output")
    return out


def build_prediction(source_zip: str | Path, feature_zip: str | Path) -> dict:
    source = load_training_only(source_zip, feature_zip)
    x, h, text, y = source['train_X'], source['held_X'], source['T'], source['train_labels']
    checked_shape(x,y,text)
    held_rows = source['held']
    need(len(held_rows) == 24 and len({r['case_id'] for r in held_rows}) == 24,
         "original TEST image population drift")
    data = {}
    for k, name in enumerate(FOLDS):
        a, b, work = fit_without_one_class(x, text, y, k)
        scores = score_with_weights(h, text, a, b)
        data[name] = {'work':work,'rows':[
            {'id':r['case_id'], 'group_id':r['group_id'],
             'image_sha256':r['image_sha256'],
             'scores':scores[i].tolist()}
            for i,r in enumerate(held_rows)]}
    # Strong original frozen 3-class DINO reference has seen all TRAIN classes;
    # it is intentionally a *privileged* reference, NOT a zero-shot comparator.
    fulla, fullb, full_work = fit_rank8(x, text, y)
    full_scores = score_with_weights(h,text,fulla,fullb)
    ridge_scores = ridge(x,y,h)
    result = {
        'schema': SCHEMA, 'original_source_zip_sha256':SOURCE_ZIP_SHA,
        'original_feature_zip_sha256': FEATURE_ZIP_SHA,
        'model_scope': MODEL_SCOPE, 'original_historical_public_not_future': True,
        'test_labels_read_during_fit': False, 'new_pretrained_model_forwards': 0,
        'independent_source_issuers_verified': False,
        'zero_shot_semantic_transfer_verified': False,
        'automatic_cell_split_authorized': False, 'production_authorized': False,
        'frozen_teacher_classes':list(CLASSES), 'train_classes_per_fold':2,
        'train_images_per_fold':24, 'held_images':24,
        'train_label_digest':sha(canonical([
            (r['case_id'],CLASSES[int(y[i])]) for i,r in enumerate(source['train'])])),
        'query_feature_digests':source['text_hashes'],
        'folds':data,
        'full_three_class_organ_work':full_work,
        'full_three_class_organ_scores':full_scores.tolist(),
        'vision_only_ridge_scores':ridge_scores.tolist(),
        'frozen_three_class_visual_reference':[
            {'id':r['case_id'],'predicted_class':CLASSES[source['strong'][r['case_id']]]}
            for r in held_rows],
    }
    result['prediction_seal_sha256'] = sha(canonical(result))
    return result


def verify_source_and_predictions(doc: dict, source_zip: str | Path,
                                  feature_zip: str | Path) -> dict:
    """Independent late reader verifies all original per-case scores before targets."""
    need(type(doc) is dict and doc.get('schema') == SCHEMA and
         doc.get('prediction_seal_sha256') == sha(canonical({k:v for k,v in doc.items()
                                        if k != 'prediction_seal_sha256'})) and
         doc.get('original_source_zip_sha256') == SOURCE_ZIP_SHA and
         doc.get('original_feature_zip_sha256') == FEATURE_ZIP_SHA and
         doc.get('model_scope') == MODEL_SCOPE and
         doc.get('test_labels_read_during_fit') is False and
         doc.get('new_pretrained_model_forwards') == 0 and
         doc.get('production_authorized') is False and
         doc.get('automatic_cell_split_authorized') is False and
         doc.get('zero_shot_semantic_transfer_verified') is False and
         doc.get('original_historical_public_not_future') is True,
         "unknown/altered/authorizing original prediction seal")
    original = load_training_only(source_zip,feature_zip)
    X,T,y,h = original['train_X'],original['T'],original['train_labels'],original['held_X']
    need(doc['train_label_digest'] == sha(canonical([
         (r['case_id'],CLASSES[int(y[i])]) for i,r in enumerate(original['train'])])) and
         doc['query_feature_digests'] == original['text_hashes'] and
         doc['frozen_teacher_classes'] == list(CLASSES) and
         doc['train_classes_per_fold'] == 2 and
         doc['train_images_per_fold'] == 24 and
         doc['held_images'] == 24 and
         set(doc['folds']) == set(FOLDS), "source/budget mismatch")
    for k,name in enumerate(FOLDS):
        arm = doc['folds'][name]
        work = arm['work']
        need(work['steps'] == STEPS and work['parameter_count'] == 2*WIDTH*RANK and
             work['paid_scalar_updates'] == STEPS*2*WIDTH*RANK and
             work['train_images'] == 24 and work['withheld_images_fit'] == 0 and
             work['withheld_class_index'] == k and
             work['seen_class_indices'] == [c for c in range(3) if c != k],
             "withheld class contributed gradients or wrong training work")
        a,b,expected_work = fit_without_one_class(X,T,y,k)
        need(work['weights_sha256'] == expected_work['weights_sha256'] and
             abs(work['first_cross_entropy']-expected_work['first_cross_entropy'])<1e-10 and
             abs(work['last_cross_entropy']-expected_work['last_cross_entropy'])<1e-10,
             "original paid SGD weights not independently reproduced")
        scores=score_with_weights(h,T,a,b)
        need(len(arm['rows']) == 24, "incomplete scored original images")
        for j,row in enumerate(original['held']):
            q=arm['rows'][j]
            need(set(q) == {'id','group_id','image_sha256','scores'} and
                 q['id'] == row['case_id'] and
                 q['group_id'] == row['group_id'] and
                 q['image_sha256'] == row['image_sha256'],
                 "original source / prediction label identity mismatch")
            observed=np.asarray(q['scores'],dtype=np.float64)
            need(observed.shape == (3,) and np.all(np.isfinite(observed)) and
                 np.allclose(observed,scores[j],rtol=0,atol=1e-9),
                 "unfitted or altered original held predictions")
    a,b,full=fit_rank8(X,T,y)
    expect=score_with_weights(h,T,a,b)
    need(doc['full_three_class_organ_work']['parameters'] == 2*WIDTH*RANK and
         doc['full_three_class_organ_work']['steps'] == STEPS and
         np.allclose(np.asarray(doc['full_three_class_organ_scores']),expect,rtol=0,atol=1e-9),
         "changed full-fit model control")
    need(np.allclose(np.asarray(doc['vision_only_ridge_scores']),ridge(X,y,h),
                     rtol=0,atol=1e-10), "changed visual ridge control")
    need(doc['frozen_three_class_visual_reference'] == [
        {'id':r['case_id'],'predicted_class':CLASSES[original['strong'][r['case_id']]]}
        for r in original['held']], "strong visual baseline changed")
    return original


def review_after_seal(doc:dict, source_zip:str|Path, feature_zip:str|Path,
                      target_zip:str|Path, *, publisher_train=None,
                      publisher_test=None) -> dict:
    from review_organ_binding_v12 import load_original_blind, paired_exact
    evidence=verify_source_and_predictions(doc,source_zip,feature_zip)
    labels=load_original_blind(source_zip,target_zip,evidence['held'])
    publisher_check=False
    if publisher_train is not None or publisher_test is not None:
        need(publisher_train is not None and publisher_test is not None,
             "publisher source incomplete")
        import original_beans_v9 as original
        originals={'train':{
            row['case_id']:CLASSES[int(evidence['train_labels'][i])]
            for i,row in enumerate(evidence['train'])},
            'held':{case:{'class_label':name} for case,name in labels.items()}}
        original.verify_publisher_parquets(
            publisher_train,publisher_test,evidence['train'],evidence['held'],originals)
        publisher_check=True
    totals={}
    per_case={}
    for withheld,name in enumerate(FOLDS):
        scores=np.asarray([r['scores'] for r in doc['folds'][name]['rows']],dtype=float)
        pred=np.argmax(scores,axis=1)
        truth=np.asarray([CLASSES.index(labels[r['case_id']]) for r in evidence['held']])
        hit=pred==truth
        withheld_mask=truth==withheld
        totals[name]={'train_seen_images':24,'test_images':24,
            'historical_unseen_class_test_images':int(np.sum(withheld_mask)),
            'unseen_correct':int(np.sum(hit & withheld_mask)),
            'unseen_incorrect':int(np.sum(~hit & withheld_mask)),
            'seen_correct':int(np.sum(hit & ~withheld_mask)),
            'seen_incorrect':int(np.sum(~hit & ~withheld_mask)),
            'total_correct':int(np.sum(hit)),
            'predicted_unseen_class':int(np.sum(pred==withheld)),
            'held_issuer_count_verified':1}
        per_case[name] = {r['case_id']:bool(hit[j]) for j,r in enumerate(evidence['held'])}
    truth=np.asarray([CLASSES.index(labels[r['case_id']]) for r in evidence['held']])
    full_hit=np.argmax(doc['full_three_class_organ_scores'],axis=1)==truth
    ridge_hit=np.argmax(doc['vision_only_ridge_scores'],axis=1)==truth
    strong_hit=np.asarray([rec['predicted_class']==labels[rec['id']]
                            for rec in doc['frozen_three_class_visual_reference']])
    paired={}
    for name in FOLDS:
        wins=sum(per_case[name][r['case_id']] and not strong_hit[j]
                 for j,r in enumerate(evidence['held']))
        losses=sum(strong_hit[j] and not per_case[name][r['case_id']]
                   for j,r in enumerate(evidence['held']))
        paired[name]={'fold_vs_privileged_strong_dino_wins':int(wins),
                      'fold_vs_privileged_strong_dino_losses':int(losses),
                      'image_cluster_nominal_exact_p':float(paired_exact(int(wins),int(losses)))}
    return {'schema':RESULT_SCHEMA,
        'predictor_prelabel_sha256':doc['prediction_seal_sha256'],
        'verified_historical_source':True,
        'publisher_byte_reverification':publisher_check,
        'actual_organ_sgd_completed':True,
        'trained_organ_count':3,
        'train_rows_per_organ':24,
        'train_updates_per_organ':STEPS,
        'real_pretrained_feature_reused':True,
        'new_pretrained_forward_count':0,
        'held_images':24,
        'unseen_class_per_fold':totals,
        'full_three_class_trained_organ_correct':int(np.sum(full_hit)),
        'vision_only_ridge_correct':int(np.sum(ridge_hit)),
        'privileged_frozen_visual_prototype_correct':int(np.sum(strong_hit)),
        'paired_vs_privileged_prototype':paired,
        'independent_source_issuers_verified':False,
        'new_text_paraphrases_encoded':False,
        'unseen_class_learned_semantics_proven':False,
        'future_time_generalization_proven':False,
        'model_promoted':False,'cell_split_authorized':False,
        'production_authorized':False,
        'disposition':'HOLD_NO_GO_DENY_ALL'}


def main(argv=None):
    p=argparse.ArgumentParser(description='Original frozen class-withheld transfer V13, DENY_ALL')
    sub=p.add_subparsers(dest='command',required=True)
    train=sub.add_parser('train')
    train.add_argument('--source-zip',required=True)
    train.add_argument('--feature-zip',required=True)
    train.add_argument('--out',required=True)
    reviewer=sub.add_parser('review')
    reviewer.add_argument('--source-zip',required=True)
    reviewer.add_argument('--feature-zip',required=True)
    reviewer.add_argument('--target-zip',required=True)
    reviewer.add_argument('--predictions',required=True)
    reviewer.add_argument('--publisher-train')
    reviewer.add_argument('--publisher-test')
    reviewer.add_argument('--out',required=True)
    args=p.parse_args(argv)
    try:
        if args.command=='train':
            output=build_prediction(args.source_zip,args.feature_zip)
        else:
            from organ_query_binding_v12 import read_json
            doc=read_json(Path(args.predictions).read_bytes())
            output=review_after_seal(doc,args.source_zip,args.feature_zip,args.target_zip,
                publisher_train=args.publisher_train,publisher_test=args.publisher_test)
        write_new(args.out,output)
    except (Denied,ValueError,KeyError,TypeError,OSError,ImportError,
            np.linalg.LinAlgError) as error:
        p.exit(2,'DENY_ALL: '+str(error)+'\n')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
