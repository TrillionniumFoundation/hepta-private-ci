import json,sys,time,hashlib,re
from pathlib import Path
import argparse
import numpy as np
q=argparse.ArgumentParser();q.add_argument('root',type=Path);q.add_argument('output',type=Path);args=q.parse_args();base=args.root.resolve()
sys.path.insert(0,str(base/'campaign/field'))
import torch
from models import Data,make_table
from fit import model,predict,SEEDS,ARMS
from sklearn.metrics import average_precision_score
torch.set_num_threads(1);torch.set_num_interop_threads(1)
out={'scope':'No field test file opened. Field development only and published physiology cold packages.'}
dev=Data(base/'field-data/dev.npz');y=dev.y.numpy();assert np.all(y[:,1,0]==y[:,0,0]) and np.all(y[:,3,0]==y[:,2,0]);table=make_table(base/'verified/qualification/hcsn_continuous_20261127/core')
out['fee_development']={}
for arm in ARMS:
    rows=[]
    for seed in SEEDS:
        p=base/'field-data/runs'/f'{arm}-{seed}'/'m30.pt';h=json.loads(p.with_suffix('.json').read_bytes())
        assert hashlib.sha256(p.read_bytes()).hexdigest()==h['weights_sha256']
        n=model(arm,table);n.load_state_dict(torch.load(p,weights_only=True));pred=predict(n,dev)
        fee=pred[:,[1,3]]-pred[:,[0,2]];reserve=pred[:,:2]-pred[:,2:];horiz=np.diff(pred,axis=2)
        rows.append({'seed':seed,'dev_brier':float(np.mean((pred-y)**2)),'one_hour_fee_invariance_mean_abs':float(abs(fee[:,:,0]).mean()),'one_hour_fee_invariance_max_abs':float(abs(fee[:,:,0]).max()),'late_fee_reverse_fraction':float((fee[:,:,1:]<0).mean()),'reserve_reverse_fraction':float((reserve<0).mean()),'horizon_reverse_fraction':float((horiz<0).mean())})
        assert abs(rows[-1]['dev_brier']-h['dev_brier'])<1e-7
    out['fee_development'][arm]=rows
with np.load(base/'scale-data/packet/pack.npz') as pack:
    # Access only image/split arrays globally and caption IDs for train and development.
    sp=pack['split'];pics=pack['images'];text=pack['captions'][sp<=1]
    inv={s:{hashlib.sha256(v.tobytes()).hexdigest() for v in pics[sp==s]} for s in range(3)}
    train,valid=text[sp[sp<=1]==0],text[sp[sp<=1]==1]
    tr={tuple(np.trim_zeros(v,'b')) for v in train.reshape(-1,22)}
    va=[tuple(np.trim_zeros(v,'b')) for v in valid.reshape(-1,22)]
    di=json.loads((base/'campaign/scale/data.json').read_bytes())
    out['ucm']={'unique_visible_rgb332':{s:len(g) for s,g in inv.items()},'cross_split_rgb332_equal_unique':{str((a,b)):len(inv[a]&inv[b]) for a,b in ((0,1),(0,2),(1,2))},'dev_caption_n':len(va),'dev_caption_exact_encoded_seen_train':sum(v in tr for v in va),'dev_actual_unknown':int((valid==1).sum()),'manifest_dev_unknown':di['source_unknown_count']['1'],'dev_actual_tokens':sum(len(v)-2 for v in va),'manifest_dev_tokens':di['source_tokens']['1']}
out['physiology']={}
for k in 'ABC':
    with np.load(base/f'campaign/neurons/{k}.npz') as f:
        y=f['y'];loss=lambda p:-(y*np.log(p[:,None])+(1-y)*np.log1p(-p[:,None]))
        d=loss(f['literal'])-loss(f['lif'])
        by_repeat=d.mean(0)
        out['physiology'][k]={'bins':len(y),'repeats':y.shape[1],'repeat_loss_delta_literal_lif':by_repeat.tolist(),'n_favor_literal':int((by_repeat<0).sum()),'rate':float(y.mean())}
with np.load(base/'campaign/synapse/cold.npz') as f:
    y=f['y'];rep=f['repeat'];loss=lambda p:-(y*np.log(p)+(1-y)*np.log1p(-p))
    dif=loss(f['predictive'])-loss(f['augmented']);v=[float(dif[rep==k].mean()) for k in sorted(set(rep))]
    out['retina']={'repeat_sizes':[int((rep==k).sum()) for k in sorted(set(rep))],'predictive_minus_augmented_by_repeat':v,'pooled':float(dif.mean()),'balanced':float(np.mean(v)),'n_favor_predictive':int((np.array(v)<0).sum()),'pre_duplicate_time_within_trial':sum(len(f['time_ms'][rep==k])-len(set(f['time_ms'][rep==k])) for k in set(rep))}
args.output.write_text(json.dumps(out,indent=1)+'\n')
print(out['ucm']);print(out['retina']);print({k:v['n_favor_literal'] for k,v in out['physiology'].items()})
for k,r in out['fee_development'].items():print(k,{s:np.mean([j[s] for j in r]) for s in r[0] if s not in ('seed','dev_brier')})
