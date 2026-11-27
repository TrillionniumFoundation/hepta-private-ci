import time,json,hashlib,math,zipfile
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from biophysics import build
HERE=Path(__file__).resolve().parent
NAMES=["qvi","fixed","qvi_subtracted","fixed_subtracted","lif","softplus","relu","constant","interpolate"]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,j):
    with p.open('x') as f:json.dump(j,f,allow_nan=False,sort_keys=True);f.write('\n')
def load():
    rows=defaultdict(lambda:defaultdict(list));sources=json.loads((HERE/'source.json').read_text())
    for n,h in sources['page_sha256'].items():
        p=HERE/'cache'/n;assert sha(p)==h
        for r in json.loads(p.read_text())['msg']:
            t=r['stimulus_duration'];n=r['num_spikes'];i=r['stimulus_absolute_amplitude']
            if r['stimulus_units']!='Amps' or t is None or not .99<=t<=1.01 or i is None or not np.isfinite(i) or n is None or not isinstance(n,int) or n<0:continue
            rows[r['specimen_id']][round(i)].append((n,t,r['id']))
    candidates=[s for s,levels in rows.items() if len(levels)>=9 and max(levels)-min(levels)>=30 and min(levels)>=-2000 and max(levels)<=2000]
    chosen=sorted(candidates,key=lambda s:hashlib.sha256(f'HCSN-FI-v1/{s}'.encode()).digest())[:72]
    tasks={}
    for s in chosen:
        levels=rows[s];x=np.array(sorted(levels));y=np.array([np.mean([n for n,t,rr in levels[i]]) for i in x]);duration=np.array([np.mean([t for n,t,rr in levels[i]]) for i in x])
        split=np.arange(len(x))%3==2;split[[0,-1]]=False
        tasks[s]=(2*(x-x[0])/(x[-1]-x[0])-1,y,duration,split,x,[[rr for n,t,rr in levels[i]] for i in x])
    return tasks,len(candidates)
def evaluate(name,params,x,d,grid,train):
    if name=='constant':return np.full_like(x,params[0])
    if name=='interpolate':return np.interp(x,train[0],train[1])
    if name=='relu':return d*params[1]*np.maximum(0,x-params[0])
    center,width,speed=params
    z=(x-center)/width
    if name=='lif':
        y=np.zeros_like(x);r=z>0;y[r]=speed/(.1+np.log1p(1/z[r]));return y*d
    if name=='softplus':return speed*d*np.logaddexp(0,z)
    mode=name.split('_')[0];mu=np.clip(-.2-.15*np.tanh(z),-.35,-.05)
    value=grid[mode](np.column_stack([mu,d*speed]))
    if name.endswith('subtracted'):
        mumax=np.clip(-.2-.15*math.tanh((-1-center)/width),-.35,-.05)
        ref=grid[mode](np.column_stack([np.full_like(mu,mumax),d*speed]));value=np.maximum(value-ref,0)
    return value
def fit(name,x,y,d,grid):
    train=(x,y)
    if name=='constant':return [float(y.mean())],0
    if name=='interpolate':return [],0
    if name=='relu':
        starts=[(-.8,5.),(0.,30.),(.6,80.)];lower=[-2,.01];upper=[2,2000]
    else:
        rh=name in ('qvi','fixed','qvi_subtracted','fixed_subtracted'); vmax=500. if rh else 2000.
        a=max(.12,min(vmax*.8, max(float(y.max())*.8,1.)*(3 if rh else .3)))
        starts=[(c,w,a) for c,w in [(-.6,.2),(0,.15),(.6,.2),(-.5,1.),(0,.7),(.4,1.5)]]
        lower=[-2,.03,.1 if rh else .01];upper=[2,4,vmax]
    best=(float('inf'),None,None)
    for start in starts:
        res=least_squares(lambda a:evaluate(name,a,x,d,grid,train)-y,start,bounds=(lower,upper),max_nfev=160,ftol=1e-8,xtol=1e-8,gtol=1e-8)
        if np.isfinite(res.cost) and res.cost<best[0]:best=(res.cost,res.x.tolist(),int(res.status))
    if best[1] is None:raise ValueError('no finite fit')
    return best[1],best[2]
