"""Pin original frame and acoustic tensors before any cloud resource is allocated."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

SOURCE='18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad'
TIERS=((24,8,16),(96,24,48),(384,96,192),(1152,240,384),(4984,1147,1311))

def sha(b):return hashlib.sha256(b).hexdigest()

def stages(fold):
    lists=[np.random.default_rng(280911+j).permutation(np.flatnonzero(fold==j)) for j in range(3)]
    return [np.concatenate([a[:n] for a,n in zip(lists,tier)]) for tier in TIERS]

def main(src,out):
    with src.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==SOURCE
    with np.load(src,allow_pickle=False) as q:
        names=q['ids'];splits=q['split'];images=q['images'];audio=q['audio']
        rows=stages(splits)
        data={'source_sha256':SOURCE,'source_bytes':src.stat().st_size,'tiers':[],
              'arrays':{k:{'sha256':sha(q[k].tobytes()),'shape':list(q[k].shape),'dtype':str(q[k].dtype)} for k in q},
              'first48':{str(names[i]):{'image_sha256':sha(images[i].tobytes()),'audio_sha256':sha(audio[i].tobytes())} for i in rows[0]}}
        for ix in rows:
            data['tiers'].append({'n':len(ix),'split':np.bincount(splits[ix]).tolist(),
                'ids':sha(names[ix].tobytes()),'images':sha(images[ix].tobytes()),'audio':sha(audio[ix].tobytes())})
    out.write_text(json.dumps(data,indent=1)+'\n');print(out.stat().st_size,sha(out.read_bytes()))

if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
