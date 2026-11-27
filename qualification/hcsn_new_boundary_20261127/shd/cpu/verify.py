"""Recount all saved classifications. Reevaluate sampled deep paths with direct FP64 (A7)."""
import argparse
import hashlib
from pathlib import Path
import json
import numpy as np
from scipy.special import ndtr

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def direct(u):
    r=.08;delta=.02;vol=.23;v=vol**2;a=(r-delta-v/2)/v;q=.09
    z=np.sqrt(a*a+2*r/v);zb=np.sqrt(a*a+2*q/v);eta=z-a;g=z+a;disc=np.exp(-q);s=vol;C=6.39;P=61.68
    sml=lambda y:disc*(ndtr(y*s)-np.exp(r)*ndtr(-z*s))/(z+y)
    big=lambda y:(ndtr(y*s)-np.exp((z*z-y*y)*s*s/2)*ndtr(-z*s))/(z+y)
    b=sml(a)+sml(-a);h=big(zb)+big(-zb);den=delta/(eta-1)+.6*h
    w=(1-disc)/eta+b
    bc=(.73/eta+(h-w)/q)/den;bp=w/den;B=bc*C+bp*P
    x=.18-np.log1p(.28*bp*P/B*np.tanh(u));live=np.maximum(x,0.)
    def pair(y):
        def fn(y,j):
            return np.exp(((j-a)**2-y*y)*s*s/2-j*live)*ndtr((-live+(j-a)*s*s)/s)-np.exp(-(a+y)*live)*ndtr((-live+y*s*s)/s)
        def tot(y):
            return (ndtr(y*s)-np.exp(((g-a)**2-y*y)*s*s/2)*ndtr((g-a)*s))*np.exp(-g*live)+fn(y,g)
        return (tot(y)+fn(-y,-eta))/(z-y)+(tot(-y)+fn(y,-eta))/(z+y)
    principal=P-C/q;cost=.73*C+(1-disc)*principal
    equity=B*np.exp(live)+(-delta*B*np.exp(-g*live)/(g+1)-cost*(1/eta-np.expm1(-g*live)/g)+disc*principal*pair(a)-(.6*B-C/q)*pair(zb))/(z*v)
    risk=ndtr((-live-a*v)/vol)+np.exp(-2*a*live)*ndtr((-live+a*v)/vol)
    return np.stack((np.where(x>0,equity/20,0),np.where(x>0,risk,1)),-1)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--raw',type=Path);args=ap.parse_args()
    d=args.root;manifest=json.loads((d/'seal.json').read_text());res=json.loads((d/'results.json').read_text())
    law=json.loads((d/'data/law.json').read_text());mx=[];parts=0;score_n=0;max_err=0
    if args.raw:
        raw=np.load(args.raw/'x_test.npy',mmap_mode='r');sample=np.arange(0,len(raw),53)
    for name,ident in manifest['models'].items():
        loc=d/'test'/name;checkpoint=d/'fits'/name/'selected.npz'
        assert sha(checkpoint)==ident['model']
        pt=loc/'scores.npz';assert sha(pt)==json.loads((loc/'receipt.json').read_text())['predictions']
        with np.load(pt) as p,np.load(checkpoint) as weights:
            y=p['y'];sp=p['people'];score=p['logits'];pred=score.argmax(1)
            assert np.array_equal(p['record'],np.arange(2264));score_n+=score.size
            for task,row in res['rows'][name]['metrics'].items():
                mask={'joint':np.ones(len(y),bool),'old':y<10,'new':y>=10}[task]
                target=y[mask] if task=='joint' else y[mask]%10
                good=pred[mask]==target;ppl=sp[mask];per=[good[ppl==v].mean() for v in np.unique(ppl)]
                assert abs(good.mean()-row['acc']) <1e-12
                assert abs(np.mean(per)-row['speaker_balanced']) <1e-12
                assert np.sum(row['confusion'])==len(target);parts+=1
            if args.raw and weights['kind'].item()=='physical':
                h=(raw[sample].astype('f8')-weights['center'])/weights['scale']
                for w,b in [('w1','b1'),('w2','b2')]:
                    h=direct(h@weights[w]+weights[b])
                    h=(h-law['anchor'])/law['range_raw']
                    h=h.reshape(len(h),12,-1)
                pred64=h.reshape(len(h),6,2,-1).mean(2).reshape(len(h),-1)@weights['head']+weights['head_bias']
                err=np.abs(pred64-score[sample]);max_err=max(max_err,err.max())
                mx.append(dict(model=name,abs=float(err.max()),argmax_change=int((pred64.argmax(1)!=score[sample].argmax(1)).sum())))
    print(json.dumps(dict(models=len(manifest['models']),verified_task_metrics=parts,raw_logits=score_n,
        direct_fp64_checks=mx,max_abs_sampled=float(max_err),sampled_records_per_model=(len(sample) if args.raw else None)),indent=2))
if __name__=='__main__':main()
