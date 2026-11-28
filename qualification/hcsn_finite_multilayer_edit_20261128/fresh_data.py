"""Read precisely registered AudioMNIST WAV blobs at a fixed revision into ordered panels."""
import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import time
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from data import features

REV='630d7dab4c040882834de6fa21baf9a60372accd'
EXCLUDED={1,4,7,10,13,16,19,22}
def construct(repo, known, out, retention=False, additional=()):
    out.mkdir(parents=True,exist_ok=True)
    git=['git','--git-dir='+str(repo.resolve())]
    def run(args,**kwargs):return subprocess.run(git+args,check=True,**kwargs)
    members={}
    for i,s in enumerate(sorted(set(range(1,61))-EXCLUDED)):
        panel='S' if retention else 'AB'[i%2]
        for y in range(10):
            for n in (range(20,24) if retention else range(12 if panel=='A' else 16,16 if panel=='A' else 20)):
                path=f'data/{s:02d}/{y}_{s:02d}_{n}.wav'
                members[path]=(panel,y,s)
    source={}
    for line in run(['ls-tree','-r',REV,'data'],capture_output=True,text=True).stdout.splitlines():
        meta,path=line.split('\t',1)
        if path in members:source[path]=meta.split()[2]
    assert len(source)==2080
    env=dict(os.environ,GIT_NO_LAZY_FETCH='1',GIT_TERMINAL_PROMPT='0')
    sha_to_path={v:k for k,v in source.items()}; ids=sorted(sha_to_path)
    chk=run(['cat-file','--batch-check'],input='\n'.join(ids)+'\n',capture_output=True,text=True,env=env).stdout
    missing=[row.split()[0] for row in chk.splitlines() if row.endswith(' missing')]
    for start in range(0,len(missing),96):
        run(['-c','fetch.negotiationAlgorithm=noop','-c','gc.auto=0','fetch','-q','--no-tags','--no-write-fetch-head','origin',*missing[start:start+96]],env=env)
        print('fetched',start+len(missing[start:start+96]),'of',len(missing),flush=True)
    prior=set()
    with known.open() as fh:
        for r in csv.DictReader(fh,delimiter='\t'): prior.add(r['pcm_sha256'])
    for path in additional:
        with path.open() as fh:
            prior.update(row.split('\t')[-1].strip() for row in fh if row.strip())
    roster='S' if retention else 'AB'
    received={k:[] for k in roster}; dup=[]; manifest=[];timers={}
    with subprocess.Popen(git+['cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,env=env) as proc:
        for panel in roster:
            wall=time.monotonic();cpu=time.process_time()
            for name in sorted(members):
                group,digit,speaker=members[name]
                if group!=panel:continue
                oid=source[name];proc.stdin.write((oid+'\n').encode());proc.stdin.flush()
                rawhead=proc.stdout.readline().split(); assert rawhead[:2]==[oid.encode(),b'blob']
                raw=proc.stdout.read(int(rawhead[2]));assert proc.stdout.read(1)==b'\n'
                assert hashlib.sha1(b'blob '+rawhead[2]+b'\0'+raw).hexdigest()==oid
                hz,x=wavfile.read(io.BytesIO(raw));ph=hashlib.sha256(str((hz,x.shape,x.dtype)).encode()+x.tobytes()).hexdigest()
                if ph in prior:dup.append([panel,name,ph]);continue
                prior.add(ph);received[panel].append((features(x,hz),digit,speaker,name));manifest.append([panel,name,oid,ph])
            X,y,s,names=zip(*received[panel]);np.savez_compressed(out/(panel+'.npz'),x=X,y=y,speaker=s,record=names)
            timers[panel]={'wall':time.monotonic()-wall,'cpu':time.process_time()-cpu,'n':len(y)}
        proc.stdin.close()
    with (out/'waveforms.tsv').open('w') as f:
        w=csv.writer(f,delimiter='\t',lineterminator='\n');w.writerow(['panel','path','git_blob','pcm_sha256']);w.writerows(manifest)
    (out/'preparation.json').write_text(json.dumps(dict(revision=REV,skipped=dup,splits=timers),indent=2)+'\n')
if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for n in ('repo','known','out'):ap.add_argument(n,type=Path)
    ap.add_argument('--retention',action='store_true');ap.add_argument('--additional',type=Path,nargs='*',default=[])
    a=ap.parse_args();construct(a.repo,a.known,a.out,a.retention,a.additional)
