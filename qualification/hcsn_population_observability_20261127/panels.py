"""Read immutable aeon v1.3.0 measured-record sources. Test conversion requires fit seals."""
import argparse,hashlib,json
from pathlib import Path
import urllib.request
import numpy as np

SETS=("BasicMotions","ItalyPowerDemand","JapaneseVowels")
BLOBS={
"BasicMotions_TRAIN.ts":"49452c6e6309742dc0609896136aa3e727428533","BasicMotions_TEST.ts":"f44be88c557bb914c3d30098ac809795a269c41d",
"ItalyPowerDemand_TRAIN.ts":"a310296a2fcdec5b358f0d0d99ceca5b2b39c0a6","ItalyPowerDemand_TEST.ts":"4303ddce190876efffa8a91e054c387913e83425",
"JapaneseVowels_TRAIN.ts":"e50606ea9c7acdcc1677d5e5b79602200bb2ba97","JapaneseVowels_TEST.ts":"9c46401a48f491c3770a8ad120905ec5984c2f1d"}
def read(raw,name):
    raw.mkdir(parents=True,exist_ok=True);path=raw/name
    if path.exists():body=path.read_bytes()
    else:
        dataset=name.split("_")[0]
        url="https://raw.githubusercontent.com/aeon-toolkit/aeon/v1.3.0/aeon/datasets/data/"+dataset+"/"+name
        with urllib.request.urlopen(url,timeout=35) as f:body=f.read()
    oid=hashlib.sha1(b"blob "+str(len(body)).encode()+b"\0"+body).hexdigest()
    assert oid==BLOBS[name],name
    if not path.exists():path.write_bytes(body)
    text=body.decode();samples=[];labels=[];codes=[]
    for row in text[text.lower().index("@data")+5:].strip().splitlines():
        if not row or row.startswith("#"):continue
        fields=row.split(":");sample=np.array([[float(v) for v in c.split(",")] for c in fields[:-1]],dtype="<f8").T
        codes.append(hashlib.sha256(sample.tobytes()).hexdigest());labels.append(fields[-1].strip())
        features=[]
        for i in range(8):
            lo,hi=(i*len(sample))//8,((i+1)*len(sample))//8
            local=sample[lo:max(lo+1,hi)]
            features.append(np.r_[local.mean(0),np.sqrt(np.mean(local**2,axis=0))])
        samples.append(features)
    return np.array(samples),np.array(labels),np.array(codes)
def prepare(raw,out,phase):
    out.mkdir(parents=True,exist_ok=True)
    receipts={}
    for name in SETS:
        x,y,code=read(raw,name+"_TRAIN.ts");cls=np.unique(y);ids=np.arange(len(y))
        dev=[]
        for label in cls:
            ix=ids[y==label]
            ordered=sorted(ix,key=lambda i:hashlib.sha256(f"population-v1/{name}/{i}".encode()).digest())
            dev.extend(ordered[:max(1,round(.2*len(ix)))])
        dev=np.sort(dev);fit=ids[~np.isin(ids,dev)]
        mean=x[fit].mean((0,1));sd=x[fit].std((0,1)).clip(1e-8)
        scale=lambda vals:np.clip((vals-mean)/sd,-8,8)
        if phase=="fit":
            np.savez_compressed(out/f"{name}-fit.npz",x=scale(x[fit]),y=np.searchsorted(cls,y[fit]),x_dev=scale(x[dev]),y_dev=np.searchsorted(cls,y[dev]),fit_ids=fit,dev_ids=dev,labels=cls)
            receipts[name]={"nfit":len(fit),"ndev":len(dev),"classes":cls.tolist(),"train_blob":BLOBS[name+"_TRAIN.ts"]}
        else:
            xt,yt,test_ids=read(raw,name+"_TEST.ts");keep=~np.isin(test_ids,code);seen=set()
            for i,k in enumerate(test_ids):
                if k in seen:keep[i]=False
                seen.add(k)
            np.savez_compressed(out/f"{name}-test.npz",x=scale(xt[keep]),y=np.searchsorted(cls,yt[keep]),id=np.flatnonzero(keep),labels=cls)
            receipts[name]={"source_n":len(xt),"n":int(keep.sum()),"excluded":np.flatnonzero(~keep).tolist(),"test_blob":BLOBS[name+"_TEST.ts"]}
    (out/f"source-{phase}.json").write_text(json.dumps(receipts,indent=2)+"\n")
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("phase",choices=["fit","confirm"]);ap.add_argument("root",type=Path);args=ap.parse_args()
    if args.phase=="confirm":assert (args.root/"fit/SEAL.json").is_file()
    prepare(args.root/"raw",args.root/"panels",args.phase)
