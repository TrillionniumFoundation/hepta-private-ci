"""110-dps independently evaluated same reflection formula; diagnostic not interval proof."""
import math
from decimal import Decimal
import mpmath as mp
mp.mp.dps=110
r=mp.mpf(.007595780582070804)
d=mp.mpf(3.5072936797757205e-07)
s=mp.mpf(1.8581469732429565)
hazard=mp.mpf(1.158839083935111e-13)
t=mp.mpf(2.2216211523554883e-08)
asset=mp.mpf(1.000000000000002)
barrier=mp.mpf(1.0)
x=mp.log(asset/barrier)
a=(r-d-mp.mpf('.5')*s*s)/(s*s)
z=mp.sqrt(a*a+2*(r+hazard)/(s*s))
u=s*mp.sqrt(t)
Phi=lambda x:mp.erfc(-x/mp.sqrt(2))/2
F=Phi((-x-a*u*u)/u)+mp.exp(-2*a*x)*Phi((-x+a*u*u)/u)
G=mp.exp((-a+z)*x)*Phi((-x-z*u*u)/u)+mp.exp((-a-z)*x)*Phi((-x+z*u*u)/u)
print('mpmath dps',mp.mp.dps)
print('F',mp.nstr(F,70))
print('G',mp.nstr(G,70))
print('F-G',mp.nstr(F-G,55))
assert 0<G<F<1
