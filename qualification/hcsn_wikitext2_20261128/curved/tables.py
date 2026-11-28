"""Continuous-margin price curves and the global uniform L2-optimal bilinear projection."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import numpy as np
from numpy.polynomial import chebyshev as cheb
from numpy.polynomial import polynomial as power
from numpy.polynomial.legendre import leggauss

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from closed_form import Contract,Prices

LOW,HIGH=.02,.80
DEGREE=22

def build():
    qs=[Prices(replace(Contract(),principal=61.68*(1+.28*u))) for u in (-1.,0.,1.)]
    def curves(t):
        x=(LOW+HIGH)/2+t*(HIGH-LOW)/2
        vals=np.array([[q.equity(x),q.credit_loss(x)] for q in qs])
        return [*vals[1],*((vals[2]-vals[0])/2)]
    # E0,L0,Eu,Lu as affine functions of u at each actual continuum margin.
    grid=np.cos(np.pi*(np.arange(DEGREE+1)+.5)/(DEGREE+1))
    cc=cheb.chebfit(grid,np.array([curves(t) for t in grid]),DEGREE)
    pp=np.stack([cheb.cheb2poly(vec) for vec in cc.T],1)
    E,L=curves(1)[0],curves(-1)[1]
    scalar=np.stack([pp[:,0]/E-pp[:,1]/L,pp[:,2]/E-pp[:,3]/L],1)
    scalar[0,1]+=1
    # Continuous-uniform L2 on independent t,u in [-1,1]. {1,t}
    # are orthogonal; f0(t) and u*f1(t) have orthogonal u factors.
    t,weights=leggauss(120)
    truth=np.array([curves(x) for x in t])
    f=np.stack([truth[:,0]/E-truth[:,1]/L,1+truth[:,2]/E-truth[:,3]/L],1)
    proj=np.stack([weights@f/2,(3*weights*t)@f/2])
    def errs(f1,f2):
        z=f1-f2
        return dict(max_abs=float(np.max(np.abs(z[:,0])+np.abs(z[:,1]))),
                    uniform_rmse=float(np.sqrt(weights@(z[:,0]**2+z[:,1]**2/3)/2)))
    xy=np.linspace(-1,1,2001)
    actual=np.array([curves(ti) for ti in xy])
    recon=power.polyval(xy,pp).T
    deriv=power.polyval(xy,power.polyder(pp)).T
    h=2e-5
    dactual=np.array([(-np.array(curves(y+2*h))+8*np.array(curves(y+h))-8*np.array(curves(y-h))+np.array(curves(y-2*h)))/(12*h) for y in xy])
    # Independently test the reference probability-coordinate dependence with
    # intermediate principals, not just endpoint budgets.
    max_mid=0.
    for u in np.linspace(-.97,.97,17):
        q=Prices(replace(Contract(),principal=61.68*(1+.28*u)))
        for tt in np.linspace(-1,1,21):
            xx=.5*(LOW+HIGH+(HIGH-LOW)*tt)
            ar=power.polyval(tt,pp)
            max_mid=max(max_mid,abs(q.equity(xx)-ar[0]-u*ar[2]),abs(q.credit_loss(xx)-ar[1]-u*ar[3]))
    ppred=power.polyval(t,proj).T
    return dict(margin=[LOW,HIGH],degree=DEGREE,price_bases=pp.tolist(),scalar_coefficients=scalar.tolist(),
             uniform_projection_coefficients=proj.tolist(),normalizing_equity=E,normalizing_loss=L,
             independent_points=len(xy),price_basis_max_abs=float(np.max(np.abs(actual-recon))),
             intermediate_contract_max_abs=max_mid,derivative_d_dt_4th_order_max_abs=float(np.max(np.abs(deriv-dactual))),
             normalized_projection_error=errs(f,ppred),normalized_curve_error=errs(f,power.polyval(t,scalar).T),
             projection_normal_equations=(np.stack([weights@(f-ppred)/2,(weights*t)@(f-ppred)/2])).tolist())

if __name__=='__main__':
    p=Path(__file__).with_name('tables.json');out=build();p.write_text(json.dumps(out,indent=2)+'\n')
    for k in ('price_basis_max_abs','intermediate_contract_max_abs','derivative_d_dt_4th_order_max_abs','normalized_projection_error','normalized_curve_error'):print(k,out[k])
