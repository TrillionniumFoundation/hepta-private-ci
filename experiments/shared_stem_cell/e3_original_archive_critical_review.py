"""Read-only independent numerical/conformance review of E3 original ScienceQA ZIP.

Does not possess held-out labels or rerun original model weights. Source/claim
consistency and exploratory multiple-comparison tests only. DENY_ALL.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
import re
import stat
import zipfile
from pathlib import Path

ARCHIVE_SHA = '7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30'
SOURCE_HEAD = 'b8b2f10fe38506972301e77e3836729a90200673'
DATASET_REVISION = 'b9984af01798586705cee1fbdfa80a6dcbef04f1'
GRANITE_REVISION = '835ad14087e140460703cf0fae09f97d469d65c2'
DINO_REVISION = 'ed25f3a31f01632728cabb09d1542f84ab7b0056'
ARMS = ('text_only', 'unaligned_equal_fusion', 'rotated_equal_fusion',
        'bridge_image_only', 'bridge_equal_fusion', 'train_gate',
        'calibrated_fusion', 'image_masked')
BASE = 'hepta.e3-granite-dinov2-scienceqa.v1'
EXPECTED_FILES = {'SHA256SUMS','independent-descriptive-review.json',
                  'offline-tests.txt','optimized-tests.txt',
                  'predictions-before-labels.sha256',
                  'sealed-source-bound-predictions.json',
                  'source-blobs-SHA256','source-head.txt',
                  'source-seals.json','source-tree.txt','versions.txt'}

class AuditReject(ValueError): pass

def require(ok, why):
    if not ok: raise AuditReject(why)

def sha(raw): return hashlib.sha256(raw).hexdigest()

def decode(raw):
    def no_duplicates(pairs):
        out={}
        for k,v in pairs:
            require(k not in out, 'duplicated JSON key')
            out[k]=v
        return out
    data=json.loads(raw, object_pairs_hook=no_duplicates,
            parse_constant=lambda _: (_ for _ in ()).throw(AuditReject('nonfinite JSON')))
    return data

def exact_p(rescued, harmed):
    require(type(rescued) is int and type(harmed) is int and min(rescued,harmed)>=0,
            'invalid discordance count')
    n=rescued+harmed
    if not n:return 1.0
    return min(1.0, 2.0*math.fsum(math.comb(n,i) for i in range(min(rescued,harmed)+1))/2**n)

def holm(pvalues):
    """Exploratory Holm adjusted p, returns keyed p in original arm order."""
    for value in pvalues.values():
        require(type(value) in (float,int) and math.isfinite(value) and 0<=value<=1,
                'invalid p-value')
    ranked=sorted(pvalues,key=lambda k:(pvalues[k],k))
    out={}
    prev=0.0
    for idx,key in enumerate(ranked):
        prev=max(prev,(len(ranked)-idx)*float(pvalues[key]))
        out[key]=min(1.0,prev)
    return out

def _zip_files(archive: bytes, expected_zip_sha: str):
    require(type(expected_zip_sha) is str and len(expected_zip_sha)==64 and
            not set(expected_zip_sha).difference('0123456789abcdef') and
            0<len(archive)<=2_000_000 and sha(archive)==expected_zip_sha,
            'original artifact ZIP sha or size mismatch')
    out={}
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        entries=z.infolist()
        require(len(entries)==len(EXPECTED_FILES),'original artifact member count')
        total=0
        for e in entries:
            require(e.filename in EXPECTED_FILES and e.filename not in out and
                    not e.is_dir() and not e.flag_bits & 1 and
                    not stat.S_ISLNK(e.external_attr >> 16) and
                    0<e.file_size<=200_000,'malformed/unsafe ZIP member')
            total+=e.file_size
            require(total<=600_000,'oversized ZIP expansion')
            out[e.filename]=z.read(e)
    require(set(out)==EXPECTED_FILES,'original archive member inventory changed')
    checks=out['SHA256SUMS'].decode('ascii').splitlines()
    found=set()
    for line in checks:
        match=re.fullmatch(r'([a-f0-9]{64})  \./([^/]+)',line)
        require(match is not None,'malformed original SHA256SUMS')
        hexhash,filename=match.groups()
        require(filename!='SHA256SUMS' and filename in out and filename not in found,
                'SHA256SUMS contains extra/duplicate file')
        found.add(filename)
        require(sha(out[filename])==hexhash,'archived file digest mismatch')
    require(found==set(out)-{'SHA256SUMS'},'unbound original archive member')
    return out

def review_archive(archive: bytes, expected_zip_sha: str = ARCHIVE_SHA):
    files=_zip_files(archive,expected_zip_sha)
    require(files['source-head.txt'].decode().strip()==SOURCE_HEAD,
            'wrong exact pretrained E3 source commit')
    original=decode(files['sealed-source-bound-predictions.json'])
    score=decode(files['independent-descriptive-review.json'])
    source=decode(files['source-seals.json'])
    seal_line=files['predictions-before-labels.sha256'].decode().strip().split()
    require(seal_line and seal_line[0]==sha(files['sealed-source-bound-predictions.json']),
            'pre-label prediction seal does not match original byte digest')
    require(original.get('schema')==BASE+'.sealed-predictions' and
            score.get('schema')==BASE+'.independent-heldout-review' and
            original.get('source_sha256')==score.get('source_sha256')==source.get('source_sha256') and
            original.get('fit_labels_sha256')==source.get('fit_labels_sha256') and
            score.get('holdout_targets_sha256')==source.get('private_test_labels_sha256') and
            score.get('sealed_predictions_sha256')==seal_line[0] and
            source.get('dataset_revision')==DATASET_REVISION,
            'source/label/producer/reviewer identity mismatch')
    require(original.get('stem_model',{}).get('revision')==GRANITE_REVISION and
            original.get('vision_model',{}).get('revision')==DINO_REVISION and
            original.get('held_labels_visible_to_inference') is False and
            original.get('production_accepted') is False and
            score.get('production_accepted') is False and score.get('stem_winner') is None and
            score.get('authority')=='DENY_ALL' and
            score.get('historical_scienceqa_release_not_future') is True and
            score.get('visual_necessity_ground_truth_adjudicated') is False and
            original.get('physical_text_forward_batches',0)>0 and
            original.get('physical_vision_forward_batches',0)>0 and
            original.get('fit',{}).get('private_cell_head_parameters')==769 and
            original.get('fit',{}).get('cell_optimizer_updates')==80 and
            original.get('fit',{}).get('calibration_selected_weight')==0.0 and
            original.get('fit',{}).get('organ_bridge_parameter_count')==147840 and
            original.get('fit',{}).get('train_cases')==96 and
            original.get('fit',{}).get('calibration_cases')==32 and
            original.get('fit',{}).get('holdout_cases')==64,
            'unsupported original physical/learning/safety claim')
    require(original.get('arms')==list(ARMS) and
            set(score.get('arms',{}))==set(ARMS) and
            len(original.get('predictions',[]))==64 and
            score.get('original_heldout_cases')==64,
            'missing original arm/case inventory')
    observed=set();deltas={k:[] for k in ARMS};changes={k:0 for k in ARMS}
    for row in original['predictions']:
        rid=row.get('id')
        require(type(rid) is str and rid and rid not in observed and
                row.get('split')=='test' and type(row.get('source_input_sha256')) is str and
                len(row['source_input_sha256'])==64 and
                set(row.get('arms',{}))==set(ARMS),
                'invalid heldout prediction identity')
        observed.add(rid)
        for arm in ARMS:
            vals=row['arms'][arm]
            require(type(vals) is list and len(vals)==4 and
                    all(type(x) in (float,int) and math.isfinite(x) and 0<=x<=1 for x in vals) and
                    abs(math.fsum(vals)-1)<1e-5,'missing or invalid probability vector')
            ref=row['arms']['text_only']
            deltas[arm].append(math.fsum(abs(x-y) for x,y in zip(vals,ref)))
            if vals.index(max(vals))!=ref.index(max(ref)):
                changes[arm]+=1
        require(row['arms']['image_masked']==row['arms']['text_only'] and
                row['arms']['calibrated_fusion']==row['arms']['text_only'],
                'calibration/image-masked exact parity fails')
    paired=score.get('paired_vs_text_only')
    require(type(paired) is dict and set(paired)==set(ARMS)-{'text_only','image_masked'},
            'original paired inventory incomplete')
    pvals={}
    for arm,record in paired.items():
        r=record.get('rescued_errors_vs_text')
        h=record.get('new_errors_vs_text')
        require(type(r) is int and type(h) is int and
                record.get('discordant_cases')==r+h and
                abs(record.get('mcnemar_unadjusted_exact_p')-exact_p(r,h))<1e-13,
                'original reported paired exact test differs from recomputation')
        pvals[arm]=exact_p(r,h)
    for arm,item in score['arms'].items():
        require(type(item.get('correct')) is int and
                0<=item['correct']<=64 and item.get('cases')==64 and
                abs(item.get('accuracy')-item['correct']/64)<1e-14,
                'untrusted reported accuracy / case coverage')
    corrected=holm(pvals)
    return {
        'schema':'hepta.e3.scienceqa-original-source-bound-critical-review.v1',
        'original_zip_sha256':expected_zip_sha,'original_source_head':SOURCE_HEAD,
        'predictions_sha256':seal_line[0],
        'observed_predictions':64,
        'archived_text_forward_batches':original['physical_text_forward_batches'],
        'archived_vision_forward_batches':original['physical_vision_forward_batches'],
        'original_correct':{a:score['arms'][a]['correct'] for a in ARMS},
        'exploratory_holm_adjusted_p_vs_text':corrected,
        'exploratory_unadjusted_p_vs_text':pvals,
        'prediction_changes_vs_text':changes,
        'mean_probability_l1_vs_text':{a:math.fsum(deltas[a])/64 for a in ARMS},
        'original_calibration_selected_zero_visual_weight':True,
        'original_heldout_label_rows_not_in_archive':True,
        'independently_recomputed_accuracy_from_labels':False,
        'external_model_or_ground_truth_attested':False,
        'predeclared_image_necessity_ground_truth':False,
        'real_prospective_future_windows':False,
        'training_cost_competitor_equalized':False,
        'stem_winner':None,'production_accepted':False,'authority':'DENY_ALL'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--original-zip',type=Path,required=True)
    p.add_argument('--sha256',default=ARCHIVE_SHA)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    require(not a.original_zip.is_symlink() and a.original_zip.is_file(),'unsafe original archive path')
    result=review_archive(a.original_zip.read_bytes(),a.sha256)
    require(not a.output.exists() and not a.output.is_symlink() and a.output.parent.is_dir(),
            'create-only local audit output')
    a.output.write_text(json.dumps(result,sort_keys=True,separators=(',',':'))+'\n')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
