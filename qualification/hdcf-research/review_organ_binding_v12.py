"""Separate late-label HDCF V12 audit; counts 24 images, NOT 72 independent cases.

Uses the original sealed source/feature/target archives. When source publisher
parquets are supplied, invokes the existing original V9 independent selection
and whole-file byte checker. No self-promotion or semantic grounding claim.
"""
from __future__ import annotations
import argparse
from math import comb
from pathlib import Path

import numpy as np

from organ_query_binding_v12 import (
    CLASSES, DINO_REV, DINO_WEIGHTS, DATA_REV, PRED_SCHEMA, STEPS, RANK,
    SOURCE_ZIP_SHA, FEATURE_ZIP_SHA, TARGET_ZIP_SHA, SOURCE_MANIFEST_SHA,
    MODEL_SCOPE, PinnedArchive, Denied, need, sha, canonical, read_json,
    read_jsonl, load_training_only, write_new,
)

SUMMARY = 'hepta.hdcf.original-vision-text-binding-review.v12'


def load_original_blind(source_zip, target_zip, held_rows):
    """This function must never be called in the training/prediction stage."""
    src = PinnedArchive(source_zip, SOURCE_ZIP_SHA)
    target = PinnedArchive(target_zip, TARGET_ZIP_SHA)
    try:
        manifest = read_json(target.read('target-manifest.json'))
        need(manifest['schema'] == 'hepta.e2.beans-natural-retrospective.v1.withheld-target-plan' and
             manifest['production_accepted'] is False and
             manifest['source_manifest_sha256'] == SOURCE_MANIFEST_SHA and
             manifest['original_test_parquet_sha256'] ==
                 '534a6b0648f585d69b7ec0ad7a7540720d60c8db8106dc6d0508296316f6cb27',
             'original blind manifest changed')
        for name, expected in manifest['file_sha256s'].items():
            need(sha(target.read(name)) == expected, 'withheld blind file digest changed')
        labels = read_jsonl(target.read('future_class_targets.jsonl'))
        need(len(labels) == len(held_rows) == 24, 'incomplete blind source cases')
        out = {}
        for src_row, row in zip(held_rows, labels, strict=True):
            need(set(row) == {'case_id','class_label','group_id','observed_at',
                              'scope','source_input_sha256','source_sha256'} and
                 row['case_id'] == src_row['case_id'] and
                 row['group_id'] == src_row['group_id'] and
                 row['scope'] == MODEL_SCOPE and
                 row['source_input_sha256'] == src_row['image_sha256'] and
                 row['source_sha256'] == src_row['source_sha256'] and
                 row['class_label'] in CLASSES and
                 row['case_id'] not in out,
                 'original held label/source identity violation')
            out[row['case_id']] = row['class_label']
        return out
    finally:
        src.close()
        target.close()


def paired_exact(wins, losses):
    n = wins + losses
    if n == 0:
        return 1.0
    return min(1.0, 2*sum(comb(n,k) for k in range(min(wins,losses)+1))/(2**n))


def _score_predictions(seal, evidence, truth):
    required = {'organ','orthogonal_null','direct','visual_ridge',
                'wrong_text_cue'}
    totals = {name: 0 for name in required | {'strong_original_dino'}}
    per_image = {name: {} for name in totals}
    case_seen = set()
    for src, row in zip(evidence['held'], seal['rows'], strict=True):
        case = src['case_id']
        need(set(row) == {'id','source_sha256','group_id','image_sha256',
                          'scores','original_visual_prototype_class'} and
             row['id'] == case and row['source_sha256'] == src['source_sha256'] and
             row['group_id'] == src['group_id'] and row['image_sha256'] == src['image_sha256'] and
             case not in case_seen, 'sealed source population mismatch')
        case_seen.add(case)
        need(set(row['scores']) == required, 'incomplete original score arms')
        target = CLASSES.index(truth[case])
        for arm in required:
            vec = np.asarray(row['scores'][arm], dtype=np.float64)
            need(vec.shape == (3,) and np.all(np.isfinite(vec)) and
                 float(np.max(np.abs(vec))) < 1_000_000, 'invalid arm probabilities/scores')
            predicted = int(np.argmax(vec))
            per_image[arm][case] = predicted == target
            totals[arm] += int(predicted == target)
        need(max(abs(a-b) for a,b in zip(row['scores']['organ'],
                                         row['scores']['orthogonal_null'])) < 1e-8,
             'Gram-equivalent null predictions differ')
        pred_strong = row['original_visual_prototype_class']
        need(pred_strong in CLASSES and pred_strong == CLASSES[evidence['strong'][case]],
             'original strong baseline changed')
        per_image['strong_original_dino'][case] = pred_strong == truth[case]
        totals['strong_original_dino'] += int(pred_strong == truth[case])
    return totals, per_image


