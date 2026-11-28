"""Construct the author's independent official test gallery and audit transformed visual overlap."""
import argparse
from collections import Counter,defaultdict
import hashlib,io,json,sys
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from PIL import Image

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from prepare import digest,hashes,words


def vocab_and_check(src,author):
    ix=np.flatnonzero(src['split']==0);names=src['names'][ix]
    authored={r['filename']:[' '.join(words(s['raw'])) for s in r['sentences']][:5] for r in json.loads(author.read_text())['images']}
    rows=[[c for c in authored[n] if c] for n in names]
    counter=Counter(w for caps in rows for c in caps for w in c.split())
    vocab={w:i+2 for i,w in enumerate(sorted(counter,key=lambda w:(-counter[w],w))[:2046])}
    def encode(s):
        arr=np.zeros(24,np.int16);v=[vocab.get(w,1) for w in s.split()[:24]];arr[:len(v)]=v;return arr
    for n,c,expected in zip(names,rows,src['tokens'][ix]):
        assert np.array_equal(np.stack([encode(c[i%len(c)]) for i in range(5)]),expected),n
    return encode


def run(work,inputs,author):
    public=work/'public';meta=json.loads((public/'public_source.json').read_text());archive=public/'original.zip'
    assert digest(archive)==meta['assets']['original.zip']['sha256']
    names=(public/'test_filename.txt').read_text().splitlines();caps=(public/'test_caps.txt').read_text().splitlines()
    assert len(caps)==len(names)==2260
    table=defaultdict(list)
    for n,c in zip(names,caps):table[n].append(' '.join(words(c)))
    with np.load(inputs) as d:
        encode=vocab_and_check(d,author);old=d['images'];oldnames=d['names'];oldsplit=d['split']
        block=np.array([hashes(x) for x in old],np.uint64);shaold={hashlib.sha256(x.tobytes()).digest() for x in old}
    result=[];all_caps=[];label={};prev={4:[],8:[]};arrays={r:[] for r in (4,8)}
    with ZipFile(archive) as zz:
        annotation=json.loads(zz.read(next(n for n in zz.namelist() if 'dataset_rsitmd.json' in n.lower())))
        photos={r['filename']:r for r in annotation['images'] if r['split']=='test'};assert set(photos)==set(table) and len(photos)==452
        images=[];tokens=[];groups=[]
        for j,key in enumerate(sorted(photos)):
            official=[' '.join(words(s['raw'])) for s in photos[key]['sentences']];assert official==table[key]
            with Image.open(io.BytesIO(zz.read('images/'+key))) as p:
                p=p.convert('RGB');a,b=[np.asarray(p.resize((32,32),m)) for m in (Image.Resampling.BOX,Image.Resampling.BILINEAR)]
            def fingerprint(px):return np.array(hashes(px),dtype=np.uint64)
            ha,hb=fingerprint(a),fingerprint(b)
            dd=np.minimum(np.bitwise_count(block ^ ha[0]).min(1),np.bitwise_count(block ^ hb[0]).min(1))
            nearest=int(dd.argmin());k=int(dd[nearest]);exact=any(hashlib.sha256(px.tobytes()).digest() in shaold for px in (a,b))
            masks={}
            for r in (4,8):
                earlier=np.asarray(prev[r],dtype=np.uint64)
                intra=min((int(np.bitwise_count(earlier^x[0]).min()) for x in (ha,hb)),default=65) if len(earlier) else 65
                ok=k>r and not exact and intra>r
                if ok:prev[r].extend([ha,hb])
                arrays[r].append(ok);masks[r]=ok
            cap=official[0];assert cap;all_caps.append(cap);groups.append(label.setdefault(cap,len(label)));tokens.append(encode(cap));images.append(a)
            result.append(dict(name=key,min_hamming=k,nearest_prior=str(oldnames[nearest]),nearest_prior_split=int(oldsplit[nearest]),exact=exact,retained_radius4=masks[4],retained_radius8=masks[8]))
    fp=work/'rsitmd.npz'
    np.savez_compressed(fp,pixels=np.stack(images),tokens=np.stack(tokens),groups=np.array(groups),ids=np.array([r['name'] for r in result]),caps=np.array(all_caps),radius4=np.asarray(arrays[4]),radius8=np.asarray(arrays[8]))
    scores={str(r):int(sum(arrays[r])) for r in arrays}
    body=dict(author_release=meta,official_test_photos=len(photos),human_descriptions=len(caps),source_vocabulary_reconstruction='verified token-by-token on all 6308 eligible RSICD training rows and 5 annotation slots',
              archive_sha_verified=True,screen='minimum D4 pHash across BOX and BILINEAR comparisons with 32px cached prior images and prior accepted external rows',retained=scores,array_sha256=digest(fp),rows=result)
    (work/'RSITMD_ROSTER.json').write_text(json.dumps(body,indent=2)+'\n')
    print('official source',len(photos),'retained',scores,'hash',body['array_sha256'],flush=True)


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('work',type=Path);a.add_argument('inputs',type=Path);a.add_argument('author',type=Path);v=a.parse_args();run(v.work,v.inputs,v.author)
