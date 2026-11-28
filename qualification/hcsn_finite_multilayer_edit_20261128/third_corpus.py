"""Recover original ten digit identities from the unseen Speech Commands V2 restricted test archive."""
import argparse
import csv
import hashlib
import io
import json
import re
import tarfile
import time
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from data import features
NAMES='zero one two three four five six seven eight nine'.split()
def process(archive,known,fresh,out):
    st=time.monotonic();cpu=time.process_time();rows=[];meta=[];duplicates=[]
    prior=set()
    for source in (known,fresh):
        with source.open() as fh:prior.update(r['pcm_sha256'] for r in csv.DictReader(fh,delimiter='\t'))
    with tarfile.open(archive,'r:gz') as tar:
        for member in tar:
            parts=member.name.strip('./').split('/')
            if len(parts)!=2 or not member.isfile():continue
            dirn,file=parts
            if dirn=='_unknown_':
                match=re.fullmatch(r'([a-z]+)_([a-zA-Z0-9]+)_nohash_(\d+)\.wav\.wav',file)
                if not match:continue
                label,speaker=match.group(1),match.group(2)
            elif dirn in NAMES:
                label=dirn;speaker=file.split('_nohash_')[0]
            else:continue
            if label not in NAMES:continue
            raw=tar.extractfile(member).read();hz,x=wavfile.read(io.BytesIO(raw))
            pcm=hashlib.sha256(str((hz,x.shape,x.dtype)).encode()+x.tobytes()).hexdigest()
            if pcm in prior:duplicates.append([member.name,pcm]);continue
            prior.add(pcm);rows.append((features(x,hz),NAMES.index(label),speaker,member.name))
            meta.append([member.name,label,speaker,hashlib.sha256(raw).hexdigest(),pcm])
    if not rows:raise ValueError('archive contained no identifiable digits')
    x,y,s,r=map(np.asarray,zip(*rows))
    counts={NAMES[i]:[int(np.sum(y==i)),len(set(s[y==i]))] for i in range(10)}
    assert all(n>=10 and k>=5 for n,k in counts.values()),counts
    out.mkdir(exist_ok=True,parents=True);np.savez_compressed(out/'C.npz',x=x,y=y,speaker=s,record=r)
    with (out/'third_waveforms.tsv').open('w') as f:
        w=csv.writer(f,delimiter='\t',lineterminator='\n');w.writerow(['path','label','speaker','wav_sha256','pcm_sha256']);w.writerows(meta)
    receipt=dict(official='https://storage.googleapis.com/download.tensorflow.org/data/speech_commands_test_set_v0.02.tar.gz',
             archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),counts=counts,speakers=len(set(s)),n=len(s),duplicates=duplicates,
             extraction_and_features_wall=time.monotonic()-st,extraction_and_features_cpu=time.process_time()-cpu)
    (out/'third.json').write_text(json.dumps(receipt,indent=2)+'\n');print(receipt,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('archive','known','fresh','out'):p.add_argument(name,type=Path)
    a=p.parse_args();process(a.archive,a.known,a.fresh,a.out)
