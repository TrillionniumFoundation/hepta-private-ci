"""Refit NLL replay via SciPy inverse-Gaussian distribution, independent vector algebra."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import invgauss


def independent_nll(x, y, multiplier, mode):
    row = x.astype(float)
    elapsed = row[:,1:2] - row[:,6:7] - np.arange(32)[None]*row[:,5:6]
    distance = row[:,0:1] + np.arange(32)[None]*row[:,4:5]
    rate = -row[:,2:3]*multiplier
    shape = row[:,3:4]**2/(rate*distance)
    scale = distance**2/row[:,3:4]**2
    tails = invgauss.cdf(np.maximum(elapsed,0),shape,scale=scale)
    tails = np.where(elapsed>0,tails,0.)
    probs = np.concatenate([np.ones((len(row),1)),tails[:,:-1]],axis=1)-tails
    if probs.min() < -1e-10 or np.max(tails[:,-1]) > 1e-8:
        raise AssertionError('Independent support/mass failure')
    probs=np.maximum(probs,0)
    probs/=probs.sum(1,keepdims=True)
    if mode=='single_transition':
        changed=np.zeros_like(probs)
        changed[:,0]=probs[:,0]
        changed[:,1]=1-probs[:,0]
        probs=changed
    elif mode=='mean_two_point':
        mean=probs @ np.arange(32)
        lower=np.minimum(mean.astype(int),31)
        changed=np.zeros_like(probs)
        changed[np.arange(len(row)),lower]=1-(mean-lower)
        upper=np.minimum(lower+1,31)
        changed[np.arange(len(row)),upper]+=mean-lower
        probs=changed
    selected=probs[np.arange(len(row)),y]
    return float(-np.log(np.maximum(selected,1e-12)).mean()), int(np.count_nonzero(selected==0.))


def main(dest,out):
    fits=json.loads((dest/'ANALYTIC_FITS.json').read_text())
    checks=0
    max_error=0.
    report={}
    for fs,modes in fits.items():
        samples=np.load(dest/f'samples_{fs}.npz')
        report[fs]={}
        for mode,fit in modes.items():
            for candidate in fit['candidates']:
                nll,_=independent_nll(samples['train_x'],samples['train_y'],candidate['drift_scale'],mode)
                error=abs(nll-candidate['train_nll'])
                max_error=max(max_error,error)
                if error>2e-8:
                    raise AssertionError(('independent train NLL',fs,mode,candidate,error))
                checks+=1
            nll,train_zeros=independent_nll(samples['train_x'],samples['train_y'],fit['selected_scale'],mode)
            val,val_zeros=independent_nll(samples['validation_x'],samples['validation_y'],fit['selected_scale'],mode)
            error=abs(val-fit['validation_nll'])
            max_error=max(max_error,error)
            if error>2e-8:
                raise AssertionError(('independent validation NLL',fs,mode,error))
            checks+=1
            report[fs][mode]={'selected_scale':fit['selected_scale'],'train_nll':nll,'validation_nll':val,
                'train_label_zero_support_count':train_zeros,'train_examples':len(samples['train_y']),
                'validation_label_zero_support_count':val_zeros,'validation_examples':len(samples['validation_y'])}
    result={'status':'passed','checks':checks,'absolute_nll_tolerance':2e-8,'maximum_nll_error':max_error,
            'implementation':'scipy.stats.invgauss.cdf, independent vector event-count differences and count-shape transforms',
            'fits':report,'claim':'exact declared finite refit replay; no analytic neural network retraining'}
    with out.open('x') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status':'passed','checks':checks,'maximum_nll_error':max_error}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    main(args.run,args.out)
