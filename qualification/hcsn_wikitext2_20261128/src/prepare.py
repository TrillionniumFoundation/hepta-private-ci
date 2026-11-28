"""Pin plain-text official splits; use train counts alone to build frequency-ranked ids."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

import numpy as np

COMMIT = 'acc295dc7b90714f1bf47f06004fc19a7fe235c4'
SHA = dict(train='9e9fa1ad55b1c2c95b08e37dd8e653f638fac2c6de904b79e813611eefbc985f',
           valid='f0737ed31fc1329026e95cb8b98e19c2a182c39c240ab909dc31abf2f8af58e8',
           test='d790b833ef8cf03a90db7bf1271b7520b83c45ce07ba3c1a9699df81e239eca0')


def words(data):
    for line in data.decode('utf-8').splitlines():
        yield from line.split()
        yield '<eos>'


def prepare(root,download):
    raw=root/'raw';raw.mkdir(parents=True,exist_ok=True)
    data={}
    for s,sha in SHA.items():
        f=raw/(s+'.txt')
        if not f.exists() and download:
            u=f'https://raw.githubusercontent.com/pytorch/examples/{COMMIT}/word_language_model/data/wikitext-2/{s}.txt'
            f.write_bytes(urlopen(u,timeout=80).read())
        data[s]=f.read_bytes()
        if hashlib.sha256(data[s]).hexdigest()!=sha:
            raise ValueError(f'{s} hash mismatch')
    counts=Counter(words(data['train']))
    vocab=sorted(counts,key=lambda w:(-counts[w],w))
    idx={w:i for i,w in enumerate(vocab)}
    unk=idx['<unk>'];rows={}
    for s,content in data.items():
        oov=sum(1 for w in words(content) if w not in idx)
        arr=np.fromiter((idx.get(w,unk) for w in words(content)),dtype=np.int32)
        np.save(root/(s+'.npy'),arr)
        rows[s]=dict(tokens=len(arr),targets=len(arr)-1,additional_oov=oov,
                     unk_tokens=int(np.sum(arr==unk)),raw_sha256=SHA[s],
                     array_sha256=hashlib.sha256(arr.tobytes()).hexdigest(),raw_bytes=len(content))
    report=dict(repository='pytorch/examples',commit=COMMIT,encoding='utf-8',vocab=len(vocab),
                vocabulary_sha256=hashlib.sha256(json.dumps(vocab,ensure_ascii=False).encode()).hexdigest(),
                splits=rows)
    (root/'data.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);ap.add_argument('--download',action='store_true')
    args=ap.parse_args();prepare(args.root,args.download)
