"""Acquire auxiliary real clips and two previously unused repetition panels; charge network acquisition separately."""
import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
from scipy.io import wavfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from data import features
from fresh_data import EXCLUDED,REV


def main(a):
    a.out.mkdir(exist_ok=True,parents=True)
    done=a.out/'sources.json'
    if done.exists():return
    start=time.perf_counter();known=set()
    for p in a.known:
        with p.open() as f:
            rows=csv.reader(f,delimiter='\t');first=next(rows)
            if 'pcm_sha256' in first:
                column=first.index('pcm_sha256')
            elif len(first)==3 and len(first[-1])==64:
                column=-1;known.add(first[column])
            else:raise ValueError(f'unknown digest table {p.name}')
            for row in rows:known.add(row[column])
    with np.load(a.original/'new_cal.npz') as f:support={int(v) for v in np.unique(f['speaker'])}
    with np.load(a.original/'new_dev.npz') as f:development={int(v) for v in np.unique(f['speaker'])}
    assert len(support)==len(development)==4 and support|development==EXCLUDED
    folds={s:'aux' for s in support}
    for i,s in enumerate(sorted(set(range(1,61))-EXCLUDED)):
        folds[s]=('A2','B2')[i%2]
    wanted={}
    for sp,part in folds.items():
        nums={'aux':range(12,50),'A2':range(24,27),'B2':range(27,30)}[part]
        for lab in range(10):
            for rep in nums:
                name=f'data/{sp:02d}/{lab}_{sp:02d}_{rep}.wav'
                wanted[name]=[part,lab,sp,rep]
    cmd=['git','--git-dir='+str(a.repo.resolve())]
    tree=subprocess.run(cmd+['ls-tree','-r',REV,'data'],capture_output=True,text=True,check=True)
    obj={}
    for row in tree.stdout.splitlines():
        meta,name=row.split('\t',1)
        if name in wanted:obj[name]=meta.split()[2]
    assert set(obj)==set(wanted)
    env=dict(os.environ,GIT_NO_LAZY_FETCH='1',GIT_TERMINAL_PROMPT='0')
    ids=sorted(set(obj.values()))
    inspect=subprocess.run(cmd+['cat-file','--batch-check'],input='\n'.join(ids)+'\n',capture_output=True,text=True,check=True,env=env)
    missing=[line.split()[0] for line in inspect.stdout.splitlines() if line.endswith(' missing')]
    for pos in range(0,len(missing),96):
        subprocess.run(cmd+['-c','fetch.negotiationAlgorithm=noop','-c','gc.auto=0','fetch','-q','--no-tags','--no-write-fetch-head','origin',*missing[pos:pos+96]],env=env,check=True)
    fetched=time.perf_counter();panels={k:[] for k in ('aux','A2','B2')};manifest=[];dropped=[]
    with subprocess.Popen(cmd+['cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,env=env) as proc:
        for name,(part,label,sp,rep) in sorted(wanted.items()):
            key=obj[name];proc.stdin.write((key+'\n').encode());proc.stdin.flush()
            tag,kind,n=proc.stdout.readline().split();assert tag.decode()==key and kind==b'blob'
            data=proc.stdout.read(int(n));assert proc.stdout.read(1)==b'\n'
            assert hashlib.sha1(b'blob '+n+b'\0'+data).hexdigest()==key
            hz,x=wavfile.read(io.BytesIO(data));pcm=hashlib.sha256(str((hz,x.shape,x.dtype)).encode()+x.tobytes()).hexdigest()
            if pcm in known:dropped.append([name,pcm]);continue
            known.add(pcm);feature=features(x,hz);panels[part].append((feature,label,sp,name))
            manifest.append([part,name,key,pcm])
        proc.stdin.close()
    for part,recs in panels.items():
        pol=list(zip(*recs));arrays={'x':np.stack(pol[0]),'record':np.asarray(pol[3])}
        if part!='aux':arrays.update(y=np.array(pol[1]),speaker=np.array(pol[2]))
        np.savez_compressed(a.out/(part+'.npz'),**arrays)
    with (a.out/'clips.tsv').open('w') as f:
        w=csv.writer(f,delimiter='\t',lineterminator='\n');w.writerow(['split','path','git_blob','pcm_sha256']);w.writerows(manifest)
    done.write_text(json.dumps(dict(revision=REV,support_speakers=sorted(support),dev_speakers=sorted(development),
           total={k:len(v) for k,v in panels.items()},dropped=dropped,needed_git_blobs=len(missing),git_fetch_s=fetched-start,
           features_and_write_s=time.perf_counter()-fetched,total_s=time.perf_counter()-start),indent=1)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for s in ('repo','original','out'):p.add_argument(s,type=Path)
    p.add_argument('--known',nargs='+',type=Path,required=True)
    main(p.parse_args())
