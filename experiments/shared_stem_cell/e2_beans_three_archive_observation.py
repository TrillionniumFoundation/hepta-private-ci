"""Strict provisional *three-archive* reviewer of actual Beans E2 outputs.

This intentionally DOES NOT impersonate the absent fourth (original independent
geometry/scoring) GitHub artifact. The original sealed producer is never asked
to fit on withheld targets. The separate frozen-vision Ridge fit is reproduced
with SVD before the reviewer reads its own withheld target ZIP. An original
model/worker signature, natural future-time evidence, or production gate is
never inferred from local ZIP consistency.
"""
from __future__ import annotations
import argparse
from collections import Counter
import math
from pathlib import Path

from e2_beans_original_zip_review import (
    CLASSES, ARMS, SCHEMA, Reject, canon, digest, is_sha, json_object,
    member, original_zip, receipt, require, _validate_source_images,
    _validate_withheld, _validate_producer,
)
from e2_beans_independent_svd_oracle import independent_svd_parity

CASES = 24
BASE = 'vision_prototype'
RIDGE = 'vision_ridge'
PROBE = 'hepta.e2.beans-frozen-vision-linear-probe.v1'
LABELS = (*ARMS, RIDGE)


def read_seal(path: Path, sha: str) -> dict:
    path = Path(path)
    require(is_sha(sha) and path.is_file() and not path.is_symlink()
            and 0 < path.stat().st_size < 130_000,
            'unsafe or missing source-pinned seal')
    raw = path.read_bytes()
    require(digest(raw) == sha, 'seal content does not match frozen SHA-256')
    return json_object(raw)


def exact_mcnemar(rescued: int, harmed: int) -> float:
    n = rescued + harmed
    if n == 0:
        return 1.0
    return min(1.0, 2.0 * math.fsum(math.comb(n, k) for k in range(min(rescued, harmed) + 1)) / 2**n)


