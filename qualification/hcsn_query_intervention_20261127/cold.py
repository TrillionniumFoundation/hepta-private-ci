"""Evaluate registered conditional messages and shared-current subgroup on held-out windows."""
import argparse
import json
from pathlib import Path
import numpy as np
from model import HORIZONS,NEW,EPS,design,inputs,predict,score,target,time_anchors
from fit import digest

def cold(data,selected,out):
    np.seterr(invalid='raise');out.mkdir(parents=True,exist_ok=True)
    seal=json.loads((selected/'SEAL.json').read_text());results={'selection_sha256':digest(selected/'SEAL.json'),'cells':{}}
    for site,info in seal.items():
        p=data/(site+'.npz');assert digest(p)==info['source_sha256']
        with np.load(p) as z:x=z['currents'];y=z['y']
        _,_,current=inputs(x)
        anchors=time_anchors('test');tr=time_anchors('train');obs=target(y,anchors,HORIZONS)
        report={'score':{},'comparisons':{},'high_departure':{}}
        pack={'anchors':anchors,'y_count':np.rint(obs*info['repeats']).astype(np.int16),'trial_count':info['repeats'],'horizons':HORIZONS}
        idx=[HORIZONS.index(h) for h in NEW]
        primary={}
        for name,choice in info['methods'].items():
            d=selected/(site+'-'+name+'-raw.npz');assert digest(d)==info['selected_raw'][name]
            with np.load(d) as nr: raw=dict(zip(HORIZONS,nr['raw']))
            pp=predict(choice['calibrator'],design(raw,anchors,HORIZONS)).reshape(obs.shape).astype(np.float32)
            pack[name]=pp
            ll,bb=score(pp,obs);primary[name]=ll[:,idx].mean(1)
            report['score'][name]={'new_log_loss':float(ll[:,idx].mean()),'new_brier':float(bb[:,idx].mean()),
                                  'log_loss_by_horizon':ll.mean(0).tolist(),'brier_by_horizon':bb.mean(0).tolist(),
                                  'wire_error':float(np.max(np.abs(pp.astype(float)-predict(choice['calibrator'],design(raw,anchors,HORIZONS)).reshape(obs.shape))))}
        groups=(anchors-anchors[0])//250;block_counts=np.bincount(groups)
        rng=np.random.default_rng(204789);boot=rng.integers(0,len(block_counts),(5000,len(block_counts)))
        comparisons=[('literal_query',m) for m in primary if m!='literal_query']+[('fixed_query','fixed_flat'),('tangent_query','tangent_flat')]
        for a,b in comparisons:
            diff=primary[a]-primary[b];block=np.bincount(groups,weights=diff);sample=block[boot].sum(1)/block_counts[boot].sum(1)
            report['comparisons'][a+' minus '+b]={'log_loss_delta':float(diff.mean()),'paired_block_95':np.quantile(sample,[.025,.975]).tolist(),
                                                  'brier_delta':report['score'][a]['new_brier']-report['score'][b]['new_brier']}
        for h in NEW:
            def departure(ix):
                return np.stack([np.abs(current[ix+k]-current[ix-1]).max(axis=1) for k in range(h)]).max(0)
            threshold=np.quantile(departure(tr),.75);mask=departure(anchors)>threshold
            k=HORIZONS.index(h);report['high_departure'][h]={'n':int(mask.sum()),'threshold':float(threshold),'log_loss':{}}
            for m in primary:
                ll,_=score(pack[m][mask,k],obs[mask,k]);report['high_departure'][h]['log_loss'][m]=float(ll.mean())
        report['blocks']=len(block_counts);report['anchors']=len(anchors);report['repeats']=info['repeats']
        results['cells'][site]=report;np.savez_compressed(out/(site+'.npz'),**pack)
    (out/'results.json').write_text(json.dumps(results,indent=2,allow_nan=False)+'\n')

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for k in ('data','selected','out'):ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args();cold(a.data,a.selected,a.out)
