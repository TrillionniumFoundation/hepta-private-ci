"""Independent obstacle-grid convergence, differential residuals and threshold comparative statics."""
import dataclasses
import json
from pathlib import Path
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
from stopping import Continuation,FirstHit,Model

def operator(p,q,grid):
    n=len(grid); dx=np.log(grid[1]/grid[0]);mu=p.r-p.payout-p.sigma**2/2
    lo=.5*p.sigma**2/dx**2-mu/(2*dx)
    hi=.5*p.sigma**2/dx**2+mu/(2*dx)
    if min(lo,hi)<0:raise ArithmeticError('grid does not give monotone generator')
    eye=sparse.eye(n,format='csr')
    lap=sparse.diags([-lo*np.ones(n-1),(q+lo+hi)*np.ones(n),-hi*np.ones(n-1)],[-1,0,1],format='csr')
    return sparse.bmat([[lap+p.up*eye,-p.up*eye],[-p.down*eye,lap+p.down*eye]],format='csr')

def impose(matrix,rhs,rows,values):
    d=sparse.diags((~rows).astype(float),format='csr')
    a=d@matrix+sparse.diags(rows.astype(float),format='csr')
    return a,np.where(rows,values,rhs)

def reference(p,n):
    g=np.geomspace(.025,80,n);x=np.tile(g,2);ids=np.arange(2*n)
    lo=ids%n==0;hi=ids%n==n-1
    costs=np.array([p.cheap,p.dear]);c=np.linalg.solve([[p.r+p.up,-p.up],[-p.down,p.r+p.down]],costs)
    flow=p.payout*x-np.repeat(costs,n)
    A=operator(p,p.r,g);a,h=impose(A,flow,hi|lo,np.where(hi,x-np.repeat(c,n),0))
    stop=(flow<=0)&(~hi)&(~lo)
    eye=np.zeros(2*n)
    for iteration in range(2*n):
        lin,rhs=impose(a,h,stop,eye)
        y=spsolve(lin,rhs)
        advantage=y+(h-a@y)/a.diagonal()
        next_stop=(advantage<=0)&(~hi)&(~lo)
        if np.array_equal(next_stop,stop):break
        stop=next_stop
    else:raise ArithmeticError('obstacle policy did not settle')
    wall=max(np.max(np.abs(np.minimum(y[~(lo|hi)],(A@y-flow)[~(lo|hi)]))),np.max(np.maximum(-y,0)))
    op=operator(p,p.discount,g)
    loss,rhs=impose(op,eye,stop|lo|hi,np.where(hi,0,1))
    hit=spsolve(loss,rhs)
    mask=(stop|lo).reshape(2,n)
    barrier=[float(g[np.flatnonzero(m)[-1]]) for m in mask]
    return g,y.reshape(2,n).T,hit.reshape(2,n).T,barrier,iteration+1,wall

def differential(e,h,grid):
    p=e.p;flow=p.payout*grid[:,None]-np.array([p.cheap,p.dear]);Q=np.array([[-p.up,p.up],[p.down,-p.down]])
    inside=grid[:,None]>[e.b0,e.b1]
    def residual(fn,q,source):
        val=fn.values(grid);dy=fn.values(grid,1);ddy=fn.values(grid,2)
        return .5*p.sigma**2*ddy+(p.r-p.payout-.5*p.sigma**2)*dy+val@Q.T-q*val+source
    re=residual(e,p.r,flow);rh=residual(h,p.discount,0.)
    return dict(equity_live_max_abs=float(abs(re[inside]).max()),equity_stopped_max_residual=float(re[~inside].max()),
                firsthit_live_max_abs=float(abs(rh[inside]).max()),equity_min=float(e.values(grid).min()),
                discounted_hit_min=float(h.values(grid).min()),discounted_hit_max=float(h.values(grid).max()))
def main():
    p=Model();e=Continuation(p);h=FirstHit(e);grid=np.geomspace(.025,75,5001)
    results=dict(params=dataclasses.asdict(p),uncoupled=p.uncoupled().tolist(),coupled=[e.b0,e.b1],
                 smooth_matching=e.match(e.b0,e.b1).tolist(),differential=differential(e,h,grid),fd=[],switch_limits=[],samples=[])
    S=p.up+p.down;barcost=(p.down*p.cheap+p.up*p.dear)/S
    n=p.exponents(p.r)[1];results['averaged_cost_boundary']=float(n/(n-1)*barcost/p.r)
    for z in [.001,.01,.1,1,3,10,30,100,300,1000]:
        model=Continuation(dataclasses.replace(p,up=p.up*z,down=p.down*z))
        results['switch_limits'].append([z,model.b0,model.b1])
    for size in [401,801,1601,3201,6401]:
        g,E,H,b,it,err=reference(p,size)
        sl=(g>.15)&(g<4)
        results['fd'].append(dict(grid=size,barriers=b,iterations=it,obstacle_residual=float(err),
               equity_sup=float(np.max(abs(E[sl]-e.values(g[sl])))),hit_sup=float(np.max(abs(H[sl]-h.values(g[sl])))),
               equity_at_one=np.array([np.interp(1.,g,E[:,s]) for s in (0,1)]).tolist(),
               hit_at_one=np.array([np.interp(1.,g,H[:,s]) for s in (0,1)]).tolist()))
    for v in [e.b0,.5,e.b1,.72,1.,1.5]:
        results['samples'].append(dict(asset=v,equity=e.values([v])[0].tolist(),hit=h.values([v])[0].tolist()))
    assert results['differential']['equity_stopped_max_residual']<1e-8
    assert results['differential']['equity_live_max_abs']<1e-9
    assert results['differential']['firsthit_live_max_abs']<1e-9
    return results

if __name__=='__main__':
    result=main()
    Path(__file__).with_name('validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result['coupled'],result['fd'][-1],result['switch_limits'],flush=True)