def review(paths, pins, model, model_sha, predictions, predictions_sha):
    require(set(paths) == set(pins) == {'source', 'producer', 'withheld'},
            'three original ZIP roles are required; never fabricate the fourth')
    require(len({str(Path(p).resolve()) for p in paths.values()}) == 3,
            'the same ZIP is mapped to multiple original artifact roles')
    require(all(is_sha(pins[k]) for k in paths), 'missing exact original ZIP SHA-256')
    source = original_zip(paths['source'], pins['source'])
    producer = original_zip(paths['producer'], pins['producer'])
    require(not any('future_class_targets.jsonl' in p or 'future_caption_targets.jsonl' in p
                    or 'target-manifest.json' in p for archive in (source, producer) for p in archive),
            'training or producer ZIP exposed future targets')

    manifest = receipt(source, 'source-manifest.json')
    source_hash = digest(member(source, 'source-manifest.json'))
    source_rows = _validate_source_images(source, manifest)
    original_predictions, original_model_receipt = _validate_producer(
        producer, source_hash, source, source_rows)

    require(is_sha(model_sha) and is_sha(predictions_sha), 'missing exact probe seal identity')
    m = read_seal(model, model_sha)
    p = read_seal(predictions, predictions_sha)
    require(m.get('schema') == PROBE + '.model' and
            m.get('source_zip_sha256') == pins['source'] and
            m.get('producer_zip_sha256') == pins['producer'] and
            m.get('source_manifest_sha256') == source_hash and
            m.get('train_classes_sha256') == digest(member(source, 'source/train_class.jsonl')) and
            m.get('train_cases') == 36 and m.get('feature_width') == 384 and
            m.get('parameter_count') == 1155 and
            type(m.get('alpha')) is float and m['alpha'] == 0.1 and
            m.get('trained_on_future_labels') is False and
            m.get('model_origin_independently_attested') is False and
            m.get('production_accepted') is False and
            m.get('stem_selected') is False and m.get('authority') == 'DENY_ALL',
            'unapproved frozen vision Ridge model receipt')
    require(p.get('schema') == PROBE + '.sealed-predictions' and
            p.get('model_sha256') == model_sha and
            p.get('source_zip_sha256') == pins['source'] and
            p.get('producer_zip_sha256') == pins['producer'] and
            p.get('source_manifest_sha256') == source_hash and
            p.get('future_labels_seen') is False and
            p.get('target_host_attested') is False and
            p.get('training_energy_joules') is None and
            p.get('stem_selected') is False and
            p.get('production_accepted') is False and p.get('authority') == 'DENY_ALL',
            'unapproved or target-contaminated frozen Ridge predictions')

    # Algorithmically independent SVD (not the producer's dual ridge solver).
    # It cannot access withheld targets because no withheld path is passed in.
    svd = independent_svd_parity(paths['source'], pins['source'],
                                 paths['producer'], pins['producer'], m, p)
    require(svd.get('independently_replayed_all_predictions') is True and
            svd.get('future_cases') == CASES and
            svd.get('production_accepted') is False,
            'independent SVD failed to reproduce the label-blind Head')

    # This reviewer first reaches future target bytes *after* sealed SVD parity.
    withheld = original_zip(paths['withheld'], pins['withheld'])
    future_labels, target_receipt = _validate_withheld(withheld, source_hash,
                                                       manifest, source_rows)
    labels = {r['case_id']: r for r in future_labels['future_class_targets.jsonl']}
    orig = {r['case_id']: r for r in original_predictions['rows']}
    pred = {r['case_id']: r for r in p.get('rows', [])}
    future = {r['case_id']: r for r in source_rows['future_images.jsonl']}
    require(len(orig) == len(pred) == len(labels) == len(future) == CASES and
            set(orig) == set(pred) == set(labels) == set(future),
            'duplicate/omitted or mismatched original prediction cases')

    scores = Counter()
    per_class = {a: Counter() for a in LABELS}
    paired = {name: Counter() for name in ('fitted_vs_vision_ridge',
                                         'vision_ridge_vs_vision_prototype',
                                         'fitted_vs_vision_prototype')}
    same_label = 0
    for cid in sorted(future):
        s, t, op, rp = future[cid], labels[cid], orig[cid], pred[cid]
        for key in ('case_id', 'group_id', 'scope', 'observed_at'):
            require(s[key] == t[key] == op[key] == rp[key],
                    'source, label, and original pred case metadata differ')
        require(s['source_sha256'] == t['source_sha256'] and
                s['image_sha256'] == t['source_input_sha256'] ==
                op['source_input_sha256'] == rp['source_input_sha256'],
                'original image SHA / target / prediction mismatch')
        answer = op['predicted_labels']
        require(type(answer) is dict and set(answer) == set(ARMS) and
                all(type(v) is str and v in CLASSES for v in answer.values()) and
                rp['predicted_label'] in CLASSES and t['class_label'] in CLASSES,
                'unregistered real task prediction or label')
        outputs = {**answer, RIDGE: rp['predicted_label']}
        same_label += int(outputs['fitted'] == outputs[RIDGE])
        correct = {k: outputs[k] == t['class_label'] for k in LABELS}
        for arm, ok in correct.items():
            scores[arm] += int(ok)
            per_class[arm][t['class_label']] += int(ok)
        for a, b, key in (
            ('fitted', RIDGE, 'fitted_vs_vision_ridge'),
            (RIDGE, BASE, 'vision_ridge_vs_vision_prototype'),
            ('fitted', BASE, 'fitted_vs_vision_prototype'),
        ):
            chosen = ('both_correct' if correct[a] and correct[b] else
                      'rescued' if correct[a] else
                      'harmed' if correct[b] else 'both_wrong')
            paired[key][chosen] += 1
    paired_out = {}
    for name, counts in paired.items():
        for key in ('rescued', 'harmed', 'both_correct', 'both_wrong'):
            counts.setdefault(key, 0)
        require(sum(counts.values()) == CASES, 'invalid paired outcome census')
        paired_out[name] = {**dict(sorted(counts.items())),
                            'two_sided_exact_mcnemar_p': exact_mcnemar(
                                counts['rescued'], counts['harmed'])}
    return {
        'schema': 'hepta.e2.beans-natural-three-zip-preliminary.v1',
        'original_run_id': 38680856403,
        'original_source_sha': '927bf53b184c3947db17a129834046c5f03add04',
        'original_artifact_zip_sha256s': dict(sorted(pins.items())),
        'sealed_vision_ridge_model_sha256': model_sha,
        'sealed_vision_ridge_predictions_sha256': predictions_sha,
        'cases': CASES,
        'correct': {k: scores[k] for k in LABELS},
        'per_class_correct': {k: dict(sorted(per_class[k].items())) for k in LABELS},
        'fitted_bridge_equals_vision_ridge_prediction_labels': same_label,
        'paired': paired_out,
        'independent_svd': svd,
        'original_dino_granite_source_receipts_checked': True,
        'retrospective_original_public_TEST_only': True,
        'fourth_original_independent_geometry_zip_received': False,
        'four_original_archives_full_audit_passed': False,
        'external_model_or_ground_truth_attestation': False,
        'three_prospective_future_windows': False,
        'matched_parameter_and_total_compute_budget': False,
        'stem_selected': False,
        'production_accepted': False,
        'authority': 'DENY_ALL',
    }


def cli():
    cmd = argparse.ArgumentParser(description=__doc__)
    for k in ('source', 'producer', 'withheld'):
        cmd.add_argument('--' + k + '-zip', required=True, type=Path)
        cmd.add_argument('--' + k + '-sha256', required=True)
    for k in ('model', 'predictions'):
        cmd.add_argument('--' + k, required=True, type=Path)
        cmd.add_argument('--' + k + '-sha256', required=True)
    cmd.add_argument('--output', required=True, type=Path)
    args = cmd.parse_args()
    paths = {k: getattr(args, k + '_zip') for k in ('source', 'producer', 'withheld')}
    pins = {k: getattr(args, k + '_sha256') for k in paths}
    answer = review(paths, pins, args.model, args.model_sha256,
                    args.predictions, args.predictions_sha256)
    output = args.output
    require(output.parent.is_dir() and not output.exists() and not output.is_symlink(),
            'create-only output required')
    with output.open('xb') as stream:
        stream.write(canon(answer))
    print({'cases': answer['cases'], 'correct': answer['correct'],
           'fitted_vs_ridge_identical_labels':
               answer['fitted_bridge_equals_vision_ridge_prediction_labels'],
           'full_four_archive_audit': answer['four_original_archives_full_audit_passed'],
           'authority': answer['authority']})

if __name__ == '__main__':
    cli()
