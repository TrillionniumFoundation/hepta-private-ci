"""Recount sealed UCM and RSICD evidence, with caption-cluster resampling."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def contrast(a,b,g):
    d=a-b;_,ix=np.unique(g,return_inverse=True);n=np.bincount(ix)
    sums=np.bincount(ix,weights=d);rng=np.random.default_rng(91773)
    est=[]
    for j in range(100):
        draw=rng.integers(0,len(n),size=(20,len(n)));est.extend((sums[draw].sum(1)/n[draw].sum(1)).tolist())
    return {'difference':float(d.mean()),'caption_cluster_ci95':np.quantile(est,[.025,.975]).tolist()}


def summarize(work):
    seal=json.loads((work/'seal.json').read_text());prep=json.loads((work/'data.json').read_text())['prep_wall_s']
    results={};path=work/'cold'
    for target in ('ucm','rsicd'):
        selected={};costs={};all_modes=['pair','shuffle','image_constant','text_constant']
        tab={};conditional={};rungs={};groups=None
        for family in ('linear','literal','smooth','sdpa'):
            cands=[{'seed':0,'selected':0,'rungs':[{'step':0,'wall_s':seal['linear']['wall_s']}]}] if family=='linear' else [r for r in seal['neural'] if r['arm']==family]
            vals={s:[] for s in all_modes};rung={};budgets={b:[] for b in ('10','40','120')};cost=[]
            for candidate in cands:
                sd=candidate['seed']
                for r in candidate['rungs']:
                    step=r['step'];name=f'{family}-{sd}-{step}';fp=path/f'{name}.npz'
                    rr=json.loads((path/f'{name}.json').read_text())
                    assert sha(fp)==rr['file_sha256']
                    with np.load(fp) as z:
                        gg=z[f'{target}_group']
                        if groups is None:groups=gg.copy()
                        assert np.array_equal(gg,groups)
                        conform=z[f'{target}_pair'][:,:,0].mean(axis=1)
                        clock=prep+r['wall_s']+json.loads((path/f'{name}.process.json').read_text())['cold_process_wall_s']
                        rung.setdefault(str(step),[]).append((float(conform.mean()),clock))
                        if family!='linear':
                            for b,selected_rung in candidate['budgets'].items():
                                if selected_rung and selected_rung['step']==step:budgets[b].append((float(conform.mean()),clock))
                        if step==candidate['selected']:
                            for s in all_modes:vals[s].append(z[f'{target}_{s}'])
                            cost.append(dict(seed=sd,selected=step,wall_s=clock))
            arr={s:np.stack(value) for s,value in vals.items()}
            sm=arr['pair'].mean(0)
            selected[family]=sm[:,:,0].mean(1)
            tab[family]=dict(concordance=float(selected[family].mean()),image_to_text=sm.mean(0)[0].tolist(),text_to_image=sm.mean(0)[1].tolist(),
                             controls={s:float(a[:,:,:,0].mean()) for s,a in arr.items() if s!='pair'},
                             seed_concordance=arr['pair'][:,:,:,0].mean((1,2)).tolist())
            costs[family]=dict(selection=cost,first_all_seed_observed_target=next(({'step':int(n),'min_concordance':min(x[0] for x in entries),'mean_end_to_end_upper_s':float(np.mean([x[1] for x in entries]))} for n,entries in rung.items() if all(x[0]>=.60 for x in entries)),None))
            rungs[family]=rung
            conditional[family]={k:v for k,v in budgets.items() if len(v)==len(cands)}
        diffs={f'literal-minus-{f}':contrast(selected['literal'],selected[f],groups) for f in ('linear','smooth','sdpa')}
        results[target]=dict(n=len(groups),unique_captions=len(np.unique(groups)),means=tab,contrasts=diffs,quality_costs=costs,all_checkpoint_quality_and_time=rungs,source_selected_process_budgets=conditional,
                            specific_pass=all(diffs['literal-minus-'+f]['caption_cluster_ci95'][0]>0 for f in ('smooth','sdpa')) and abs(tab['literal']['controls']['shuffle']-.5)<.05)
    (work/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    for s,r in results.items():
        print(s,{k:round(v['concordance'],4) for k,v in r['means'].items()},r['contrasts'],flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('work',type=Path);summarize(ap.parse_args().work)
