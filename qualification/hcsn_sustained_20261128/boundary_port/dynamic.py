"""Independent signed-population amplitude/phase and finite pulse replay."""
import argparse
import ctypes
from dataclasses import replace
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

from port import port_gain
from frequency_transfer import Cascade


def pair(v):return [float(np.real(v)),float(np.imag(v))]


def main(ref,library):
    sys.path.insert(0,str(ref.parent))
    from closed_form import Contract,Prices
    proc=ctypes.CDLL(str(library))
    arr=np.ctypeslib.ndpointer(dtype=np.float64,flags=("C_CONTIGUOUS",))
    proc.response.argtypes=([ctypes.c_int]*3+[ctypes.c_double]*10+[arr]*5)
    proc.response.restype=None
    q0,q1=[Prices(replace(Contract(),principal=61.68*(1+.28*v))) for v in (-.9,-.7)]
    bprime=(q1.boundary-q0.boundary)/.2
    ep=.025;gain=1.
    models=[Cascade(ep,gain,b) for b in ("low","high")]
    states=[port_gain(ep,gain,b,"high") for b in ("low","high")]
    ur=port_gain(0,0,"high","high")["receiver_u"]
    output=[]
    for dx,dt,edge in ((.03,.0125,9.),(.015,.00625,9.),(.0075,.00625,9.)):
        n=round(edge/dx)-1
        x=np.arange(1,n+1)*dx
        e0=np.array([q0.equity(t)/20 for t in x]);l0=np.array([q0.credit_loss(t)/20 for t in x])
        e1=(np.array([q1.equity(t)/20 for t in x])-e0)/.2
        l1=(np.array([q1.credit_loss(t)/20 for t in x])-l0)/.2
        for mode,period in (("tone",16.),("tone",6.),("pulse",4.)):
            omega=2*np.pi/period
            rows=[]
            amp=.025
            stop=8*period if mode=="tone" else 100.
            count=round(stop/dt)
            for branch,state in zip(("low","high"),states):
                runs=[]
                for signed in (amp,-amp):
                    values=np.empty((count,6))
                    proc.response(n,count,int(mode=="pulse"),period,dx,dt,ep,gain,signed,state["u"],ur,q0.boundary,bprime,
                                  e0,e1,l0,l1,values)
                    runs.append(values)
                rows.append((runs[0]-runs[1])/(2*amp))
            t=values[:,0]
            contrast=(rows[1]-rows[0])[:,[1,3]]
            source_max_escape=[]
            i=(1j*omega if mode=="tone" else 0)
            def analytic(**kwargs):
                high=np.array(models[1].transfer(i,**kwargs))
                low=np.array(models[0].transfer(i,**kwargs))
                return high-low
            truth=analytic()
            if mode=="tone":
                keep=t>4*period
                measured=2*(np.exp(-1j*omega*t[keep])[:,None]*contrast[keep]).mean(axis=0)
            else:
                measured=dt*contrast.sum(axis=0)/4
            report=dict(dx=dx,dt=dt,edge=edge,type=mode,period=period,amplitude=amp,
                theoretical=[pair(z) for z in truth],measured=[pair(z) for z in measured],
                relative_errors=(abs(measured-truth)/abs(truth)).tolist(),
                removing_physical_wall_velocity=[pair(z) for z in analytic(moving=False)],
                removing_source_feedback=[pair(z) for z in analytic(active=False)])
            if mode=="pulse":
                report["centered_pulse_samples"]={str(s):contrast[round(s/dt)-1].tolist() for s in [18,20,21,22,24,25,27,30,40,60,100]}
            output.append(report)
            print(dx,mode,period,report["relative_errors"],flush=True)
    fine=[r for r in output if r["dx"]==.0075]
    if max(max(r["relative_errors"]) for r in fine)>.08:
        raise ArithmeticError(fine)
    return dict(epsilon=ep,kappa=gain,observable_order=["true_sender_log_boundary","full_receiver_firing_rate"],
                centered_branches="high minus low source, identical upper-branch receiver start and zero port filter",
                units="derivative with respect to g(t), multiplicative refractory-to-source actuation at g=1",rows=output)

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("reference",type=Path)
    z=a.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        library=Path(temp)/"propagate.so"
        subprocess.run(["cc","-std=c11","-O3","-shared","-fPIC",str(Path(__file__).with_name("propagate.c")),"-lm","-o",str(library)],check=True)
        result=main(z.reference,library)
    Path(__file__).with_name("dynamic.json").write_text(json.dumps(result,indent=2)+"\n")
