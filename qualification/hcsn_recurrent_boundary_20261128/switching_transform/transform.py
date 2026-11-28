"""Piecewise Laplace-domain solution of two-wall first arrival and bond pricing."""
from dataclasses import dataclass
from math import comb
import numpy as np
from scipy.linalg import expm


@dataclass
class Law:
    barriers: tuple = (73.30893, 73.89588)
    rates: tuple = (.7, .35)
    premia: tuple = (.01, .05)
    r: float = .08
    payout: float = .02
    sigma: float = .23
    coupon: float = 6.39
    principal: float = 61.68
    maturity: float = 1.
    recovery: float = .60

    def solve(self, s, V, mode):
        """Return Laplace transform for both current regimes. Barrier order is explicit."""
        if np.real(s)<=0:raise ValueError("Laplace contour requires positive real part")
        if mode not in ("first_hit","bond"):raise ValueError("Unknown payoff")
        if min(self.barriers)<=0 or V<=0:raise ValueError("Assets and barriers must be positive")
        order=np.argsort(self.barriers,kind="stable")
        wall=np.asarray(self.barriers)[order]
        jump=np.asarray(self.rates)[order]
        rates=np.asarray(self.premia)[order]+self.r if mode=="bond" else np.zeros(2)
        force=np.full(2,self.principal/self.maturity+self.coupon/(self.maturity*s) if mode=="bond" else 0.,dtype=complex)
        constant=0. if mode=="bond" else 1/s
        recovery=self.recovery/(self.maturity*s) if mode=="bond" else 0.
        boundary=lambda value:constant+recovery*value
        x=np.log(V/wall[0]); strip=np.log(wall[1]/wall[0])
        if x<=0:return np.full(2,boundary(V),dtype=complex)
        D=self.sigma**2/2; mu=self.r-self.payout-D
        I=np.eye(2)
        M=np.diag(s+rates+jump)-np.array([[0,jump[0]],[jump[1],0]])
        far=np.linalg.solve(M,force)
        # For this contour, both eigenvalues have positive real part.
        H=mu**2*I+4*D*M
        det_root=np.sqrt(np.linalg.det(H))
        sqrt_H=(H+det_root*I)/np.sqrt(np.trace(H)+2*det_root)
        K=(-mu*I-sqrt_H)/(2*D)
        g=boundary(wall[1])
        if strip==0:
            u=far+expm(K*x)@(np.full(2,g)-far)
            return u[np.argsort(order)]
        kappa=s+rates[0]+jump[0]
        root=np.sqrt(mu**2+4*D*kappa)
        pos=(-mu+root)/(2*D); neg=(-mu-root)/(2*D)
        # Each exponential is anchored at the end where its magnitude is largest.
        def particular(z):
            return (force[0]+jump[0]*constant)/kappa+jump[0]*recovery*wall[0]*np.exp(z)/(kappa-mu-D)
        dv=jump[0]*recovery*wall[1]/(kappa-mu-D)
        left=np.exp(-pos*strip);right=np.exp(neg*strip)
        kh=K[0,0]
        factors=np.array([[left,1],[pos-kh,(neg-kh)*right]])
        targets=[boundary(wall[0])-particular(0),
                 kh*(particular(strip)-far[0])+K[0,1]*(g-far[1])-dv]
        A,B=np.linalg.solve(factors,targets)
        lower=lambda z:particular(z)+A*np.exp(pos*(z-strip))+B*np.exp(neg*z)
        if x<strip:
            result=np.array([lower(x),boundary(V)])
        else:
            result=far+expm(K*(x-strip))@(np.array([lower(strip),g])-far)
        return result[np.argsort(order)]

    def value(self,V,t,mode,*,width=18.4,terms=32,smooth=30):
        """Euler-average the Bromwich Fourier series; fixed real weights for AD."""
        if t<=0:raise ValueError("Positive time required")
        sequence=[]
        acc=np.real(self.solve(width/(2*t),V,mode))/2
        for k in range(1,terms+smooth+1):
            s=(width/2+1j*np.pi*k)/t
            acc=acc+(-1)**k*np.real(self.solve(s,V,mode))
            if k>=terms:sequence.append(acc.copy())
        weights=np.array([comb(smooth,j)/2**smooth for j in range(smooth+1)])
        output=np.exp(width/2)/t*(weights@np.asarray(sequence))
        stopped=V<=np.asarray(self.barriers)
        return np.where(stopped,self.recovery*V/self.maturity if mode=="bond" else 1.,output)
