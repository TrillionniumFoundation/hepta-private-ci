"""Interval enclosure, uniqueness and global verification inequalities at the registered law."""
import json
from pathlib import Path
from flint import arb as R,arb_mat as M,ctx

def evaluate(b0,b1):
    r,d,sig,c0,c1,u,w=map(R,['.08','.02','.23','.04','.08','.12','.16'])
    drift=r-d-sig**2/2
    def exponents(q):
        rad=(drift**2+2*sig**2*q).sqrt()
        return [(-drift+rad)/sig**2,(-drift-rad)/sig**2]
    n=exponents(r+u);h=[exponents(r)[1],exponents(r+u+w)[1]]
    assert n[0]>1 and n[1]<0 and h[1]<h[0]<0
    slope=d/(d+u);cost=c0/(r+u);ratio=-u/w
    c_low=((r+w)*c0+u*c1)/(r*(r+u+w))
    c_high=(w*c0+(r+u)*c1)/(r*(r+u+w))
    m0=(-slope*b0-n[1]*(cost-slope*b0))/(n[0]-n[1])
    m=[m0,cost-slope*b0-m0]
    dm0=slope*(n[1]-1)/(n[0]-n[1]);dm=[dm0,-slope-dm0]
    D=(-b1-h[0]*(c_high-b1))/(h[1]-h[0])
    C=c_high-b1-D
    dD=(h[0]-1)/(h[1]-h[0]);dC=-1-dD
    zz=[(n_i*(b1/b0).log()).exp() for n_i in n]
    f=[];rows=[]
    for k in [0,1]:
        f.append(slope*b1-(cost if k==0 else 0)+sum(mi*zi*ni**k for mi,zi,ni in zip(m,zz,n))
                 -(b1-(c_low if k==0 else 0)+C*h[0]**k+ratio*D*h[1]**k))
        db0=sum((di-mi*ni/b0)*zi*ni**k for di,mi,ni,zi in zip(dm,m,n,zz))
        db1=slope-1+sum(mi*zi*ni**(k+1)/b1 for mi,zi,ni in zip(m,zz,n))-dC*h[0]**k-ratio*dD*h[1]**k
        rows.append([db0,db1])
    first=C*h[0]*(h[0]-1);extra=D*h[1]*(h[1]-1)
    e0b1=b1-c_low+C+ratio*D
    signs={'positive_middle0':m[0],'positive_middle1':m[1],'positive_slow_upper_curvature':first,
           'positive_dear_fast_upper_curvature':extra,'positive_cheap_upper_curvature_lower_coefficient':first+ratio*extra,
           'cheap_stop_slack':c0-d*b0,'dear_stop_slack':c1-d*b1-w*e0b1}
    return M([[x] for x in f]),M(rows),signs
def main():
    ctx.prec=256
    v=[R('0.4337188019559966'),R('0.5757069099885856')]
    rad=R('1e-11');box=[R(x,rad) for x in v];center=M([[x] for x in v])
    f0,j0,_=evaluate(*v);_,jb,signs=evaluate(*box)
    inv=j0.inv();inv=M([[inv[i,j].mid() for j in range(2)] for i in range(2)])
    ident=M([[1,0],[0,1]])
    op=ident-inv*jb
    upper=max(sum(abs(op[i,j]) for j in range(2)) for i in range(2))
    bounds=center-inv*f0+op*M([[R(0,rad)] for _ in v])
    assert upper<R(1)
    assert all(abs(bounds[i,0]-v[i])<rad for i in range(2))
    assert all(z>0 for z in signs.values())
    report={'bits':ctx.prec,'starting_box_radius':rad.str(12),'certified_bounds':[bounds[i,0].str(24) for i in range(2)],
            'contraction_upper':upper.str(24),'positive_global_verification_quantities':{k:x.str(20) for k,x in signs.items()}}
    Path(__file__).with_name('certificate.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report)
if __name__=='__main__':main()
