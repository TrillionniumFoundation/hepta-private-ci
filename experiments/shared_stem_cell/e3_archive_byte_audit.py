"""Source-bound E3 numerical ZIP verification; not an NDU or publisher attestation.

This implementation checks only completed HISTORICAL Granite/DINO and OCR
numerical ZIPs. It does not audit any later clean five-arm run; that requires
a separate original multi-artifact verifier and independent TEST evaluator.
No pretrained weights, original media or TEST labels are opened.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import zipfile

SCHEMA = 'hepta.e3-physical-original-numeric-zip-byte-audit.v1'
BASE_ZIP = 'f421f20cdb5d35becf5e93ed63e58996d48701c2b27b979d608e2b05b6b61f30'
OLD_OCR_ZIP = 'c80d5b9cda23a8a6ee144aeba459dc516b6b67c854c2c5fe86d3b2ba94884964'
BASE_PRED = 'e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7'
OLD_OCR_PRED = '96ba4117a37689eeafe2415661e028a9170b7ccdd8c345b6b8d6241b7a928885'
SOURCE = 'a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202'
FIT = 'e8506bc65f96501b6b2fa4e4ae04c094c2b6b17b353de528a051136569e2849e'
GRANITE = ('ibm-granite/granite-embedding-97m-multilingual-r2','835ad14087e140460703cf0fae09f97d469d65c2')
DINO = ('facebook/dinov2-small','ed25f3a31f01632728cabb09d1542f84ab7b0056')
GEMMA = ('google/embeddinggemma-2','914f7f89142e33e77833254d9c9b90c3cef7303b')
VALID_MEMBER = re.compile(r'[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*\Z')

class OriginalZipDenied(ValueError): pass

def need(value,reason):
    if not value: raise OriginalZipDenied(reason)

def hash_bytes(data): return hashlib.sha256(data).hexdigest()

def issha(value): return type(value) is str and len(value)==64 and all(x in '0123456789abcdef' for x in value)

def parse(data):
    def pairs(items):
        d={}
        for k,v in items:
            need(k not in d,'duplicate JSON key')
            d[k]=v
        return d
    def numeric(raw):
        v=float(raw)
        need(math.isfinite(v),'nonfinite JSON float')
        return v
    x=json.loads(data,object_pairs_hook=pairs,parse_constant=lambda v: (_ for _ in ()).throw(OriginalZipDenied('nonfinite constant')),parse_float=numeric)
    need(type(x) is dict,'only original bounded JSON objects')
    return x

def original_zip(path, expected, *, expected_members=None):
    path=Path(path)
    need(issha(expected) and path.is_file() and not path.is_symlink() and
         0<path.stat().st_size<=8*1024*1024,'unavailable/oversized original numerical archive')
    raw=path.read_bytes()
    need(hash_bytes(raw)==expected,'original archive ZIP SHA drift')
    with zipfile.ZipFile(path) as z:
        items=z.infolist()
        need(1<=len(items)<=32,'unknown ZIP member count')
        out={}
        total=0
        for item in items:
            name=item.filename
            mode=item.external_attr>>16
            need(type(name) is str and VALID_MEMBER.fullmatch(name) is not None and
                 '..' not in name.split('/') and name not in out,
                 'ZIP traversal, duplicate, or unsupported name')
            need(not item.is_dir() and not (item.flag_bits&1) and
                 stat.S_IFMT(mode) != stat.S_IFLNK and
                 item.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED),
                 'directory/encrypted/symlink/unsupported compression')
            need(0<item.file_size<=2*1024*1024 and item.compress_size<=4*1024*1024 and
                 item.file_size<=max(1,item.compress_size)*200,
                 'ZIP oversized or decompression bomb member')
            total+=item.file_size
            need(total<=8*1024*1024,'ZIP unbounded decompressed size')
            data=z.read(item)
            need(len(data)==item.file_size,'ZIP decoded length changed')
            out[name]=data
        if expected_members is not None:
            need(set(out)==set(expected_members),'ZIP omitted/replaced original numeric members')
        return out

def preds(items):
    out={}
    for x in items:
        need(type(x) is dict and issha(x.get('id')) and issha(x.get('group')) and
             issha(x.get('source_input_sha256')) and x['id'] not in out,
             'unbound/duplicate original 64-case source')
        out[x['id']]=x
    need(len(out)==64,'64 original held source rows required')
    return out

def probabilities(values):
    need(type(values) is list and len(values)==4 and
         all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in values) and
         abs(sum(values)-1)<1e-4,'invalid four-answer source prediction')
    return values

def guess(v): return max(range(4),key=lambda i:(v[i],-i))

def check_baseline(base):
    need(hash_bytes(base['sealed-source-bound-predictions.json'])==BASE_PRED,'baseline prediction member SHA drift')
    manifest=base['SHA256SUMS'].decode('ascii').splitlines()
    validated=set()
    for line in manifest:
        m=re.fullmatch(r'([0-9a-f]{64})  \./([a-zA-Z0-9_.-]+)',line)
        need(m is not None and m.group(2) in base and m.group(2) not in validated,'baseline original SHA256SUMS changed')
        need(hash_bytes(base[m.group(2)])==m.group(1),'baseline original member SHA changed')
        validated.add(m.group(2))
    need(validated==set(base)-{'SHA256SUMS'},'incomplete original baseline member inventory')
    d=parse(base['sealed-source-bound-predictions.json'])
    need(d.get('schema')=='hepta.e3-granite-dinov2-scienceqa.v1.sealed-predictions' and
         d.get('source_sha256')==SOURCE and d.get('fit_labels_sha256')==FIT and
         d.get('production_accepted') is False and
         d.get('held_labels_visible_to_inference') is False and
         d.get('independent_ground_truth_observer') is False,
         'original source/scoring/authority boundary drift')
    stem=d.get('stem_model',{});vis=d.get('vision_model',{})
    need((stem.get('repo'),stem.get('revision'))==GRANITE and
         (vis.get('repo'),vis.get('revision'))==DINO and
         issha(stem.get('sha256')) and issha(vis.get('sha256')) and
         d.get('physical_text_forward_batches')==60 and
         d.get('physical_vision_forward_batches')==24,'original actual pinned pretrained model receipt changed')
    return d,preds(d['predictions'])

def check_ocr(file_bytes, originals, *, require_historical_original=False):
    doc=parse(file_bytes)
    model=doc.get('model',{})
    need(doc.get('schema')=='hepta.e3.ocr-granite-physical.v1' and
         doc.get('source_sha256')==SOURCE and doc.get('authority')=='DENY_ALL' and
         doc.get('production_accepted') is False and doc.get('stem_selected') is False and
         doc.get('signed_model_origin_authenticated') is False and
         (model.get('repo'),model.get('revision'))==GRANITE and
         issha(model.get('pipeline_digest')) and
         doc.get('ocr_engine')=='tesseract' and
         doc.get('physical_ocr_calls')==192 and
         doc.get('physical_granite_forward_batches')==60,
         'incomplete original physical OCR/model identity')
    if require_historical_original:
        need(doc.get('ocr_nonempty_cases')==110 and
             doc.get('actual_original_pretrained_forward_self_reported') is True,
             'not pinned original OCR physical reference')
    rows=preds(doc['rows'])
    need(set(rows)==set(originals),'original OCR cohort changed')
    for k,x in rows.items():
        ref=originals[k]
        need(x['group']==ref['group'] and x['source_input_sha256']==ref['source_input_sha256'],
             'OCR source/group divergence')
        probabilities(x['probabilities'])
    return doc,rows

def historical(base_zip,ocr_zip):
    base=original_zip(base_zip,BASE_ZIP)
    orig,refs=check_baseline(base)
    ocr=original_zip(ocr_zip,OLD_OCR_ZIP,expected_members={
        'e3-ocr-observed/sealed-ocr-predictions.json','e3-ocr-packages.txt'})
    need(hash_bytes(ocr['e3-ocr-observed/sealed-ocr-predictions.json'])==OLD_OCR_PRED,
         'actual original OCR output byte drift')
    measured,rows=check_ocr(ocr['e3-ocr-observed/sealed-ocr-predictions.json'],refs,
                            require_historical_original=True)
    differences=0;gated=0;overlap=0;tv=[];masked=0
    for rid,row in refs.items():
        arms=row['arms']
        need(type(arms) is dict and all(k in arms for k in ('text_only','train_gate','image_masked')),
             'original visual negative controls missing')
        txt=probabilities(arms['text_only']);learn=probabilities(arms['train_gate']);mask=probabilities(arms['image_masked'])
        new=rows[rid]['probabilities']
        changed=guess(txt)!=guess(new)
        learned=guess(txt)!=guess(learn)
        differences+=changed;gated+=learned;overlap+=changed and learned
        masked+=txt==mask
        tv.append(sum(abs(a-b) for a,b in zip(txt,new))/2)
    return {'schema':SCHEMA,'scope':'completed_original_historical_OCR_label_blind_zip_audit',
            'baseline_zip_sha256':BASE_ZIP,'ocr_zip_sha256':OLD_OCR_ZIP,
            'original_prediction_sha256':BASE_PRED,'ocr_prediction_sha256':OLD_OCR_PRED,
            'source_sha256':SOURCE,'original_test_cases':64,
            'original_source_group_parity_cases':64,
            'original_source_input_digest_parity_cases':64,
            'original_ocr_image_calls':measured['physical_ocr_calls'],
            'original_ocr_nonempty_cases':measured['ocr_nonempty_cases'],
            'original_ocr_granite_forward_batches':measured['physical_granite_forward_batches'],
            'ocr_vs_text_changed_argmax_cases':differences,
            'learned_gate_vs_text_changed_argmax_cases':gated,
            'ocr_and_learned_gate_both_changed_cases':overlap,
            'masked_control_equal_text_cases':masked,
            'mean_total_variation_ocr_vs_text':sum(tv)/len(tv),
            'historical_original_job_was_test_target_redacted':False,
            'test_labels_read':False,'accuracy_observed':False,
            'full_original_five_arm_completed':False,
            'original_model_origin_independently_signed':False,
            'stem_winner':None,'production_accepted':False,'authority':'DENY_ALL'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline-zip',required=True,type=Path)
    p.add_argument('--ocr-zip',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    args=p.parse_args()
    result=historical(args.baseline_zip,args.ocr_zip)
    need(not args.out.exists() and not args.out.is_symlink(),'report must be create-only')
    with args.out.open('x',encoding='utf-8') as f:
        f.write(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')
        f.flush();os.fsync(f.fileno())
    print('ORIGINAL_OCR_NUMERIC_ZIP_BYTES_AUDITED / UNLABELED / DENY_ALL')
if __name__=='__main__':main()
