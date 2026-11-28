"""Mean first-exit time and an independent finite-sector Poisson-series check for two correlated paths."""
import math
import numpy as np


def wedge(correlation,distances,volatilities):
    if not -1<correlation<1 or min(*distances,*volatilities)<=0:
        raise ValueError('use a nonsingular correlation and two positive distances and volatilities')
    L=np.array([[volatilities[0],0.],[correlation*volatilities[1],volatilities[1]*math.sqrt(1-correlation**2)]])
    y=np.linalg.solve(L,distances);first=np.linalg.solve(L,[1.,0.]);last=np.linalg.solve(L,[0.,1.])
    def angle(a,b):return math.acos(np.clip(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)),-1.,1.))
    alpha=angle(first,last);theta=angle(first,y)
    assert abs(alpha-math.acos(-correlation))<1e-13 and 0<theta<alpha
    return alpha,theta,float(np.linalg.norm(y))


def infinite_mean(correlation,distances,volatilities):
    wedge(correlation,distances,volatilities)
    if correlation>=0:return math.inf
    return -distances[0]*distances[1]/(correlation*volatilities[0]*volatilities[1])


def finite_sector_mean(correlation,distances,volatilities,radius_multiple,terms=5001):
    """Solve half-Laplacian u = -1 by sine series in a wedge cut off by an absorbing outer circle."""
    if radius_multiple<=1 or terms<1:raise ValueError('outside circle and positive Fourier term count required')
    alpha,theta,r=wedge(correlation,distances,volatilities)
    modes=np.arange(1,2*terms+1,2,dtype=float)
    nu=modes*math.pi/alpha
    b=4/(math.pi*modes)
    resonant=np.abs(nu-2)<1e-12
    w=np.zeros_like(nu)
    w[resonant]=.5*b[resonant]*r*r*math.log(radius_multiple)
    # -expm1 is the difference 1 - (R/r)^(2-nu), including the divergent obtuse-sector case.
    w[~resonant]=2*b[~resonant]*r*r*(-np.expm1((2-nu[~resonant])*math.log(radius_multiple)))/(nu[~resonant]**2-4)
    return float(np.dot(w,np.sin(nu*theta)))


if __name__=='__main__':
    import argparse,hashlib,json
    from pathlib import Path
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args()
    rows=[];x=[.18,.30];sig=[.23,.31]
    for corr in (-.8,-.5,-.25,0.,.5,.8):
        u=infinite_mean(corr,x,sig);alpha,theta,rad=wedge(corr,x,sig)
        factors=np.array([2.,4.,16.,256.,65536.,1e12])
        means=[finite_sector_mean(corr,x,sig,f) for f in factors]
        assert np.min(np.diff(means))>=-1e-10
        if corr<0:
            assert max(means)<=u+1e-8
            if corr<=-.5:assert abs(means[-1]-u)<1e-8
        else:assert means[-1]>2*means[2]
        rows.append({'correlation':corr,'opening_angle_rad':alpha,'survival_exponent':math.pi/(2*alpha),
                     'infinite_mean':u if math.isfinite(u) else 'divergent',
                     'cutoff_radius_over_start':factors.tolist(),'finite_sector_expected_exit_times':means})
    out={'distances':x,'volatilities':sig,'rows':rows,'angular_fourier_odd_terms':5001,
         'source':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    a.output.write_text(json.dumps(out,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print([(r['correlation'],r['survival_exponent'],r['infinite_mean'],r['finite_sector_expected_exit_times'][-1]) for r in rows])
