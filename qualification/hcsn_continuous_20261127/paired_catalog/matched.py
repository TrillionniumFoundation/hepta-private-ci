"""Execute independent, cost-matched comparisons before opening the held-out catalog gallery."""
import time
START=time.monotonic()
from pathlib import Path
import json,sys,subprocess,tempfile,os,hashlib
import numpy as np
from common import ROOT,setup_data,gallery,score,store_model
from construct import fit,encode
HERE=Path(__file__).resolve().parent
def choose():
    rec=[json.loads(p.read_bytes()) for p in sorted((ROOT/'fitted').glob('*.json'))]
    assert len(rec)==18
    selected={}
    for name in ['linear','literal','smooth','random']:
        scores={}
        for width,ridge in [(24,.03),(48,.03),(48,.15)]:
            s=[v for v in rec if (v['kind'],v['width'],v['ridge'])==(name,width,ridge)]
            scores[(width,ridge)]=tuple(np.mean([r['development'][k] for r in s]) for k in ['strict_R1','strict_R5'])
        b=max(scores,key=scores.get)
        selected[name]=[r for r in rec if (r['kind'],r['width'],r['ridge'])==(name,*b)]
    return selected
def work_direct():
    s=choose()['literal'][0];d,V=setup_data();tr=np.flatnonzero(d['split']==0);dv=gallery(d,1)
    with np.load(ROOT/'law.npz') as z:table=dict(z)
    f=fit(V,d,tr,'literal',s['width'],s['ridge'],113,table);fit_time=time.monotonic()-START
    I,T=encode(V,d,dv,f,'literal',table);metrics,_=score(I,T,d,dv)
    assert metrics==s['development']
    with tempfile.NamedTemporaryFile(suffix='.npz',dir=ROOT) as tmp:store_model(tmp.name,f,{})
    print(json.dumps({'type':'selected_direct','fit_s':fit_time,'inside_complete_s':time.monotonic()-START,'score':metrics}))
def work_neural(arm,seed,budget):
    import torch
    from neural import fresh,masked_infonce,Adam,predictions
    torch.set_num_threads(1);torch.manual_seed(seed);rng=np.random.default_rng(seed)
    d,V=setup_data();tr=np.flatnonzero(d['split']==0);dv=gallery(d,1)
    net,inputs=fresh(arm,d,V,'cpu');opt=Adam(net.parameters(),.001,weight_decay=.001)
    # The search target only uses the training allocation of the selected constructive fit.
    # Do not subtract an unseen test validation time; report the separate actual complete clock.
    n=0;laststep=0
    while time.monotonic()-START+laststep<budget and n<1536:
        t=time.monotonic();idx=rng.choice(tr,96,replace=False);net.train();opt.zero_grad()
        I,T=net(*inputs.batch(idx));loss=masked_infonce(I,T,torch.tensor(d['title'][idx]))
        loss.backward();opt.step();n+=1;laststep=time.monotonic()-t
    fit_s=time.monotonic()-START
    I,T=predictions(net,inputs,dv);m,_=score(I,T,d,dv)
    dst=ROOT/'time_matched';dst.mkdir(exist_ok=True);p=dst/f'{arm}-{seed}.pt';torch.save(net.state_dict(),p)
    doc={'arm':arm,'seed':seed,'steps':n,'fit_budget_s':budget,'fit_s':fit_s,'inside_complete_s':time.monotonic()-START,'dev':m,'weights_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    (dst/f'{arm}-{seed}.json').write_text(json.dumps(doc));print(json.dumps(doc))
def main():
    d=ROOT/'time_matched';d.mkdir(exist_ok=True)
    e={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    if not (d/'reference.json').exists():
        runs=[]
        for i in range(3):
            start=time.monotonic();s=subprocess.check_output([sys.executable,__file__,'direct'],env=e,text=True);v=json.loads(s);v['outer_complete_s']=time.monotonic()-start;runs.append(v)
        (d/'reference.json').write_text(json.dumps(runs,indent=1))
    runs=json.loads((d/'reference.json').read_bytes());budget=np.median([v['fit_s'] for v in runs])
    for seed in [113,229,367]:
        for arm in ['conventional','physical_bp']:
            if (d/f'{arm}-{seed}.json').exists():continue
            t=time.monotonic();s=subprocess.check_output([sys.executable,__file__,'neural',arm,str(seed),str(budget)],text=True,env=e)
            with (d/'outer.jsonl').open('a') as log:log.write(json.dumps({'arm':arm,'seed':seed,'seconds':time.monotonic()-t})+'\n')
            print(s.strip(),flush=True)
if __name__=='__main__':
    if len(sys.argv)==1:main()
    elif sys.argv[1]=='direct':work_direct()
    else:work_neural(sys.argv[2],int(sys.argv[3]),float(sys.argv[4]))
