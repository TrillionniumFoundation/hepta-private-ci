"""Independent continuum and finite-grid checks for the four registered first-hit flows."""
import json
import math
from pathlib import Path

import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr


def compare(folder):
    low,high,sigma,dt=.015,1.30,.23,.25
    drift=.08-.02-.5*sigma*sigma
    shifts=(.023,-.031,.123,-.171)
    def weight(x,i):
        return (.2+np.cos(2+i/9+6*x)**2)*np.exp(-((x-.17-.13*i)/.42)**2)
    def hit(y):
        x=np.maximum(y,0.)
        s=sigma*math.sqrt(dt)
        val=ndtr((-x-drift*dt)/s)+np.exp(-2*drift*x/(sigma*sigma))*ndtr((-x+drift*dt)/s)
        return np.where(y<=0,1.,val)
    continuum=[]
    for i,shift in enumerate(shifts):
        points=[-shift] if low<-shift<high else None
        kw={'epsabs':1e-13,'epsrel':1e-13}
        den=quad(lambda x:weight(x,i),low,high,**kw)[0]
        val=quad(lambda x:weight(x,i)*float(hit(x+shift)),low,high,points=points,**kw)[0]/den
        continuum.append(val)
    observations=[]
    with np.load(folder/'checks.npz',allow_pickle=False) as z:
        for k in (256,512,1024,2048):
            grid=np.linspace(low,high,k,dtype=np.float64)
            finite=np.array([np.average(hit(grid+s),weights=weight(grid,i)) for i,s in enumerate(shifts)])
            row={'atoms':k,'finite_numpy_scipy_flow':finite.tolist(),
                 'max_finite_continuum_flow_difference':float(np.max(np.abs(finite-continuum)))}
            for dtype in ('float32','float64'):
                for mode in ('dense','fft'):
                    cloud=z[f'operator_{dtype}_{k}_{mode}__flow']
                    gap=float(np.max(np.abs(finite-cloud)))
                    assert gap<(3e-12 if dtype=='float64' else 3e-6),(dtype,k,mode,gap)
                    row[dtype+'_'+mode+'_against_finite_oracle']=gap
            observations.append(row)
    return {'domain':[low,high],'sigma':sigma,'drift':drift,'finite_step':dt,'shifts':shifts,
            'continuum_flow':continuum,'observations':observations}


if __name__=='__main__':
    folder=Path(__file__).resolve().parent
    (folder/'continuum.json').write_text(json.dumps(compare(folder),indent=2)+'\n')