def main():
    grid,verification=build();tasks,eligible=load();out=HERE/'fits';out.mkdir(exist_ok=True);start=time.perf_counter()
    for s,(x,y,d,test,amp,ids) in tasks.items():
        p=out/f'{s}.json'
        if p.exists():continue
        t=time.perf_counter();tr=~test;models={}
        for name in NAMES:
            before=time.perf_counter();a,status=fit(name,x[tr],y[tr],d[tr],grid)
            pred=evaluate(name,a,x[tr],d[tr],grid,(x[tr],y[tr]));models[name]={'params':a,'optimizer_status':status,'train_mae':float(np.abs(pred-y[tr]).mean()),'s':time.perf_counter()-before}
        write(p,dict(specimen_id=s,train_amplitudes=amp[tr].tolist(),train_y=y[tr].tolist(),models=models,wall_s=time.perf_counter()-t))
        print('fit',s,len(list(out.glob('*.json'))),flush=True)
    seal={str(s):sha(out/f'{s}.json') for s in tasks}
    if (HERE/'seal.json').exists():assert json.loads((HERE/'seal.json').read_text())==seal
    else:write(HERE/'seal.json',seal)
    output={};records=defaultdict(list)
    for s,(x,y,d,test,amp,ids) in tasks.items():
        model=json.loads((out/f'{s}.json').read_text())['models'];tr=~test;preds={}
        for name in NAMES:
            p=evaluate(name,model[name]['params'],x[test],d[test],grid,(x[tr],y[tr]));r=p-y[test]
            records[name].append([np.abs(r).mean(),np.sqrt((r*r).mean())]);preds[name]=p.tolist()
        output[str(s)]=dict(specimen_id=s,heldout_amplitudes=amp[test].tolist(),mean_counts=y[test].tolist(),duration_s=d[test].tolist(),heldout_sweep_ids=[rr for rr,k in zip(ids,test) if k],predictions=preds)
    if not (HERE/'predictions.json').exists():write(HERE/'predictions.json',output)
    agg={};rng=np.random.default_rng(8201);ix=rng.integers(len(tasks),size=(10000,len(tasks)))
    for n,R in records.items():
        M=np.array(R);pair=np.array(records['qvi'])[:,0]-M[:,0]
        agg[n]=dict(mean_cell_mae=M[:,0].mean(),median_cell_mae=np.median(M[:,0]),mean_cell_rmse=M[:,1].mean(),qvi_wins=int((pair< -1e-8).sum()),qvi_ties=int((abs(pair)<=1e-8).sum()),qvi_losses=int((pair>1e-8).sum()),qvi_minus_model_mae=pair.mean(),qvi_minus_model_95=np.quantile(pair[ix].mean(1),[.025,.975]).tolist())
    summary=dict(cells=len(tasks),eligible=eligible,n_heldout_levels=sum(len(q['mean_counts']) for q in output.values()),n_heldout_sweeps=sum(sum(map(len,q['heldout_sweep_ids'])) for q in output.values()),heldout_zero_levels=sum(sum(x==0 for x in q['mean_counts']) for q in output.values()),models=agg,validation=verification,wall_s=time.perf_counter()-start,source_sha256=sha(HERE/'source.json'),protocol_sha256=sha(HERE/'protocol.json'),forecast_scope="Currents held out within individually calibrated cells; missing count rows excluded.")
    if not (HERE/'summary.json').exists():write(HERE/'summary.json',summary)
    with zipfile.ZipFile(HERE/'ephys_records.zip','w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(out.glob('*.json')):z.write(p,'fits/'+p.name)
        for n in ['seal.json','predictions.json','source.json','protocol.json']:z.write(HERE/n,n)
    print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
