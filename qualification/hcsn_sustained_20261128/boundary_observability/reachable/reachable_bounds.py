"""Sharp noisy-port error for actual trajectories and their heterogeneous mixtures."""
import hashlib
import json
import itertools
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
from scipy.spatial.distance import pdist, squareform
from scipy import __version__ as scipy_version

PORTS = {'boundary':[0], 'flow':[1], 'priced':[1,2,3], 'horizons':[4,5,6,7],
         'augmented':[1,2,3,4,5,6,7]}
FUTURE=(-.77,-.22,.22,.77)
NOISE=(0.,.0001,.001)
ROOT=Path(__file__).resolve().parent


def ensemble(port, target, eps):
    """Affine upper bound and matching pair of mixtures with intersecting observations."""
    n, m=port.shape
    # Center/rescale input coordinates for HiGHS. Keep the noise weight in the original units.
    scale=np.ptp(port,axis=0)
    keep=scale>1e-15
    ref=port[0,keep]
    scales=scale[keep]
    q=(port[:,keep]-ref)/scales
    k=len(scales)
    ones=np.ones((n,1))
    bounds=[(None,None)]+[(0,None)]*(2*k+1)
    f=np.hstack((ones,q,-q))
    C=np.vstack((np.hstack((f,-ones)),np.hstack((-f,-ones))))
    kwargs=dict(method='highs',options=dict(primal_feasibility_tolerance=1e-9,
                                           dual_feasibility_tolerance=1e-9))
    primal=linprog(np.r_[0,eps/scales,eps/scales,1],A_ub=C,b_ub=np.r_[target,-target],
                   bounds=bounds,**kwargs)
    cons=np.hstack((q.T,-q.T))
    eq=np.zeros((2,2*n));eq[0,:n]=1;eq[1,n:]=1
    dual=linprog(np.r_[-target,target]/2,A_ub=np.vstack((cons,-cons)) if k else None,
                 b_ub=np.r_[2*eps/scales,2*eps/scales] if k else None,A_eq=eq,b_eq=[1,1],
                 bounds=(0,None),**kwargs)
    if not primal.success or not dual.success:raise ValueError((primal.message,dual.message))
    a=np.zeros(m);a[keep]=(primal.x[1:1+k]-primal.x[1+k:1+2*k])/scales
    c=primal.x[0]-a[keep]@ref
    hi,lo=np.split(dual.x,2)
    upper=np.max(abs(c+port@a-target))+eps*np.abs(a).sum()
    lower=(hi-lo)@target/2
    gap=np.max(abs((hi-lo)@port))
    assert min(hi.min(),lo.min())>=-2e-8 and max(abs(hi.sum()-1),abs(lo.sum()-1))<=2e-8
    assert gap<=2*eps+4e-8 and abs(upper-lower)<5e-7,(upper,lower,gap)
    def sparse(v): return [[int(i),v[i]] for i in np.flatnonzero(v!=0)]
    return dict(upper=upper,lower=lower,observation_gap=gap,intercept=c,a=a.tolist(),
                high=sparse(hi),low=sparse(lo))


def solve():
    path=ROOT/'reachable.npz'
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    assert sha=='53d2a42d920ce141d5d7c59d16aa1e239b9b2ca25279063989b92c2c4ce2221a'
    result={'input_sha256':sha,'scipy':scipy_version,'rows':[]}
    with np.load(path) as data:
        for atoms in (12,32):
            for name,cols in PORTS.items():
                port=data[f'message{atoms}'][:,cols]
                dst=squareform(pdist(port,metric='chebyshev'))
                for eps in NOISE:
                    close=(dst<=2*eps)
                    for j,shock in enumerate(FUTURE):
                        tgt=data[f'targets{atoms}'][:,j]
                        gaps=np.where(close,np.abs(tgt[:,None]-tgt[None,:]),-1)
                        l,r=map(int,np.unravel_index(np.argmax(gaps),gaps.shape))
                        radii=ensemble(port,tgt,eps)
                        rad=gaps[l,r]/2
                        assert rad<=radii['upper']+1e-7
                        result['rows'].append(dict(atoms=atoms,port=name,noise=eps,shock=shock,
                                                   reachable=rad,port_gap=dst[l,r],witness=[l,r],
                                                   pair_count=int(np.triu(close,1).sum()),ensemble=radii))
    (ROOT/'reachable_results.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    for row in result['rows']:
        if row['atoms']==32 and row['noise']==.001 and row['shock']==.77:
            print(row['port'],row['reachable'],row['ensemble']['upper'],row['witness'])
    print('rows',len(result['rows']))
if __name__=='__main__':solve()
