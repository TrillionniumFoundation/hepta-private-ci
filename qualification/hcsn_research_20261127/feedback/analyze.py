"""Recompute outcomes from raw predictions, treating sites/days as clusters."""
import json,hashlib,statistics,zipfile,collections
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
plan=json.loads((HERE/'protocol.json').read_text())
def auc(p,y):
    hi=p[y==1];lo=p[y==0];d=hi[:,None]-lo
    return float((np.sum(d>0)+.5*np.sum(d==0))/d.size)
def summarize(p,y):
    p=np.asarray(p);y=np.asarray(y);dec=p>=.5
    return dict(accuracy=float((y==dec).mean()),ba=float(np.mean([(y[y==a]==dec[y==a]).mean() for a in [0,1] if (y==a).any()])),
        auc=auc(p,y),brier=float(((p-y)**2).mean()),min_p=float(p.min()),max_p=float(p.max()),sd_p=float(p.std()),
        pred_pos=int(dec.sum()),n=len(p),true_pos=int(y.sum()))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
out={}
for ds in plan['tasks']:
    rows={};raw={};scores={}
    for arm in plan['arms']:
        byseed=[];pairs={}
        for seed in plan['seeds']:
            root=HERE/'results'/ds/f'{arm}-{seed}'
            item=json.loads((root/'predictions.json').read_text());fit=json.loads((root/'fit.json').read_text())
            assert fit['weights']==sha(root/'weights.pt')
            p=np.asarray(item['p']);y=np.asarray(item['y']);g=np.asarray(item['sources'])
            s=summarize(p,y);assert abs(s['brier']-item['score']['brier'])<1e-12 and abs(s['ba']-item['score']['balanced_accuracy'])<1e-12
            rr={'seed':seed,'fit_wall_s':fit['wall_seconds'],'fit_cpu_s':fit['process_cpu_seconds'],'cold_score_s':item['cold_score_s'],
                'selected':fit['selected_step'],'allocated':fit['parameters'],'active':fit['active_after_known_masks'],**s}
            if item['p_silent'] is not None:
                ps=np.asarray(item['p_silent']);rr.update(silent=summarize(ps,y),mean_abs_mute_effect=float(abs(ps-p).mean()),max_abs_mute_effect=float(abs(ps-p).max()))
            byseed.append(rr);pairs[seed]=p
        raw[arm]=pairs;rows[arm]=byseed;scores[arm]={k:float(np.mean([r[k] for r in byseed])) for k in ('auc','ba','accuracy','brier','sd_p','fit_wall_s','fit_cpu_s','cold_score_s')}
    groups=sorted(set(g));bounds={};rng=np.random.default_rng(121277)
    group_choices=rng.integers(len(groups),size=(8192,len(groups)))
    for arm in [a for a in plan['arms'] if a!='dual']:
        group_d={};pooled=0
        for key in groups:
            idx=g==key
            d=np.asarray([((raw['dual'][s][idx]-y[idx])**2-(raw[arm][s][idx]-y[idx])**2).mean() for s in plan['seeds']]);group_d[key]=float(d.mean())
        a=np.array([group_d[key] for key in groups]);boot=a[group_choices].mean(1)
        bounds[arm]=dict(dual_minus_control_pooled_brier=scores['dual']['brier']-scores[arm]['brier'],dual_minus_control_ba=scores['dual']['ba']-scores[arm]['ba'],
            group_equal_mean_brier=float(a.mean()),cluster_percentile95_brier=np.quantile(boot,[.025,.975]).tolist(),group_brier=group_d)
    out[ds]=dict(per_seed=rows,means=scores,paired= bounds,heldout_source_counts={k:int(np.sum(g==k)) for k in groups},gate_pass=all(x['dual_minus_control_ba']>=.02 and x['dual_minus_control_pooled_brier']<=0 for x in bounds.values()),interaction={k:scores['dual'][k]-scores['restore'][k]-scores['risk'][k]+scores['zero'][k] for k in ('ba','brier')})
out['inference_scope']='Fixed finite datasets. Seed averages do not create independent sources. Cluster intervals are descriptive conditional domain resampling of held-out days/stations (only 7 and 4 groups). No out-of-domain guarantee.'
(HERE/'primary_summary.json').write_text(json.dumps(out,sort_keys=True,indent=1)+'\n')
for tag,glob in [('predictions','predictions.json'),('weights','weights.pt'),('fit_records','fit.json')]:
    with zipfile.ZipFile(HERE/f'primary_{tag}.zip','w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted((HERE/'results').rglob(glob)):z.write(p,p.relative_to(HERE/'results'))
        z.write(HERE/'results/seal.json','seal.json')
for ds in plan['tasks']:
 print(ds)
 for arm in plan['arms']:
    r=out[ds]['means'][arm];print(arm,*[round(r[k],5) for k in ('ba','auc','brier','fit_wall_s','cold_score_s')])
 print('dual ranges',[(r['seed'],round(r['min_p'],6),round(r['max_p'],6),round(r['auc'],5),round(r['silent']['auc'],5)) for r in out[ds]['per_seed']['dual']])
