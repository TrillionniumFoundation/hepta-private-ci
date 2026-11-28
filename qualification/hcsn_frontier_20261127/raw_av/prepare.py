"""Verify CREMA-D source media against pinned Git LFS identities and decode both channels."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.request import Request, urlopen
import numpy as np

REV='1658cd342dff90010aa843eaeebd53610a08b1dc'
REPO='CheyneyComputerScience/CREMA-D'
T=12
EMOTIONS={'ANG':'anger','DIS':'disgust','FEA':'fear','HAP':'happy','NEU':'neutral','SAD':'sad'}
SENTENCES=('DFA','IEO','IOM','ITH','ITS','IWL','IWW','MTI','TAI','TIE','TSI','WSI')


def sha(s):
    return hashlib.sha256(s).hexdigest()


def download(url):
    last=None
    for i in range(5):
        try:
            with urlopen(Request(url,headers={'User-Agent':'Hepta-CREMA-D-research/1'}),timeout=50) as stream:
                return stream.read()
        except OSError as e:
            last=e
            time.sleep(min(45,2**(i+1)))
    raise last


def extract_one(item):
    root,idx,entry=item
    name=Path(entry['path']).stem
    base=root/'data';rr=base/'raw'/(name+'.flv');out=base/'clips'/(name+'.npz')
    pointer=entry['sha']
    if out.exists():
        with np.load(out) as f:
            assert f['video'].shape==(T,28,28) and f['audio'].shape==(T,64)
            assert str(f['pointer'])==pointer
            return name,str(f['sha256']),int(f['samples']),int(f['frames'])
    if rr.exists():content=rr.read_bytes()
    else:content=download(f"https://media.githubusercontent.com/media/{REPO}/{REV}/{entry['path']}")
    digest=sha(content)
    ptr=f'version https://git-lfs.github.com/spec/v1\noid sha256:{digest}\nsize {len(content)}\n'.encode()
    oid=hashlib.sha1(b'blob '+str(len(ptr)).encode()+b'\0'+ptr).hexdigest()
    assert oid==pointer and content.startswith(b'FLV'), (name,pointer,oid,len(content))
    if not rr.exists():
        temp=rr.with_suffix('.part');temp.write_bytes(content);temp.replace(rr)
    cmd=[str(root/'env/ffmpeg'),'-nostdin','-loglevel','error','-threads','1','-filter_threads','1','-i',str(rr)]
    def decode(extra):
        return subprocess.run(cmd+extra+['pipe:1'],capture_output=True,check=True,timeout=70).stdout
    pix=np.frombuffer(decode(['-map','0:v:0','-vf','scale=28:28:flags=area','-pix_fmt','gray','-f','rawvideo']),np.uint8).reshape(-1,28,28)
    wave=np.frombuffer(decode(['-map','0:a:0','-ac','1','-ar','8000','-f','s16le']),'<i2')
    assert len(pix)>T and len(wave)>=1024
    frame=pix[np.minimum(len(pix)-1,((np.arange(T)+.5)*len(pix)/T).astype(int))]
    # Fixed signal transform from the original synchronized audio stream. No fitted speech encoder.
    w=wave.astype(np.float32)/32768
    windows=np.lib.stride_tricks.sliding_window_view(w,256)[::80]
    amp=np.abs(np.fft.rfft(windows*np.hanning(256),axis=-1))**2
    band=.5*(amp[:,1:129:2]+amp[:,2:129:2])
    a=np.stack([np.log1p(s).mean(0) for s in np.array_split(band,T)]).astype('float32')
    assert np.isfinite(a).all()
    temp=out.with_suffix('.part')
    with temp.open('wb') as f:np.savez_compressed(f,video=frame,audio=a,frames=len(pix),samples=len(wave),sha256=digest,pointer=pointer)
    temp.replace(out)
    return name,digest,len(wave),len(pix)


def prepare(root):
    base=root/'data'
    for d in ('raw','clips'): (base/d).mkdir(exist_ok=True,parents=True)
    source=base/'tree.json'
    if not source.exists():
        source.write_bytes(download(f'https://api.github.com/repos/{REPO}/git/trees/{REV}?recursive=1'))
    tree=json.loads(source.read_bytes());assert not tree['truncated']
    rows=sorted([r for r in tree['tree'] if r['path'].startswith('VideoFlash/') and r['path'].lower().endswith('.flv')],key=lambda x:x['path'])
    assert len(rows)==7442, len(rows)
    actors=sorted({Path(e['path']).stem.split('_')[0] for e in rows},key=lambda x:sha(('hepta-crema-v1|'+x).encode()))
    assert len(actors)==91
    split={a:0 if i<61 else 1 if i<75 else 2 for i,a in enumerate(actors)}
    readme=next(r for r in tree['tree'] if r['path']=='docs/README.md')
    txt=download(f'https://raw.githubusercontent.com/{REPO}/{REV}/docs/README.md')
    assert hashlib.sha1(b'blob '+str(len(txt)).encode()+b'\0'+txt).hexdigest()==readme['sha']
    doc=txt.decode().replace('’',"'")
    labels={}
    for code in SENTENCES:
        m=re.search(r'(?m)^\s*[-*]\s*(.+?)\s*\('+code+r'\)',doc)
        assert m,code
        labels[code]=re.findall(r"[a-z]+(?:'[a-z]+)?",m.group(1).lower())
    # The transcript and performed-emotion code become text candidates, never audiovisual input.
    words=[labels[s]+[emo] for s in SENTENCES for emo in EMOTIONS.values()]
    voc=['<PAD>','<END>']+sorted({w for sentence in words for w in sentence});vi={w:i for i,w in enumerate(voc)}
    texts=np.zeros((len(words),T),np.int64)
    for k,t in enumerate(words):
        assert len(t)+1<=T
        texts[k,:len(t)]=[vi[j] for j in t];texts[k,-1]=1
    (base/'roster.json').write_text(json.dumps(dict(rev=REV,tree_oid=tree['sha'],tree_json_sha256=sha(source.read_bytes()),actors=split,sentences=labels,vocab=voc,
        sentences_order=SENTENCES,emotions=list(EMOTIONS),sources=[[r['path'],r['sha']] for r in rows]),indent=1))
    def safe(item):
        try:return extract_one(item)
        except Exception as e:return [Path(item[2]['path']).stem,type(e).__name__,str(e)[:600]]
    failures=[];records=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i,ret in enumerate(pool.map(safe,[(root,i,item) for i,item in enumerate(rows)])):
            if len(ret)==4:records.append(ret)
            else:failures.append(ret)
            if i%150==0:print('decoded',i+1,'failures',len(failures),flush=True)
    (base/'failures.json').write_text(json.dumps(failures,indent=2))
    if failures:raise RuntimeError(f'{len(failures)} sources failed; see failures.json')
    vv=[];aa=[];ids=[];fold=[];target=[]
    for name,digest,_,_ in records:
        actor,s,emo,_=name.split('_');fold.append(split[actor]);target.append(6*SENTENCES.index(s)+list(EMOTIONS).index(emo))
        with np.load(base/'clips'/(name+'.npz')) as z:
            assert str(z['sha256'])==digest;vv.append(z['video']);aa.append(z['audio'])
        ids.append(name)
    pack=base/'data.npz';temp=pack.with_suffix('.part')
    with temp.open('wb') as f:np.savez_compressed(f,images=np.stack(vv),audio=np.stack(aa),ids=np.array(ids),split=np.array(fold),labels=np.asarray(target),tokens=texts)
    temp.replace(pack)
    (base/'media.json').write_text(json.dumps(records,separators=(',',':')))
    info=dict(splits=np.bincount(fold).tolist(),classes=np.bincount(target,minlength=72).tolist(),
              samples=len(rows),actors=len(actors),data_sha256=sha(pack.read_bytes()),media_sha256=sha((base/'media.json').read_bytes()),
              roster_sha256=sha((base/'roster.json').read_bytes()),decoder=json.loads((root/'env/decoder.json').read_text()))
    (base/'prepared.json').write_text(json.dumps(info,indent=2));print('verified and sealed',info,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);prepare(p.parse_args().root.resolve())
