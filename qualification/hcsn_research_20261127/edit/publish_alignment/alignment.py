"""Measure fixed-design reachability and held-out alignment of local physical targets."""
import json,sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import torch
from scipy.stats import spearmanr
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D.parent))
import experiment as core
import exact
from finalize import split_zip,copy_file
def main():
    torch.set_num_threads(1)
    root=D/'alignment-results';root.mkdir(exist_ok=True);out=[]
    for seed in core.DIGESTS:
        arg=SimpleNamespace(seed=seed,parents=Path('/tmp/hcsn-audit-c889/nobp'),input=D.parent/'input')
        m,c,original=core.read_parent(arg);tr=core.loads(arg,'train',c);te=core.loads(arg,'test',c)
        traces={k:exact.trace(m,v[0]) for k,v in tr.items()}
        prototype=torch.stack([traces['ar']['drift'][tr['ar'][1]==i].mean(0) for i in range(10)])
        desired=prototype[tr['eng'][1]];conf=m.config;pre=((desired-conf.base_drift)/conf.drift_scale).clamp(-1+1e-8,1-1e-8).atanh()
        error=(pre-traces['eng']['preactivation']).flatten(0,1);design=traces['eng']['keys'].flatten(0,1)
        u,s,v=torch.linalg.svd(design,full_matrices=False);rank=int(torch.linalg.matrix_rank(design));projection=u[:,:rank]@(u[:,:rank].T@error)
        constrained,_=core.solve(m,traces,tr,'direct');den=float(error.square().sum())
        diagnostics=dict(seed=seed,singular_values=s.tolist(),rank=rank,shape=list(design.shape),unmodified_error_norm=float(error.norm()),
               conditional_residual_norm=float((error-projection).norm()),conditional_explainable_fraction=1-float((error-projection).square().sum())/den,
               full_constrained_explainable_fraction=1-float((error-design@constrained).square().sum())/den)
        x,y,ids=te['eng'];truth=prototype[y];margin0=phys0=correct0=None
        speaker=np.array([n.split('_')[1] for n in ids]);details={}
        rseed=root/str(seed);rseed.mkdir(exist_ok=True)
        arr={'ids':ids,'y':y.numpy(),'speaker':speaker}
        for arm in core.METHODS:
            folder=D.parent/'first'/str(seed)/arm
            selected=torch.load(folder/'selected.pt',weights_only=True,map_location='cpu');m.load_state_dict(selected['model'],strict=True)
            actual=exact.trace(m,x)['drift'];phys=(actual-truth).square().mean((1,2)).numpy()
            with np.load(folder/'predictions.npz',allow_pickle=False) as p:
                assert np.array_equal(ids,p['eng_id'])
                scores=p['eng_scores'].copy().astype(np.float64);pred=p['eng_class']
            truth_score=scores[np.arange(len(y)),y].copy();scores[np.arange(len(y)),y]=-np.inf
            margin=truth_score-scores.max(1);correct=pred==y.numpy()
            if arm=='keep':phys0=phys;margin0=margin;correct0=correct
            gain=phys0-phys;delta=margin-margin0;correct_delta=correct.astype(int)-correct0.astype(int)
            arr.update({arm+'_physical_error':phys,arm+'_margin':margin,arm+'_correct':correct})
            subset={}
            for label,inds in [('all',np.ones(len(y),dtype=bool)), *[(p,speaker==p) for p in sorted(set(speaker))]]:
                g=gain[inds];marg=delta[inds];success=correct_delta[inds];matched=g>0
                subset[label]=dict(physical_mse=float(np.mean(phys[inds])),physical_gain=float(np.mean(g)),
                           margin_gain=float(marg.mean()),correlation=float(spearmanr(g,marg).statistic) if np.std(g)>0 and np.std(marg)>0 else None,
                           lower_physical_error=int(matched.sum()),net_correct_total=int(success.sum()),
                           improved_correct_on_lower_error=int((success[matched]==1).sum()),regressed_correct_on_lower_error=int((success[matched]==-1).sum()))
            details[arm]=subset
        np.savez_compressed(rseed/'raw.npz',**arr)
        diagnostics.update(measured=details,raw_sha256=core.sha((rseed/'raw.npz').read_bytes()));core.write(rseed/'metrics.json',diagnostics);out.append(diagnostics)
    dest=D.parent/'publish_alignment';dest.mkdir(exist_ok=True)
    for name in ('alignment.py','ALIGNMENT_PROTOCOL.md'):copy_file(D/name,dest/name)
    archives=split_zip(root,list(root.glob('*/*')),dest)
    core.write(dest/'results.json',dict(rows=out,archives=archives,source=core.sha((D/'alignment.py').read_bytes()),reference=core.sha((D.parent/'first'/'seal.json').read_bytes())))
    for row in out:print(row['seed'],row['conditional_explainable_fraction'],row['measured']['direct']['all'],flush=True)
if __name__=='__main__':main()
