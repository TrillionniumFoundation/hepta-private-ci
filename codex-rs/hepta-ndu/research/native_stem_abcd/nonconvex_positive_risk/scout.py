import numpy as np
from scipy.optimize import brentq
G=.9
risk=[.5,1.]

def derivative(t):
 u=t-1
 total=0.
 for x in (-1,1):
  y=[risk[p]*(u*x/5+(1-2*p)/100) for p in (0,1)]
  A=[p/20+G/risk[p]*np.log(np.cosh(y[p])) for p in (0,1)]
  for p0 in (0,1):
   d=risk[p0]*(A[1]-A[0]);w=1/(1+np.exp(-d))
   total+= G*G*(2*u+x/5*((1-w)*np.tanh(y[0])+w*np.tanh(y[1])))/4
 return total+.5
root=brentq(derivative,.1,1.,xtol=2e-15)
s=np.sqrt(root)
print('t',format(root,'.17f'),'s',format(s,'.17f'),'D(0)',derivative(0), 'derivative final',derivative(s*s))
