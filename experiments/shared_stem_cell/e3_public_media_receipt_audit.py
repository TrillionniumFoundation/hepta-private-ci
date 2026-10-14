#!/usr/bin/env python3
"""Read-only independent numeric review of one successful public CLIP/ScienceQA study.

No model is loaded or authenticated. A publisher/content digest claim is not a
signature. This study is NOT a Granite+DINOv2 or EmbeddingGemma2 comparison.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from zipfile import ZipFile, BadZipFile

ARCHIVE_SHA256 = '1836173b1f92f21bb26296ccf06e929646ff60ff933e3880716dcce62faf3f53'
ARCHIVE_ARTIFACT = 11881821872
ARCHIVE_RUN = 38532887290
ROOTS = {
    'hepta-public-media': {'train': 64, 'calibration': 16, 'holdout': 32},
    'hepta-calibrated-media': {'train': 64, 'calibration': 32, 'holdout': 64},
    'hepta-choice-media': {'train': 64, 'calibration': 32, 'holdout': 64},
}
REQUIRED_OPERATORS = {'as_observed', 'mask:image', 'mask:text', 'rotate:image', 'rotate:text'}
MAX_ARCHIVE_BYTES = 4_000_000
MAX_EXTRACTED_BYTES = 16_000_000

class Invalid(ValueError):
    pass


def pairs(entries):
    out = {}
    for k, v in entries:
        if k in out:
            raise Invalid('duplicate JSON key')
        out[k] = v
    return out


def load(data: bytes):
    if len(data) > 5_000_000:
        raise Invalid('oversized JSON document')
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda val: (_ for _ in ()).throw(Invalid('nonfinite JSON')))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_check(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise Invalid('invalid SHA-256')
    return value


def probability_matrix(matrix, count):
    if not isinstance(matrix, list) or len(matrix) != count:
        raise Invalid('missing prediction row coverage')
    for row in matrix:
        if not isinstance(row, list) or len(row) != 4:
            raise Invalid('wrong option width')
        if any(type(v) not in (float, int) or not math.isfinite(v) or v < 0 or v > 1 for v in row):
            raise Invalid('invalid probabilities')
        if abs(sum(row) - 1) > 0.0001:
            raise Invalid('unnormalized choice probabilities')
    return matrix


def scores(matrix, labels):
    probability_matrix(matrix, len(labels))
    choices = [max(range(4), key=lambda i: row[i]) for row in matrix]
    correct = [int(pred == gold) for pred, gold in zip(choices, labels)]
    nll = -sum(math.log(max(row[gold], 1e-30)) for row, gold in zip(matrix, labels))/len(labels)
    return {'cases': len(labels), 'correct': sum(correct), 'nll': nll, 'correct_by_case': correct}


def compare(actual, reported, label):
    if reported.get('cases') != actual['cases'] or reported.get('correct') != actual['correct']:
        raise Invalid('published score differs from raw predictions: '+label)
    if not isinstance(reported.get('nll'), (int, float)) or abs(reported['nll'] - actual['nll']) > 2e-5:
        raise Invalid('published NLL differs from raw predictions: '+label)


def verify_interventions(original, report, labels):
    interventions = original.get('modality_interventions')
    if not isinstance(interventions, dict) or set(interventions.get('predictions', {})) != REQUIRED_OPERATORS:
        raise Invalid('incomplete modality intervention comparison')
    if interventions.get('causal_semantics_established') is not False:
        raise Invalid('unsupported causal claim')
    n = len(labels)
    pred = interventions['predictions']
    observed = scores(pred['as_observed'], labels)['correct_by_case']
    out = {}
    for name in sorted(REQUIRED_OPERATORS):
        x = scores(pred[name], labels)
        a = x['correct_by_case']
        gain = sum(one and not orig for one, orig in zip(a, observed))
        loss = sum(orig and not one for one, orig in zip(a, observed))
        count = {'correct': x['correct'], 'gains': gain, 'losses': loss, 'ties': n-gain-loss,
                 'delta_accuracy_vs_observed': (gain-loss)/n}
        stored = report['modality_intervention_scores']['holdout']['paired'][name]
        for field, value in (('gains',gain),('losses',loss),('ties',n-gain-loss)):
            if stored.get(field) != value:
                raise Invalid('reported intervention discordance changed: '+name)
        if abs(stored['accuracy_delta']-count['delta_accuracy_vs_observed']) > 1e-9:
            raise Invalid('intervention accuracy delta altered: '+name)
        out[name] = count
    rows = interventions.get('source_rows')
    if set(rows) != REQUIRED_OPERATORS:
        raise Invalid('missing source intervention identities')
    if rows['as_observed'].get('rows') != list(range(n)):
        raise Invalid('raw intervention row order changed')
    for mod in ('image', 'text'):
        if rows['mask:'+mod].get('rows') != [None]*n:
            raise Invalid('mask did not remove source rows')
        if rows['rotate:'+mod].get('rows') != list(range(1,n))+[0]:
            raise Invalid('rotation failed to change source rows')
    if interventions.get('partitions') != ['holdout']*n:
        raise Invalid('intervention not limited to holdout')
    return out


def review(archive: Path):
    blob = archive.read_bytes()
    if not 0 < len(blob) <= MAX_ARCHIVE_BYTES or sha(blob) != ARCHIVE_SHA256:
        raise Invalid('missing or changed approved source ZIP')
    try:
        with ZipFile(archive) as z:
            members = z.infolist()
            names = [info.filename for info in members]
            if (len(names) != len(set(names)) or
                    sum(info.file_size for info in members) > MAX_EXTRACTED_BYTES or
                    any(not name or name.startswith('/') or '\\' in name or '..' in name.split('/')
                        for name in names)):
                raise Invalid('unsafe ZIP structure')
            docs, group_sets, input_image_sha = {}, [], []
            for root, expected in ROOTS.items():
                dataset_name = root+'/dataset.jsonl'
                raw_rows = z.read(dataset_name)
                rows = [load(raw) for raw in raw_rows.splitlines()]
                tally = Counter(row['split'] for row in rows)
                if tally != expected or len({r['case_id'] for r in rows}) != len(rows):
                    raise Invalid('incomplete or duplicate dataset cohort')
                groups = {r['group'] for r in rows}
                if len(groups) != len(rows) or any(groups & other for other in group_sets):
                    raise Invalid('nonindependent source groups across cohorts')
                group_sets.append(groups)
                image_ids = {r['inputs']['image']['sha256'] for r in rows}
                if any(image_ids & old for old in input_image_sha):
                    raise Invalid('recycled image bytes across cohorts')
                input_image_sha.append(image_ids)
                test = [r for r in rows if r['split'] == 'holdout']
                labels = [r['label'] for r in test]
                if any(type(y) is not int or y not in range(4) for y in labels):
                    raise Invalid('invalid independent source label')
                suffix = '/choice-execution' if root == 'hepta-choice-media' else '/media-execution'
                pred_name = root+suffix+'/predictions.json'
                pred_bytes = z.read(pred_name)
                pred = load(pred_bytes)
                report = load(z.read(root+suffix+'/report.json'))
                if pred.get('case_ids') != [r['case_id'] for r in test]:
                    raise Invalid('predictions mismatch untouched holdout IDs')
                if sha(pred_bytes) != report.get('prediction_sha256'):
                    raise Invalid('published output SHA mismatch')
                scores_map = pred.get('probabilities') if suffix == '/choice-execution' else pred.get('predictions')
                frozen = {} if suffix == '/choice-execution' else pred.get('frozen_predictions')
                if not isinstance(scores_map, dict) or not isinstance(frozen, dict):
                    raise Invalid('missing trained/frozen predictions')
                if report.get('production_accepted') is not False or report.get('simulated_towers') is not False or report.get('independent_evaluation') is not False:
                    raise Invalid('publication authority or model execution kind changed')
                if suffix == '/media-execution':
                    if not frozen or not isinstance(report.get('scores'), list):
                        raise Invalid('missing matched frozen control or published scores')
                    published = {}
                    for item in report['scores']:
                        if not isinstance(item, dict) or not isinstance(item.get('arm'), str) or item['arm'] in published:
                            raise Invalid('invalid or duplicate published media score')
                        if item.get('split') != 'holdout' or item.get('cases') != len(labels):
                            raise Invalid('wrong published media score cohort')
                        published[item['arm']] = item
                    if set(published) != set(scores_map):
                        raise Invalid('media score coverage differs from raw predictions')
                calculated = {}
                for name, matrix in {**scores_map, **{k+':frozen':v for k,v in frozen.items()}}.items():
                    res=scores(matrix,labels)
                    calculated[name] = {'correct': res['correct'], 'total':res['cases'], 'nll':res['nll']}
                    if suffix == '/choice-execution':
                        compare(res, report['scores'][name], root+'/'+name)
                    elif name in scores_map:
                        entry = published[name]
                        if (type(entry.get('accuracy')) not in (float, int) or
                                not math.isfinite(entry['accuracy']) or
                                abs(entry['accuracy'] - res['correct']/len(labels)) > 1e-8):
                            raise Invalid('published media accuracy differs from raw probabilities: '+name)
                diag = {'n_holdout':len(test), 'scores':calculated, 'is_real_physical_public_model_claim':True,
                        'production_accepted':False}
                if suffix == '/media-execution':
                    diag['modality_interventions'] = verify_interventions(pred,report,labels)
                else:
                    if pred.get('selected_key') != report.get('selected_key'):
                        raise Invalid('selected model drift')
                    if report.get('heldout_option_permutation_passed') is not True:
                        raise Invalid('source option-order control failed')
                    diag['selected_key'] = report['selected_key']
                docs[root]=diag
            return {'schema':'hepta.e3-public-clip-receipt-audit.v1',
                    'source_artifact_id':ARCHIVE_ARTIFACT,'source_workflow_run':ARCHIVE_RUN,
                    'source_zip_sha256':ARCHIVE_SHA256,'results':docs,
                    'archived_public_forward_observations':True,
                    'independently_attested_original_model_and_labels':False,
                    'granite_dinov2_or_gemma_multimodal_comparison_performed':False,
                    'natural_future_NDU_established':False,'all_acceptance_gates_passed':False,
                    'authority':'DENY_ALL','production_promotion_permitted':False}
    except (BadZipFile,KeyError,TypeError,IndexError,UnicodeDecodeError) as exc:
        raise Invalid('invalid or incomplete physical source archive') from exc


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-zip',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args()
    result=review(a.source_zip)
    with a.output.open('x',encoding='utf-8') as file:
        json.dump(result,file,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)
        file.write('\n')

if __name__ == '__main__':
    main()
