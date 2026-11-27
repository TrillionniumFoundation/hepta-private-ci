"""Recover chronological next-word targets from original-author sentences at sealed pixel rows."""
import argparse, hashlib, json, re
from collections import Counter
from pathlib import Path
import numpy as np

def sha(x):return hashlib.sha256(x).hexdigest()
def main(data,raw,out):
    out.mkdir(parents=True,exist_ok=True)
    orig=(raw/'original.json').read_bytes(); assert sha(orig)=='5e342037d469d074711676bdb9c02b6942a624530b1959d24d2734e68af9cede'
    source={d['filename']:d for d in json.loads(orig)['images']}
    rows=json.loads((data/'rows.json').read_text()); prepared=json.loads((data/'prepared.json').read_text());words=[]
    pixels=data/'pixels32.npy';assert sha(pixels.read_bytes())==prepared['prepared_hashes']['pixels32.npy']
    for row in rows:
        s=source[row['filename']]; matches={' '.join(re.findall(r'[a-z0-9]+',t['raw'].lower())) for t in s['sentences']}; matches=[c for c in matches if sha(c.encode())==row['caption_sha']]
        assert len(matches)==1;words.append(matches[0].split())
    splits=np.array([x['split'] for x in rows]);counts=Counter(w for i,ws in enumerate(words) if splits[i]==0 for w in ws)
    vocab={w:i+4 for i,(w,n) in enumerate(sorted(((w,n) for w,n in counts.items() if n>=2),key=lambda row:(-row[1],row[0])))}
    x=np.zeros((len(rows),17),np.int16);y=np.zeros_like(x);truncated=Counter()
    for i,ws in enumerate(words):
        ids=[vocab.get(w,1) for w in ws[:16]]; targets=ids+([3] if len(ws)<=16 else [])
        prev=[2]+ids;x[i,:len(targets)]=prev[:len(targets)];y[i,:len(targets)]=targets
        truncated[int(splits[i])]+=len(ws)>16
    idx={k:np.flatnonzero(splits==j) for j,k in enumerate(['train','development_all','test'])}
    idx['development']=np.array(sorted(idx['development_all'],key=lambda i:sha(('RSICD-fullstack-dev-'+rows[i]['filename']).encode()))[:128]);assert len(set(idx['test'])&set(idx['development']))==0
    artifact=out/'data.npz';np.savez_compressed(artifact,inputs=x,targets=y,**idx)
    (out/'vocabulary.json').write_text(json.dumps(vocab,sort_keys=True));meta={'input_sha':sha(artifact.read_bytes()),'vocabulary_sha':sha((out/'vocabulary.json').read_bytes()),'rows_sha':sha((data/'rows.json').read_bytes()),'pixel_sha':sha(pixels.read_bytes()),'vocab_size':len(vocab)+4,'splits':{k:len(v) for k,v in idx.items()},'truncated_no_EOS':dict(truncated),'target_counts':{k:int((y[v]!=0).sum()) for k,v in idx.items()},'pixels':str(pixels.resolve())};(out/'data.json').write_text(json.dumps(meta,indent=1));print(meta)
if __name__=='__main__':
    p=argparse.ArgumentParser();[p.add_argument(n,type=Path) for n in ('data','raw','output')];a=p.parse_args();main(a.data,a.raw,a.output)
