"""Small, explicitly specified frozen-feature head and calibration diagnostic."""
import argparse, hashlib, json, math, time
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
H=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def probabilities(a,T=1.0):
    a=np.asarray(a,dtype=np.float64)/T
    if not np.isfinite(a).all() or not math.isfinite(T) or T<=0: raise ValueError('invalid logits/temperature')
    shifted=a-a.max(axis=1,keepdims=True);e=np.exp(shifted)
    return e/e.sum(axis=1,keepdims=True)
def nll_rows(a,y,T=1.0):
    a=np.asarray(a,dtype=np.float64)/T
    return np.logaddexp.reduce(a,axis=1)-a[np.arange(len(y)),y]
def fit_temperature(a,y):
    objective=lambda t:float(nll_rows(a,y,math.exp(t)).mean())
    lo,hi=-5.,5.;phi=(math.sqrt(5)-1)/2
    c=hi-phi*(hi-lo);d=lo+phi*(hi-lo);fc,fd=objective(c),objective(d)
    for _ in range(100):
        if fc<fd:
            hi,d,fd=d,c,fc;c=hi-phi*(hi-lo);fc=objective(c)
        else:
            lo,c,fc=c,d,fd;d=lo+phi*(hi-lo);fd=objective(d)
    candidates=[-5.,0.,5.,(lo+hi)/2];t=min(candidates,key=objective)
    return {'T':math.exp(t),'log_T':t,'boundary':abs(abs(t)-5)<1e-5,'raw_tune_nll':objective(0),'tuned_tune_nll':objective(t)}
def threshold(scores,alpha=.1):
    scores=np.asarray(scores,dtype=np.float64)
    if scores.ndim!=1 or len(scores)==0 or not np.isfinite(scores).all() or not 0<alpha<1: raise ValueError('invalid calibration scores')
    k=math.ceil((len(scores)+1)*(1-alpha))
    return (float('inf') if k>len(scores) else float(np.partition(scores,k-1)[k-1])),k
def aps_scores(p,u):
    p=np.asarray(p,dtype=np.float64);u=np.asarray(u,dtype=np.float64)
    if p.ndim!=2 or u.shape!=(len(p),) or not np.isfinite(p).all() or not np.isfinite(u).all() or np.any(p<0) or not np.allclose(p.sum(1),1) or np.any((u<0)|(u>=1)): raise ValueError('invalid APS inputs')
    order=np.argsort(-p,axis=1,kind='stable');sp=np.take_along_axis(p,order,axis=1)
    sorted_s=np.cumsum(sp,axis=1)-u[:,None]*sp
    s=np.empty_like(p);np.put_along_axis(s,order,sorted_s,axis=1)
    return s
def wilson(errors,n):
    if n==0:return None
    z=1.959963984540054;p=errors/n;den=1+z*z/n;center=(p+z*z/(2*n))/den;rad=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0.,center-rad),min(1.,center+rad)]
def set_metrics(sets,y):
    size=sets.sum(1);covered=sets[np.arange(len(y)),y];single=size==1;n=int(single.sum());wrong=int((single&~covered).sum())
    return {'coverage':float(covered.mean()),'coverage_wilson95':wilson(int(covered.sum()),len(y)),'mean_set_size':float(size.mean()),'empty_fraction':float((size==0).mean()),'singleton_acceptance':n/len(y),'singleton_count':n,'singleton_errors':wrong,'singleton_error':wrong/n if n else None,'singleton_error_wilson95':wilson(wrong,n),'per_class':{str(k):{'n':int((y==k).sum()),'covered':int(covered[y==k].sum()),'coverage':float(covered[y==k].mean())} for k in range(4)}}
def metrics(a,y,T):
    p=probabilities(a,T);pred=p.argmax(1);correct=pred==y;conf=p.max(1);ece=0.;bins=[]
    for b in range(10):
        mask=(conf>=b/10)&((conf<(b+1)/10) if b<9 else (conf<=1))
        n=int(mask.sum());acc=float(correct[mask].mean()) if n else None;avg=float(conf[mask].mean()) if n else None
        if n:ece+=n/len(y)*abs(acc-avg)
        bins.append({'n':n,'accuracy':acc,'confidence':avg})
    return {'accuracy':float(correct.mean()),'correct':int(correct.sum()),'n':len(y),'accuracy_wilson95':wilson(int(correct.sum()),len(y)),'nll':float(nll_rows(a,y,T).mean()),'brier':float(np.square(p-np.eye(4)[y]).sum(1).mean()),'ece10':ece,'ece_bins':bins}
def paired_interval(d):
    d=np.asarray(d,dtype=np.float64);rng=np.random.default_rng(20261026)
    means=d[rng.integers(0,len(d),size=(5000,len(d)))].mean(1)
    return {'mean':float(d.mean()),'bootstrap95':np.quantile(means,[.025,.975]).tolist(),'replicates':5000}
