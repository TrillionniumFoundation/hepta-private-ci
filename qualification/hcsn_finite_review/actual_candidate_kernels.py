"""Read-only finite kernels bound to a supplied graded model and actual lift.

This does not run JointModel's DDE solver. It independently evaluates the SAME
generator's single-hit finite transforms at T<=delay, with source-row lift
weights supplied by the actual migration adapter. Continuum references remain
separate in audit_short_gap.continuum_basis. Callers must pin all imported
source bytes and report this distinct scope.
"""

import math

import numpy as np
from scipy.linalg import eigh_tridiagonal

from audit_short_gap import NodalKernels


class ActualCandidateFiniteKernels(NodalKernels):
    """Reuse phase-convolution algebra with actual model geometry and lift."""

    def __init__(self, model, lift_weights):
        self.nodes=np.asarray(model.spatial.nodes,dtype=np.float64).copy()
        self.q=float(model.discount)
        self.delay=float(model.delay)
        self.reset=float(model.reset)
        self.weights=np.asarray(lift_weights,dtype=np.float64).copy()
        if (self.nodes.ndim!=1 or len(self.nodes)<5 or self.nodes[0]!=0
                or not np.isfinite(self.nodes).all() or np.any(np.diff(self.nodes)<=0)
                or self.weights.shape!=(17,len(self.nodes))
                or not np.isfinite(self.weights).all() or self.weights.min()<0
                or np.any(self.weights[:,0]!=0)
                or np.max(abs(self.weights.sum(1)-1))>2e-13
                or not 0<self.q<=4 or not 0<self.delay<=2
                or not self.nodes[1]<=self.reset<=self.nodes[-2]):
            raise ValueError('validated actual graded model and zero-lower conservative lift required')
        self.down,self.up=(np.asarray(v,dtype=float).copy() for v in model.spatial.rates)
        n=len(self.nodes)-1
        if (self.down.shape!=(n-1,) or self.up.shape!=(n-1,)
                or not np.isfinite(self.down).all() or not np.isfinite(self.up).all()
                or min(self.down.min(),self.up.min())<=0):
            raise ValueError('positive actual birth/death rates required')
        reconstructed=np.zeros((n+1,n+1));i=np.arange(1,n)
        reconstructed[i,i-1]=self.down;reconstructed[i,i+1]=self.up
        reconstructed[i,i]=-(self.down+self.up)
        if not np.array_equal(reconstructed,np.asarray(model.spatial.matrix())):
            raise ValueError('actual matrix disagrees with supplied rates')
        transient,lower,upper,reset=model.ingredients()
        if (not np.array_equal(transient,reconstructed[1:-1,1:-1])
                or not np.array_equal(lower,reconstructed[1:-1,0])
                or not np.array_equal(upper,reconstructed[1:-1,-1])):
            raise ValueError('actual flow ingredients disagree with spatial generator')
        left=min(int(np.searchsorted(self.nodes,self.reset,side='right'))-1,n-1)
        fraction=(self.reset-self.nodes[left])/(self.nodes[left+1]-self.nodes[left])
        expected_reset=np.zeros(n+1);expected_reset[left]=1-fraction;expected_reset[left+1]=fraction
        if not np.array_equal(reset,expected_reset[1:-1]):
            raise ValueError('actual reset law differs from declared nodal interpolation')
        self.d=np.exp(np.r_[0.,np.cumsum(.5*np.log(self.up[:-1]/self.down[1:]))])
        if not np.isfinite(self.d).all() or self.d.min()<=0:
            raise ArithmeticError('unresolved reversible scaling')
        self.eigen,self.v=eigh_tridiagonal(-(self.down+self.up),np.sqrt(self.up[:-1]*self.down[1:]))
        if self.eigen.max()>=0:raise ArithmeticError('unresolved transient spectrum')
        forcing=np.zeros(n-1);forcing[0]=self.down[0]
        self.coefficient=self.v.T@(self.d*forcing);self.cache={}

    def at(self,t):
        if isinstance(t,(bool,np.bool_)) or not math.isfinite(t) or not 0<=t<=self.delay:
            raise ValueError('single-hit kernels require time in [0,delay]')
        key=round(float(t),14)
        if key not in self.cache:
            rate=self.eigen;z=rate*key
            f=np.r_[1.,(self.v@(self.coefficient*(-np.expm1(z)/(-rate))))/self.d,0.]
            qrate=rate-self.q
            g=np.r_[1.,(self.v@(self.coefficient*(-np.expm1(qrate*key)/(-qrate))))/self.d,0.]
            series=.5+z/6+z*z/24+z**3/120+z**4/720
            gain=np.where(abs(z)<1e-3,key*key*series,(np.expm1(z)-z)/(rate*rate))
            j=np.r_[key,(self.v@(self.coefficient*gain))/self.d,0.]
            a=-math.expm1(-self.q*key)/self.q-(g-math.exp(-self.q*key)*f)/self.q
            a[0]=0.
            if not all(np.isfinite(x).all() for x in (f,g,a,j)):
                raise ArithmeticError('nonfinite finite kernels')
            self.cache[key]=(f,g,a,j)
        return self.cache[key]

    def basis(self,t,reset=None,delay=None):
        """Return original 16 uniform + tail + 8 phase law M/H/A coefficients.

        Optional reset/delay support caching the same fixed generator/lift
        across original physical boundary snapshots. They must come from the
        caller's independently validated candidate model identities.
        """
        reset=self.reset if reset is None else float(reset)
        delay=self.delay if delay is None else float(delay)
        if (delay!=self.delay or not self.nodes[1]<=reset<=self.nodes[-2]
                or not 0<=t<=delay):
            raise ValueError('matching delay and interior reset required')
        return super().basis(t,reset,delay)
