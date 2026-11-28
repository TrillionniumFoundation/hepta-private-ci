"""Numerically reconstruct conditional first-passage, reset and causal filters independently."""
import json
from pathlib import Path
import numpy as np
from forecast import ROOT,Model,MODES,DT,EPS,put,sha
def independent(model,x,y,mode):
    m=model.s["reset"].copy();grid=model.s["grid"];centre=m@grid;reset=m.copy();last=E=L=0.;refr=False
    pts=[];maxmass=0.;minp=1.
    for current,observed in zip(x,y):
        u=np.tanh(current/100.);w=np.log1p(model.s["kappa"].item()*u)
        drift=.03355-.70*u+(last-w)/.25;mean=m@grid
        if mode in ("dual","equity"):drift+=.65*np.tanh(max(E,0))*(centre-mean)
        if mode in ("dual","loss"):drift-=.65*np.tanh(max(L,0))
        z=(drift+5.)*409.6;k=int(z);kernel=model.table[k]+(z-k)*(model.table[k+1]-model.table[k])
        movement=m@kernel;maxmass=max(maxmass,abs(movement.sum()-1.));minp=min(minp,float(movement.min()))
        hazard=0. if refr else movement[-1];pts.append(np.log(-np.log1p(-np.clip(hazard,EPS,1.-EPS))))
        if observed:refr=True;m=reset.copy();E=L=0.
        else:
            m=reset.copy() if refr else movement[:-1]/sum(movement[:-1]);refr=False
            E,L=m@(model.s["pmid"]+u*model.s["pd"])
        last=w
    return np.array(pts),maxmass,minp
def main():
    m=Model(ROOT/"source",ROOT/"law4.npz");x=np.sin(np.arange(250)*.14)*170.+35.;y=np.zeros(250,dtype=np.uint16);y[[12,43,44,80,193]]=1
    out={}
    for mode in MODES:
        c=m.features(mode,100,(0,0,x,y))[0][:,0];right,mass,low=independent(m,x,y,mode);delta=float(abs(c-right).max())
        assert delta<3e-8 and mass<2e-12 and low>=-1e-13
        changed=y.copy();changed[80]^=1;after=m.features(mode,100,(0,1,x,changed))[0][:,0];assert np.array_equal(c[:81],after[:81])
        out[mode]=dict(max_independent_log_hazard_error=delta,max_step_mass_error=mass,minimum_raw_transition_mass=low,exact_pre_event_prefix_bins=81)
    current=np.full(30,100.);events=np.zeros(len(current),dtype=np.uint16);events[12]=1
    pred=m.features("lif",15,(1,0,current,events))[0][:,0]
    expect=1.-np.exp(-.002*np.arange(1,14)/.015)
    assert np.max(abs(pred[:13]-expect))<1e-14 and pred[13]==0 and abs(pred[14]-(1-np.exp(-.002/.015)))<1e-14
    put(ROOT/"numeric_qualification.json",{"modes":out,"lif_analytic_max_error":float(abs(pred[:13]-expect).max()),"lif_reset_silent_bin":True,"kernel_max_row_error":float(abs(m.table.sum(-1)-1).max()),"physical_model_sha256":sha(ROOT/"physical.c")})
if __name__=="__main__":main()
