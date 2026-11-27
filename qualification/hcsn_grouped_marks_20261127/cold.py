"""Open the frozen confirmation gallery only after the joint 72-model manifest exists."""
import argparse
import time
import numpy as np
import torch

from fit import ARMS, CONFIRM, DATA, ROOT, SRC, external, json_file, run_path, score, sha, write_json
from grouped_router import build_model


def cold(arm,seed):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    start=time.perf_counter()
    freeze=ROOT/'evaluation_seal.json'
    sealed=json_file(freeze)
    assert len(sealed['assignments'])==len(ARMS)*len(CONFIRM) and sealed['all_sources_frozen']
    for name,h in sealed['sources'].items():assert sha(SRC/name)==h
    assert sealed['tuning']==sha(ROOT/'tuning_seal.json') and sealed['manifest']==sha(ROOT/'gallery/manifest.json')
    rates=json_file(ROOT/'tuning_seal.json')['rates']
    d=run_path('confirm',arm,seed,rates[arm]);j=sealed['assignments'][d.name]
    assert sha(d/'complete.json')==j['complete']
    if (d/'cold.json').exists():
        have=json_file(d/'cold.json')
        assert have['seal']==sha(freeze) and all(sha(d/f)==h for f,h in have['arrays'].items())
        return
    gallery={s:external(s) for s in ('development','test')}
    assert len(gallery['test'].ids)==800 and len(gallery['development'].ids)==320
    assert not set(gallery['test'].ids).intersection(gallery['development'].ids)
    vocabulary=len(json_file(DATA/'manifest.json')['vocab'])
    refs={};files={};stats={}
    for name,record in j['assignment'].items():
        h=record['state'];refs[name]=h
        if h in stats:continue
        checkpoint=d/record['name'];assert sha(checkpoint)==h
        torch.manual_seed(seed);model=build_model(arm,vocabulary).cuda()
        model.load_state_dict(torch.load(checkpoint,map_location='cuda',weights_only=True));model.eval()
        scores={};measures={}
        for split,data in gallery.items():
            ix=np.arange(len(data.ids)); loss,n=score(model,data,ix);swapped,m=score(model,data,ix,True)
            assert np.array_equal(n,m)
            scores.update({split+'_sum':loss,split+'_swapped':swapped,split+'_counts':n,split+'_ids':data.ids})
            measures[split]={'nll':float(loss.sum()/n.sum()),'conditioning_gain':float((swapped-loss).sum()/n.sum())}
        fname='cold-'+h[:16]+'.npz';tmp=d/(fname+'.part')
        with tmp.open('wb') as stream:np.savez_compressed(stream,**scores)
        tmp.replace(d/fname); files[fname]=sha(d/fname);stats[h]=measures
    write_json(d/'cold.json',{'arm':arm,'seed':seed,'seal':sha(freeze),'complete':j['complete'],'references':refs,'arrays':files,
        'scores':stats,'cold_seconds':time.perf_counter()-start,'device':torch.cuda.get_device_name()})
    print('cold',arm,seed,len(stats),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('arm',choices=ARMS);p.add_argument('seed',type=int,choices=CONFIRM)
    a=p.parse_args();cold(a.arm,a.seed)
