"""Recount the prespecified CPU 1B quality panel from sealed per-clip logits."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np

ARMS=('literal','smooth','lif','sdpa')
MODES=('aligned','video_swapped','audio_swapped','both_swapped')


def read(p):return json.loads(p.read_text())


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def metrics(s,y):
    x=s.astype(np.float64);t=x.max(1);p=np.exp(x-t[:,None]);p/=p.sum(1,keepdims=True);joint=x.argmax(1)
    tab=p.reshape(-1,12,6)
    return {'nll':-np.log(p[np.arange(len(y)),y]),'joint_top1':(joint==y).astype(float),'script_top1':(tab.sum(2).argmax(1)==y//6).astype(float),'instruction_top1':(tab.sum(1).argmax(1)==y%6).astype(float)}


def ci(delta,actors):
    _,idx=np.unique(actors,return_inverse=True);weights=np.bincount(idx);sums=np.bincount(idx,weights=delta)
    draws=np.random.default_rng(21094).integers(0,len(weights),(4000,len(weights)))
    effect=sums[draws].sum(1)/weights[draws].sum(1)
    return {'difference':float(delta.mean()),'actor_cluster_ci95':np.quantile(effect,[.025,.975]).tolist()}


def main(w):
    manifest=read(w/'seal.json');raw={};dev={};resource={};factual={}
    canonical_ids=None
    for arm in ARMS:
        base=w/'fits'/arm;fit=read(base/'fit.json');assert sha(base/'fit.json')==manifest['fits'][arm]
        d={}
        for e in fit['observations']:
            path=base/f"panel-{e['step']}.npz";assert sha(path)==e['panel_sha256']
            with np.load(path) as z:d[e['step']]=metrics(z['aligned'],z['labels'])['nll'];panel_actors=np.array([x.split('_')[0] for x in z['ids']])
        dev[arm]={'mean':{k:float(v.mean()) for k,v in d.items()},'initial_minus_step16':ci(d[0]-d[16],panel_actors),'threshold_005_observed':bool(d[0].mean()-d[16].mean()>=.05)}
        with np.load(base/'full-dev-16.npz') as z:
            nll=metrics(z['aligned'],z['labels'])['nll'];mask=z['ids']!='1076_MTI_NEU_XX';assert (~mask).sum()==1
            dev[arm]['full_dev_with_short']=float(nll.mean());dev[arm]['full_dev_without_short']=float(nll[mask].mean())
        cell=w/'cold'/arm;doc=read(cell/'result.json');assert sha(cell/'logits.npz')==doc['sha256']
        with np.load(cell/'logits.npz') as z:
            ids=z['ids'];labels=z['labels'];actors=np.array([i.split('_')[0] for i in ids])
            assert len(ids)==1311 and len(np.unique(actors))==16
            if canonical_ids is None:canonical_ids=ids.copy()
            assert np.array_equal(canonical_ids,ids);lookup={m:metrics(z[m],labels) for m in MODES}
        factual[arm]=lookup['aligned'];raw[arm]={'by_mode':{m:{k:float(x.mean()) for k,x in mm.items()} for m,mm in lookup.items()},'perturbation_minus_aligned_nll':{m:ci(lookup[m]['nll']-factual[arm]['nll'],actors) for m in MODES[1:]}}
        resource[arm]={'training_presentations':fit['train_clips_seen'],'total_cpu_s':fit['cpu_s'],'active_wall_s':fit['active_wall_s'],'paused_wall_s':fit['paused_wall_s'],'params':fit['params'],'selected':fit['selected_step'],'full_parameter_gradients':fit['train_steps'][0]['grad_scalars'],'peak_rss_kib':max(s['peak_rss_kib'] for s in fit['train_steps']),'active_training_throughput_presentations_per_s':fit['train_clips_seen']/sum(s['wall_active_s'] for s in fit['train_steps'])}
    delta={arm:{k:ci(factual['literal'][k]-factual[arm][k],actors) for k in factual['literal']} for arm in ARMS[1:]}
    doc={'CPU_single_seed':137,'development':dev,'held_actors':raw,'literal_minus_other':delta,'resources':resource,'seal_sha256':sha(w/'seal.json'),'uncertainty':'paired whole actor resampling conditional on this one fitted seed; lower NLL is better'}
    p=w/'SUMMARY.json';tmp=p.with_suffix('.part');tmp.write_text(json.dumps(doc,indent=2)+'\n');tmp.replace(p);print('sealed',sha(p),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();main(a.root)
