"""After both seals, import and independently re-evaluate the unmodified BP baselines."""
import time
import argparse
import shutil
from cold import Held
from support import *


@torch.inference_mode()
def main():
    a=argparse.ArgumentParser();a.add_argument('work',type=Path);a.add_argument('base',type=Path);a.add_argument('kind',choices=['literal','sdpa','merge']);p=a.parse_args()
    r=json.loads((p.work/'remote_seal_receipt.json').read_bytes());assert sha(p.work/'SEAL.json')==r['seal_sha256']
    bp=p.base;br=json.loads((bp/'seal.json').read_bytes());manifest=json.loads((bp/'cold_manifest.json').read_bytes())
    target=p.work/'bp';target.mkdir(exist_ok=True)
    if p.kind=='merge':
        joint={}
        for k in ('literal','sdpa'):joint.update(json.loads((target/(k+'.json')).read_bytes()))
        write(target/'index.json',joint);return
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    prep=json.loads((p.work/'prepared.json').read_bytes());d=Held(p.work);ids=d.ids;shift=np.roll(ids,1)
    procs=[json.loads(l) for l in (bp/'processes.jsonl').read_text().splitlines()]
    fit=FitData(p.work);index={};checked={}
    for seed in SEEDS:
        key=f'{p.kind}-{seed}';dir=bp/'runs'/key;hist=json.loads((dir/'history.json').read_bytes());done=json.loads((dir/'done.json').read_bytes())
        proc=next(v for v in procs if v['arm']==p.kind and v['seed']==seed and v['exit']==0)
        setup=max(done['setup_s'],proc['wall_s']-done['elapsed']['wall'])
        _,_,_,_,batch=sampled_data(fit,seed,done['steps']);assert hashlib.sha256(''.join(batch).encode()).hexdigest()==done['batch_roster_sha']
        index[key]={}
        for bslot,rec in br[key].items():
            if rec is None:continue
            slot=bslot.replace('steps','step').replace('wall','wall_s').replace('cpu','cpu_s')
            fn=rec['sha']+'.npz';scores=bp/'cold'/fn;assert sha(scores)==manifest[fn] and sha(dir/rec['state'])==rec['sha']
            if rec['step'] in (4,16):
                _,_,y,_,prefix=sampled_data(fit,seed,rec['step']);assert int((y!=0).sum())==rec['train_tokens']
                local=json.loads((p.work/'fits'/f'forward-{seed}'/'history.json').read_bytes())
                for row in local:
                    if row['prefix']==rec['step']:assert row['batch_digests']==prefix and row['train_tokens']==rec['train_tokens']
            if fn not in checked:
                t=time.perf_counter()
                model=net(p.kind,seed,d);model.load_state_dict(torch.load(dir/rec['state'],weights_only=True,map_location='cpu'));t1=time.perf_counter()
                aa,nn=eval_rows(model,d,ids);t2=time.perf_counter();bb,kk=eval_rows(model,d,ids,shift)
                with np.load(scores) as z:assert np.array_equal(aa,z['matched']) and np.array_equal(bb,z['shifted']) and np.array_equal(nn,z['counts']) and np.array_equal(kk,nn)
                checked[fn]={'cold_model_reconstruction_wall_s':t1-t,'matched_inference_wall_s':t2-t1,'shifted_inference_wall_s':time.perf_counter()-t2}
                if not (target/fn).exists():shutil.copyfile(scores,target/fn)
            clock=next((k for k in ('wall_s','cpu_s') if slot.startswith(k)),None)
            if clock:
                cut=int(slot[len(clock):]);rawclock=clock.split('_')[0];after=[x['wall'] for x in hist if x[rawclock]>cut]
                wall=min(after+[done['elapsed']['wall']])
            else:wall=rec['wall']
            times=checked[fn]
            index[key][slot]={**rec,'archive_sha256':manifest[fn],'selection_wall_upper':wall,'bp_setup_and_process_overhead_upper':setup,
             **times,'end_to_end_upper_s':prep['total_wall_s']+setup+wall+times['cold_model_reconstruction_wall_s']+times['matched_inference_wall_s']}
        print('paired external replay',key,len(index[key]),flush=True)
    write(target/(p.kind+'.json'),index)
    write(target/(p.kind+'-verification.json'),{'base_seal_sha256':sha(bp/'seal.json'),'base_cold_manifest_sha256':sha(bp/'cold_manifest.json'),
       'own_seal_sha256':sha(p.work/'SEAL.json'),'distinct_baseline_states':len(checked),'every_matched_and_shifted_image_sum_exact':True,'hashes':{n:sha(target/n) for n in checked}})


if __name__=='__main__':main()
