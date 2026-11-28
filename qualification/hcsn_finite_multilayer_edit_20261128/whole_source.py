"""Stream the official SCv2 archive, validating its MD5 without retaining 2.4 GB of compressed media."""
import argparse
import csv
import hashlib
import io
import json
import re
import tarfile
import time
import urllib.request
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from data import features
from third_corpus import NAMES
URL='https://storage.googleapis.com/download.tensorflow.org/data/speech_commands_v0.02.tar.gz'
SIZE=2428923189
MD5='6b74f3901214cb2c2934e98196829835'
class RangeReader:
    def __init__(self):
        self.pos=0;self.buffer=b'';self.md5=hashlib.md5();self.current=0;self.part=0
    def read(self,n=-1):
        if self.current==len(self.buffer):
            if self.pos==SIZE:return b''
            last=min(self.pos+16*1024*1024,SIZE)-1;failure=None
            for t in range(4):
                try:
                    req=urllib.request.Request(URL+f'?hcsn_range={self.pos}',headers={'Range':f'bytes={self.pos}-{last}'})
                    with urllib.request.urlopen(req,timeout=90) as rsp:
                        if rsp.status!=206 or rsp.headers.get('Content-Range')!=f'bytes {self.pos}-{last}/{SIZE}':raise ValueError('range mismatch '+str(rsp.status))
                        block=rsp.read()
                    if len(block)!=last-self.pos+1:raise ValueError('short chunk')
                    self.buffer=block;self.current=0;self.pos=last+1;self.md5.update(block);self.part+=1
                    if self.part%10==0:print('compressed bytes verified by range',self.pos,flush=True)
                    break
                except Exception as e:
                    failure=e;print('retry range',self.pos,type(e).__name__,str(e)[:100],flush=True);time.sleep(min(8,2**t))
            else:raise RuntimeError('unreadable range') from failure
        take=len(self.buffer)-self.current if n<0 else min(n,len(self.buffer)-self.current)
        ans=self.buffer[self.current:self.current+take];self.current+=take;return ans

def main(src,known,out):
    out.mkdir(parents=True,exist_ok=True);st=time.monotonic();cpu=time.process_time();rec=[];splits={}
    # The third corpus manifest uses member names with the original label prefixed; exclude by PCM.
    with known.open() as fh:prior={r['pcm_sha256'] for r in csv.DictReader(fh,delimiter='\t')}
    obj=RangeReader() if src is None else src.open('rb')
    with tarfile.open(fileobj=obj,mode='r|gz',bufsize=1024*1024) as tar:
        for m in tar:
            name=m.name.removeprefix('./')
            if not m.isfile():continue
            if name in ('validation_list.txt','testing_list.txt'):
                splits[name]=set(v.strip() for v in tar.extractfile(m).read().decode().splitlines());continue
            parts=name.split('/')
            if len(parts)!=2 or parts[0] not in NAMES:continue
            match=re.fullmatch(r'([a-zA-Z0-9]+)_nohash_(\d+)\.wav',parts[1]);assert match,name
            raw=tar.extractfile(m).read();hz,x=wavfile.read(io.BytesIO(raw))
            h=hashlib.sha256(str((hz,x.shape,x.dtype)).encode()+x.tobytes()).hexdigest()
            rec.append((name,NAMES.index(parts[0]),match.group(1),h,hashlib.sha256(raw).hexdigest(),features(x,hz)))
    if src is None:
        while obj.read(1024*1024):pass
        assert obj.md5.hexdigest()==MD5,(obj.pos,obj.md5.hexdigest())
    else:
        obj.close()
        with src.open('rb') as fh:assert hashlib.file_digest(fh,'md5').hexdigest()==MD5
    assert len(splits)==2
    used=set();parts={k:[] for k in ('support','development','confirmation')};skips=0;overlap=[]
    for r in sorted(rec,key=lambda q:hashlib.sha256(q[0].encode()).digest()):
        name,y,sp,h,wsha,x=r
        k='confirmation' if name in splits['testing_list.txt'] else 'development' if name in splits['validation_list.txt'] else 'support'
        if h in prior:overlap.append((k,name,h));continue
        if h in used:skips+=1;continue
        used.add(h);parts[k].append(r)
    selected={};manifest=[];speakers={}
    for k,rows in parts.items():
        cap={'support':30,'development':25,'confirmation':200}[k]
        take=[r for label in range(10) for r in [z for z in rows if z[1]==label][:cap]]
        name,y,sp,pcm,wh,x=map(np.asarray,zip(*take));selected[k]={'utterances':len(x),'per_label':np.bincount(y,minlength=10).tolist(),'speakers':len(set(sp))}
        np.savez_compressed(out/(k+'.npz'),x=x,y=y,speaker=sp,record=name)
        manifest.extend((k,*r[:5]) for r in take);speakers[k]=set(sp)
    for a,b in [('support','development'),('support','confirmation'),('development','confirmation')]:assert not speakers[a]&speakers[b]
    with (out/'source.tsv').open('w') as f:
        w=csv.writer(f,delimiter='\t',lineterminator='\n');w.writerow(['part','path','digit','speaker','pcm_sha256','wave_sha256']);w.writerows(manifest)
    info=dict(url=URL,compressed_bytes=SIZE,md5=MD5,raw_digits=len(rec),duplicate_pcm=skips,excluded_restricted_pcm=overlap,selected=selected,
              full_stream_and_preparation_wall=time.monotonic()-st,full_stream_and_preparation_cpu=time.process_time()-cpu)
    (out/'PREPARATION.json').write_text(json.dumps(info,indent=2)+'\n');print(selected,flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('known',type=Path);ap.add_argument('out',type=Path);ap.add_argument('--archive',type=Path);a=ap.parse_args();main(a.archive,a.known,a.out)
