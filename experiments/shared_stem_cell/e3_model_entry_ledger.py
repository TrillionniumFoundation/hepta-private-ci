#!/usr/bin/env python3
"""Independent, STDlib-only pre/post-model file-tree evidence boundary (DENY_ALL).

Consumes only the locally staged source files. The actual model runner may never
import/open the original publisher Parquet, TEST labels or target-derived SHA.
This checks that a producer has delivered only the bounded admitted model view;
it is not proof of independent publisher authentication or a filesystem sandbox.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat

SCHEMA = 'hepta.e3-model-input-filetree-audit.v1'
FINGERPRINT_PROFILE = 'hepta.e3-path-byte-sha256.v2'
SOURCE_DATASET = 'lmms-lab/ScienceQA-IMG'
REVISION = 'b9984af01798586705cee1fbdfa80a6dcbef04f1'
SIZES = {'train':96,'validation':32,'test':64}
ROOT_FILES = {'source-seals.json','inputs/sources.jsonl',
              'inputs/fit_labels.jsonl','inputs/cohort-before-labels.json'}
SOURCE_FIELDS = {'id','group','split','image','scope','question','hint','choices'}
LABEL_FIELDS = {'id','group','split','label'}
IMAGE_MAX = 8 * 1024 * 1024
FULL_BYTE_MAX = 512 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{64}\Z')

class ModelEntryDenied(ValueError):
    """Unregistered or target-bearing input cannot enter an Encoder job."""


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ModelEntryDenied(message)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hex_sha(value: object) -> bool:
    return type(value) is str and SHA.fullmatch(value) is not None and value != '0'*64


def canonical(obj: object) -> bytes:
    return (json.dumps(obj,sort_keys=True,ensure_ascii=True,
                       allow_nan=False,separators=(',',':'))+'\n').encode()


def strict(data: bytes) -> object:
    def unique(pairs):
        out={}
        for k,v in pairs:
            require(k not in out,'duplicate JSON key')
            out[k]=v
        return out
    try:
        val=json.loads(data,object_pairs_hook=unique,
                       parse_constant=lambda x: (_ for _ in ()).throw(
                           ModelEntryDenied('nonfinite JSON: '+x)))
        canonical(val)
        return val
    except (TypeError,UnicodeError,ValueError,OverflowError) as exc:
        raise ModelEntryDenied('invalid canonical JSON') from exc


def read_file(path: Path, maximum: int) -> bytes:
    require(path.is_file() and not path.is_symlink(), 'missing or symlinked input')
    mode=path.lstat()
    require(stat.S_ISREG(mode.st_mode) and mode.st_nlink == 1 and
            0 < mode.st_size <= maximum, 'oversized or hardlinked input')
    return path.read_bytes()


def document(root: Path, relative: str, size: int = 32*1024*1024):
    payload=read_file(root/relative,size)
    return payload,strict(payload)


def json_lines(payload: bytes) -> list[dict]:
    require(payload.endswith(b'\n'), 'unsealed JSONL')
    lines=payload.splitlines()
    require(1<=len(lines)<=256, 'invalid source row count')
    result=[]
    for line in lines:
        record=strict(line)
        require(type(record) is dict and canonical(record).strip()==line,
                'noncanonical input row')
        result.append(record)
    return result


def audit(root: Path, source_sha256: str, fit_sha256: str) -> dict:
    require(root.is_dir() and not root.is_symlink(), 'local source root required')
    require(hex_sha(source_sha256) and hex_sha(fit_sha256),
            'two pinned source/fit hashes required')
    # Independent recursive inventory: reject every unlisted path, hard link,
    # symlink or public source archive even when it has a plausible checksum.
    registered=[]
    file_byte_hashes=[]
    image_names=set()
    total_bytes=0
    for base, dirs, files in os.walk(root,topdown=True,followlinks=False):
        parent=Path(base)
        for name in dirs:
            folder=parent/name
            require(not folder.is_symlink() and folder.is_dir(),
                    'symlinked or invalid folder')
            rel=folder.relative_to(root).as_posix()
            require(rel in {'inputs','images'}, 'unregistered source directory')
        for name in files:
            p=parent/name
            require(not p.is_symlink(), 'symlink in model-facing input')
            rel=p.relative_to(root).as_posix()
            require(rel in ROOT_FILES or (rel.startswith('images/')
                    and rel.count('/')==1 and hex_sha(rel[7:])),
                    'unexpected file or held-target media in model view')
            st=p.lstat()
            maximum=IMAGE_MAX if rel.startswith('images/') else 32*1024*1024
            require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and
                    0 < st.st_size <= maximum, 'unsafe input file storage')
            total_bytes+=st.st_size
            # The model-entry fingerprint binds each admitted path AND bytes.
            # Path-only hashes could miss valid-schema metadata reserialization.
            raw=p.read_bytes()
            file_digest=digest(raw)
            require(len(raw)==st.st_size, 'file changed during audit')
            registered.append(rel)
            file_byte_hashes.append([rel,file_digest])
            if rel.startswith('images/'):
                require(file_digest==rel[7:], 'raw image hash differs from manifest')
                require(raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff'),
                        'not an original PNG/JPEG signature')
                image_names.add(rel[7:])
    require(total_bytes<=FULL_BYTE_MAX and set(ROOT_FILES)<=set(registered),
            'bounded and complete source handoff required')
    source_raw=read_file(root/'inputs/sources.jsonl',32*1024*1024)
    fit_raw=read_file(root/'inputs/fit_labels.jsonl',32*1024*1024)
    require(digest(source_raw)==source_sha256 and digest(fit_raw)==fit_sha256,
            'original registered source and TRAIN/CAL hashes changed')
    sources=json_lines(source_raw)
    fit=json_lines(fit_raw)
    require(len(sources)==192 and len(fit)==128,
            'full 96/32/64 source and 128 fit label counts required')
    sources_by_id={}
    groups=set()
    counts=Counter()
    for s in sources:
        require(set(s)==SOURCE_FIELDS and all(hex_sha(s.get(k)) for k in ('id','group','image')),
                'source-only exact row schema required')
        require(s['split'] in SIZES and s['scope']=='public-scienceqa-e3-research',
                'invalid model input source/scope')
        require(s['id'] not in sources_by_id and s['group'] not in groups,
                'duplicate source or image-group alias across splits')
        require(type(s['question']) is str and 1<=len(s['question'].encode())<=4096 and
                type(s['hint']) is str and len(s['hint'].encode())<=2048 and
                type(s['choices']) is list and len(s['choices'])==4 and
                all(type(c) is str and 1<=len(c.encode())<=1024 for c in s['choices']),
                'unbounded source question/options')
        counts[s['split']]+=1
        groups.add(s['group'])
        sources_by_id[s['id']]=s
        require(s['image'] in image_names, 'declared input image missing')
    require(dict(counts)==SIZES and
            image_names=={r['image'] for r in sources},
            'missing image or source cohort drift')
    seen_fit=set()
    for f in fit:
        require(set(f)==LABEL_FIELDS and hex_sha(f.get('id')) and hex_sha(f.get('group')) and
                f['split'] in ('train','validation') and type(f['label']) is int and
                0<=f['label']<4 and f['id'] not in seen_fit, 'invalid TRAIN/CAL-only label')
        s=sources_by_id.get(f['id'])
        require(s is not None and s['group']==f['group'] and s['split']==f['split'],
                'label not bound to admitted TRAIN/CAL source')
        seen_fit.add(f['id'])
    require(seen_fit=={id for id,s in sources_by_id.items()
                       if s['split']!='test'},
            'missing or unexpected training/calibration labels')
    seal_raw,seal=document(root,'source-seals.json',1_000_000)
    cohort_raw,cohort=document(root,'inputs/cohort-before-labels.json',1_000_000)
    require(type(seal) is dict and set(seal)=={
        'dataset','dataset_revision','source_sha256','cohort_sha256',
        'fit_labels_sha256','private_test_labels_sha256','raw_image_count',
        'model_inference_completed','externally_independent_labels','production_accepted'},
        'noncanonical original source receipt')
    require(seal['dataset']==SOURCE_DATASET and seal['dataset_revision']==REVISION and
            seal['source_sha256']==source_sha256 and seal['fit_labels_sha256']==fit_sha256 and
            seal['cohort_sha256']==digest(cohort_raw) and
            seal['private_test_labels_sha256'] is None and
            type(seal['raw_image_count']) is int and seal['raw_image_count']==len(image_names) and
            all(seal[k] is False for k in ('model_inference_completed',
                'externally_independent_labels','production_accepted')),
            'source seal contains held target or invented authority')
    require(type(cohort) is dict and set(cohort)=={
        'schema','dataset','revision','source_sha256','counts','source_only',
        'chronological_future','production_accepted'}, 'wrong prelabel source fields')
    require(cohort['schema']=='hepta.e3-source-membership.v1' and
            cohort['dataset']==SOURCE_DATASET and cohort['revision']==REVISION and
            cohort['source_sha256']==source_sha256 and cohort['counts']==SIZES and
            cohort['source_only'] is True and cohort['chronological_future'] is False and
            cohort['production_accepted'] is False,
            'changed prelabel source cohort')
    return {'schema':SCHEMA,'authority':'DENY_ALL','production_accepted':False,
            'source_sha256':source_sha256,'fit_sha256':fit_sha256,
            'source_count':len(sources),'train_cal_count':len(fit),
            'test_label_count':0,'image_count':len(image_names),
            'image_bytes_total':sum((root/'images'/h).stat().st_size for h in image_names),
            'source_root_local_only':True,'raw_model_media_uploaded':False,
            'unknown_parquet_or_arrow_file_present':False,
            'test_target_bytes_or_digest_admitted':False,
            'independent_publisher_attested':False,'model_quality_certified':False,
            'scope':'prepost_physical_model_entry_source_tree',
            'tree_fingerprint_profile':FINGERPRINT_PROFILE,
            'tree_fingerprint_file_count':len(file_byte_hashes),
            'tree_fingerprint':digest(canonical(sorted(file_byte_hashes))),
            'original_source_receipt_sha256':digest(seal_raw)}


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--staged',type=Path,required=True)
    ap.add_argument('--source-sha256',required=True)
    ap.add_argument('--fit-sha256',required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    report=audit(args.staged,args.source_sha256,args.fit_sha256)
    with args.out.open('x',encoding='utf8') as file:
        file.write(json.dumps(report,sort_keys=True,separators=(',',':'))+'\n')
    print('E3_MODEL_VIEW_NO_TEST_TARGETS / SOURCE_BOUND / DENY_ALL')

if __name__=='__main__':
    main()
