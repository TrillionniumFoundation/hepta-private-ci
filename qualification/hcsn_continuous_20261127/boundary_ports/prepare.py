import os,urllib.request,hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(os.environ.get('HCSN_FORD_DATA','/mnt/data/hcsn-ford-9c415'));ROOT.mkdir(parents=True,exist_ok=True)
def main():
    receipt={};allhash={}
    for name in ['TRAIN','TEST']:
        filename='FordA_'+name+'.tsv';p=ROOT/filename;url='https://raw.githubusercontent.com/hfawaz/cd-diagram/master/FordA/'+filename
        if not p.exists():
            with urllib.request.urlopen(url,timeout=60) as f:b=f.read(36000000);assert not f.read(1)
            p.write_bytes(b)
        a=np.loadtxt(p,dtype=np.float32);assert a.shape==({'TRAIN':3601,'TEST':1320}[name],501)
        labels=(a[:,0]>0).astype(np.int64);raw=np.ascontiguousarray(a[:,1:])
        keys=np.array([hashlib.sha256(x.tobytes()).hexdigest() for x in raw]);f=raw.reshape(-1,20,25);power=abs(np.fft.rfft(f-f.mean(2,keepdims=True),axis=2))**2
        feat=np.stack([f.mean(2),np.sqrt((f*f).mean(2)),abs(np.diff(f,axis=2)).mean(2),abs(np.diff(f,n=2,axis=2)).mean(2),*[power[:,:,lo:hi].sum(2)/np.maximum(power[:,:,1:].sum(2),1e-8) for lo,hi in [(1,3),(3,7),(7,13)]]],-1).astype(np.float32)
        allhash[name]=set(keys);record={'url':url,'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'count':len(keys),'unique':len(set(keys))}
        if name=='TRAIN':
            dev=np.sort(np.concatenate([ix[np.argsort(keys[ix])][::5] for ix in [np.flatnonzero(labels==c) for c in [0,1]]]))
            train=np.setdiff1d(np.arange(len(keys)),dev)
            # The same deterministic balanced dev subset is used throughout.
            val=np.sort(np.concatenate([i[np.argsort(keys[i])][:192] for i in [dev[labels[dev]==c] for c in [0,1]]]))
            mean=feat[train].mean((0,1));std=feat[train].std((0,1)).clip(1e-5)
            np.savez(ROOT/'train.npz',raw=raw,feat=(feat-mean)/std,y=labels,train=train,val=val,full_dev=dev,ident=keys,mean=mean,std=std)
            record.update(train=len(train),dev=len(dev),dev_used=len(val))
        else:
            np.savez(ROOT/'sealed.npz',raw=raw,feat=(feat-mean)/std,y=labels,ident=keys)
        receipt[name]=record
    receipt['exact_signal_overlap']=len(allhash['TRAIN']&allhash['TEST'])
    (ROOT/'source.json').write_text(json.dumps(receipt,indent=2));print(receipt)
if __name__=='__main__':main()
