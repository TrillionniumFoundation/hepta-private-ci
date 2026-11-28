"""Certified finite-gain branch enclosures for the coupled physical cascade."""
from pathlib import Path
import json
from mpmath import iv,mp
from halfline import Stationary
from sharp_roots import High
from enclose import Rigorous,Dual,enclosing_numbers
from port import drive

mp.dps=83;iv.dps=83

def numerics():
    h=Stationary(High)
    eps=mp.mpf('.025');a=mp.mpf('.3');d=mp.mpf('.25')
    R=lambda u:d*u/(a+d*u)
    v=lambda u:drive(eps*R(u),High)
    loops={}
    for name,br in (("low",(.034,.044)),("high",(.29,.34))):
        u=mp.findroot(lambda z:Stationary(High,drive=v(z)).stationary(z)[0],br)
        vs=v(u)
        y=mp.log(Stationary(High,drive=vs).B/h.B)
        vr=drive(y,High)
        loops["source_"+name]=u
        for rec,br2 in (("low",(.034,.045)),("high",(.29,.34))):
            loops["receiver_"+name+"_"+rec]=mp.findroot(lambda z:Stationary(High,drive=vr).stationary(z)[0],br2)
    return loops

def run():
    num=numerics()
    eps,a,d=[Dual(x) for x in ('.025','.30','.25')]
    nominal=Stationary(Rigorous)
    results={}
    def pkg(key,inp,drive_for,rad,rb=None):
        es=[mp.nstr(inp+t*mp.mpf(rad),56) for t in (-1,1)]
        uv=Dual(iv.mpf(es))
        v=drive_for(uv)
        def S(z):
            t=Dual(z)
            return Stationary(Rigorous,drive=drive_for(t)).stationary(t)[0].v
        rl=S(es[0]);rh=S(es[1])
        if not (rl<0 and rh>0):raise ArithmeticError((key,rl,rh))
        vv=[iv.nstr(v.v.a,75).split(',')[0][1:],iv.nstr(v.v.b,75).split(',')[-1][:-1].strip()]
        # Include an explicit decimal guard against rounding during serialization.
        vstr=[mp.nstr(mp.mpf(vv[0])-mp.mpf('1e-70'),75),mp.nstr(mp.mpf(vv[1])+mp.mpf('1e-70'),75)]
        results[key]=dict(u=es,v=vstr,left=enclosing_numbers(rl),right=enclosing_numbers(rh),
                          source_feedback=key.startswith("source"),finite_epsilon=".025")
        return uv,v
    for name in ("low","high"):
        tag="source_"+name
        def vs(u):return drive(eps*d*u/(a+d*u),Rigorous)
        u,v=pkg(tag,num[tag],vs,'1e-33')
        y=Dual(iv.log((Stationary(Rigorous,drive=v).B/nominal.B).v))
        vr=drive(y,Rigorous)
        for rec in ("low","high"):
            tag="receiver_"+name+"_"+rec
            pkg(tag,num[tag],lambda u:vr,'1e-29')
    return results

if __name__=="__main__":
    result=run()
    Path(__file__).with_name("operating_points.json").write_text(json.dumps(result,indent=2)+"\n")
    print([(k,v["u"][0]) for k,v in result.items()])
