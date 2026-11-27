from pathlib import Path
import argparse, hashlib, json
import numpy as np
def mean_cluster(folder):
    with np.load(folder/'ranks.npz') as data:
        i,t,own=data['image'],data['caption'],data['owner']
    # Total mean R1 gives equal query weight within each direction, even with four-caption exceptions.
    n=len(i)
    signal_t=np.bincount(own,weights=(t<=1),minlength=n)
    count_t=np.bincount(own,minlength=n)
    return (i<=1).astype(float),signal_t,count_t
def score(a,idx):
    i,t,c=a
    return .5*(i[idx].mean(axis=-1)+t[idx].sum(axis=-1)/c[idx].sum(axis=-1))
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,required=True)
    out=p.parse_args().out
    seal=json.loads((out/'seal.json').read_text())
    arms={}
    for name,sha in seal['states'].items():
        f=out/name
        assert hashlib.sha256((f/'selected.pt').read_bytes()).hexdigest()==sha
        fit=json.loads((f/'fit.json').read_bytes())
        test=json.loads((f/'test.json').read_bytes())
        assert hashlib.sha256((f/'ranks.npz').read_bytes()).hexdigest()==test['ranks_sha256']
        arm=fit['arm']
        arms.setdefault(arm,[]).append((f,fit,test))
    summary={}
    clusters={}
    for a,obs in arms.items():
        clusters[a]=tuple(np.stack(v).mean(axis=0) for v in zip(*[mean_cluster(f) for f,_,_ in obs]))
        summary[a]={
            'selected':[fit['selected'] for _,fit,_ in obs],
            'dev_bidir_r1':float(np.mean([max(h['bidir_r1'] for h in fit['history']) for _,fit,_ in obs])),
            'cold_fit_test_seconds_mean':float(np.mean([fit['cold_elapsed_seconds']+test['cold_elapsed_seconds'] for _,fit,test in obs])),
            'update_seconds_mean':float(np.mean([fit['update_seconds'] for _,fit,_ in obs])),
            'ranks':{d:{k:float(np.mean([test['metrics'][d][k] for _,_,test in obs])) for k in ('r1','r5','r10','mrr')} for d in ('image_to_text','text_to_image')},
        }
    best=sorted((a for a in arms if a not in ('physical','randomphysical')),key=lambda a:(-summary[a]['dev_bidir_r1'],a))[0]
    n=len(clusters[best][0])
    idx=np.random.default_rng(30117).integers(n,size=(2000,n))
    for a in arms:
        diff=score(clusters[a],idx)-score(clusters[best],idx)
        summary[a]['bidir_r1']=float(score(clusters[a],np.arange(n)))
        summary[a]['delta_vs_dev_best']=summary[a]['bidir_r1']-float(score(clusters[best],np.arange(n)))
        summary[a]['paired95']=np.quantile(diff,[.025,.975]).tolist()
    (out/'report.json').write_text(json.dumps({'development_selected_conventional_arm':best,'n_image_clusters':n,'arms':summary},indent=2))
if __name__=='__main__':main()
