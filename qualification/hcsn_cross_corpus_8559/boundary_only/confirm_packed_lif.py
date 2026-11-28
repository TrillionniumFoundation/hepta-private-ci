"""Seal the separate hard-spike fits and compare all methods on exactly 256 transmitted bits."""
import argparse,json,os,sys,time
from pathlib import Path

import numpy as np

import confirm_port
from packed_lif import SpikeEncoder
from port import ARMS,SEEDS
from report import contrast
from train_port import sha,write


def read(p):return json.loads(p.read_text())


def finish(src,main,out,law):
    for n in ('rsitmd.npz','nocaps.npz','NOCAPS_ROSTER.json','RSITMD_ROSTER.json'):
        p=out/n
        if not p.exists():p.symlink_to((main/n).resolve())
    trials=[];meta=read(main/'seal.json')
    for seed in SEEDS:
        folder=out/'fits'/f'lif_packed-8-{seed}';r=read(folder/'selected.json')
        assert [x['step'] for x in r['history']]==[128,512,2048]
        for x in r['history']:assert sha(folder/f"s{x['step']}.pt")==x['sha256']
        trials.append(r)
    seal={k:meta[k] for k in ('source','target','roster','law','natural','natural_roster')};seal.update(runs=trials,primary_seal=sha(main/'seal.json'),method_code=sha(Path(__file__).with_name('packed_lif.py')))
    if not (out/'seal.json').exists():write(out/'seal.json',seal)
    else:assert read(out/'seal.json')==seal
    confirm_port.PortEncoder=SpikeEncoder;confirm_port.confirm(src,out,law)
    while not (main/'results.json').exists():time.sleep(15)
    report={}
    for g in confirm_port.GALLERIES:
        signals={};firing=[];groups=None;means={}
        for arm in ('lif_packed',*ARMS):
            primary=[];metrics=[]
            for seed in SEEDS:
                root=out if arm=='lif_packed' else main
                with np.load(root/'cold'/f'{arm}-8-{seed}.npz') as z:
                    gg=z[g+'_group']
                    if groups is None:groups=gg
                    assert np.array_equal(groups,gg);primary.append(z[g+'_pair'][:,:,0].mean(1,dtype=np.float64))
                    metrics.append({m:z[g+'_'+m].mean((0,1),dtype=np.float64).tolist() for m in confirm_port.MODES})
                    if arm=='lif_packed':
                        firing.append({name:float(np.unpackbits(z[g+'_'+name+'_wire'],axis=-1,bitorder='little').mean()) for name in ('image','text')})
            signals[arm]=np.mean(primary,axis=0);means[arm]=dict(seed_primary=[float(v.mean()) for v in primary],metrics=metrics)
        report[g]={'means':means,'literal_minus_lif':contrast(signals['literal'],signals['lif_packed'],groups),'all_arms_minus_lif':{a:contrast(signals[a],signals['lif_packed'],groups) for a in ARMS},'lif_firing_density':firing,'n':len(groups)}
    write(out/'results.json',{'primary_seal':seal['primary_seal'],'supplement_seal':sha(out/'seal.json'),'physical_bits_per_image_or_text':256,'galleries':report})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('main',type=Path);p.add_argument('out',type=Path);p.add_argument('law',type=Path);a=p.parse_args()
    while not (a.main/'seal.json').exists() or len(list((a.out/'fits').glob('*/selected.json')))!=3:time.sleep(20)
    finish(a.source,a.main,a.out,a.law)
