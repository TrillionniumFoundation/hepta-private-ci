"""Verify the sealed artifacts and independently reconstruct every held-out comparison."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

SEEDS = (107, 211, 431)
ARMS = ('keep','soft','unprotected','wrong','bp')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def report(root):
    parent_dir=root.parent
    seal=read(root/'seal.json')
    assert sha(parent_dir/'PROTOCOL.md')==seal['protocol']
    assert sha(parent_dir/'receiver_edit.py')==seal['program']
    rows=[]
    for seed in SEEDS:
        fit_dir=root/f'fit-{seed}'
        fit=read(fit_dir/'fit.json')
        assert sha(fit_dir/'fit.json')==seal['fits'][str(seed)]['fit']
        assert sha(fit_dir/'selected.npz')==seal['fits'][str(seed)]['selected']
        assert sha(fit_dir/'response.npz')==fit['response_sha']
        with np.load(fit_dir/'selected.npz',allow_pickle=False) as source:
            w={k:source[k].copy() for k in source.files}
        for arm in ARMS:
            raw=root/f'test-{seed}-{arm}'
            r=read(raw/'receipt.json')
            assert r['seal']==sha(root/'seal.json')
            assert sha(raw/'predictions.npz')==r['predictions']
            assert hashlib.sha256(w[arm].tobytes()).hexdigest()==fit['fits'][arm]['site_sha256']
            assert int((w[arm]!=w['keep']).sum())==fit['fits'][arm]['changed']
            with np.load(raw/'predictions.npz',allow_pickle=False) as data:
                cur={k:data[k].copy() for k in data}
            if arm=='keep':
                base=cur
            scores={}
            for lang,n in [('eng',1000),('ar',2200)]:
                ids=cur[lang+'_ids']
                y=cur[lang+'_labels']
                z=cur[lang+'_scores']
                z0=base[lang+'_scores']
                assert np.array_equal(ids,base[lang+'_ids']) and np.array_equal(y,base[lang+'_labels'])
                assert len(np.unique(ids))==n and z.shape==(n,10) and np.isfinite(z).all()
                ok=z.argmax(1)==y
                old=z0.argmax(1)==y
                p=np.exp(z-z.max(1,keepdims=True));p/=p.sum(1,keepdims=True)
                shift=z-z0
                s={
                    'n':n,'acc':float(ok.mean()),'brier':float(np.mean(np.sum((p-np.eye(10)[y])**2,axis=1))),
                    'gain':float(ok.mean()-old.mean()),'newly_correct':int((ok&~old).sum()),
                    'newly_wrong':int((~ok&old).sum()),
                    'mean_centered_logit_shift_sq':float(np.mean((shift-shift.mean(1,keepdims=True))**2))
                }
                if lang=='eng':
                    people=np.array([str(v).split('_')[1] for v in ids])
                    assert sorted(set(people))==['nicolas','theo']
                    s['by_speaker']={p:{'n':int((people==p).sum()),'net_correct':int(ok[people==p].sum()-old[people==p].sum())} for p in sorted(set(people))}
                scores[lang]=s
            times=fit['times']
            timer_sum={unit:sum(x[unit] for x in times.values()) for unit in ('wall','cpu')}
            charge={}
            for unit in ('wall','cpu'):
                shared=max(0.,fit[unit+'_since_entry']-timer_sum[unit])+times['setup'][unit]
                forward=times['basis_and_forward_probes'][unit] if arm in ('soft','unprotected','wrong') else 0.
                charge[unit]=dict(common=shared,probes=forward,arm_fit=times[arm][unit],cold=r[unit+'_since_entry'],
                                  total=shared+forward+times[arm][unit]+r[unit+'_since_entry'])
            rows.append({'seed':seed,'arm':arm,'selected':fit['fits'][arm]['label'],'changed':int((w[arm]!=w['keep']).sum()),
                      'frob_delta':float(np.linalg.norm(w[arm].astype(float)-w['keep'])),'eval':scores,'charged_seconds':charge})
    gates={}
    for seed in SEEDS:
        s=next(x for x in rows if x['seed']==seed and x['arm']=='soft')
        b=next(x for x in rows if x['seed']==seed and x['arm']=='bp')
        gates[str(seed)]={'gain':s['eval']['eng']['gain']+1e-12>=.02,
                         'retention':s['eval']['ar']['gain']>=-.02-1e-12,
                         'both_speakers':all(z['net_correct']>0 for z in s['eval']['eng']['by_speaker'].values()),
                         'bp_quality':s['eval']['eng']['acc']>=b['eval']['eng']['acc']-.01-1e-12}
    costs={u:{a:sum(r['charged_seconds'][u]['total'] for r in rows if r['arm']==a) for a in ARMS} for u in ('wall','cpu')}
    speed_gate=costs['wall']['soft']<=.9*costs['wall']['bp']
    quality=all(all(k.values()) for k in gates.values())
    return dict(rows=rows,quality_by_seed=gates,aggregate_cost_seconds=costs,
                aggregate_cost_gate=speed_gate,all_quality_gates=quality,qualified=quality and speed_gate,
                source_note='Reused FSDD and Arabic benchmarks, historical BP-pretrained parents, CPU adaptation costs including allocated common and cold work. Correlated recordings and parents; two English test speakers.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path)
    args=p.parse_args()
    outcome=report(args.root)
    (args.root/'summary.json').write_text(json.dumps(outcome,indent=2,sort_keys=True,allow_nan=False)+'\n')
    for x in outcome['rows']:
        print(x['seed'],x['arm'],x['selected'],x['changed'],x['eval']['eng']['acc'],x['eval']['ar']['acc'])
    print('qualified',outcome['qualified'])
