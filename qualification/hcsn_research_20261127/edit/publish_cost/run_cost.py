"""Cost measurement using matched strongly supervised fits, frozen cold panels and CPU accounting."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
import numpy as np
D=Path(__file__).resolve().parent;root=D/'cost-results'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(f,v):f.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
def main():
    logs=root/'logs';logs.mkdir(exist_ok=True,parents=True)
    items=[(s,m) for i,s in enumerate((107,211,431)) for m in (('direct','bp') if i%2==0 else ('bp','direct'))]
    def run(mode,seed,method):
        dest=root/str(seed)/method
        if (dest/(mode+'_process_resource.json')).exists():return
        outer=time.perf_counter()
        with (logs/f'{mode}-{seed}-{method}.txt').open('w') as f:
            proc=subprocess.run([sys.executable,str(D/'cost.py'),mode,'--seed',str(seed),'--method',method,'--input',str(D.parent/'input'),
                  '--parents','/tmp/hcsn-audit-c889/nobp','--output',str(root)],stdout=f,stderr=subprocess.STDOUT)
        dump(logs/f'{mode}-{seed}-{method}.json',dict(exit=proc.returncode,elapsed_s=time.perf_counter()-outer))
        if proc.returncode:raise RuntimeError(f'{mode} {seed}/{method} failed {proc.returncode}')
        print(mode,seed,method,flush=True)
    if not (root/'seal.json').exists():
        for s,m in items:run('fit',s,m)
        seal={'models':{f'{s}/{m}':sha(root/str(s)/m/'selected.pt') for s,m in items},
              'reference':sha(D.parent/'first'/'seal.json'),'protocol':sha(D/'COST_PROTOCOL.md')}
        dump(root/'seal.json',seal)
    for s,m in items:run('eval',s,m)
    rows=[]
    for s,m in items:
        r=root/str(s)/m;q=D.parent/'first'/str(s)/m
        f=json.loads((r/'fit.json').read_text());g=json.loads((q/'fit.json').read_text())
        with np.load(r/'weights.npz',allow_pickle=False) as a,np.load(q/'weights.npz',allow_pickle=False) as b:
            delta={k:float(np.linalg.norm(a[k]-b[k])) for k in a.files}
        with np.load(r/'predictions.npz',allow_pickle=False) as a,np.load(q/'predictions.npz',allow_pickle=False) as b:
            score={k:float(np.abs(a[k+'_scores']-b[k+'_scores']).max()) for k in ('eng','ar')}
            disagreement={k:int((a[k+'_class']!=b[k+'_class']).sum()) for k in ('eng','ar')}
        resources={phase:json.loads((r/(phase+'_process_resource.json')).read_text()) for phase in ('fit','eval')}
        external={phase:json.loads((logs/f'{phase}-{s}-{m}.json').read_text()) for phase in ('fit','eval')}
        rows.append(dict(seed=s,method=m,selected=f['selected'],reference_selected=g['selected'],weight_delta=delta,max_score_error=score,
                         class_disagreements=disagreement,gate=f['selected']==g['selected'] and max(score.values())<=1e-4 and sum(disagreement.values())==0,
                         cold_total_wall=sum(z['elapsed_s'] for z in external.values()),cold_total_cpu=sum(z['cpu_s'] for z in resources.values()),resources=resources,external=external))
    dump(root/'results.json',dict(rows=rows,source=sha(D/'exact.py'),reference_seal=sha(D.parent/'first'/'seal.json'),
           all_qualified=all(r['gate'] for r in rows)))
if __name__=='__main__': main()
