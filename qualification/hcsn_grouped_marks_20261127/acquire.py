"""Freeze distinct development and confirmation images before model selection."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os
import hashlib
import json
import re
import sys
import time

import legacy_cohort_reference as reference
import numpy as np

PARENT = Path(os.environ['HEPTA_FLICKR_ROOT']).resolve()
STUDY = Path(os.environ['HCSN_GROUPED_STUDY']).resolve()
OUTPUT = STUDY/'gallery'
SALT = 'hepta-flickr-grouped-marks-cohort-20261127-v1'
DEVELOPMENT = 320
CONFIRMATION = 800
NEEDED = DEVELOPMENT + CONFIRMATION


def write_once(path, value):
    raw = (json.dumps(value, sort_keys=True, allow_nan=False) + '\n').encode()
    if path.exists():
        if raw != path.read_bytes():
            raise RuntimeError(f'Frozen record differs: {path.name}')
        return
    tmp = path.with_suffix(path.suffix + '.new')
    tmp.write_bytes(raw)
    tmp.replace(path)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    reference.BASE = OUTPUT
    (OUTPUT/'images').mkdir(exist_ok=True)
    source_path = PARENT/'coco_source_receipt.json'
    source = json.loads(source_path.read_text())
    annotations = PARENT/'coco_restored/test.json'
    expected_size, expected_hash = source['files']['test.json']
    assert annotations.stat().st_size == expected_size and reference.sha(annotations) == expected_hash
    prior = {n:(h,b) for n,h,b in source['jpeg']}
    prior_roster = PARENT/'attention_free/external/roster.json'
    earlier = json.loads(prior_roster.read_text())['all_512_names']
    assert len(earlier)==512
    # Freeze every other local preallocation encountered before qualification. This study is outside PARENT.
    ignored = set(prior) | set(earlier)
    old_rosters = {}
    for r in sorted(PARENT.glob('**/roster.json')):
        old_rosters[str(r.relative_to(PARENT))] = reference.sha(r)
        j = json.loads(r.read_text())
        if r == prior_roster:
            continue
        keys = [k for k in j if ('names' in k or 'files' in k) and isinstance(j[k],list)]
        if not keys:
            raise RuntimeError('Unrecognized prior COCO roster to review: '+r.name)
        for k in keys:
            ignored.update(Path(s).name for s in j[k] if isinstance(s,str) and s.lower().endswith(('.jpg','.jpeg')))
    rows = {}
    for record in json.loads(annotations.read_text()):
        relative = record['image']
        name = Path(relative).name
        row = rows.setdefault(name,dict(file=name,source=relative,captions=[]))
        captions = record['caption'] if isinstance(record['caption'],list) else [record['caption']]
        for caption in captions:
            if caption not in row['captions'] and len(row['captions']) < 5:
                row['captions'].append(caption)
    ordered = sorted(set(rows)-ignored, key=lambda n: hashlib.sha256((SALT+n).encode()).digest())
    assert len(ordered) >= 1300
    write_once(OUTPUT/'roster.json',dict(salt=SALT,excluded_filenames=sorted(ignored),prior_rosters=old_rosters,
         prior_receipt=reference.sha(source_path),annotation_sha256=expected_hash,all_names_in_order=ordered))
    fm = json.loads((PARENT/'data/manifest.json').read_text())
    known_hashes = set()
    known_codes = []
    for split, manifest in fm['splits'].items():
        for ext in ('ids','pixels'):
            file = PARENT/'data'/(split+'_'+ext+'.npy')
            assert reference.sha(file)==manifest['files'][file.name]
        ids = np.load(PARENT/'data'/(split+'_ids.npy'))
        pixels = np.load(PARENT/'data'/(split+'_pixels.npy'),mmap_mode='r')
        for raw_hash, pixel in zip(ids,pixels):
            known_hashes.add(bytes(raw_hash).decode())
            known_codes.append(reference.dhash(pixel))
    for name,(raw_hash,size) in prior.items():
        file = PARENT/'coco_restored/images'/name
        assert file.stat().st_size==size and reference.sha(file)==raw_hash
        known_hashes.add(raw_hash); known_codes.append(reference.dhash(reference.image_data(file)))
    for name in earlier:
        file = PARENT/'attention_free/external/images'/name
        if not file.is_file():
            # The earlier filename remains excluded regardless. Acquire its reference pixels for a dHash comparison.
            oldbase=reference.BASE
            compare=OUTPUT/'old_reference'
            (compare/'images').mkdir(exist_ok=True,parents=True)
            reference.BASE=compare
            try:reference.fetch(rows[name])
            finally:reference.BASE=oldbase
            file=compare/'images'/name
        known_hashes.add(reference.sha(file)); known_codes.append(reference.dhash(reference.image_data(file)))
    known_codes=np.stack(known_codes)
    count_bits=np.unpackbits(np.arange(256,dtype=np.uint8)[:,None],axis=1).sum(1).astype(np.uint8)
    vocab={word:i for i,word in enumerate(fm['vocab'])}
    kept=[];rejected=[];new_codes=[];caps=[];pixels=[];ids=[];downloaded=[]
    cursor=0;end=1300
    while len(kept)<NEEDED:
        chunk=ordered[cursor:end]
        if not chunk:raise RuntimeError('Exhausted canonical COCO annotation roster')
        with ThreadPoolExecutor(max_workers=3) as pool:
            receipts=list(pool.map(reference.fetch,[rows[n] for n in chunk]))
        downloaded.extend(receipts)
        for named, rec in zip(chunk,receipts):
            if len(kept)==NEEDED:break
            row=rows[named]; px=reference.image_data(OUTPUT/'images'/named); code=reference.dhash(px)
            olddist=int(count_bits[np.bitwise_xor(known_codes,code)].sum(1).min())
            newdist=int(count_bits[np.bitwise_xor(np.stack(new_codes),code)].sum(1).min()) if new_codes else 65
            if rec['sha256'] in known_hashes or min(olddist,newdist)<=2 or len(row['captions'])<5:
                rejected.append(dict(name=named,old_distance=olddist,new_distance=newdist,captions=len(row['captions'])))
                continue
            enc=np.zeros((5,32),np.int16)
            for c,s in enumerate(row['captions']):
                tokens=re.findall(r"[a-z]+(?:'[a-z]+)?|[0-9]+|[^\w\s]",s.lower())[:30]
                seq=[1]+[vocab.get(word,3) for word in tokens]+[2]
                enc[c,:len(seq)]=seq
            known_hashes.add(rec['sha256']);new_codes.append(code);kept.append(named);pixels.append(px);caps.append(enc);ids.append(rec['sha256'])
        cursor=end;end=min(len(ordered),end+200)
    result={}
    for label,lo,hi in [('development',0,DEVELOPMENT),('test',DEVELOPMENT,NEEDED)]:
        arrays=dict(images=np.stack(pixels[lo:hi]),tokens=np.stack(caps[lo:hi]),ids=np.asarray(ids[lo:hi],dtype='S64'))
        dest=OUTPUT/(label+'.npz'); temp=OUTPUT/(label+'.new')
        with temp.open('wb') as stream:np.savez_compressed(stream,**arrays)
        if dest.exists():assert reference.sha(temp)==reference.sha(dest)
        temp.replace(dest)
        tok=arrays['tokens'];result[label]=dict(file=dest.name,sha256=reference.sha(dest),images=hi-lo,
            captions=(hi-lo)*5,names=kept[lo:hi],id_sha256=hashlib.sha256(arrays['ids'].tobytes()).hexdigest(),
            unknown_fraction=float((tok==3).sum()/max(1,((tok>3)|(tok==3)).sum())))
    assert not set(kept[:DEVELOPMENT]) & set(kept[DEVELOPMENT:])
    write_once(OUTPUT/'manifest.json',dict(cohorts=result,roster_sha256=reference.sha(OUTPUT/'roster.json'),excluded=rejected,
        jpeg_receipts=downloaded,train_manifest=reference.sha(PARENT/'data/manifest.json'),source=reference.sha(Path(__file__)),
        prior_file_count=len(ignored),near_duplicate_radius=2))
    print('frozen roster',len(kept),len(rejected),reference.sha(OUTPUT/'manifest.json'),flush=True)


if __name__=='__main__':
    main()
