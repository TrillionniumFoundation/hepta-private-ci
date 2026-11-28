"""Torch equity resolvent with an implicit backward pass for the financial boundary."""
from math import comb
import torch
from equity import EquityTransform
from transform import Law


def equity_and_slopes(assets,walls,jumps,premia,*,sigma=.23,r=.08,payout=.02,
                      coupon=6.39,principal=61.68,maturity=1.,recovery=.6,tax=.27):
    """Return the two equity values at each asset and both log-asset contact slopes.

    The spectral splitting here assumes a distinct eigenvalue pair for each regime
    matrix. Both positive switching rates ensure this for real discounts.
    """
    if (walls<=0).any() or (assets<=0).any() or (jumps<=0).any():
        raise ValueError("Positive assets, ordered nonzero walls and positive switching rates required")
    order=torch.argsort(walls);inverse=torch.argsort(order)
    w=walls[order];jump=jumps[order];q=r+premia[order]
    device=w.device;dtype=w.dtype
    width=22.;N=29;M=24
    k=torch.arange(N+M+1,device=device,dtype=dtype)
    s=torch.complex(torch.full_like(k,width/2),torch.pi*k)/maturity
    smooth=[comb(M,j)/2**M for j in range(M+1)]
    euler=torch.tensor([.5]+[1.]*N+[sum(smooth[j:]) for j in range(1,M+1)],device=device,dtype=dtype)
    weight=euler*(-1.)**k*torch.exp(torch.as_tensor(width/2,device=device,dtype=dtype))/maturity
    I=torch.eye(2,device=device,dtype=dtype)
    D=sigma**2/2;mu=r-payout-D
    Q=torch.stack((torch.stack((-jump[0],jump[0])),torch.stack((jump[1],-jump[1]))))
    def spectral(A):
        gap=torch.sqrt((A[0,0]-A[1,1])**2+4*A[0,1]*A[1,0])
        lo=(torch.trace(A)-gap)/2;hi=lo+gap
        P=(hi*I-A)/gap
        return torch.stack((lo,hi)),torch.stack((P,I-P)).to(s.dtype)
    er,projE=spectral(r*I-Q);br,projB=spectral(torch.diag(q)-Q)
    a=jump[0];h=torch.log(w[1]/w[0]);kap=s+q[0]+a
    er=er.to(s.dtype);br=br.to(s.dtype)
    bval=s[:,None]+br;epow=(-mu-torch.sqrt(mu**2+4*D*er))/(2*D)
    bpow=(-mu-torch.sqrt(mu**2+4*D*bval))/(2*D)
    K=torch.einsum("j,jab->ab",epow,projE)
    Kb=torch.einsum("fj,jab->fab",bpow,projB)
    par=principal/maturity;costs=(1-tax)*coupon+par
    ones=torch.ones(2,dtype=s.dtype,device=device)
    far=(par+coupon/(maturity*s))[:,None]*torch.einsum("fj,jab,b->fa",1/bval,projB,ones)
    rec=recovery/(maturity*s)
    def power_pair(kappa):
        root=torch.sqrt(mu**2+4*D*kappa)
        return (-mu+root)/(2*D),(-mu-root)/(2*D)
    pb,nb=power_pair(kap)
    bl=torch.exp(-pb*h);bw=torch.exp(nb*h)
    bc=(par+coupon/(maturity*s))/kap;bv=a*rec/(kap-mu-D)
    def solve_pair(l,b,minus,plus,goal0,goal1):
        A=(goal1-minus*goal0)/(plus-minus*l)
        return A,goal0-l*A
    Ab,Bb=solve_pair(bl,bw,(nb-Kb[:,0,0])*bw,pb-Kb[:,0,0],
                     rec*w[0]-bc-bv*w[0],Kb[:,0,0]*(bc+bv*w[1]-far[:,0])
                     +Kb[:,0,1]*(rec*w[1]-far[:,1])-bv*w[1])
    btop=torch.stack((bc+bv*w[1]+Ab+Bb*bw,rec*w[1]),dim=-1)
    bcoef=torch.einsum("jab,fb->fja",projB,btop-far)
    const=torch.einsum("j,jab,fb->fa",1/er,projE,far-costs/s[:,None])
    geo=torch.einsum("fjk,kab,fjb->fja",1/(er[None,None,:]-bval[:,:,None]),projE,bcoef)
    po=w[1]/s[:,None]+const+geo.sum(1)
    dpo=w[1]/s[:,None]+(bpow[:,:,None]*geo).sum(1)
    pe,ne=power_pair(r+a)
    el=torch.exp(-pe*h);ew=torch.exp(ne*h)
    ec=(bc-costs/s)/(r+a);ev=(payout/s+bv)/(r+a-mu-D)
    Aj=Ab/(r-q[0]-s);Bj=Bb/(r-q[0]-s)
    e0=ec+ev*w[0]+Aj*bl+Bj
    de0=ev*w[0]+pb*Aj*bl+nb*Bj
    eh=ec+ev*w[1]+Aj+Bj*bw
    deh=ev*w[1]+pb*Aj+nb*Bj*bw
    Ae,Be=solve_pair(el,ew,(ne-K[0,0])*ew,pe-K[0,0],-e0,
                     dpo[:,0]+K[0,0]*(eh-po[:,0])-K[0,1]*po[:,1]-deh)
    top=torch.stack((eh+Ae+Be*ew,torch.zeros_like(Ae)),dim=-1)
    delta=dpo+torch.einsum("ab,fb->fa",K,top-po)
    slopes=weight@torch.stack((de0+pe*Ae*el+ne*Be,delta[:,1]),dim=-1).real
    x=torch.log(assets.reshape(-1)/w[0])
    z=torch.minimum(torch.clamp_min(x,0.),h)[:,None]
    lower=ec+ev*w[0]*torch.exp(z)+Aj*torch.exp(pb*(z-h))+Bj*torch.exp(nb*z)+Ae*torch.exp(pe*(z-h))+Be*torch.exp(ne*z)
    below=torch.stack((lower,torch.zeros_like(lower)),dim=-1)
    above=torch.clamp_min(x-h,0.)
    outer=w[1]*torch.exp(above)[:,None,None]/s[None,:,None]+const+torch.einsum(
        "xfj,fja->xfa",torch.exp(bpow*above[:,None,None]),geo)
    corr=torch.einsum("xj,jab,fb->xfa",torch.exp(epow*above[:,None]),projE,top-po)
    both=torch.where((x>h)[:,None,None],outer+corr,torch.where((x>0)[:,None,None],below,0.))
    price=torch.einsum("f,xfa->xa",weight,both.real)
    return price[:,inverse],slopes[inverse]


class EndogenousWalls(torch.autograd.Function):
    @staticmethod
    def forward(ctx,jumps,premia):
        law=Law(rates=tuple(jumps.detach().cpu().tolist()),premia=tuple(premia.detach().cpu().tolist()))
        walls=torch.as_tensor(EquityTransform(law).barriers(),device=jumps.device,dtype=jumps.dtype)
        ctx.save_for_backward(walls,jumps,premia)
        return walls

    @staticmethod
    def backward(ctx,output_gradient):
        walls,jumps,premia=ctx.saved_tensors
        with torch.enable_grad():
            w=walls.detach().requires_grad_()
            j=jumps.detach().requires_grad_()
            p=premia.detach().requires_grad_()
            def slopes(w,j,p):
                return equity_and_slopes(w[:1],w,j,p)[1]
            J,Jj,Jp=torch.autograd.functional.jacobian(slopes,(w,j,p))
            dual=torch.linalg.solve(J.T,output_gradient)
        return -Jj.T@dual,-Jp.T@dual
