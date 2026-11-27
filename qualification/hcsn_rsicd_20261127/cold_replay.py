"""Replay each original eligible checkpoint from cached raw data in a fresh Python process."""
import argparse, json, os, subprocess, sys, tempfile, time
from pathlib import Path

def worker(kind,seed,budget):
    import numpy as np
    from study import ROOT,REF, gallery,score, atomic
    import prepare
    if kind in ("linear","conventional"):
        prepare.build=lambda:None
    prepare.main()
    d,V=prepare_inputs=__import__("common").setup_data()
    tr=np.flatnonzero(d["split"]==0);dv=gallery(d,1);te=gallery(d,2)
    origin=Path(os.environ["RSICD_ORIGINAL_SHORT"]);old=origin/(kind+"-"+str(seed))
    history=json.loads((old/"history.json").read_text())
    eligible=[r for r in history if r["time"]<=budget];assert eligible
    started=time.monotonic();records=[];states=[];chosen=None;best=(-1,-1)
    if kind=="conventional":
        import copy,torch
        from neural import Conventional,Inputs,masked_infonce
        from adam import Adam
        torch.set_num_threads(1);n=[];o=[];g=[]
        for lr in [.001,.0003]:
            torch.manual_seed(seed);net=Conventional(int(d["tokens"].max())+1,24);n.append(net);o.append(Adam(net.parameters(),lr,weight_decay=.001));g.append(np.random.default_rng(seed))
        st=[0,0];batcher=Inputs("conv",d,V,"cpu")
        def embed(net,ix):
            I=[];T=[];net.eval()
            with torch.no_grad():
                for j in range(0,len(ix),128):
                    x,y=net(*batcher.batch(ix[j:j+128]));I.append(x.numpy());T.append(y.numpy())
            return np.concatenate(I),np.concatenate(T)
        for original in eligible:
            i=[.001,.0003].index(original["rate"]);net=n[i];net.train()
            while st[i]<original["step"]:
                ix=g[i].choice(tr,64,replace=False);o[i].zero_grad();x,y=net(*batcher.batch(ix))
                loss=masked_infonce(x,y,torch.tensor(d["title"][ix]));loss.backward();o[i].step();st[i]+=1
            metrics,_=score(*embed(net,dv),d,dv);q=(metrics["strict_R1"],metrics["strict_R5"])
            assert max(abs(q[0]-original["dev_r1"]),abs(q[1]-original["dev_r5"]))<1e-12
            if q>best:
                chosen=(i,st[i]);best=q;torch.save(net.state_dict(),ROOT/"selected.pt")
            records.append(q)
        fit_s=time.monotonic()-started;cold=time.monotonic();net=n[chosen[0]]
        net.load_state_dict(torch.load(ROOT/"selected.pt",weights_only=True,map_location='cpu'));I,T=embed(net,te)
    else:
        from construct import fit,encode
        from common import store_model,load_model
        if kind=="literal":
            with np.load(ROOT/"law.npz") as f:z=dict(f)
        else:z={}
        for original in eligible:
            w,reg=original["width"],original["ridge"];m=fit(V,d,tr,kind,w,reg,seed,z)
            I,T=encode(V,d,dv,m,kind,z);met,_=score(I,T,d,dv);q=(met["strict_R1"],met["strict_R5"])
            assert max(abs(q[0]-original["dev_r1"]),abs(q[1]-original["dev_r5"]))<1e-12
            store_model(ROOT/f'{w}-{reg}.npz',m,{})
            if q>best:best=q;chosen=(w,reg)
            records.append(q)
        fit_s=time.monotonic()-started;cold=time.monotonic();m,_=load_model(ROOT/f'{chosen[0]}-{chosen[1]}.npz')
        I,T=encode(V,d,te,m,kind,z)
    met,rank=score(I,T,d,te)
    with np.load(origin/"cold_ranks.npz") as src:
        raw=src[f"{kind}/{seed}/{budget}"];current=np.stack(list(rank.values()))
        assert np.array_equal(raw,current)
    prep=json.loads((ROOT/"prepared.json").read_text())
    atomic(ROOT/"done.json",{"method":kind,"seed":seed,"budget":budget,"eligible":len(eligible),"selection":chosen,"source_decode_s":prep["source_verify_decode_preparation_s"],"price_table_s":prep["literal_table_s"],"fit_and_select_s":fit_s,"cold_test_s":time.monotonic()-cold,"strict_R1":met["strict_R1"],"rank_mismatches":int((raw!=current).sum())})

def supervisor():
    loc=Path(os.environ["RSICD_ORIGINAL_SHORT"]).parent/'cold_replay';loc.mkdir(exist_ok=True)
    for seed in [109,271,463]:
        for k,b in [('literal',12),('linear',12),('conventional',12),('conventional',60)]:
            receipt=loc/f'{k}-{seed}-{b}.json'
            if receipt.exists():continue
            with tempfile.TemporaryDirectory(prefix='rsicd-cold-') as tmp:
                env={**os.environ,"HCSN_CATALOG_DATA":tmp};clock=time.perf_counter()
                result=subprocess.run([sys.executable,str(Path(__file__).resolve()),k,str(seed),str(b)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                elapsed=time.perf_counter()-clock
                if result.returncode:
                    (loc/(receipt.stem+".failure.log")).write_bytes(result.stdout)
                    raise RuntimeError((k,b,seed,result.returncode))
                r=json.loads((Path(tmp)/"done.json").read_text());r["external_process_s"]=elapsed
                receipt.write_text(json.dumps(r,indent=1));print(k,seed,b,elapsed,flush=True)
if __name__=="__main__":
    if len(sys.argv)==1:supervisor()
    else:worker(sys.argv[1],int(sys.argv[2]),int(sys.argv[3]))
