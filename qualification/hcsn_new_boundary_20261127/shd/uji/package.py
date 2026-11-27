import hashlib,json,itertools,shutil,zipfile,sys
from pathlib import Path
import numpy as np
root=Path(__file__).resolve().parent
out=root/'publish';out.mkdir(exist_ok=True)
def sh(b):return hashlib.sha256(b).hexdigest()
def save(p,v):p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')
def zip_files(path,items):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for rel in items:z.write(root/rel,rel)
arms=['physicalBP','smoothBP','physicalConstruct','smoothConstruct','shuffle','random','ridge','secant','shuffledSecant','Adam','LoRA']
seeds=(409,571,647);ind=json.loads((root/'results/independent.json').read_text());native={}
for s in seeds:
    for a in arms:
        pp=root/'predictions'/f'{s}-{a}.npz'
        with np.load(pp) as f:pr=dict(f)
        for g in ('old','new'):
            raw=np.fromfile(root/'v8'/f'{s}-{a}-{g}.bin','<f8').reshape(208,26)
            z=pr[g+'_logits'];d=abs(raw-z)
            native[f'{s}-{a}-{g}']={'max_abs':float(d.max()),'argmax_diff':int((raw.argmax(1)!=z.argmax(1)).sum())}
            pr[g+'_logits']=raw
        np.savez_compressed(pp,**pr)
assert sum(q['argmax_diff'] for q in native.values())==0
save(root/'results/v8-vs-node.json',{'class_scores':33*416*26,'max_abs':max(x['max_abs'] for x in native.values()),'native_node_score':json.loads((root/'results/node-replay.json').read_text()),'per':native})
cost={}
for a in arms:
    run=[json.loads((root/'fits'/f'{s}-{a}.json').read_text()) for s in seeds]
    cost[a]={'fit_seconds':[q['seconds'] for q in run],'fit_sum_s':sum(q['seconds'] for q in run),'input_parse_sum_s':sum(q['split']['prep'] for q in run)}
    if a in ('secant','shuffledSecant','Adam','LoRA'):cost[a]['selected']=[q['selected'] for q in run]
metrics={a:{g:ind['paired'][f'{a}/{g}'] for g in ('old','new')} for a in arms}
gate={}
for a in ('secant','shuffledSecant','Adam','LoRA'):
    gate[a]=[bool(n['mean']>=.02 and n['lo']>=0 and o['mean']>=-.02) for n,o in zip(metrics[a]['new']['by_seed'],metrics[a]['old']['by_seed'])]
save(root/'results/summary.json',dict(costs=cost,gate=gate,metrics=metrics,independent_logits=ind['tested_class_logits'],latency_context='V8 one serial worker; CPU model identity unavailable; no GPU comparison. Four held-out writers and 52 samples per case per writer.'))
blobs=[]
for name in ['train-source.json','sources.json','verify.py','package.py','results/summary.json','results/independent.json','results/node-replay.json','results/v8-vs-node.json']:
    dst=out/name;dst.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(root/name,dst)
groups=[('raw',sorted('raw/'+p.name for p in (root/'raw').glob('UJIpenchars*')))]
for s in seeds:
    groups.append((f'fits-{s}',[f'fits/{s}-{a}.json' for a in arms]))
    for k in range(0,len(arms),4):groups.append((f'pred-{s}-{k//4}',[f'predictions/{s}-{a}.npz' for a in arms[k:k+4]]))
for name,items in groups:
    dst=out/(name+'.zip');zip_files(dst,items)
    with zipfile.ZipFile(dst) as z:
        assert z.testzip() is None
        for i in items:assert z.read(i)==(root/i).read_bytes()
    blobs.append({'path':dst.name,'size':dst.stat().st_size,'sha256':sh(dst.read_bytes()),'members':{i:sh((root/i).read_bytes()) for i in items}})
save(out/'archives.json',blobs)
print([(b['path'],b['size']) for b in blobs])
