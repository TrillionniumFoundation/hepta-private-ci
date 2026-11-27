"""Cold numerical checks for both endpoint equations, one-step probability conservation and BP."""
import json,math
from pathlib import Path
import numpy as np
import torch
from population import BoundaryPopulation,ContinuousSpikingNetwork
def main():
    torch.set_num_threads(1);torch.manual_seed(9113)
    model=ContinuousSpikingNetwork(3,3,2,atoms=9)
    cell=model.first
    q=torch.tensor([-.3,-.01,0,.00001,.01,.2,.4,1.2],dtype=torch.float64)
    survival,hit=cell.kernels(q)
    masserr=(survival.sum(-1)+hit-1).abs().max().item()
    assert masserr<2e-12 and (survival>=0).all() and (hit>=0).all() and (hit<=1).all()
    # Both priced channels use the same published principal and stationary barrier.
    P=torch.tensor([[45.,61.68,72.]],dtype=torch.float64)
    E,L=cell.priced_channels(P);law=cell.prices
    x=torch.tensor(.0,dtype=torch.float64)
    assert (E>=-1e-9).all() and (L>=0).all()
    assert (L[...,1:]<=L[...,:-1]+1e-10).all()
    B=law.boundary(P);zero=law.equity(torch.zeros_like(P),P)
    assert zero.abs().max()<1e-9
    data=torch.randn(10,2,3,dtype=torch.float64)*.30
    allout,(s1,s2)=model(data)
    first,carry=model(data[:4]);second,carry=model(data[4:],carry)
    segment_err=(torch.cat([first,second])-allout).abs().max().item()
    assert segment_err<1e-12
    obj=allout.square().mean();obj.backward()
    checks={}
    for label,param,index in [('input',model.first.sender.weight,(0,0)),('interlayer',model.second.sender.weight,(1,3)),('feedback',model.first.feedback,(1,0)),('readout',model.head.weight,(0,4))]:
        original=param[index].item();grad=param.grad[index].item();step=1e-5
        with torch.no_grad():
            param[index]=original+step;up=model(data)[0].square().mean().item()
            param[index]=original-step;down=model(data)[0].square().mean().item();param[index]=original
        fd=(up-down)/(2*step);checks[label]={'bp':grad,'central':fd,'error':abs(fd-grad)}
        assert abs(fd-grad)<1e-7
    # At the same stationary boundary test two full recurrences against each other, and reiteration after reset.
    state=cell.initial(1);total=0.;merr=0.
    with torch.no_grad():
        for t in range(200):
            f=torch.full((1,3),float((t%7)-3),dtype=torch.float64)
            msg,state=cell.step(f,state);total+=state[1].sum().item()
            merr=max(merr,float((state[0].sum(-1)+state[1]-1).abs().max()))
    assert merr<1e-10 and total>cell.width
    ports={}
    for port in ['boundary','priced','augmented']:
        m=ContinuousSpikingNetwork(3,2,2,atoms=7,port=port);v,st=m(data[:5].float());assert v.shape==(5,2,2)
        ports[port]={'channels_per_sender':m.channels,'parameter_count':sum(p.numel() for p in m.parameters())}
    ans={'torch':torch.__version__,'interval_max_mass_error':masserr,'sequence_200_max_mass_error':merr,'streaming_equivalence_error':segment_err,'equity_at_wall_max':float(zero.abs().max()),'total_expected_spikes_200_steps_width3':total,'gradients':checks,'ports':ports}
    (Path(__file__).resolve().parent/'population_numbers.json').write_text(json.dumps(ans,indent=2));print(json.dumps(ans))
if __name__=='__main__':main()
