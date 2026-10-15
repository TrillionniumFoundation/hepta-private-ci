"""Producer-independent, exact-count and small-n uncertainty audit for Beans E2.

No imports of model, source author, Bridge or first scoring process. Not a
production permission or scientifically qualified future evidence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

PREFIX = 'hepta.e2.beans-natural-retrospective.v1'
ARMS = ('fitted', 'rotated_target_control', 'unaligned_identity', 'vision_prototype')
CLASSES = ('angular_leaf_spot', 'bean_rust', 'healthy')
HEX = set('0123456789abcdef')
DATA_REVISION = '27aa014ce09b193e1a6f58112d4a66e0eddb69c5'
TRAIN_PARQUET_SHA = '7f905a7323966a58e89b8e839ed656bb869fc82d16a3fadc7dce40972a5f8b19'
TEST_PARQUET_SHA = '534a6b0648f585d69b7ec0ad7a7540720d60c8db8106dc6d0508296316f6cb27'
SOURCE_FILES = {'train_images.jsonl', 'future_images.jsonl', 'train_anchors.jsonl', 'train_class.jsonl'}
WITHHELD_FILES = {'future_caption_targets.jsonl', 'future_class_targets.jsonl'}

class AuditFailure(ValueError):
    pass

def require(condition, message):
    if not condition: raise AuditFailure(message)

def sha(raw): return hashlib.sha256(raw).hexdigest()

def canonical(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode()

def pairs(items):
    output = {}
    for name, value in items:
        require(name not in output, 'duplicate JSON key')
        output[name] = value
    return output

def parse(raw):
    val = json.loads(raw, object_pairs_hook=pairs,
                     parse_constant=lambda _: (_ for _ in ()).throw(AuditFailure('nonfinite JSON')))
    require(raw == canonical(val), 'noncanonical JSON input')
    return val

def read_pinned(path, expected, jsonl=False):
    require(type(expected) is str and len(expected) == 64 and not (set(expected) - HEX),
            'invalid source SHA-256')
    path = Path(path)
    require(not path.is_symlink() and path.is_file() and 0 < path.stat().st_size <= 4_000_000,
            'missing, symlinked or oversized input')
    blob = path.read_bytes()
    require(sha(blob) == expected, 'changed pinned artifact')
    if not jsonl: return parse(blob)
    require(blob.endswith(b'\n'), 'JSONL missing final newline')
    records = [parse(line + b'\n') for line in blob.splitlines()]
    require(1 <= len(records) <= 256, 'invalid row cardinality')
    return records

def require_original_target_seal(source_manifest, source_digest, target_manifest,
                                 target_digest, future_source_digest, future_target_digest):
    """Bind original, separately withheld target bytes before class scoring.

    SHA-256 gives byte identity, NOT independent label-owner attestation.
    Returns no production or model-selection authority.
    """
    def good_sha(value):
        return type(value) is str and len(value)==64 and not set(value).difference(HEX)
    require(all(good_sha(v) for v in (source_digest, target_digest,
            future_source_digest, future_target_digest)), 'missing strict byte pins')
    require(type(source_manifest) is dict and
            sha(canonical(source_manifest))==source_digest and
            source_manifest.get('schema')==PREFIX+'.source-plan' and
            source_manifest.get('dataset_repo')=='AI-Lab-Makerere/beans' and
            source_manifest.get('dataset_revision')==DATA_REVISION and
            source_manifest.get('train_parquet_sha256')==TRAIN_PARQUET_SHA and
            source_manifest.get('phase_time_is_not_original_timestamp') is True and
            source_manifest.get('test_cases')==24 and
            source_manifest.get('production_accepted') is False and
            source_manifest.get('stem_selected') is False and
            source_manifest.get('authority')=='DENY_ALL' and
            type(source_manifest.get('file_sha256s')) is dict and
            set(source_manifest['file_sha256s'])==SOURCE_FILES and
            all(good_sha(x) for x in source_manifest['file_sha256s'].values()) and
            source_manifest['file_sha256s']['future_images.jsonl']==future_source_digest,
            'source must bind original Beans bytes without future labels')
    require(type(target_manifest) is dict and
            set(target_manifest)=={'schema','source_manifest_sha256',
                'original_test_parquet_sha256','file_sha256s','production_accepted','authority'} and
            sha(canonical(target_manifest))==target_digest and
            target_manifest['schema']==PREFIX+'.withheld-target-plan' and
            target_manifest['source_manifest_sha256']==source_digest and
            target_manifest['original_test_parquet_sha256']==TEST_PARQUET_SHA and
            target_manifest['production_accepted'] is False and
            target_manifest['authority']=='DENY_ALL' and
            type(target_manifest['file_sha256s']) is dict and
            set(target_manifest['file_sha256s'])==WITHHELD_FILES and
            all(good_sha(x) for x in target_manifest['file_sha256s'].values()) and
            target_manifest['file_sha256s']['future_class_targets.jsonl']==future_target_digest,
            'unverified withheld original test-target provenance')
    return {'withheld_manifest_sha256':target_digest,
            'target_byte_lineage_consistent':True,
            'independent_ground_truth_owner_attested':False}


def wilson(correct, total):
    require(type(correct) is int and type(total) is int and 0 <= correct <= total and total > 0,
            'invalid accuracy count')
    z = 1.959963984540054
    p = correct / total
    den = 1 + z*z/total
    half = z*math.sqrt((p*(1-p) + z*z/(4*total)) / total) / den
    mid = (p + z*z/(2*total)) / den
    return [0.0 if correct == 0 else max(0.0, mid-half),
            1.0 if correct == total else min(1.0, mid+half)]

def exact_mcnemar(rescued, harmed):
    require(type(rescued) is int and type(harmed) is int and min(rescued,harmed) >= 0,
            'invalid discordance')
    n = rescued + harmed
    if n == 0: return 1.0
    return min(1.0, 2.0 * sum(math.comb(n, k) for k in range(min(rescued,harmed)+1)) / (2**n))

def audit(source_manifest, source_rows, target_rows, predictions, original):
    require(type(source_manifest) is dict and source_manifest.get('schema') == PREFIX + '.source-plan'
            and source_manifest.get('dataset_repo') == 'AI-Lab-Makerere/beans'
            and source_manifest.get('natural_images') is True
            and source_manifest.get('phase_time_is_not_original_timestamp') is True
            and source_manifest.get('test_cases') == 24
            and source_manifest.get('authority') == 'DENY_ALL'
            and source_manifest.get('production_accepted') is False
            and type(source_manifest.get('file_sha256s')) is dict,
            'unapproved source manifest or false prospective identity')
    require(type(predictions) is dict and predictions.get('schema') == PREFIX + '.class-predictions'
            and predictions.get('natural_images') is True
            and predictions.get('arms') == list(ARMS)
            and predictions.get('future_labels_seen') is False
            and predictions.get('stem_selected') is False
            and predictions.get('production_accepted') is False
            and predictions.get('authority') == 'DENY_ALL', 'unsealed or authority-claiming prediction')
    require(type(original) is dict and original.get('schema') == PREFIX + '.independent-class-readout'
            and original.get('total_cases') == 24
            and original.get('chronological_future_test') is False
            and original.get('independent_ground_truth_owner') is False
            and original.get('production_accepted') is False
            and original.get('model_selection_permitted') is False
            and original.get('authority') == 'DENY_ALL', 'invalid prior independent score')
    require(all(type(rows) is list and len(rows) == 24 for rows in
                (source_rows, target_rows, predictions.get('rows'))), 'incomplete original panel')
    src, tgt, pred = {}, {}, {}
    for row in source_rows:
        require(type(row) is dict and set(row) == {'case_id','group_id','scope','observed_at',
                'split','condition','image_path','image_sha256','question','source_sha256'}
                and row['split'] == 'future' and row['condition'] == 'vision_required',
                'unapproved future source fields')
        key = row['case_id']
        require(type(key) is str and key and key not in src, 'duplicate source')
        src[key] = row
    for row in target_rows:
        require(type(row) is dict and set(row) == {'case_id','group_id','scope','observed_at',
                'source_sha256','source_input_sha256','class_label'}
                and row['class_label'] in CLASSES, 'invalid hidden target')
        key = row['case_id']
        require(key not in tgt, 'duplicate target')
        tgt[key] = row
    for row in predictions['rows']:
        require(type(row) is dict and set(row) == {'case_id','group_id','scope','observed_at',
                'source_input_sha256','predicted_labels'}
                and type(row['predicted_labels']) is dict
                and set(row['predicted_labels']) == set(ARMS)
                and all(x in CLASSES for x in row['predicted_labels'].values()),
                'invalid prediction census')
        key = row['case_id']
        require(key not in pred, 'duplicate prediction')
        pred[key] = row
    require(set(src) == set(tgt) == set(pred), 'case/source/label coverage differs')
    counts = {a:0 for a in ARMS}
    per_class = {a:{c:0 for c in CLASSES} for a in ARMS}
    class_counts = {c:0 for c in CLASSES}
    paired = {a:{'rescued':0,'harmed':0,'both_correct':0,'both_wrong':0}
              for a in ARMS if a != 'vision_prototype'}
    for case, s in src.items():
        t, p = tgt[case], pred[case]
        for key in ('case_id','group_id','scope','observed_at'):
            require(s[key] == t[key] == p[key], 'wrong paired metadata')
        require(s['source_sha256'] == t['source_sha256'] and
                s['image_sha256'] == t['source_input_sha256'] == p['source_input_sha256'],
                'changed actual image identity')
        class_counts[t['class_label']] += 1
        correct = {a:p['predicted_labels'][a] == t['class_label'] for a in ARMS}
        for a in ARMS:
            counts[a] += int(correct[a]); per_class[a][t['class_label']] += int(correct[a])
        for a in paired:
            current, base = correct[a], correct['vision_prototype']
            key = ('rescued' if current and not base else 'harmed' if base and not current
                   else 'both_correct' if current else 'both_wrong')
            paired[a][key] += 1
    require(class_counts == {c:8 for c in CLASSES}, 'imbalanced original TEST groups')
    require(original['accuracy'] == {a:{'correct':counts[a],'total':24} for a in ARMS},
            'first readout class counts differ from raw prediction/target')
    require(original['paired_vs_frozen_vision_prototype'] == paired,
            'first readout paired changes differ from raw data')
    for a in ARMS:
        for c in CLASSES:
            require(original['per_class'][a][c] == {'correct':per_class[a][c], 'total':8},
                    'first readout per-class count differs from raw data')
    raw_p = {a:exact_mcnemar(paired[a]['rescued'],paired[a]['harmed']) for a in paired}
    ordered = sorted(raw_p, key=lambda a:(raw_p[a],a))
    adjusted, prev = {}, 0.0
    for index, a in enumerate(ordered):
        prev = min(1.0, max(prev, (len(ordered)-index)*raw_p[a]))
        adjusted[a] = prev
    return {'schema':PREFIX+'.second-opinion-paired-uncertainty.v1',
            'cases':24, 'original_source_identity_rechecked':True,
            'raw_predictions_independently_rescored':True,
            'accuracy':{a:{'correct':counts[a],'total':24,
                           'wilson95':wilson(counts[a],24)} for a in ARMS},
            'paired_vs_frozen_vision_prototype':{
                a:{**paired[a], 'two_sided_exact_mcnemar_p':raw_p[a],
                   'holm_adjusted_p_three_comparisons':adjusted[a]} for a in paired},
            'source_class_counts':class_counts, 'p_values_only_descriptive':True,
            'natural_retrospective_test':True,'three_chronological_future_windows':False,
            'source_group_independence_attested':False,
            'independent_ground_truth_owner':False,'model_selected':False,
            'production_accepted':False,'authority':'DENY_ALL'}

def main():
    a = argparse.ArgumentParser()
    for key in ('source_manifest','future_source','future_targets','sealed_predictions','original_readout'):
        a.add_argument('--'+key.replace('_','-'), required=True, type=Path)
        a.add_argument('--'+key.replace('_','-')+'-sha256', required=True)
    a.add_argument('--target-manifest', required=True, type=Path)
    a.add_argument('--target-manifest-sha256', required=True)
    a.add_argument('--output', required=True, type=Path)
    p=a.parse_args()
    m=read_pinned(p.source_manifest,p.source_manifest_sha256)
    target_manifest=read_pinned(p.target_manifest,p.target_manifest_sha256)
    proof=require_original_target_seal(m,p.source_manifest_sha256,target_manifest,
              p.target_manifest_sha256,p.future_source_sha256,p.future_targets_sha256)
    s=read_pinned(p.future_source,p.future_source_sha256,True)
    t=read_pinned(p.future_targets,p.future_targets_sha256,True)
    q=read_pinned(p.sealed_predictions,p.sealed_predictions_sha256)
    o=read_pinned(p.original_readout,p.original_readout_sha256)
    require(m['file_sha256s']['future_images.jsonl']==p.future_source_sha256,
            'source manifest and future image metadata differ')
    require(o['source_manifest_sha256']==p.source_manifest_sha256 and
            o['predictions_sha256']==p.sealed_predictions_sha256,
            'original evaluator not bound to same sealed case cohort')
    result=audit(m,s,t,q,o)
    result.update(proof)
    require(not p.output.exists() and p.output.parent.is_dir(), 'write-once output required')
    with p.output.open('xb') as f:f.write(canonical(result))
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