def main():
    import torch
    global P
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True,help='Prepared directory with frozen features and extraction receipt')
    args=parser.parse_args()
    P=args.output_dir.resolve()
    if not __debug__: raise RuntimeError('optimized Python forbidden')
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True);torch.manual_seed(20261023)
    assert not (P/'results.json').exists(), 'never overwrite results'
    assert H(P/'plan.json')=='48ff3c003067370449254daefcf465c4960fbc01a39dae5b83d98123d3aec55c'
    plan=json.loads((P/'plan.json').read_text());manifest=json.loads((P/'rows.json').read_text());extraction=json.loads((P/'extraction.json').read_text())
    assert H(P/'rows.json')==plan['rows_sha256'] and extraction['plan_sha256']==H(P/'plan.json')
    assert H(P/'features.npz')==extraction['features_file_sha256']
    data=np.load(P/'features.npz',allow_pickle=False);X={k:np.asarray(data[k],dtype=np.float64) for k in manifest};y={k:np.array([r['label'] for r in rows],dtype=np.int64) for k,rows in manifest.items()}
    for k,z in X.items(): assert z.shape==(len(y[k]),640) and np.isfinite(z).all() and np.allclose(np.linalg.norm(z,axis=1),1,atol=1e-5)
    train=X['head_train'];labels=y['head_train'];centroid=np.stack([train[labels==k].mean(0) for k in range(4)]);centroid/=np.linalg.norm(centroid,axis=1,keepdims=True)
    t=time.monotonic();xt=torch.from_numpy(train);yt=torch.from_numpy(labels);W=torch.zeros((640,4),dtype=torch.float64,requires_grad=True);b=torch.zeros(4,dtype=torch.float64,requires_grad=True);optimizer=torch.optim.Adam([W,b],lr=.1);curve=[]
    for step in range(200):
        optimizer.zero_grad();ce=torch.nn.functional.cross_entropy(xt@W+b,yt);loss=ce+.001/2*W.square().sum();loss.backward();optimizer.step()
        if step in [0,49,99,149,199]:curve.append({'step':step+1,'objective_pre_update':float(loss.detach()),'cross_entropy_pre_update':float(ce.detach())})
    optimizer.zero_grad();loss=torch.nn.functional.cross_entropy(xt@W+b,yt)+.001/2*W.square().sum();loss.backward()
    training={'steps':200,'curve':curve,'final_objective':float(loss.detach()),'final_gradient_l2':float(torch.sqrt(W.grad.square().sum()+b.grad.square().sum())),'seconds':time.monotonic()-t,'warning':'Fixed-step optimizer, no formal optimum/convergence claim.'}
    lw,lb=W.detach().numpy(),b.detach().numpy()
    meanX=train.mean(0);onehot=np.eye(4)[labels];meanY=onehot.mean(0);Z=train-meanX;Y=onehot-meanY
    rw=np.linalg.solve(Z.T@Z+np.eye(640),Z.T@Y);rb=meanY-meanX@rw
    all_logits={'centroid':{k:v@centroid.T for k,v in X.items()},'logistic':{k:v@lw+lb for k,v in X.items()},'ridge':{k:v@rw+rb for k,v in X.items()}}
    results={'profile':plan['profile'],'plan_sha256':H(P/'plan.json'),'rows_sha256':H(P/'rows.json'),'feature_sha256':H(P/'features.npz'),'extraction_sha256':H(P/'extraction.json'),'analysis_driver_sha256':H(__file__),'training':training,'heads':{}}
    uc=np.random.default_rng(20261024).random(len(y['conformal']));ut=np.random.default_rng(20261025).random(len(y['test']))
    retained={'centroid':centroid,'logistic_W':lw,'logistic_b':lb,'ridge_W':rw,'ridge_b':rb,'calibration_uniform':uc,'test_uniform':ut}
    for head,logits in all_logits.items():
        temperature=fit_temperature(logits['temperature'],y['temperature']);out={'temperature_fit':temperature,'variants':{}}
        for name,T in [('raw',1.),('TS',temperature['T'])]:
            assert all(np.array_equal(a.argmax(1),(a/T).argmax(1)) for a in logits.values())
            calp=probabilities(logits['conformal'],T);testp=probabilities(logits['test'],T);variant=metrics(logits['test'],y['test'],T);variant['sets']={}
            for method,cal_scores,test_scores in [('LAC',1-calp,1-testp),('APS',aps_scores(calp,uc),aps_scores(testp,ut))]:
                q,k=threshold(cal_scores[np.arange(len(uc)),y['conformal']]);sets=test_scores<=q
                variant['sets'][method]={'threshold':q,'k':k,**set_metrics(sets,y['test'])}
                retained[f'{head}_{name}_{method}_test_sets']=sets
            out['variants'][name]=variant
        out['TS_nll_gain']=paired_interval(nll_rows(logits['test'],y['test'])-nll_rows(logits['test'],y['test'],temperature['T']))
        results['heads'][head]=out
        for split,a in logits.items():retained[f'{head}_{split}_logits']=a
    results['primary_adaptation_accuracy_gain']=paired_interval((all_logits['logistic']['test'].argmax(1)==y['test']).astype(float)-(all_logits['centroid']['test'].argmax(1)==y['test']).astype(float))
    adapted=results['primary_adaptation_accuracy_gain'];calibrated=results['heads']['logistic']['TS_nll_gain'];utility=results['heads']['logistic']['variants']['TS']['sets']['LAC']
    results['preregistered_outcomes']={'adaptation':'supported_in_sampled_pilot' if adapted['bootstrap95'][0]>0 else ('no_demonstrated_benefit' if adapted['mean']<=0 else 'uncertain'),'calibration':'supported_in_sampled_pilot' if calibrated['bootstrap95'][0]>0 else ('no_demonstrated_benefit' if calibrated['mean']<=0 else 'uncertain'),'pilot_utility':bool(utility['singleton_acceptance']>=.5 and utility['singleton_error_wilson95'] and utility['singleton_error_wilson95'][1]<=.1)}
    np.savez_compressed(P/'head-artifacts.npz',**retained);results['head_artifacts_sha256']=H(P/'head-artifacts.npz')
    (P/'results.json').write_text(json.dumps(results,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({'outcomes':results['preregistered_outcomes'],'accuracy_gain':adapted,'nll_gain':calibrated,'utility':utility},indent=2))
if __name__=='__main__':main()