def review(*, source_zip, feature_zip, target_zip, predictions,
           publisher_train=None, publisher_test=None):
    doc = read_json(Path(predictions).read_bytes())
    need(type(doc) is dict and doc.get('schema') == PRED_SCHEMA,
         'wrong sealed model product')
    self_digest = doc.get('prediction_seal_sha256')
    need(type(self_digest) is str and len(self_digest) == 64 and
         self_digest == sha(canonical({k:v for k,v in doc.items() if k!='prediction_seal_sha256'})),
         'original predictions changed after sealing')
    need(doc['model_scope'] == MODEL_SCOPE and
         doc['original_source_zip_sha256'] == SOURCE_ZIP_SHA and
         doc['original_feature_zip_sha256'] == FEATURE_ZIP_SHA and
         doc['producer_actual_new_pretrained_forwards'] == 0 and
         doc['cell_split_authorized'] is False and
         doc['production_authorized'] is False and
         doc['original_public_historical_not_true_future'] is True and
         doc['train_images'] == 36 and doc['held_images'] == 24 and
         doc['train_membership_pairs'] == 108 and
         doc['held_membership_pairs'] == 72 and
         doc['text_class_order'] == list(CLASSES) and
         doc['rank'] == RANK and len(doc['rows']) == 24 and
         doc['original_gram_invariant_max_score_abs_error'] < 1e-8,
         'model/cost/frame/authority identity differs')
    for arm in ('real_text_organ','signed_permutation_control'):
        record = doc['fit_cost'][arm]
        need(record['steps'] == STEPS and record['parameters'] == 2*384*RANK and
             record['paid_scalar_updates'] == STEPS*2*384*RANK and
             np.isfinite(record['start_ce']) and np.isfinite(record['final_ce']) and
             record['cpu_ns_unattested'] >= 0 and record['wall_ns_unattested'] >= 0,
             'claimed optimizer work malformed')
    evidence = load_training_only(source_zip, feature_zip)
    need(doc['source_label_hash'] == sha(canonical([{
         'id': src['case_id'], 'class': CLASSES[int(evidence['train_labels'][i])]}
         for i,src in enumerate(evidence['train'])])) and
         doc['text_source_sha256s'] == evidence['text_hashes'],
         'train-only source/Granite identities changed')
    truth = load_original_blind(source_zip, target_zip, evidence['held'])
    publisher_verified = False
    if publisher_train is not None or publisher_test is not None:
        need(publisher_train is not None and publisher_test is not None,
             'both publisher source files required')
        # The original V9 reviewer verifies exact two Parquet byte hashes,
        # independent sample selection, and all 36+24 published class labels.
        # This deliberately requires the inherited, separately authored verifier.
        import original_beans_v9 as original
        records = {'train': {row['case_id']: CLASSES[int(evidence['train_labels'][i])]
                             for i,row in enumerate(evidence['train'])},
                   'held': {key:{'class_label':val} for key,val in truth.items()}}
        original.verify_publisher_parquets(
            publisher_train, publisher_test, evidence['train'], evidence['held'], records)
        publisher_verified = True
    totals, per_image = _score_predictions(doc, evidence, truth)
    comparisons = {}
    for arm in ('organ','visual_ridge','direct','wrong_text_cue','orthogonal_null'):
        other = per_image['strong_original_dino']
        wins = sum(per_image[arm][i] and not other[i] for i in truth)
        losses = sum(other[i] and not per_image[arm][i] for i in truth)
        comparisons[arm+'_versus_strong_dino'] = {
            'image_level_wins':wins, 'image_level_losses':losses,
            'image_level_nominal_exact_p':paired_exact(wins,losses)}
    wins = sum(per_image['organ'][i] and not per_image['visual_ridge'][i] for i in truth)
    losses = sum(per_image['visual_ridge'][i] and not per_image['organ'][i] for i in truth)
    comparisons['organ_versus_visual_ridge'] = {
        'image_level_wins':wins,'image_level_losses':losses,
        'image_level_nominal_exact_p':paired_exact(wins,losses)}
    # Three membership pairs share ONE original image/label. Because each arm
    # chooses exactly one of three text classes, each incorrect image yields
    # one correct of three membership answers; a correct image yields 3/3.
    membership = {k: {'correct': 24 + 2*v, 'total':72} for k,v in totals.items()}
    return {
      'schema': SUMMARY, 'source': 'real_pinned_DINO_and_Granite_features',
      'prediction_seal_sha256':self_digest, 'original_36_train_24_test':True,
      'image_clusters':24, 'synthetic_class_membership_queries':72,
      'true_independent_source_families_verified':False,
      'historical_not_future_time':True, 'publisher_original_bytes_reverified':publisher_verified,
      'pretrained_new_forward_count':0, 'rank8_organ_train_steps_each':STEPS,
      'rank8_parameter_count_each':2*384*RANK,
      'arm_correct_images':totals, 'arm_binary_membership':membership,
      'paired_image_cluster_comparisons':comparisons,
      'orthogonal_null_prototype_isometry_max_abs_error':doc['original_gram_invariant_max_score_abs_error'],
      'semantic_identifiability_proven':False,
      'attention_or_time_reasoning_proven':False,
      'service_rss_gpu_energy_p99_attested':False,
      'automatic_cell_split_approved':False, 'production_authorized':False,
      'disposition':'HOLD_NO_GO_DENY_ALL'
    }


def main(argv=None):
    p = argparse.ArgumentParser(description='Late-label publisher-audited HDCF V12')
    p.add_argument('--source-zip',required=True)
    p.add_argument('--features-zip',required=True)
    p.add_argument('--targets-zip',required=True)
    p.add_argument('--predictions',required=True)
    p.add_argument('--publisher-train')
    p.add_argument('--publisher-test')
    p.add_argument('--out',required=True)
    a=p.parse_args(argv)
    try:
        doc=review(source_zip=a.source_zip,feature_zip=a.features_zip,
                   target_zip=a.targets_zip,predictions=a.predictions,
                   publisher_train=a.publisher_train,publisher_test=a.publisher_test)
        write_new(a.out,doc)
    except (Denied,OSError,ValueError,KeyError,TypeError,ImportError) as e:
        p.exit(2,'DENY_ALL: '+str(e)+'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
