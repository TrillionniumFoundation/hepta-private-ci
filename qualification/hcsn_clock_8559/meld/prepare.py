"""Decode authors' original MELD clip files locally; published manifests omit media and transcripts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import numpy as np

SPLITS=('train','dev','test')
EMOTIONS=('anger','disgust','fear','joy','neutral','sadness','surprise')

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def atomic(p,item):
    temp=p.with_suffix('.tmp');temp.write_text(json.dumps(item,ensure_ascii=False)+'\n');os.replace(temp,p)
def untar(root):
    work=root/'official';work.mkdir(exist_ok=True)
    if (work/'FILES.json').exists():return
    target={'train.tar.gz','dev.tar.gz','test.tar.gz'}|{s+'_sent_emo.csv' for s in SPLITS}
    found={}
    with tarfile.open(root/'MELD.Raw.tar.gz','r|gz') as arc:
        for member in arc:
            name=Path(member.name).name
            if not member.isfile() or name not in target:continue
            assert name not in found
            out=work/name
            if not (out.exists() and out.stat().st_size==member.size):
                tmp=out.with_suffix(out.suffix+'.partial')
                with arc.extractfile(member) as src,tmp.open('wb') as fp:shutil.copyfileobj(src,fp,1048576)
                assert tmp.stat().st_size==member.size;os.replace(tmp,out)
            found[name]={'bytes':member.size,'sha256':digest(out)}
            print('reference member',name,member.size,flush=True)
    if set(found)!=target:raise ValueError(('missing nested official file',sorted(target-found.keys()),sorted(found)))
    atomic(work/'FILES.json',found)

def annotations(root,s):
    p=root/'official'/(s+'_sent_emo.csv')
    for enc in ('utf-8-sig','cp1252','latin1'):
        try:
            with p.open(encoding=enc,newline='') as fp:rows=list(csv.DictReader(fp))
            break
        except UnicodeError:continue
    out={}
    for row in rows:
        key=f"dia{int(row['Dialogue_ID'])}_utt{int(row['Utterance_ID'])}"
        if key in out:raise ValueError((s,key))
        out[key]=row
    return out
def invoke(args,timeout=60):
    return subprocess.run(args,check=True,capture_output=True,timeout=timeout).stdout

def decode(path):
    start=time.perf_counter()
    raw=invoke(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)])
    dur=float(raw)
    if not 0<dur<=240:raise ValueError('invalid utterance duration')
    ff=['ffmpeg','-nostdin','-loglevel','error','-threads','1','-filter_threads','1','-i',str(path)]
    video=invoke([*ff,'-map','0:v:0','-vf',f'fps={8/dur:.15g}:round=up,scale=32:32','-frames:v','8','-threads','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
    v=np.frombuffer(video,np.uint8).reshape(-1,32,32,3)
    if not len(v):raise ValueError('empty video')
    decoded=len(v)
    if len(v)<8:v=np.concatenate([v,np.repeat(v[-1:],8-len(v),axis=0)])
    audio=invoke([*ff,'-map','0:a:0','-ac','1','-ar','8000','-threads','1','-f','s16le','pipe:1'])
    a=np.frombuffer(audio,dtype='<i2');clip=np.zeros((8,2048),dtype=np.int16)
    if not len(a):raise ValueError('empty audio')
    for k in range(8):
        first=round((k+.5)*dur*8000/8)-1024;lo=max(0,first);hi=min(len(a),first+2048)
        if hi>lo:clip[k,lo-first:hi-first]=a[lo:hi]
    return v,clip,dict(duration=dur,audio_samples=len(a),video_frames=decoded,decode_s=time.perf_counter()-start)

def one(path,media_sha,row,out):
    file=out/(path.stem+'.npz');receipt=out/(path.stem+'.json')
    try:
        if receipt.exists() and json.loads(receipt.read_text())['media_sha256']==media_sha:return
        v,a,s=decode(path)
        with file.with_suffix('.partial').open('wb') as fp:np.savez_compressed(fp,video=v,audio=a)
        os.replace(file.with_suffix('.partial'),file)
        y=EMOTIONS.index(row['Emotion'].strip().lower())
        s.update(usable=True,media_sha256=media_sha,derived_sha256=digest(file),y=y,
                 dialogue=int(row['Dialogue_ID']),utterance=int(row['Utterance_ID']),
                 season=row.get('Season',''),episode=row.get('Episode',''))
        atomic(receipt,s)
    except (subprocess.SubprocessError,ValueError,KeyError) as e:
        atomic(receipt,dict(usable=False,media_sha256=media_sha,error=type(e).__name__,detail=str(e)[:150]))
    finally:path.unlink(missing_ok=True)

def process(root,s,workers):
    labels=annotations(root,s);out=root/'decoded'/s;out.mkdir(parents=True,exist_ok=True)
    allnames=set();matches=set();jobs=[];t=time.perf_counter()
    with tempfile.TemporaryDirectory(dir=root) as tmp,ThreadPoolExecutor(workers) as pool:
        with tarfile.open(root/'official'/(s+'.tar.gz'),'r|gz') as arc:
            for member in arc:
                if not member.isfile() or not member.name.lower().endswith('.mp4'):continue
                key=Path(member.name).stem
                if key in allnames:raise ValueError('duplicate clip '+s+'/'+key)
                allnames.add(key)
                if key not in labels:continue
                matches.add(key)
                if (out/(key+'.json')).exists():continue
                if not re.fullmatch(r'dia[0-9]+_utt[0-9]+',key):raise ValueError(key)
                p=Path(tmp)/(key+'.mp4')
                with arc.extractfile(member) as source,p.open('wb') as dest:shutil.copyfileobj(source,dest,262144)
                jobs.append(pool.submit(one,p,digest(p),labels[key],out))
                if len(jobs)>=workers*2:jobs.pop(0).result()
                if len(matches)%500==0:print(s,len(matches),round(time.perf_counter()-t),flush=True)
        for job in jobs:job.result()
    rows={p.stem:json.loads(p.read_text()) for p in sorted(out.glob('dia*.json'))}
    missing=sorted(set(labels)-matches)
    assert len(rows)==len(matches)
    evidence=dict(annotation_sha256=digest(root/'official'/(s+'_sent_emo.csv')),annotated=len(labels),media_files=len(allnames),
                  annotated_missing=missing,unannotated_files=sorted(allnames-labels.keys()),rows=rows,elapsed_s=time.perf_counter()-t)
    atomic(root/(s+'-decoded.json'),evidence)
    print(s,'finished',len(rows),'missing',len(missing),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--workers',type=int,default=3)
    a=p.parse_args();untar(a.root)
    for s in SPLITS:process(a.root,s,a.workers)
