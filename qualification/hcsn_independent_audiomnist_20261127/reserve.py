"""Independent 40-speaker confirmation from already sealed final-budget models."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from data import sha as bytes_sha,features
from receiver import Cell,encode,scores
from verify import diagnostic,contrast
from fit import ARMS,SEEDS,dump,sha


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for name in ('audio','data','models','table','seal','primary','out'):ap.add_argument(name,type=Path)
    a=ap.parse_args();a.out.mkdir(exist_ok=True,parents=True)
    wall=time.perf_counter();cpu=time.process_time()
    seal=json.loads(a.seal.read_bytes());primary=json.loads(a.primary.read_bytes())
    manifest=(a.data/'sources.tsv').read_text().splitlines()[1:];seen={line.split('\t')[-1] for line in manifest}
    raw=[];source=[];duplicates=[]
    for i in range(1,61):
        if i%3==1:continue
        for f in sorted((a.audio/'data'/f'{i:02}').glob('*.wav')):
            digit,speaker,rep=f.stem.split('_')
            if int(rep)>=12:continue
            hz,x=wavfile.read(f);key=bytes_sha(str((hz,x.shape,x.dtype)).encode()+x.tobytes())
            if key in seen:
                duplicates.append(f.name);continue
            seen.add(key);raw.append((features(x,hz),int(digit),speaker,f.name));source.append([f.name,bytes_sha(f.read_bytes()),key])
    assert len(raw)+len(duplicates)==4800
    x,y,sp,rec=map(np.asarray,zip(*raw));assert len(set(sp))==40
    (a.out/'source.tsv').write_text(''.join('\t'.join(v)+'\n' for v in source))
    np.savez_compressed(a.out/'reference.npz',y=y,speaker=sp,record=rec)
    prep={'reserve_records':len(y),'speakers':len(set(sp)),'duplicate_pcm':duplicates,'wall':time.perf_counter()-wall,'cpu':time.process_time()-cpu,
          'primary_seal':sha(a.seal),'reserve_protocol':sha(Path(__file__).resolve().parent/'RESERVE_PROTOCOL.md'),'source_manifest':sha(a.out/'source.tsv')}
    law=Cell(a.table);all_models={};hashes={}
    for seed in SEEDS:
        pp=a.models/f'parent_{seed}.npz';assert sha(pp)==seal['fits'][pp.name]
        with np.load(pp) as f:p=dict(f)
        for arm in ('keep',*ARMS):
            c=time.process_time();wall=time.perf_counter()
            if arm=='keep':w=p['W'];key=f'{arm}_{seed}_0'
            else:
                key=f'{arm}_{seed}_45';path=a.models/(key+'.npy');assert sha(path)==seal['fits'][path.name];w=np.load(path)
            pred=[]
            for i in range(0,len(x),256):
                k=encode(x[i:i+256].astype('float64'),p,law);pred.append(scores(k,w,p,law)[0])
            z=np.concatenate(pred);output=a.out/(key+'.npz');np.savez_compressed(output,scores=z)
            hashes[key]=sha(output)
            all_models[key]={'new':diagnostic(z,y,sp),'old':primary['per_model'][key]['old'],'cpu':time.process_time()-c,'wall':time.perf_counter()-wall}
    rng=np.random.default_rng(12089);draws={k:rng.integers(n,size=(20000,n)) for k,n in [('old',6),('new',40)]}
    baseline=[all_models[f'keep_{s}_0'] for s in SEEDS]
    per_arm={arm:[all_models[f'{arm}_{s}_45'] for s in SEEDS] for arm in ARMS}
    effects={}
    for arm,items in per_arm.items():
        effect=contrast(items,baseline,draws)
        effect['passes_both_by_parent']=[bool(n>=2-1e-10 and o>=-2-1e-10) for n,o in zip(effect['new']['per_parent_pp'],effect['old']['per_parent_pp'])]
        effects[arm]=effect
    contrasts={arm:contrast(per_arm['direct'],per_arm[arm],draws) for arm in ('bp','lora','wrong')}
    dump(a.out/'SUMMARY.json',{'scope':prep,'prediction_hashes':hashes,'per_model':all_models,'vs_keep':effects,'direct_minus':contrasts,'total_class_scores':len(y)*len(all_models)*10})
