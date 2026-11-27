"""Independent category audit for sealed strict retrieval. No new selection or fitting."""
import collections
import json
import os
from pathlib import Path
import sys
import numpy as np
import torch
from study import ROOT, REF, SEEDS, setup_data, gallery, score, load_model, encode, sha, atomic
from neural import Conventional, Inputs

def main():
    base=Path(os.environ["RSICD_RAW"])/"classes"
    categories={}
    for path in sorted(base.glob("*.txt")):
        for line in path.read_text().splitlines():
            name=line.strip()
            assert name and name not in categories
            categories[name]=path.stem.lower()
    assert len(categories)==10921
    assert sha(base.parent/"classes.rar")=="0ce6663c67e9e9301511e0719ce93108aa45fb8468dd174c446d5ab733975b99"
    torch.set_num_threads(1);p=ROOT/"short";testrows=json.loads((ROOT/"rows.json").read_text())
    d,V=setup_data();ix=gallery(d,2);cats,idx=np.unique([categories[r["filename"]] for r in testrows],return_inverse=True)
    d["group"]=idx
    with np.load(ROOT/"law.npz") as ff:z=dict(ff)
    frozen=json.loads((p/"seal.json").read_text())
    rows={};cache={};ranks={}
    with np.load(p/"cold_ranks.npz") as old:
        for k,row in frozen.items():
            if not row:continue
            path=ROOT/row["path"];s=row["sha256"];assert sha(path)==s
            if s not in cache:
                method=k.split("/")[0]
                if method=="conventional":
                    ob=Inputs("conv",d,V,"cpu");n=Conventional(int(d["tokens"].max())+1,24)
                    n.load_state_dict(torch.load(path,map_location="cpu",weights_only=True));n.eval();I=[];T=[]
                    with torch.no_grad():
                        for j in range(0,len(ix),128):
                            x,y=n(*ob.batch(ix[j:j+128]));I.append(x.numpy());T.append(y.numpy())
                    I,T=np.concatenate(I),np.concatenate(T)
                else:
                    m,_=load_model(path);I,T=encode(V,d,ix,m,method,z)
                _,rank=score(I,T,d,ix);cache[s]=np.stack(list(rank.values())).astype(np.int16)
            v=cache[s];assert np.array_equal(v[:,:,:2],old[k][:,:,:2])
            a=(v[:,:,2]==1).mean(0)
            rows[k]=dict(image_weighted=float(a.mean()),equal_category=float(np.mean([a[idx[ix]==j].mean() for j in np.unique(idx[ix])])))
            ranks[k]=v[:,:,2]
    out=p/"official_category_ranks.npz";np.savez_compressed(out,**ranks)
    intervals={}
    for t in (12,60):
        for b in ('smooth','linear','conventional'):
            avgs=[np.mean([(ranks[f"{m}/{s}/{t}"]==1).mean(0) for s in SEEDS],0) for m in ('literal',b)]
            gap=avgs[0]-avgs[1]
            g=np.random.default_rng(220711);boot=np.concatenate([gap[g.integers(len(ix),size=(100,len(ix)))].mean(1) for _ in range(80)])
            intervals[f"literal-{b}/{t}"]={"estimate":float(gap.mean()),"paired95":np.quantile(boot,[.025,.975]).tolist()}
    atomic(p/"official_categories.json",{"official_archive_sha":sha(base.parent/"classes.rar"),"n_groups":len(cats),"all_query_rows":len(ix),"names_recovered_from_official_mapping":sum(not testrows[i]["category"] for i in ix),"scores":rows,"paired":intervals,"ranks_sha":sha(out),"preexisting_strict_and_caption_ranks_preserved":True,"scope":"descriptive semantic metric; no new selection"})
if __name__=="__main__":main()
