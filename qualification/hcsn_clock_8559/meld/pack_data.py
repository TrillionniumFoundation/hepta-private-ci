"""Make contiguous arrays and dialogue/source manifests after original-media preparation."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import numpy as np
from prepare import SPLITS,annotations,atomic,digest
def tokens(s):
    return re.findall(r"[^\W_]+(?:[’'][^\W_]+)?|[^\w\s]",s.lower(),flags=re.UNICODE)[:128]
def raw_manifest(root):
    rows={s:json.loads((root/f'{s}-decoded.json').read_text())['rows'] for s in SPLITS}
    docs={s:annotations(root,s) for s in SPLITS}
    seen={};episode={s:set() for s in SPLITS};plan={};duplicates={};c=collections.Counter()
    for s in SPLITS:
        plan[s]=[];duplicates[s]=[]
        for key,item in sorted(rows[s].items(),key=lambda r:tuple(map(int,re.findall(r'\d+',r[0])))):
            if not item['usable']:continue
            sha=item['media_sha256'];episode[s].add((item['season'],item['episode']))
            anchor=seen.get(sha);clean=anchor is None
            if clean:seen[sha]=(s,key)
            else:duplicates[s].append((key,anchor))
            if s=='train' and clean:c.update(tokens(docs[s][key]['Utterance']))
            plan[s].append((key,item,clean))
    vocab={k:i+2 for i,(k,_) in enumerate(sorted(c.items(),key=lambda x:(-x[1],x[0]))[:4094])}
    return plan,docs,vocab,duplicates,episode
def main(root):
    plan,docs,vocab,duplicates,episode=raw_manifest(root)
    dest=root/'arrays';dest.mkdir(exist_ok=True);out={}
    for s in SPLITS:
        items=plan[s];n=len(items);f=dest/s;f.mkdir(exist_ok=True)
        shapes={'video':(np.uint8,(n,8,32,32,3)),'audio':(np.int16,(n,8,2048)),
                'text':(np.int16,(n,8,16)),'label':(np.int8,(n,)),'dialogue':(np.int32,(n,)),'clean':(np.bool_,(n,))}
        arr={k:np.lib.format.open_memmap(f/(k+'.npy'),mode='w+',dtype=d,shape=sh) for k,(d,sh) in shapes.items()}
        for i,(key,row,clean) in enumerate(items):
            raw=root/'decoded'/s/(key+'.npz')
            assert digest(raw)==row['derived_sha256']
            with np.load(raw) as z:arr['video'][i]=z['video'];arr['audio'][i]=z['audio']
            run=[vocab.get(tok,1) for tok in tokens(docs[s][key]['Utterance'])]
            arr['text'][i]=0
            for j,chunk in enumerate(np.array_split(np.asarray(run,np.int16),8)):
                arr['text'][i,j,:len(chunk)]=chunk
            arr['label'][i]=row['y'];arr['dialogue'][i]=row['dialogue'];arr['clean'][i]=clean
        for v in arr.values():v.flush()
        out[s]=dict(rows=n,unique_clean=int(arr['clean'].sum()),hashes={k:digest(f/(k+'.npy')) for k in shapes},
                    clip_ids=[a for a,_,_ in items],exact_byte_duplicates=duplicates[s])
    summary=dict(splits=out,vocabulary_size=len(vocab)+2,
          vocabulary_sha256=hashlib.sha256(json.dumps(vocab,sort_keys=True).encode()).hexdigest(),
          episode_intersections={a+'-'+b:len(episode[a]&episode[b]) for a,b in [('train','dev'),('dev','test'),('train','test')]},
          alignment='Eight relative-time audio and RGB positions. Eight relative-order text groups without forced word timestamps.')
    atomic(dest/'INPUTS.json',summary)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();main(a.root)
