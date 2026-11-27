"""Obtain publication datasets, create independent cheap/extra frame stores, verify archive identity.
Run from the directory containing this file with Python, NumPy and SciPy.
"""
from pathlib import Path
import hashlib,zipfile,urllib.request,re,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parent/"acq_inputs"
ROOT.mkdir(exist_ok=True)
SOURCES={"daphnet":(245,"daphnet+freezing+of+gait","27c6173b3acee75a69284903756b9011a00766c1bbb743c37fc884c5dbc39399"),"mhealth":(319,"mhealth+dataset","16ad0ce709f3f00df18f348610d15bce0884b79e2143f57f446493673f02b8e0")}
def features(x,rate):
    centered=x-x.mean(1,keepdims=True)
    spec=abs(np.fft.rfft(centered,axis=1))**2/x.shape[1]**2
    freq=np.fft.rfftfreq(x.shape[1],1/rate)
    bands=[np.log1p(spec[:,(freq>=a)&(freq<b)].sum(1)) for a,b in [(0.5,3),(3,8),(8,15),(15,rate/2+.5)]]
    return np.concatenate([x.mean(1),np.log1p(x.std(1)),np.log1p(abs(np.diff(x,axis=1)).mean(1)),x.min(1),x.max(1),*bands],axis=-1).astype('float32')
def prepare(name):
    idx,slug,expected=SOURCES[name];src=ROOT/(name+'.zip')
    if not src.exists():
        part=src.with_suffix('.partial')
        with urllib.request.urlopen('https://archive.ics.uci.edu/static/public/%d/%s.zip'%(idx,slug),timeout=90) as response,part.open('wb') as out:
            for block in iter(lambda:response.read(1048576),b''):
                if out.tell()+len(block)>130000000:raise ValueError('archive size exceeded')
                out.write(block)
        assert hashlib.sha256(part.read_bytes()).hexdigest()==expected;part.replace(src)
    assert hashlib.sha256(src.read_bytes()).hexdigest()==expected
    dest=ROOT/name;dest.mkdir(exist_ok=True)
    rate=64 if name=='daphnet' else 50;n=2*rate
    cheap=[];extra=[];subject=[];labels=[];segments=[];offset=[];directory=[];sn=0
    with zipfile.ZipFile(src) as archive:
        for filename in sorted(archive.namelist()):
            m=re.search(r'/S(\d+)R\d+\.txt$' if name=='daphnet' else r'/mHealth_subject(\d+)\.log$',filename)
            if not m:continue
            with archive.open(filename) as f:a=np.loadtxt(f,dtype='float32')
            who=int(m.group(1));y=a[:,-1].astype(int)
            edges=np.diff(np.r_[False,y>0,False].astype(int))
            for start,end in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)):
                cuts=[start,end] if name=='mhealth' else [start,*list(start+1+np.flatnonzero(np.diff(a[start:end,0])>25)),end]
                for lo,hi in zip(cuts,cuts[1:]):
                    count=(hi-lo)//n
                    if count<1:continue
                    x=a[lo:lo+count*n].reshape(count,n,-1)
                    c=x[:,:,7:10] if name=='daphnet' else x[:,:,:3]
                    e=x[:,:,1:7] if name=='daphnet' else np.concatenate([x[:,:,5:11],x[:,:,14:20]],axis=2)
                    cheap.append(features(c,rate));extra.append(np.ascontiguousarray(e))
                    labels.extend(np.bincount(v).argmax()-1 for v in y[lo:lo+count*n].reshape(count,n))
                    segments.extend([sn]*count);subject.extend([who]*count);offset.extend(lo+np.arange(count)*n)
                    directory.append([sn,who,filename,int(lo),int(count)]);sn+=1
    np.save(dest/'expensive.npy',np.concatenate(extra))
    np.savez(dest/'cheap.npz',features=np.concatenate(cheap),subject=subject,segment=segments,row=offset,label=labels,rate=rate)
    (dest/'source.json').write_text(json.dumps({'archive_sha256':expected,'rate':rate,'directory':directory},indent=1))
    print(name,len(labels),len(directory),flush=True)
if __name__=='__main__':
    for name in SOURCES:prepare(name)
