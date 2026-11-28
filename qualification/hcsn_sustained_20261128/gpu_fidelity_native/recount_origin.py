"""Check every returned per-clip SHA on the physical host holding the full original arrays."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import numpy as np


def sha(b):return hashlib.sha256(b).hexdigest()

def run(src,ingress,out):
    with src.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()=='18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad'
    assert sha(ingress.read_bytes())=='ed3422d1607cab6ffebb7c5c08ba57011e1fcffd2d2f2d8e4c8e47087758d47a'
    raw=json.loads(ingress.read_text());entries=raw['entries'];failures=[];counts=Counter();byfold=Counter()
    with np.load(src,allow_pickle=False) as z:
        vid,audio,ids,fold=z['images'],z['audio'],z['ids'],z['split']
        for e in entries:
            i=e['index'];assert e['id']==ids[i]
            image=(sha(vid[i].tobytes())==e['image_sha256']);sound=(sha(audio[i].tobytes())==e['audio_sha256'])
            counts['image_exact']+=image;counts['audio_exact']+=sound;counts['both_exact']+=image and sound
            if image and sound:byfold[int(fold[i])]+=1
            else:failures.append({'index':int(i),'id':str(ids[i]),'image_exact':image,'audio_exact':sound})
    o={'source_sha256':'18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad','cloud_ingress_sha256':sha(ingress.read_bytes()),'decoded':len(entries),'checked_original_modality_sha256s':2*len(entries),'counts':dict(counts),'exact_per_split':dict(byfold),'different':failures,'fetch_errors':raw['errors']}
    out.write_text(json.dumps(o,indent=1)+'\n');print({k:v for k,v in o.items() if k not in ('different','fetch_errors')},'different',len(failures),'errors',len(raw['errors']))

if __name__=='__main__':run(*(Path(a) for a in sys.argv[1:]))
