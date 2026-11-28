"""Can the sender's boundary alone distinguish earlier inputs under identical current stimulation?"""
import json
import math
from pathlib import Path
import torch
from population import BoundaryPopulation


def layer(gains,coupling):
    n=BoundaryPopulation(1,1,24,probe_horizons=(),cache_prices=True,initial_physical_gain=.70,
                         boundary_path="linear_log",signed_force_gains=gains,initial_flow_coupling=coupling)
    with torch.no_grad():
        n.sender.weight.fill_(1.);n.sender.bias.zero_();n.recurrent.weight.zero_()
    return n


def run():
    torch.set_num_threads(1);dtype=torch.float64
    signal=torch.tensor([[-.995],[.995]],dtype=dtype).atanh()
    common=torch.tensor([[-.3],[-.3]],dtype=dtype).atanh()
    report={}
    for coefficient in (0.,.1,.3):
        sender=layer((.02,3.),coefficient);receiver=layer((.65,.65),None)
        with torch.no_grad():
            b1=sender._price_basis();b2=receiver._price_basis()
            state=sender.initial(2);rx=receiver.initial(2);received=[];states=[]
            for step in range(1600):
                tx,state=sender.step(signal if step<700 else common,state,b1)
                if step>=1500:
                    out,rx=receiver.step(tx[:,:,0],rx,b2)
                    received.append(out[:,:,0:2].squeeze(1).tolist())
                    states.append(tx[:,:,0:2].squeeze(1).tolist())
        first=torch.tensor(states,dtype=dtype);second=torch.tensor(received,dtype=dtype)
        fb=(first[-1,1]-first[-1,0]).tolist();sb=(second[-1,1]-second[-1,0]).tolist()
        if coefficient==0.:
            assert fb[0]==0 and fb[1]>.1 and (second[:,0]-second[:,1]).abs().max().item()<1e-12
        report[str(coefficient)]=dict(sender_difference=fb,receiver_difference=sb,sender_probe=states,receiver_probe=received)
    sender=layer((.02,3.),.1)
    trace=torch.cat([signal.unsqueeze(0).repeat(7,1,1),common.unsqueeze(0).repeat(9,1,1)])
    def objective():
        out,_=sender(trace)
        return out[-1,1,0,0]-out[-1,0,0,0]
    exact=torch.autograd.grad(objective(),sender.flow_coupling)[0].item()
    with torch.no_grad():
        saved=sender.flow_coupling.item();sender.flow_coupling.fill_(saved+1e-5);hi=objective().item()
        sender.flow_coupling.fill_(saved-1e-5);lo=objective().item();sender.flow_coupling.fill_(saved)
    fd=(hi-lo)/2e-5
    if abs(exact-fd)>1e-8 or abs(exact)<1e-8:raise ValueError((exact,fd))
    report["d_boundary_d_coupling"]=dict(autograd=exact,finite_difference=fd)
    return report
if __name__=="__main__":
    r=run();Path(__file__).with_name("boundary_memory.json").write_text(json.dumps(r,separators=(",",":"))+"\n")
    for k,v in r.items():print(k,{a:b for a,b in v.items() if not a.endswith("_probe")},flush=True)
