"""Write from one shared reset with a rectangular current, then read only the wall."""
import argparse
import ctypes
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
from port import port_gain


class Simulator:
    def __init__(self,reference,lib,dx,dt,edge):
        sys.path.insert(0,str(reference.parent))
        from closed_form import Contract,Prices
        self.dx,self.dt=dx,dt
        self.n=round(edge/dx)-1
        x=dx*np.arange(1,self.n+1)
        self.proc=ctypes.CDLL(str(lib))
        arr=np.ctypeslib.ndpointer(dtype=np.float64,flags=("C_CONTIGUOUS",))
        self.proc.condition.argtypes=[ctypes.c_int]*2+[ctypes.c_double]*10+[arr]*5
        self.proc.condition.restype=None
        q0,q1=[Prices(replace(Contract(),principal=61.68*(1+.28*v))) for v in (-.9,-.7)]
        self.base=q0.boundary;self.bslope=(q1.boundary-q0.boundary)/.2
        e0=np.array([q0.equity(t)/20 for t in x]);l0=np.array([q0.credit_loss(t)/20 for t in x])
        e1=(np.array([q1.equity(t)/20 for t in x])-e0)/.2
        l1=(np.array([q1.credit_loss(t)/20 for t in x])-l0)/.2
        self.tables=(e0,e1,l0,l1)
        self.recv=port_gain(0,0,"high","high")["receiver_u"]

    def run(self,amp,duration,stop,read,eps=.025,gain=1):
        count=round(stop/self.dt);raw=np.empty((count,6))
        self.proc.condition(self.n,count,self.dx,self.dt,eps,gain,amp,duration,read,self.recv,
                            self.base,self.bslope,*self.tables,raw)
        return raw


def main(ref,lib,action):
    if action=="explore":
        sim=Simulator(ref,lib,.03,.025,12.)
        rows=[]
        for duration in (5.,15.,30.):
            for amp in (-.6,-.30,-.12,-.05,0.,.05,.12,.20,.30,.5):
                z=sim.run(amp,duration,200,150)[-1]
                rows.append(dict(duration=duration,amplitude=amp,log_wall=float(z[1]),source_rate=float(z[2]),
                                 receiver_rate=float(z[3]),source_exit_mass=float(z[4])))
                print(duration,amp,*np.round(z[1:5],8),flush=True)
        Path(__file__).with_name("conditioning_exploration.json").write_text(json.dumps(dict(dx=.03,dt=.025,edge=12.,
            measured_at=200.,read_from=150.,rows=rows),indent=2)+"\n")
        return
    # The final independent comparison uses the chosen amplitudes unchanged
    # under progressively finer spatial resolution and a larger exit distance.
    expected=[port_gain(.025,1.,b,"high") for b in ("low","high")]
    output=[]
    for dx,dt,edge in ((.03,.025,12.),(.015,.0125,12.),(.0075,.00625,12.),(.0075,.00625,15.),(.00375,.00625,15.)):
        sim=Simulator(ref,lib,dx,dt,edge)
        currents=[.12,-.12]
        candidates=[sim.run(q,5.,220.,170.) for q in currents]
        low,high=candidates
        gap=high-low
        pre=round(170/dt)
        if np.max(abs(gap[:pre,3]))!=0: raise ArithmeticError("receiver side channel before the gate")
        late=gap[round(215/dt):]
        times=[5,10,20,40,80,150,170,171,175,185,200,220]
        output.append(dict(dx=dx,dt=dt,open_edge=edge,pulse_amps=currents,
            expected_steady_source_rates=[q["rate"] for q in expected],
            expected_steady_receiver_rates=[q["receiver_rate"] for q in expected],
            sampled={str(t):dict(source_rate=[float(z[round(t/dt)-1,2]) for z in candidates],
                true_boundary_contrast=float(gap[round(t/dt)-1,1]),
                receiver_rate_contrast=float(gap[round(t/dt)-1,3])) for t in times},
            last_source_rates=[float(z[-1,2]) for z in candidates],
            last_receiver_rates=[float(z[-1,3]) for z in candidates],
            last_contrast=float(gap[-1,3]),last_5_receiver_span=float(np.ptp(late[:,3])),
            cumulative_upper_escape=[z[-1,4:].tolist() for z in candidates],
            pre_read_receiver_difference=float(np.max(abs(gap[:pre,3])))))
        print(dx,edge,output[-1]["last_source_rates"],gap[-1,1:4],flush=True)
    fine=output[-1]
    if max(abs(x-y) for x,y in zip(fine["last_source_rates"],fine["expected_steady_source_rates"]))>.0025:
        raise ArithmeticError(fine)
    if abs(fine["last_contrast"]-(expected[1]["receiver_rate"]-expected[0]["receiver_rate"]))>3e-6:
        raise ArithmeticError(fine)
    d=dict(initial_source="all active mass at x=0.30, empty queue, z=0",
           source_eps=.025,receiver_initial="identical high parent, empty port filter",
           current_duration=5.,read_from=170.,all_external_current_zero_after=5.,
           grids=output,exploratory_amplitude_and_duration_scan=True)
    Path(__file__).with_name("conditioning.json").write_text(json.dumps(d,indent=2)+"\n")

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("reference",type=Path);a.add_argument("action")
    z=a.parse_args()
    with tempfile.TemporaryDirectory() as td:
        lib=Path(td)/"cell.so"
        subprocess.run(["cc","-O3","-std=c11","-shared","-fPIC",str(Path(__file__).with_name("propagate.c")),"-lm","-o",str(lib)],check=True)
        main(z.reference,lib,z.action)
