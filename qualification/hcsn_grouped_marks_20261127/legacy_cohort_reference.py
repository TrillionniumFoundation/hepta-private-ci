"""Freeze a previously unscored external COCO image-caption gallery from official bytes."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import sys
import time
import urllib.request

ROOT=Path(os.environ.get('HEPTA_FLICKR_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(ROOT/'prepare_packages'))
import numpy as np
from PIL import Image,ImageOps
BASE=ROOT/'attention_free'/'external'
SALT='hepta-full-operator-external-20261127-v1:'


def sha(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def image_data(p):
    with Image.open(p) as im:
        return np.asarray(ImageOps.fit(im.convert('RGB'),(64,64),method=Image.Resampling.BILINEAR)).copy()


def dhash(px):
    im=Image.fromarray(px).convert('L').resize((9,8),Image.Resampling.BILINEAR)
    arr=np.asarray(im)
    return np.packbits((arr[:,1:]>arr[:,:-1]).ravel())


def fetch(row):
    root=BASE/'images';dest=root/row['file'];info=dest.with_suffix('.json')
    url='https://s3.amazonaws.com/images.cocodataset.org/'+row['source']
    if dest.exists() and info.exists():
        record=json.loads(info.read_text())
        assert record['sha256']==sha(dest) and record['bytes']==dest.stat().st_size and record['url']==url
        return record
    for attempt in range(4):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Hepta prospective encoder study'})
            with urllib.request.urlopen(req,timeout=40) as source, dest.with_suffix('.part').open('wb') as f:
                expected=int(source.headers['Content-Length'])
                etag=source.headers.get('ETag','').strip('"')
                assert 0<expected<24_000_000
                while chunk:=source.read(131072):f.write(chunk)
            tmp=dest.with_suffix('.part')
            assert tmp.stat().st_size==expected
            if re.fullmatch('[0-9a-fA-F]{32}',etag):
                with tmp.open('rb') as f:assert hashlib.file_digest(f,'md5').hexdigest()==etag.lower()
            record=dict(file=row['file'],url=url,bytes=expected,etag=etag,sha256=sha(tmp))
            tmp.replace(dest);info.write_text(json.dumps(record,sort_keys=True))
            return record
        except (OSError,ValueError,AssertionError) as exc:
            with (BASE/'network.jsonl').open('a') as f:f.write(json.dumps([row['file'],attempt,type(exc).__name__])+'\n')
            if attempt==3:raise
            time.sleep(2**attempt)


def main():
    BASE.mkdir(exist_ok=True,parents=True)
    (BASE/'images').mkdir(exist_ok=True)
    if (BASE/'manifest.json').is_file():
        assert sha(BASE/'external.npz')==json.loads((BASE/'manifest.json').read_text())['arrays_sha256']
        return
    end=time.monotonic()+7000
    while not (ROOT/'coco_restored/verification.json').is_file():
        if time.monotonic()>end:raise TimeoutError('Original cohort still unavailable')
        time.sleep(15)
    r=json.loads((ROOT/'coco_source_receipt.json').read_text())
    old={name:(h,n) for name,h,n in r['jpeg']}
    ann=ROOT/'coco_restored/test.json'
    assert ann.stat().st_size==r['files']['test.json'][0] and sha(ann)==r['files']['test.json'][1]
    docs=json.loads(ann.read_text());by={}
    for doc in docs:
        source=doc['image'];name=source.split('/')[-1]
        if name in old:continue
        row=by.setdefault(name,{'file':name,'source':source,'captions':[]})
        captions=doc['caption']
        for c in (captions if isinstance(captions,list) else [captions]):
            if c not in row['captions'] and len(row['captions'])<5:row['captions'].append(c)
    ids=sorted(by,key=lambda k:hashlib.sha256((SALT+k).encode()).digest())[:512]
    assert len(ids)==512 and not set(ids).intersection(old)
    prospective={'salt':SALT,'annotation_sha256':sha(ann),'all_512_names':ids,'prior_sha256':sha(ROOT/'coco_source_receipt.json')}
    roster=BASE/'roster.json'
    if roster.exists():assert json.loads(roster.read_text())==prospective
    else:roster.write_text(json.dumps(prospective,sort_keys=True))
    with ThreadPoolExecutor(max_workers=3) as pool:
        source=list(pool.map(fetch,[by[i] for i in ids]))
    known={};codes=[]
    fm=json.loads((ROOT/'data/manifest.json').read_text())
    for split,rec in fm['splits'].items():
        for ext in ('ids','pixels'):
            n=f'{split}_{ext}.npy';assert sha(ROOT/'data'/n)==rec['files'][n]
        pix=np.load(ROOT/'data'/f'{split}_pixels.npy',mmap_mode='r')
        ii=np.load(ROOT/'data'/f'{split}_ids.npy')
        for px,im_id in zip(pix,ii):
            known[bytes(im_id).decode()]='flickr_'+split;codes.append(dhash(px))
    for name,(h,length) in old.items():
        pp=ROOT/'coco_restored'/'images'/name
        assert pp.stat().st_size==length and sha(pp)==h
        known[h]='old_coco';codes.append(dhash(image_data(pp)))
    codes=np.stack(codes)
    table=np.unpackbits(np.arange(256,dtype=np.uint8)[:,None],axis=1).sum(1).astype(np.uint8)
    vocab={k:i for i,k in enumerate(fm['vocab'])}
    pix=[];caps=[];names=[];kept=[];drop=[];unknown=lex=trunc=0;newcodes=[]
    for src in source:
        k=src['file'];r=by[k];px=image_data(BASE/'images'/k);h=dhash(px)
        dist=int(table[np.bitwise_xor(codes,h)].sum(1).min())
        newdist=min((int(table[np.bitwise_xor(v,h)].sum()) for v in newcodes),default=65)
        if src['sha256'] in known or dist<=2 or newdist<=2 or len(r['captions'])<5:
            drop.append(dict(file=k,raw_intersection=known.get(src['sha256']),old_roster_dhash=dist,new_roster_dhash=newdist,caption_count=len(r['captions'])));continue
        known[src['sha256']]='new_coco';newcodes.append(h)
        words=np.zeros((5,32),dtype=np.int16)
        for j,t in enumerate(r['captions']):
            ws=re.findall(r"[a-z]+(?:'[a-z]+)?|[0-9]+|[^\w\s]",t.lower());trunc+=int(len(ws)>30)
            w=[vocab.get(x,3) for x in ws[:30]];lex+=len(w);unknown+=w.count(3);seq=[1]+w+[2]
            words[j,:len(seq)]=seq
        pix.append(px);caps.append(words);names.append(src['sha256']);kept.append(k)
    with (BASE/'external.part').open('wb') as f:
        np.savez_compressed(f,images=np.stack(pix),tokens=np.stack(caps),ids=np.asarray(names,dtype='S64'))
    (BASE/'external.part').replace(BASE/'external.npz')
    rec=dict(images=len(pix),captions=5*len(pix),kept=kept,excluded=drop,source=source,input_roster_sha256=sha(roster),
        arrays_sha256=sha(BASE/'external.npz'),lexical_tokens=lex,unknown=unknown,truncated=trunc,
        prior_unique_filenames=len(old),flickr_manifest=sha(ROOT/'data/manifest.json'),source_sha256=sha(Path(__file__)))
    (BASE/'manifest.part').write_text(json.dumps(rec,sort_keys=True))
    (BASE/'manifest.part').replace(BASE/'manifest.json')
    print('external frozen',len(pix),len(drop),flush=True)


if __name__=='__main__':main()
