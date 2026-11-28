"""Replay all original development scores, both budgets and selected held logits on one CPU thread."""
from hashlib import sha256
from pathlib import Path
import json
import numpy as np
import torch
from setup_native import inputs

HERE=Path(__file__).resolve().parent
def digest(p):return sha256(p.read_bytes()).hexdigest()


def greedy(model, source, modes, max_text):
    from data import START,PAD,EOS
    pred=np.full((len(source),17),PAD,np.int16)
    with torch.no_grad():
        for m in range(3):
            ids=np.flatnonzero(modes==m)
            for block in np.array_split(ids,int(np.ceil(len(ids)/96))):
                x=source[block].clone();x[:,START+1:]=PAD
                alive=torch.ones(len(block),dtype=torch.bool)
                for t in range(17 if m<2 else min(17,max_text+2)):
                    nxt=model(x[:,:START+t+1])[:,-1].argmax(-1)
                    nxt=torch.where(alive,nxt,PAD);pred[block,t]=nxt.numpy()
                    alive&=nxt!=EOS
                    if not alive.any():break
                    if t+1<17:x[:,START+t+1]=nxt
    return pred


def main():
    torch.set_num_threads(1)
    x,y,(tr,dev,held),actors,modes,V,_=inputs()
    from data import EOS
    from train import evaluate
    from network import architecture
    study=json.loads((HERE/'result.json').read_text())
    scored=HERE/'tri_private_scores'
    truth=y[held].numpy();rows=[];vec={};raw={}
    max_text=int((y[tr[modes[tr]==2]]!=-100).sum(1).max())-1
    for setting in study['rows']:
        arm=setting['arm']
        for chk in setting['rows']:
            label='_'.join(chk['labels'])
            file=scored/chk['weights'];assert digest(file)==chk['weights_sha256']
            model,_,_=architecture(V,arm,137)
            with np.load(file) as weights:model.load_state_dict({k:torch.from_numpy(v) for k,v in weights.items()})
            model.eval()
            ref=scored/chk['dev_scores'];assert digest(ref)==chk['dev_scores_sha256']
            dev_nll,devp,deva=evaluate(model,x,y,dev,modes)
            with np.load(ref) as a:
                devd=float(np.max(abs(a['logp']-devp)))
                deva_mis=int(((a['pred']!=deva)&(y[dev].numpy()>=0)).sum())
            tst,v,a=evaluate(model,x,y,held,modes)
            selected=chk['weights']==setting['selected_weights']
            hold_diff=None;hold_pred_mis=None
            if selected:
                ref=scored/setting['test_scores'];assert digest(ref)==setting['test_sha256']
                with np.load(ref) as prior:
                    hold_diff=float(np.max(abs(prior['logp']-v)))
                    hold_pred_mis=int(((prior['pred']!=a)&(truth>=0)).sum())
            generated=greedy(model,x[held],modes[held],max_text)
            metrics=[]
            for m in range(3):
                mask=modes[held]==m;valid=truth[mask]>=0
                if m<2:valid &= truth[mask]!=EOS
                hit=(generated[mask]==truth[mask])&valid
                metrics.append(dict(accuracy=float(hit.sum()/valid.sum()),
                                    exact=float((hit|~valid).all(1).mean()),tokens=int(valid.sum())))
            key=arm+'_'+label;raw[key+'_held_lp']=v;raw[key+'_held_greedy']=generated
            vec[arm,label]=v
            rows.append(dict(arm=arm,label=label,selected=selected,dev=dev_nll,held=tst,greedy=metrics,
                             dev_max_abs_gpu_logp=devd,dev_differing_predictions=deva_mis,
                             held_max_abs_gpu_logp=hold_diff,held_differing_predictions=hold_pred_mis))
    people=actors[held];unique=np.unique(people);rng=np.random.default_rng(360131)
    bootstrap=rng.integers(0,len(unique),(4000,len(unique)))
    intervals={}
    for gate in ('epoch1','time60'):
        delta=-(vec['financial',gate]-vec['sdpa_matched',gate]).sum(1,dtype=np.float64)
        out=[]
        for m in range(3):
            selection=modes[held]==m
            by=np.asarray([[delta[(people==a)&selection].sum(),(truth[(people==a)&selection]>=0).sum()] for a in unique])
            sampled=by[bootstrap].sum(1)
            out.append(dict(delta=float(by[:,0].sum()/by[:,1].sum()),
                            lo=float(np.quantile(sampled[:,0]/sampled[:,1],.025)),
                            hi=float(np.quantile(sampled[:,0]/sampled[:,1],.975))))
        intervals[gate]=out
    dest=HERE/'native_recount_scores.npz';np.savez_compressed(dest,**raw)
    study=dict(device='cpu',threads=1,source='native Radeon trained weights',rows=rows,
               paired_actor_ci=intervals,unique_held_actors=unique.tolist(),score_sha256=digest(dest))
    (HERE/'native_recount.json').write_text(json.dumps(study,indent=2)+'\n')
    print(json.dumps(study['paired_actor_ci']))
if __name__=='__main__':main()
