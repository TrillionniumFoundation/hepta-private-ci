"""Sharper input intervals for the imaginary-axis arithmetic."""
from pathlib import Path
import json
from mpmath import mp,iv
from halfline import Stationary
from enclose import Rigorous,Dual,enclosing_numbers

mp.dps=85
iv.dps=85
class High:
    number=staticmethod(mp.mpf)
    sqrt2pi=staticmethod(lambda:mp.sqrt(2*mp.pi))
    sqrt=staticmethod(mp.sqrt)
    exp=staticmethod(mp.exp)
    tanh=staticmethod(mp.tanh)
    phi=staticmethod(mp.ncdf)
    is_zero=staticmethod(lambda x:x==0)

def run():
    p=Stationary(High); v=Stationary(Rigorous)
    output=[]
    for x,y in ((.035,.04),(.14,.15),(.30,.32)):
        u=mp.findroot(lambda w:p.stationary(w)[0],(x,y))
        lo,hi=[mp.nstr(u+t*mp.mpf('1e-33'),55) for t in [-1,1]]
        left,right=[v.stationary(Dual(z))[0].v for z in (lo,hi)]
        if not ((left<0 and right>0) or (left>0 and right<0)):
            raise RuntimeError((left,right))
        output.append(dict(inward_drift=[lo,hi],left=enclosing_numbers(left),right=enclosing_numbers(right)))
    return output
if __name__=="__main__":
    out=run()
    Path(__file__).with_name("sharp_roots.json").write_text(json.dumps(out,indent=2)+"\n")
    print(out)
