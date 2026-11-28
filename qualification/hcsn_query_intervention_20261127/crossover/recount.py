"""Rebuild all response contrasts directly from the source spike times and delivered FP32."""
import argparse
import json
from pathlib import Path
import numpy as np

def audit(raw,preds):
    report=json.loads((preds/'results.json').read_text());largest={k:0. for k in ('primary','secondary','high_noise2','mid_noise2')};queries=0
    for sid,expected in report['donors'].items():
        by={};true={};n=len(np.arange(30,481,2))
        with np.load(raw/f'{sid}.npz') as src:
            for t in ('1','2'):
                for r in (0,1):
                    file=preds/f'{sid}_{t}_{r}.npz'
                    if not file.exists():
                        assert np.array_equal(src['x'+t+'_0'],src['x'+t+'_1']);file=preds/f'{sid}_{t}_0.npz'
                    with np.load(file) as f:
                        for key in expected:
                            assert f[key].dtype==np.float32 and f[key].shape==(3,3,n,2)
                            by[t,r,key]=f[key].astype(float)
                    y=src['y'+t+'_'+str(r)];box=np.empty((3,3,n,2),bool)
                    for d in range(3):
                        for c in range(3):
                            idx=d*4000+c*500+np.arange(30,481,2)
                            for h,z in enumerate((2,6)):
                                box[d,c,:,h]=np.logical_or.reduce([y[idx+j] for j in range(z)])
                    true[t,r]=box;queries+=box.size
        for key,metrics in expected.items():
            for name,(t_hi,d_hi,t_lo,d_lo) in {'primary':('2',2,'2',1),'secondary':('2',2,'1',2)}.items():
                dt=[];dp=[]
                for r in (0,1):
                    dt.append(np.mean(true[t_hi,r][d_hi],0)-np.mean(true[t_lo,r][d_lo],0))
                    dp.append(np.mean(by[t_hi,r,key][d_hi],0)-np.mean(by[t_lo,r,key][d_lo],0))
                pred=np.mean(dp,0);truth=np.mean(dt,0)
                val=[np.mean((pred-truth)**2),np.mean((pred-dt[0])*(pred-dt[1])),np.mean((dt[0]-dt[1])**2)/4,pred.mean(),truth.mean()]
                largest[name]=max(largest[name],float(np.max(abs(np.array(val)-metrics[name]))))
            for name,dose in (('high_noise2',2),('mid_noise2',1)):
                prob=np.clip(np.stack([by['2',r,key][dose] for r in (0,1)]),1e-7,1.-1e-7)
                truth=np.stack([true['2',r][dose] for r in (0,1)])
                val=[np.mean(-np.where(truth,np.log(prob),np.log1p(-prob))),np.mean((prob-truth)**2)]
                largest[name]=max(largest[name],float(np.max(abs(np.array(val)-metrics[name]))))
    return {'donors':len(report['donors']),'individual_query_targets_rebuilt':queries,'max_donor_metric_absolute_difference':largest,
            'note':'Original running means use FP32. This recount averages the transmitted FP32 values in FP64.'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('preds',type=Path);a=p.parse_args()
    print(json.dumps(audit(a.raw,a.preds),indent=1))
